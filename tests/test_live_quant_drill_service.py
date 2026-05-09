from __future__ import annotations

from datetime import datetime

import pytest

from app.quant_sim.db import QuantSimDB
from app.quant_sim.replay_service import QuantSimReplayService


class FakeReplayRunner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def start_run(self, run_id, target, *args):
        self.calls.append({"run_id": run_id, "target": target, "args": args})
        return True


def test_enqueue_live_quant_drill_creates_run_with_metadata(tmp_path, monkeypatch):
    live_db_file = tmp_path / "live.db"
    replay_db_file = tmp_path / "replay.db"
    live_db = QuantSimDB(str(live_db_file))
    live_db.add_watch(stock_code="600519", stock_name="贵州茅台", source="manual")
    live_db.upsert_quant_universe_state(
        "600519",
        {
            "stock_name": "贵州茅台",
            "quant_status": "active",
            "health_score": 91.0,
            "quant_entry_source": "manual_seed",
        },
    )

    runner = FakeReplayRunner()
    monkeypatch.setattr("app.quant_sim.replay_service.get_quant_sim_replay_runner", lambda db_file=None: runner)

    service = QuantSimReplayService(db_file=str(live_db_file), replay_db_file=str(replay_db_file))
    run_id = service.enqueue_live_quant_drill(
        start_datetime=datetime(2026, 1, 5, 9, 30),
        end_datetime=datetime(2026, 1, 6, 15, 0),
        timeframe="30m",
        market="CN",
        initial_cash=100000,
        seed_current_quant_universe=True,
        generate_historical_candidate_events=True,
        auto_entry_enabled=True,
        auto_exit_enabled=True,
        execute_trades=True,
        liquidate_at_end=True,
    )

    run = service.db.get_sim_run(run_id)
    metadata = run["metadata"]
    assert run["mode"] == "live_quant_drill"
    assert run["status"] == "queued"
    assert run["progress_total"] > 0
    assert metadata["run_type"] == "live_quant_drill"
    assert metadata["seed_current_quant_universe"] is True
    assert metadata["generate_historical_candidate_events"] is True
    assert metadata["auto_entry_enabled"] is True
    assert metadata["auto_exit_enabled"] is True
    assert metadata["execute_trades"] is True
    assert metadata["liquidate_at_end"] is True
    assert metadata["stock_codes"] == ["600519"]
    assert metadata["initial_quant_universe_snapshot"][0]["stock_code"] == "600519"
    assert metadata["initial_quant_universe_snapshot"][0]["quant_status"] == "active"
    assert metadata["candidate_generation"]["estimated_strategy_invocations"] >= 0
    assert metadata["estimated_candidate_generation_runs"] >= 0
    assert metadata["estimated_strategy_invocations"] >= 0
    assert metadata["enabled_candidate_sources"]
    assert metadata["candidate_event_dedup_days"] == 5
    assert metadata["data_warnings"] == []
    assert metadata["lifecycle_settings_snapshot"]["auto_entry_mode"]
    assert metadata["strategy_profile_snapshot"]
    assert metadata["strategy_profile_version_id"] is not None
    assert runner.calls[0]["target"].__name__ == "execute_live_quant_drill_worker"


def test_live_quant_drill_requires_at_least_one_stock_source(tmp_path):
    service = QuantSimReplayService(db_file=str(tmp_path / "live.db"), replay_db_file=str(tmp_path / "replay.db"))

    with pytest.raises(ValueError, match="No quant universe source selected"):
        service.enqueue_live_quant_drill(
            start_datetime=datetime(2026, 1, 5, 9, 30),
            end_datetime=datetime(2026, 1, 6, 15, 0),
            timeframe="30m",
            market="CN",
            seed_current_quant_universe=False,
            generate_historical_candidate_events=False,
        )


