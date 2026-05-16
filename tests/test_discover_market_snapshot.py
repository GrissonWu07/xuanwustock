from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CHANGE_ID = "discover-market-data-snapshot-gate"
ARCHIVED_CHANGE_ID = "2026-05-16-discover-market-data-snapshot-gate"


def _params_path(filename: str) -> Path:
    candidates = [
        REPO_ROOT / "openspec" / "changes" / CHANGE_ID / "test-params" / filename,
        REPO_ROOT / "openspec" / "changes" / "archive" / ARCHIVED_CHANGE_ID / "test-params" / filename,
    ]
    for path in candidates:
        if path.exists():
            return path
    raise AssertionError(f"missing OpenSpec test parameters for {CHANGE_ID}: {filename}")


PARAMS_PATH = _params_path("discovery-snapshot-readiness.md")
UI_PARAMS_PATH = _params_path("discover-ui-snapshot-readiness.md")
GATE_PARAMS_PATH = _params_path("lifecycle-gate-missing-snapshot.md")


def _load_case(name: str) -> dict[str, Any]:
    return _load_case_from(PARAMS_PATH, name)


def _load_case_from(path: Path, name: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"## {re.escape(name)}\s+```json\s*(.*?)\s*```", text, flags=re.S)
    assert match, f"missing case {name} in {path}"
    return json.loads(match.group(1))


