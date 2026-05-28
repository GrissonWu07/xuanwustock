from __future__ import annotations

from datetime import datetime

from app.quant_kernel.models import Decision
from app.quant_sim.db import QuantSimDB
from app.quant_sim.replay_artifact_adapter import RunArtifactContext, write_run_artifact_from_snapshot
from app.quant_sim.replay_service import QuantSimReplayService


class DrillSnapshotProvider:
    def prepare(self, stock_codes, start_datetime, end_datetime, timeframe):
        del stock_codes, start_datetime, end_datetime, timeframe

    def get_snapshot(self, stock_code, checkpoint, timeframe, stock_name=None):
        del stock_code, checkpoint, timeframe, stock_name
        return {
            "current_price": 10.0,
            "latest_price": 10.0,
            "ma5": 10.2,
            "ma10": 10.1,
            "ma20": 10.0,
            "ma20_slope": 0.03,
            "ma60": 9.8,
            "amount": 80_000_000,
            "macd": 0.1,
            "rsi12": 50.0,
            "volume_ratio": 1.2,
            "trend": "up",
            "row_count": 180,
        }


def _passing_low_price_evidence(db_file, run_id, checkpoint: datetime | None = None) -> dict:
    checkpoint = checkpoint or datetime(2026, 1, 5, 10, 0)
    result = write_run_artifact_from_snapshot(
        RunArtifactContext(
            db_file=db_file,
            run_id=run_id,
            run_type="live_quant_drill",
            market="CN",
            timeframe="30m",
        ),
        stock_code="600519",
        checkpoint=checkpoint,
        snapshot={
            "current_price": 8.8,
            "latest_price": 8.8,
            "ma5": 9.2,
            "ma10": 9.0,
            "ma20": 8.6,
            "ma20_slope": 0.02,
            "ma60": 8.0,
            "amount": 80_000_000,
            "volume_ratio": 1.5,
            "rsi": 62,
            "macd": 0.05,
            "trend": "up",
            "technical_snapshot_ready": True,
            "technical_snapshot_status": "ready",
            "technical_snapshot_timeframe": "30m",
            "technical_snapshot_provider": "unit-test",
            "technical_snapshot_indicator_version": "technical-entry-v1",
        },
    )
    return {
        "technical_snapshot_ready": True,
        "technical_snapshot_status": "ready",
        "technical_snapshot_timeframe": "30m",
        "technical_snapshot_provider": "unit-test",
        "technical_snapshot_at": "2026-01-05 10:00:00",
        "technical_snapshot_row_count": 180,
        "technical_snapshot_indicator_version": "technical-entry-v1",
        "artifact_ref": result["artifact_ref"],
        "source_status": result["source_status"],
        "reason_code": result["reason_code"],
        "consecutive_checkpoint_score": 1.0,
        "ma20_breakout_retest_score": 1.0,
    }


class PreparedOnlyDrillSnapshotProvider(DrillSnapshotProvider):
    def __init__(self) -> None:
        self.prepared: list[tuple[tuple[str, ...], datetime, datetime, str]] = []

    def prepare(self, stock_codes, start_datetime, end_datetime, timeframe):
        self.prepared.append((tuple(stock_codes), start_datetime, end_datetime, timeframe))

    def get_snapshot(self, stock_code, checkpoint, timeframe, stock_name=None):
        if not self.prepared:
            return None
        return super().get_snapshot(stock_code, checkpoint, timeframe, stock_name=stock_name)


class DrillHoldAdapter:
    def analyze_candidate(self, candidate, market_snapshot=None, analysis_timeframe="30m", strategy_mode="auto", current_time=None):
        del analysis_timeframe, strategy_mode
        price = float((market_snapshot or {}).get("current_price") or 0)
        return Decision(
            code=candidate["stock_code"],
            action="HOLD",
            confidence=0.7,
            price=price,
            timestamp=current_time,
            reason="drill checkpoint signal",
            tech_score=0.2,
            context_score=0.1,
            position_ratio=0.0,
            decision_type="test",
            strategy_profile={"market_snapshot": market_snapshot or {}},
        )

    def analyze_position(self, candidate, position, market_snapshot=None, analysis_timeframe="30m", strategy_mode="auto", current_time=None):
        raise AssertionError("position analysis should not run without positions")


