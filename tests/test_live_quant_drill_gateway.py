from __future__ import annotations

from fastapi.testclient import TestClient

from app.gateway.live_sim import _action_live_sim_start_drill


class FakeReplayService:
    def __init__(self):
        self.payload = None

    def enqueue_live_quant_drill(self, **kwargs):
        self.payload = kwargs
        return 42


class FakeContext:
    def __init__(self):
        self.service = FakeReplayService()
        self.db_runtime = None
        self.replay = None

    def replay_service(self):
        return self.service

    def replay_db(self):
        return self.replay


class FakeReplayDB:
    def __init__(self, run):
        self.run = run
        self.calls: list[dict] = []

    def get_sim_run(self, run_id):
        return self.run

    def list_sim_run_quant_states(self, run_id, **kwargs):
        self.calls.append({"method": "states", "run_id": run_id, **kwargs})
        return {"items": [], "total": 0, "page": kwargs.get("page", 1), "pageSize": kwargs.get("page_size", 50)}

    def list_sim_run_quant_events(self, run_id, **kwargs):
        self.calls.append({"method": "events", "run_id": run_id, **kwargs})
        return {"items": [], "total": 0, "page": kwargs.get("page", 1), "pageSize": kwargs.get("page_size", 50)}

    def list_sim_run_candidate_events(self, run_id, **kwargs):
        self.calls.append({"method": "candidate_events", "run_id": run_id, **kwargs})
        return {"items": [], "total": 0, "page": kwargs.get("page", 1), "pageSize": kwargs.get("page_size", 50)}

    def list_profit_gap_attributions(self, historical_run_id, drill_run_id, *, limit=200):
        self.calls.append(
            {
                "method": "profit_gap",
                "historical_run_id": historical_run_id,
                "drill_run_id": drill_run_id,
                "limit": limit,
            }
        )
        return [
            {
                "stock_code": "301666",
                "stock_name": "大普微-UW",
                "historical_total_pnl": 41119.0,
                "drill_total_pnl": 18023.59,
                "pnl_gap": 23095.41,
                "attribution_labels": ["size_too_small"],
                "primary_reason": "entry matched but drill sizing was materially lower",
            }
        ]


def test_start_drill_gateway_calls_replay_service():
    context = FakeContext()
    result = _action_live_sim_start_drill(
        context,
        {
            "startDate": "2026-01-01",
            "endDate": "2026-05-09",
            "market": "CN",
            "timeframe": "30m",
            "initialCash": 50000,
            "autoEntryEnabled": True,
            "autoExitEnabled": True,
            "executeTrades": True,
            "liquidateAtEnd": True,
            "seedCurrentQuantUniverse": True,
            "generateHistoricalCandidateEvents": True,
            "candidateGenerationFrequency": "daily_first_checkpoint",
            "candidateGenerationCheckpointInterval": 8,
            "confirmLongRunning": False,
        },
    )

    assert result["runId"] == 42
    assert result["runType"] == "live_quant_drill"
    assert result["redirect"] == "/his-replay?runId=42"
    assert context.service.payload["start_datetime"] == "2026-01-01"


def test_start_drill_gateway_returns_400_when_long_run_is_not_confirmed():
    class LongRunService(FakeReplayService):
        def enqueue_live_quant_drill(self, **kwargs):
            raise ValueError("Long running drill requires confirmation")

    context = FakeContext()
    context.service = LongRunService()

    result = _action_live_sim_start_drill(
        context,
        {
            "startDate": "2026-01-01",
            "endDate": "2026-05-09",
            "market": "CN",
            "timeframe": "30m",
            "confirmLongRunning": False,
        },
    )

    assert result["statusCode"] == 400
    assert result["error"] == "Long running drill requires confirmation"


def test_drill_lifecycle_query_endpoints_are_registered():
    from app.gateway_api import create_app

    app = create_app(FakeContext())
    routes = {
        route.path
        for route in app.routes
        if hasattr(route, "methods") and "GET" in route.methods
    }
    assert "/api/v1/quant/replay/{run_id}/quant-states" in routes
    assert "/api/v1/quant/replay/{run_id}/quant-events" in routes
    assert "/api/v1/quant/replay/{run_id}/candidate-events" in routes
    assert "/api/v1/quant/his-replay/runs/{drill_run_id}/profit-gap" in routes


def test_drill_lifecycle_endpoint_rejects_missing_and_non_drill_runs():
    from app.gateway_api import create_app

    missing_context = FakeContext()
    missing_context.replay = FakeReplayDB(None)
    missing_client = TestClient(create_app(missing_context))
    assert missing_client.get("/api/v1/quant/replay/404/quant-states").status_code == 404

    non_drill_context = FakeContext()
    non_drill_context.replay = FakeReplayDB({"id": 1, "mode": "historical_replay", "metadata": {}})
    non_drill_client = TestClient(create_app(non_drill_context))
    assert non_drill_client.get("/api/v1/quant/replay/1/quant-states").status_code == 400


def test_drill_lifecycle_query_endpoints_pass_filters_to_replay_db():
    from app.gateway_api import create_app

    context = FakeContext()
    context.replay = FakeReplayDB({"id": 1, "mode": "live_quant_drill", "metadata": {"run_type": "live_quant_drill"}})
    client = TestClient(create_app(context))

    response = client.get(
        "/api/v1/quant/replay/1/quant-events",
        params={"eventType": "candidate_promoted_to_trial", "fromStatus": "inactive", "toStatus": "trial", "stock": "600519", "page": 2, "pageSize": 3},
    )

    assert response.status_code == 200
    assert context.replay.calls[-1] == {
        "method": "events",
        "run_id": 1,
        "event_type": "candidate_promoted_to_trial",
        "from_status": "inactive",
        "to_status": "trial",
        "stock": "600519",
        "page": 2,
        "page_size": 3,
    }


def test_profit_gap_endpoint_reads_replay_attribution_rows():
    from app.gateway_api import create_app

    context = FakeContext()
    context.replay = FakeReplayDB({"id": 2, "mode": "live_quant_drill", "metadata": {"run_type": "live_quant_drill"}})
    client = TestClient(create_app(context))

    response = client.get(
        "/api/v1/quant/his-replay/runs/2/profit-gap",
        params={"historicalRunId": 1, "limit": 25},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["historical_run_id"] == 1
    assert payload["drill_run_id"] == 2
    assert payload["items"][0]["attribution_labels"] == ["size_too_small"]
    assert context.replay.calls[-1] == {
        "method": "profit_gap",
        "historical_run_id": 1,
        "drill_run_id": 2,
        "limit": 25,
    }