def test_live_quant_drill_requires_confirmation_for_large_candidate_generation(tmp_path, monkeypatch):
    service = QuantSimReplayService(db_file=str(tmp_path / "live.db"), replay_db_file=str(tmp_path / "replay.db"))
    monkeypatch.setattr(
        "app.quant_sim.replay_service.estimate_candidate_generation",
        lambda **kwargs: {
            "estimated_candidate_generation_runs": 999,
            "enabled_candidate_sources": ["low_price", "main_force", "manual_seed"],
            "estimated_strategy_invocations": 3001,
        },
    )
    runner = FakeReplayRunner()
    monkeypatch.setattr("app.quant_sim.replay_service.get_quant_sim_replay_runner", lambda db_file=None: runner)

    with pytest.raises(ValueError, match="Long running drill requires confirmation"):
        service.enqueue_live_quant_drill(
            start_datetime=datetime(2026, 1, 5, 9, 30),
            end_datetime=datetime(2026, 5, 1, 15, 0),
            timeframe="30m",
            market="CN",
            confirm_long_running=False,
            seed_current_quant_universe=False,
            generate_historical_candidate_events=True,
        )

    run_id = service.enqueue_live_quant_drill(
        start_datetime=datetime(2026, 1, 5, 9, 30),
        end_datetime=datetime(2026, 5, 1, 15, 0),
        timeframe="30m",
        market="CN",
        confirm_long_running=True,
        seed_current_quant_universe=False,
        generate_historical_candidate_events=True,
    )
    assert run_id > 0


def test_live_quant_drill_is_blocked_by_running_historical_backtest(tmp_path):
    live_db_file = tmp_path / "live.db"
    replay_db_file = tmp_path / "replay.db"
    service = QuantSimReplayService(db_file=str(live_db_file), replay_db_file=str(replay_db_file))
    service.db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-01-01 09:30:00",
        end_datetime="2026-01-02 15:00:00",
        initial_cash=100000,
        status="running",
    )

    with pytest.raises(ValueError, match="已有回放任务运行中"):
        service.enqueue_live_quant_drill(
            start_datetime=datetime(2026, 1, 5, 9, 30),
            end_datetime=datetime(2026, 1, 6, 15, 0),
            timeframe="30m",
            market="CN",
        )


def test_live_quant_drill_initializes_run_local_quant_state(tmp_path):
    live_db_file = tmp_path / "live.db"
    live_db = QuantSimDB(str(live_db_file))
    live_db.add_watch(stock_code="600519", stock_name="贵州茅台", source="manual")
    live_db.upsert_quant_universe_state(
        "600519",
        {
            "stock_name": "贵州茅台",
            "quant_status": "active",
            "health_score": 91.0,
            "candidate_score": 72.0,
            "candidate_confidence": 0.83,
        },
    )
    live_db.add_watch(stock_code="000001", stock_name="平安银行", source="manual")
    live_db.upsert_quant_universe_state(
        "000001",
        {
            "stock_name": "平安银行",
            "quant_status": "cooling",
            "health_score": 35.0,
        },
    )

    service = QuantSimReplayService(db_file=str(live_db_file), replay_db_file=str(tmp_path / "replay.db"))
    context = service._prepare_live_quant_drill_context(
        start_datetime=datetime(2026, 1, 5, 9, 30),
        end_datetime=datetime(2026, 1, 6, 15, 0),
        timeframe="30m",
        market="CN",
        strategy_profile_id=None,
        initial_cash=100000,
        ai_dynamic_strategy="off",
        ai_dynamic_strength=0,
        ai_dynamic_lookback=24,
        auto_entry_enabled=True,
        auto_exit_enabled=True,
        execute_trades=True,
        liquidate_at_end=True,
        seed_current_quant_universe=True,
        generate_historical_candidate_events=False,
        candidate_generation_frequency="daily_first_checkpoint",
        candidate_generation_checkpoint_interval=8,
    )
    temp_db = service._create_live_quant_drill_temp_db(context, tmp_path / "temp.db")

    state = temp_db.get_quant_universe_state("600519")
    candidate = temp_db.get_candidate("600519")
    cooling_state = temp_db.get_quant_universe_state("000001")
    scan_candidates = temp_db.get_candidates(quant_statuses=["trial", "active", "exit_only"])
    assert state["quant_status"] == "active"
    assert state["health_score"] == 91.0
    assert state["candidate_score"] == 72.0
    assert state["candidate_confidence"] == 0.83
    assert candidate["stock_code"] == "600519"
    assert cooling_state["quant_status"] == "cooling"
    assert [row["stock_code"] for row in scan_candidates] == ["600519"]