def test_live_quant_drill_new_trial_is_scanned_in_same_checkpoint(tmp_path, monkeypatch):
    replay_db_file = tmp_path / "replay.db"
    service = QuantSimReplayService(
        db_file=str(tmp_path / "live.db"),
        replay_db_file=str(replay_db_file),
        snapshot_provider=DrillSnapshotProvider(),
        adapter=DrillHoldAdapter(),
    )

    def fake_generate(*args, **kwargs):
        return [
            {
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "source_type": "low_price",
                "source_key": "low_price:2026-01-05",
                "candidate_score": 0.95,
                "confidence": 0.90,
                "trend": "up",
                "status": "active",
                "reason_text": "historical low price candidate",
                "evidence_json": _passing_low_price_evidence(replay_db_file, kwargs["run_id"]),
            }
        ]

    monkeypatch.setattr(service, "_generate_live_quant_drill_candidate_events", fake_generate)

    result = service.run_live_quant_drill(
        start_datetime=datetime(2026, 1, 5, 10, 0),
        end_datetime=datetime(2026, 1, 5, 10, 30),
        timeframe="30m",
        market="CN",
        seed_current_quant_universe=False,
        generate_historical_candidate_events=True,
        execute_trades=False,
    )

    replay_signals = service.db.get_sim_run_signals(result["run_id"], limit=10)
    assert any(signal["stock_code"] == "600519" for signal in replay_signals)
    candidate_events = service.db.list_sim_run_candidate_events(result["run_id"], page_size=10)
    assert candidate_events["items"][0]["stock_code"] == "600519"
    assert candidate_events["items"][0]["status"] == "consumed"


def test_live_quant_drill_auto_entry_disabled_keeps_candidate_out_of_scan(tmp_path, monkeypatch):
    replay_db_file = tmp_path / "replay.db"
    service = QuantSimReplayService(db_file=str(tmp_path / "live.db"), replay_db_file=str(replay_db_file))

    monkeypatch.setattr(
        service,
        "_generate_live_quant_drill_candidate_events",
        lambda *args, **kwargs: [
            {
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "source_type": "low_price",
                "source_key": "low_price:2026-01-05",
                "candidate_score": 0.95,
                "confidence": 0.90,
                "trend": "up",
                "status": "active",
                "reason_text": "historical low price candidate",
                "evidence_json": _passing_low_price_evidence(replay_db_file, kwargs["run_id"]),
            }
        ],
    )

    result = service.run_live_quant_drill(
        start_datetime=datetime(2026, 1, 5, 10, 0),
        end_datetime=datetime(2026, 1, 5, 10, 30),
        timeframe="30m",
        market="CN",
        seed_current_quant_universe=False,
        generate_historical_candidate_events=True,
        auto_entry_enabled=False,
        execute_trades=False,
    )

    candidate_events = service.db.list_sim_run_candidate_events(result["run_id"], page_size=10)
    states = service.db.list_sim_run_quant_states(result["run_id"], stock="600519")
    assert service.db.get_sim_run_signals(result["run_id"], stock_keyword="600519") == []
    assert candidate_events["items"][0]["status"] == "active"
    lifecycle = candidate_events["items"][0]["evidence_json"]["lifecycle_evaluation"]
    assert lifecycle["decision"] == "eligible"
    assert lifecycle["skip_reason"] == "auto_entry_confirm_first"
    assert lifecycle["evaluated_candidate_score"] >= 0.5
    assert {item["quant_status"] for item in states["items"]} == {"inactive"}


def test_live_quant_drill_historical_candidate_events_promote_inactive_stock(tmp_path):
    live_db_file = tmp_path / "live.db"
    replay_db_file = tmp_path / "replay.db"
    live_db = QuantSimDB(str(live_db_file))
    live_db.add_watch(stock_code="600519", stock_name="贵州茅台", source="manual")
    live_db.upsert_quant_universe_state("600519", {"quant_status": "inactive", "health_score": 100.0})

    service = QuantSimReplayService(
        db_file=str(live_db_file),
        replay_db_file=str(replay_db_file),
        snapshot_provider=PreparedOnlyDrillSnapshotProvider(),
        adapter=DrillHoldAdapter(),
    )
    result = service.run_live_quant_drill(
        start_datetime=datetime(2026, 1, 5, 10, 0),
        end_datetime=datetime(2026, 1, 5, 10, 30),
        timeframe="30m",
        market="CN",
        seed_current_quant_universe=True,
        generate_historical_candidate_events=True,
        auto_entry_enabled=True,
        execute_trades=False,
    )

    candidate_events = service.db.list_sim_run_candidate_events(result["run_id"], page_size=10)
    quant_events = service.db.list_sim_run_quant_events(result["run_id"], stock="600519")
    replay_signals = service.db.get_sim_run_signals(result["run_id"], stock_keyword="600519")
    assert candidate_events["total"] >= 1
    assert candidate_events["items"][0]["source_type"] == "low_price"
    assert candidate_events["items"][0]["status"] == "consumed"
    evidence = candidate_events["items"][0]["evidence_json"]
    assert evidence["artifact_ref"]
    for key in ("price", "ma20", "rsi", "macd", "amount", "trend"):
        assert key not in evidence
    lifecycle = candidate_events["items"][0]["evidence_json"]["lifecycle_evaluation"]
    assert lifecycle["entry_gate"]["passed"] is True
    assert lifecycle["entry_gate"]["result"] == "passed"
    assert any(event["to_status"] == "trial" for event in quant_events["items"])
    assert replay_signals