class FakeMarketDataService:
    def __init__(self, snapshots: dict[str, dict[str, Any]]):
        self.snapshots = snapshots
        self.calls: list[tuple[str, str]] = []

    def get_latest_snapshot(self, symbol: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((symbol, str(kwargs.get("period"))))
        return dict(self.snapshots.get(symbol, {}))


class RaisingMarketDataService:
    def get_latest_snapshot(self, symbol: str, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("provider unavailable")


def test_prepare_discovery_market_snapshots_marks_complete_snapshot_ready():
    from app.discover.market_snapshot import prepare_discovery_market_snapshots

    params = _load_case("complete_snapshot")
    service = FakeMarketDataService({"600001": params["snapshot"]})

    result = prepare_discovery_market_snapshots(
        params["rows"],
        market_data_service=service,
        now_fn=lambda: datetime(2026, 5, 16, 10, 0, 0),
    )

    row = result.rows[0]
    expected = params["expected"]
    assert row["technical_snapshot_ready"] is expected["technical_snapshot_ready"]
    assert row["technical_snapshot_status"] == expected["technical_snapshot_status"]
    assert row["technical_snapshot_missing_fields"] == expected["missing_fields"]
    assert row["technical_snapshot_timeframe"] == "30m"
    assert row["technical_snapshot_provider"] == "fixture"
    assert row["technical_snapshot_at"] == "2026-05-15 14:30:00"
    assert row["latestPrice"] == params["snapshot"]["close"]
    assert row["rsi"] == params["snapshot"]["rsi14"]
    assert result.summary["uniqueStocks"] == expected["unique_stocks"]
    assert result.summary["complete"] == expected["complete"]
    assert result.summary["incomplete"] == expected["incomplete"]


def test_prepare_discovery_market_snapshots_lists_missing_fields():
    from app.discover.market_snapshot import prepare_discovery_market_snapshots

    params = _load_case("missing_snapshot")
    service = FakeMarketDataService({"600002": params["snapshot"]})

    result = prepare_discovery_market_snapshots(
        params["rows"],
        market_data_service=service,
        now_fn=lambda: datetime(2026, 5, 16, 10, 0, 0),
    )

    row = result.rows[0]
    expected = params["expected"]
    assert row["technical_snapshot_ready"] is False
    assert row["technical_snapshot_status"] == expected["technical_snapshot_status"]
    assert row["blocking_reason"] == expected["blocked_reason"]
    assert row["technical_snapshot_missing_fields"] == expected["missing_fields"]
    assert result.summary["blocked"] == 1


def test_prepare_discovery_market_snapshots_deduplicates_codes_per_task():
    from app.discover.market_snapshot import prepare_discovery_market_snapshots

    params = _load_case("duplicate_rows")
    complete = _load_case("complete_snapshot")["snapshot"]
    service = FakeMarketDataService({"600003": complete})

    result = prepare_discovery_market_snapshots(
        params["rows"],
        market_data_service=service,
        now_fn=lambda: datetime(2026, 5, 16, 10, 0, 0),
    )

    assert service.calls == [("600003", "minute30")]
    assert result.summary["uniqueStocks"] == params["expected"]["unique_stocks"]
    assert len(result.rows) == params["expected"]["rows"]
    assert all(row["technical_snapshot_ready"] for row in result.rows)
    assert {row["technical_snapshot_at"] for row in result.rows} == {"2026-05-15 14:30:00"}


def test_prepare_discovery_market_snapshots_reports_provider_failure():
    from app.discover.market_snapshot import prepare_discovery_market_snapshots

    params = _load_case("provider_failure")
    service = FakeMarketDataService({"600004": params["snapshot"]})

    result = prepare_discovery_market_snapshots(
        params["rows"],
        market_data_service=service,
        now_fn=lambda: datetime(2026, 5, 16, 10, 0, 0),
    )

    row = result.rows[0]
    expected = params["expected"]
    assert row["technical_snapshot_ready"] is False
    assert row["technical_snapshot_status"] == expected["technical_snapshot_status"]
    assert row["blocking_reason"] == expected["blocked_reason"]
    assert result.summary["failed"] == expected["failed"]


def test_prepare_discovery_market_snapshots_normalizes_metadata_and_provider_errors():
    from app.discover.market_snapshot import prepare_discovery_market_snapshots

    complete = {
        **_load_case("complete_snapshot")["snapshot"],
        "datetime": "2026-05-15T14:30:00Z",
        "period": "30min",
        "row_count": 77,
    }
    service = FakeMarketDataService({"600005": complete})

    result = prepare_discovery_market_snapshots(
        [{"code": "600005.SH", "cells": ["600005", "测试", "行业", "main_force", "--"]}],
        market_data_service=service,
        now_fn=lambda: datetime(2026, 5, 16, 10, 0, 0),
    )

    row = result.rows[0]
    assert row["technical_snapshot_at"] == "2026-05-15 22:30:00"
    assert row["technical_snapshot_timeframe"] == "30m"
    assert row["technical_snapshot_row_count"] == 77
    assert row["cells"][4] == complete["close"]

    failed = prepare_discovery_market_snapshots(
        [{"code": "600006"}],
        market_data_service=RaisingMarketDataService(),
        now_fn=lambda: datetime(2026, 5, 16, 10, 0, 0),
    )
    assert failed.rows[0]["technical_snapshot_status"] == "failed"
    assert failed.rows[0]["technical_snapshot_error"] == "provider unavailable"


def test_tdx_market_data_service_uses_remote_fetcher_when_local_cache_is_empty():
    import pandas as pd

    from app.data.services.market_data_service import MarketDataService

    class EmptyCacheTdxSource:
        def __init__(self):
            self.calls: list[dict[str, Any]] = []

        def get_kline_data_range(
            self,
            symbol: str,
            *,
            kline_type: str,
            start_datetime: Any,
            end_datetime: Any,
            remote_fetcher: Any,
        ) -> pd.DataFrame:
            self.calls.append(
                {
                    "symbol": symbol,
                    "kline_type": kline_type,
                    "start_datetime": start_datetime,
                    "end_datetime": end_datetime,
                }
            )
            return remote_fetcher()

    class PassthroughIndicatorEngine:
        def calculate(self, frame: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
            return frame.assign(calculated_source=kwargs["source"], calculated_timeframe=kwargs["timeframe"])

    source = EmptyCacheTdxSource()
    service = MarketDataService(provider="tdx", source=source, indicator_engine=PassthroughIndicatorEngine())
    remote_calls: list[dict[str, Any]] = []

    def remote_fetch(symbol: str, period: str, start_date: Any, end_date: Any) -> pd.DataFrame:
        remote_calls.append(
            {
                "symbol": symbol,
                "period": period,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        return pd.DataFrame(
            [
                {
                    "datetime": "2026-05-15 14:30:00",
                    "open": 12.0,
                    "high": 12.5,
                    "low": 11.9,
                    "close": 12.34,
                    "volume": 1000000,
                    "amount": 120000000,
                }
            ]
        )

    service._fetch_tdx_remote_ohlcv = remote_fetch  # type: ignore[attr-defined]

    frame = service.get_ohlcv("600001", period="minute30", start_date="2026-01-01", end_date="2026-05-16")

    assert source.calls == [
        {
            "symbol": "600001",
            "kline_type": "minute30",
            "start_datetime": "2026-01-01",
            "end_datetime": "2026-05-16",
        }
    ]
    assert remote_calls == [
        {
            "symbol": "600001",
            "period": "minute30",
            "start_date": "2026-01-01",
            "end_date": "2026-05-16",
        }
    ]
    assert frame.iloc[-1]["close"] == 12.34
    assert frame.iloc[-1]["calculated_source"] == "tdx"


def test_market_data_service_latest_snapshot_reports_indicator_row_count():
    import pandas as pd

    from app.data.services.market_data_service import MarketDataService

    class FakeSource:
        def get_stock_hist_data(self, symbol: str, **kwargs: Any) -> pd.DataFrame:
            assert symbol == "600001"
            return pd.DataFrame([{"close": 10.0}, {"close": 10.5}, {"close": 10.8}])

    class FakeIndicatorEngine:
        def calculate(self, frame: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
            return frame.assign(
                ma5=[9.8, 10.1, 10.3],
                ma10=[9.7, 10.0, 10.2],
                ma20=[9.6, 9.9, 10.1],
                ma20_slope=[0.01, 0.02, 0.03],
                ma60=[9.0, 9.1, 9.2],
                amount=[1, 2, 3],
                volume_ratio=[1.0, 1.1, 1.2],
                rsi14=[50, 55, 58],
                macd=[0.01, 0.02, 0.03],
                trend=["up", "up", "up"],
                datetime=["2026-05-15 14:00:00", "2026-05-15 14:30:00", "2026-05-15 15:00:00"],
                provider="fixture",
                timeframe="30m",
                indicator_version="fixture-v1",
            )

        @staticmethod
        def latest_dict(frame: pd.DataFrame) -> dict[str, Any]:
            return frame.iloc[-1].to_dict()

    service = MarketDataService(provider="fixture", source=FakeSource(), indicator_engine=FakeIndicatorEngine())

    snapshot = service.get_latest_snapshot("600001", period="minute30")

    assert snapshot["row_count"] == 3


def test_discover_task_prepares_snapshots_before_lifecycle_ingest(monkeypatch):
    import app.discover.discover as discover_gateway

    rows = [{"code": "600020", "name": "准备完成股", "source": "main_force"}]
    prepared_rows = [
        {
            **rows[0],
            "technical_snapshot_ready": True,
            "technical_snapshot_status": "ready",
        }
    ]
    summary = {
        "uniqueStocks": 1,
        "prepared": 1,
        "complete": 1,
        "incomplete": 0,
        "failed": 0,
        "blocked": 0,
        "items": [],
    }
    calls: list[str] = []

    monkeypatch.setattr(
        discover_gateway,
        "_run_discover_strategies",
        lambda context, payload: {"completed": [{"strategy": "main_force"}], "failed": []},
    )
    monkeypatch.setattr(discover_gateway, "_discover_rows", lambda context: [dict(row) for row in rows])

    def fake_prepare(input_rows: list[dict[str, Any]]) -> SimpleNamespace:
        calls.append("prepare")
        assert input_rows == rows
        return SimpleNamespace(rows=prepared_rows, summary=summary)

    def fake_ingest(context: Any, input_rows: list[dict[str, Any]], *, source_type: str) -> dict[str, Any]:
        calls.append("ingest")
        assert source_type == "discover"
        assert input_rows == prepared_rows
        return {"attempted": 1, "events": 1, "eligible": 1, "promoted": 0, "skipped": []}

    monkeypatch.setattr(discover_gateway, "prepare_discovery_market_snapshots", fake_prepare, raising=False)
    monkeypatch.setattr(discover_gateway, "ingest_lifecycle_entry_rows", fake_ingest)

    task_id = discover_gateway.discover_task_manager.create_task(now=discover_gateway._now)

    discover_gateway._run_discover_task(object(), task_id, {"strategy": "main_force"})

    task = discover_gateway.discover_task_manager.get_task(task_id)
    assert calls == ["prepare", "ingest"]
    assert task is not None
    assert task["status"] == "completed"
    assert task["result"]["candidateCount"] == 1
    assert task["result"]["technicalSnapshotPreparation"] == summary
    assert task["result"]["quantAutoEntry"]["attempted"] == 1


def test_candidate_event_payload_preserves_technical_snapshot_diagnostics():
    from app.gateway.quant_universe_entry import _candidate_event_payload

    params = _load_case_from(UI_PARAMS_PATH, "discover_ui_rows")
    row = params["rows"][1]

    payload = _candidate_event_payload(row, source_type="discover")

    event_payload = payload["payload"]
    assert event_payload["technical_snapshot_ready"] is False
    assert event_payload["technical_snapshot_status"] == "incomplete"
    assert event_payload["technical_snapshot_missing_fields"] == ["ma10", "ma60", "rsi", "macd"]
    assert event_payload["technical_snapshot_timeframe"] == "30m"


def test_lifecycle_enrichment_hydrates_technical_snapshot_diagnostics(tmp_path):
    from app.gateway.quant_universe_entry import enrich_lifecycle_entry_rows
    from app.gateway_api import UIApiContext

    params = _load_case_from(UI_PARAMS_PATH, "discover_ui_rows")
    row = params["rows"][1]
    context = UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=tmp_path / "selector_results",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        quant_sim_replay_db_file=tmp_path / "quant_sim_replay.db",
    )
    context.quant_db().add_candidate_event(
        {
            "stock_code": row["code"],
            "stock_name": row["name"],
            "source_type": "discover",
            "source_key": "main_force",
            "source_score": 0.88,
            "confidence": 0.8,
            "trend": "up",
            "status": "blocked",
            "payload": {
                "technical_snapshot_ready": False,
                "technical_snapshot_status": "incomplete",
                "technical_snapshot_missing_fields": row["technical_snapshot_missing_fields"],
                "technical_snapshot_timeframe": "30m",
                "technical_snapshot_provider": "fixture",
                "technical_snapshot_at": "2026-05-15 14:30:00",
                "entry_gate": {
                    "reason_code": "missing_technical_snapshot",
                    "reason_codes": ["missing_technical_snapshot"],
                },
            },
        }
    )

    enriched = enrich_lifecycle_entry_rows(context, [{"code": row["code"]}])

    assert enriched[0]["eligible_status"] == "blocked"
    assert enriched[0]["blocking_reason"] == "missing_technical_snapshot"
    assert enriched[0]["technical_snapshot_ready"] is False
    assert enriched[0]["technical_snapshot_status"] == "incomplete"
    assert enriched[0]["technical_snapshot_missing_fields"] == row["technical_snapshot_missing_fields"]
    assert enriched[0]["technical_snapshot_timeframe"] == "30m"


def test_lifecycle_enrichment_hydrates_consumed_event_snapshot_for_quant_member(tmp_path):
    from app.gateway.quant_universe_entry import enrich_lifecycle_entry_rows
    from app.gateway_api import UIApiContext

    context = UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=tmp_path / "selector_results",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        quant_sim_replay_db_file=tmp_path / "quant_sim_replay.db",
    )
    context.quant_db().upsert_quant_universe_state(
        "301081",
        {
            "stock_name": "严牌股份",
            "quant_status": "trial",
            "candidate_score": 0.5113,
            "candidate_confidence": 0.55,
            "quant_entry_source": "discover",
        },
    )
    context.quant_db().add_candidate_event(
        {
            "stock_code": "301081",
            "stock_name": "严牌股份",
            "source_type": "discover",
            "source_key": "small_cap",
            "source_score": 0.5113,
            "confidence": 0.55,
            "trend": "up",
            "status": "consumed",
            "payload": {
                "technical_snapshot_ready": True,
                "technical_snapshot_status": "ready",
                "technical_snapshot_at": "2026-05-15 14:30:00",
                "technical_snapshot_provider": "tdx",
                "technical_snapshot_timeframe": "30m",
                "technical_snapshot_indicator_version": "fixture-v1",
                "technical_snapshot_row_count": 601,
                "price": 21.5,
                "ma5": 21.1,
                "ma10": 20.8,
                "ma20": 20.1,
                "ma20_slope": 0.04,
                "ma60": 18.9,
                "amount": 150000000,
                "volume_ratio": 1.4,
                "rsi": 56.2,
                "macd": 0.18,
                "trend": "up",
            },
        }
    )

    enriched = enrich_lifecycle_entry_rows(context, [{"code": "301081"}])

    assert enriched[0]["eligible_status"] == "already_in_quant"
    assert enriched[0]["technical_snapshot_ready"] is True
    assert enriched[0]["technical_snapshot_status"] == "ready"
    assert enriched[0]["technical_snapshot_row_count"] == 601


def test_discover_api_exposes_technical_snapshot_readiness_fields(tmp_path):
    import pandas as pd
    from fastapi.testclient import TestClient

    from app.gateway_api import UIApiContext, create_app
    from app.selector_ui_state import save_simple_selector_state

    params = _load_case_from(UI_PARAMS_PATH, "discover_api_row")
    context = UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=tmp_path / "selector_results",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        quant_sim_replay_db_file=tmp_path / "quant_sim_replay.db",
    )
    save_simple_selector_state(
        "low_price_bull",
        pd.DataFrame([params["selector_row"]]),
        "2026-05-16 10:00:00",
        base_dir=context.selector_result_dir,
    )
    client = TestClient(create_app(context=context))

    response = client.get("/api/v1/discover")

    assert response.status_code == 200
    row = response.json()["candidateTable"]["rows"][0]
    expected = params["expected"]
    assert row["technical_snapshot_ready"] is True
    assert row["technical_snapshot_status"] == expected["ready_label"]
    assert row["technical_snapshot_timeframe"] == expected["timeframe"]
    assert row["technical_snapshot_provider"] == expected["provider"]
    assert "T" not in row["technical_snapshot_at"]


def test_entry_gate_blocks_discovery_score_without_technical_snapshot():
    from app.quant_sim.candidate_entry_gate import evaluate_candidate_entry_gate

    params = _load_case_from(GATE_PARAMS_PATH, "score_without_snapshot")

    result = evaluate_candidate_entry_gate(params["event"], profile_id="aggressive")

    expected = params["expected"]
    assert result["passed"] is expected["passed"]
    assert result["status"] == expected["status"]
    assert result["reason_code"] == expected["reason_code"]
    assert result["missing_fields"] == expected["missing_fields"]


def test_entry_gate_blocks_text_only_technical_reason_without_snapshot():
    from app.quant_sim.candidate_entry_gate import evaluate_candidate_entry_gate

    params = _load_case_from(GATE_PARAMS_PATH, "text_only_technical_reason")

    result = evaluate_candidate_entry_gate(params["event"], profile_id="aggressive")

    expected = params["expected"]
    assert result["passed"] is expected["passed"]
    assert result["status"] == expected["status"]
    assert result["reason_code"] == expected["reason_code"]


def test_entry_gate_allows_complete_discovery_snapshot_to_continue():
    from app.quant_sim.candidate_entry_gate import evaluate_candidate_entry_gate

    params = _load_case_from(GATE_PARAMS_PATH, "complete_snapshot_event")

    result = evaluate_candidate_entry_gate(params["event"], profile_id="aggressive")

    expected = params["expected"]
    assert result["passed"] is expected["passed"]
    assert result["status"] == expected["status"]
    assert result["reason_code"] == expected["reason_code"]


def test_entry_gate_blocks_ready_flag_without_structured_snapshot_fields():
    from app.quant_sim.candidate_entry_gate import evaluate_candidate_entry_gate

    params = _load_case_from(GATE_PARAMS_PATH, "ready_flag_without_snapshot_fields")

    result = evaluate_candidate_entry_gate(params["event"], profile_id="aggressive")

    expected = params["expected"]
    assert result["passed"] is expected["passed"]
    assert result["status"] == expected["status"]
    assert result["reason_code"] == expected["reason_code"]
    assert result["missing_fields"] == expected["missing_fields"]