def test_live_quant_drill_execution_does_not_write_live_account(tmp_path):
    live_db_file = tmp_path / "live.db"
    replay_db_file = tmp_path / "replay.db"
    live_db = QuantSimDB(str(live_db_file))
    live_db.configure_account(50000)
    live_db.add_watch(stock_code="600519", stock_name="贵州茅台", source="manual")
    live_db.upsert_quant_universe_state("600519", {"quant_status": "active", "health_score": 85.0})
    before = live_db.get_account_summary()

    service = QuantSimReplayService(db_file=str(live_db_file), replay_db_file=str(replay_db_file))
    result = service.run_live_quant_drill(
        start_datetime=datetime(2026, 1, 5, 10, 0),
        end_datetime=datetime(2026, 1, 5, 10, 30),
        timeframe="30m",
        market="CN",
        initial_cash=50000,
        seed_current_quant_universe=True,
        generate_historical_candidate_events=False,
        execute_trades=True,
    )

    after = live_db.get_account_summary()
    run = service.db.get_sim_run(result["run_id"])
    assert result["run_id"] > 0
    assert result["status"] == "completed"
    assert run["mode"] == "live_quant_drill"
    assert after["available_cash"] == before["available_cash"]
    assert after["total_equity"] == before["total_equity"]
    assert live_db.get_trade_history(limit=10) == []
    quant_summary = service.db.list_sim_run_quant_summary(result["run_id"])
    quant_states = service.db.list_sim_run_quant_states(result["run_id"], page_size=10)
    assert quant_summary
    assert quant_summary[0]["active_count"] == 1
    assert quant_states["items"][0]["stock_code"] == "600519"
    assert quant_states["items"][0]["quant_status"] == "active"


def test_live_quant_drill_runs_cooling_opportunistic_review_after_main_scan(tmp_path, monkeypatch):
    service = QuantSimReplayService(db_file=str(tmp_path / "live.db"), replay_db_file=str(tmp_path / "replay.db"))
    call_order: list[str] = []

    def fake_main_scan(*args, **kwargs):
        call_order.append("main_scan")
        return {"signals": [], "candidates_scanned": 1}

    def fake_cooling_review(*args, **kwargs):
        call_order.append("cooling_review")
        return {"reviewed": 2, "restored": 1}

    monkeypatch.setattr(service, "_run_live_quant_drill_main_scan", fake_main_scan)
    monkeypatch.setattr(service, "_run_live_quant_drill_cooling_review", fake_cooling_review)

    service._run_live_quant_drill_checkpoint(
        run_id=1,
        checkpoint=datetime(2026, 1, 5, 10, 0),
        checkpoint_index=1,
        context={
            "checkpoints": [datetime(2026, 1, 5, 10, 0)],
            "timeframe": "30m",
            "market": "CN",
            "start_dt": datetime(2026, 1, 5, 10, 0),
            "end_dt": datetime(2026, 1, 5, 10, 0),
            "execute_trades": True,
        },
        temp_db=QuantSimDB(str(tmp_path / "temp.db")),
        engine=object(),
        portfolio=object(),
        manager=object(),
    )

    assert call_order == ["main_scan", "cooling_review"]


def test_live_quant_drill_new_trial_is_scanned_in_same_checkpoint(tmp_path, monkeypatch):
    service = QuantSimReplayService(db_file=str(tmp_path / "live.db"), replay_db_file=str(tmp_path / "replay.db"))
    scanned_codes: list[str] = []

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
                "evidence_json": {"price_structure": "strong"},
            }
        ]

    monkeypatch.setattr(service, "_generate_live_quant_drill_candidate_events", fake_generate)
    monkeypatch.setattr(
        service,
        "_evaluate_drill_candidate",
        lambda candidate, *args, **kwargs: scanned_codes.append(candidate["stock_code"]),
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

    assert "600519" in scanned_codes
    candidate_events = service.db.list_sim_run_candidate_events(result["run_id"], page_size=10)
    assert candidate_events["items"][0]["stock_code"] == "600519"
    assert candidate_events["items"][0]["status"] == "consumed"


def test_live_quant_drill_auto_entry_disabled_keeps_candidate_out_of_scan(tmp_path, monkeypatch):
    service = QuantSimReplayService(db_file=str(tmp_path / "live.db"), replay_db_file=str(tmp_path / "replay.db"))
    scanned_codes: list[str] = []

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
            }
        ],
    )
    monkeypatch.setattr(
        service,
        "_evaluate_drill_candidate",
        lambda candidate, *args, **kwargs: scanned_codes.append(candidate["stock_code"]),
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
    assert scanned_codes == []
    assert candidate_events["items"][0]["status"] == "active"
    assert {item["quant_status"] for item in states["items"]} == {"inactive"}


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