def test_live_quant_drill_historical_candidate_events_queue_soft_review_for_cooling_stock(tmp_path, monkeypatch):
    live_db_file = tmp_path / "live.db"
    replay_db_file = tmp_path / "replay.db"
    live_db = QuantSimDB(str(live_db_file))
    live_db.add_watch(stock_code="600519", stock_name="贵州茅台", source="manual")
    live_db.upsert_quant_universe_state(
        "600519",
        {
            "quant_status": "cooling",
            "health_score": 35.0,
            "cooling_until": "2026-01-10T02:00:00Z",
        },
    )
    service = QuantSimReplayService(
        db_file=str(live_db_file),
        replay_db_file=str(replay_db_file),
        snapshot_provider=DrillSnapshotProvider(),
        adapter=DrillHoldAdapter(),
    )

    monkeypatch.setattr(
        service,
        "_generate_live_quant_drill_candidate_events",
        lambda *args, **kwargs: [
            {
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "source_type": "low_price",
                "source_key": "low_price:2026-01-05",
                "candidate_score": 0.95,
                "confidence": 0.90,
                "trend": "up",
                "status": "active",
                "reason_text": "expired cooling stock is rediscovered",
                "evidence_json": _passing_low_price_evidence(replay_db_file, kwargs["run_id"]),
            }
        ],
    )

    result = service.run_live_quant_drill(
        start_datetime=datetime(2026, 1, 5, 10, 0),
        end_datetime=datetime(2026, 1, 5, 10, 30),
        timeframe="30m",
        market="CN",
        seed_current_quant_universe=True,
        generate_historical_candidate_events=True,
        auto_entry_enabled=True,
        execute_trades=False,
    )

    quant_events = service.db.list_sim_run_quant_events(result["run_id"], stock="600519")
    candidate_events = service.db.list_sim_run_candidate_events(result["run_id"], stock="600519")
    final_state = service.db.list_sim_run_quant_states(result["run_id"], stock="600519", page_size=1)["items"][0]
    lifecycle = candidate_events["items"][0]["evidence_json"]["lifecycle_evaluation"]

    assert not any(event["from_status"] == "cooling" and event["to_status"] == "trial" for event in quant_events["items"])
    assert lifecycle["decision"] == "cooling_review_queued"
    assert lifecycle["skip_reason"] == "cooling_review_required"
    assert any(event["event_type"] == "cooling_review_not_restored" for event in quant_events["items"])
    assert final_state["quant_status"] == "cooling"


def test_live_quant_drill_persists_quant_summary(tmp_path):
    live_db_file = tmp_path / "live.db"
    replay_db_file = tmp_path / "replay.db"
    live_db = QuantSimDB(str(live_db_file))
    live_db.add_watch(stock_code="600519", stock_name="贵州茅台", source="manual")
    live_db.upsert_quant_universe_state(
        "600519",
        {
            "stock_name": "贵州茅台",
            "quant_status": "active",
            "health_score": 85.0,
            "quant_entry_source": "manual_seed",
        },
    )

    service = QuantSimReplayService(db_file=str(live_db_file), replay_db_file=str(replay_db_file))
    result = service.run_live_quant_drill(
        start_datetime=datetime(2026, 1, 5, 10, 0),
        end_datetime=datetime(2026, 1, 5, 10, 30),
        timeframe="30m",
        market="CN",
        seed_current_quant_universe=True,
        generate_historical_candidate_events=False,
        execute_trades=False,
    )

    summary = service.db.list_sim_run_quant_summary(result["run_id"])
    states = service.db.list_sim_run_quant_states(result["run_id"], stock="600519")
    assert len(summary) >= 1
    assert states["total"] >= 1
    assert summary[0]["active_count"] >= 1


def test_live_quant_drill_persists_lifecycle_events_from_run_local_db(tmp_path, monkeypatch):
    service = QuantSimReplayService(db_file=str(tmp_path / "live.db"), replay_db_file=str(tmp_path / "replay.db"))

    monkeypatch.setattr(
        service,
        "_generate_live_quant_drill_candidate_events",
        lambda *args, **kwargs: [
            {
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "source_type": "low_price",
                "source_key": "low_price:2026-01-05",
                "candidate_score": 0.95,
                "confidence": 0.90,
                "trend": "up",
                "status": "active",
                "reason_text": "historical low price candidate",
                "evidence_json": _passing_low_price_evidence(tmp_path / "replay.db", kwargs["run_id"]),
            }
        ],
    )

    result = service.run_live_quant_drill(
        start_datetime=datetime(2026, 1, 5, 10, 0),
        end_datetime=datetime(2026, 1, 5, 10, 30),
        timeframe="30m",
        market="CN",
        seed_current_quant_universe=False,
        generate_historical_candidate_events=True,
        execute_trades=False,
    )

    events = service.db.list_sim_run_quant_events(result["run_id"], stock="600519")
    assert events["total"] >= 1
    assert events["items"][0]["event_type"] == "candidate_promoted_to_trial"
    assert events["items"][0]["to_status"] == "trial"
