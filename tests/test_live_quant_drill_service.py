from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import pytest

from app.quant_kernel.models import Decision
from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.db import QuantSimDB
from app.quant_sim.engine import QuantSimEngine
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.quant_universe_lifecycle import QuantUniverseManager
from app.quant_sim.replay_service import QuantSimReplayService


class FakeReplayRunner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def start_run(self, run_id, target, *args):
        self.calls.append({"run_id": run_id, "target": target, "args": args})
        return True


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


def _passing_low_price_evidence() -> dict:
    return {
        "price": 8.8,
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
        "technical_snapshot_at": "2026-01-05 10:00:00",
        "technical_snapshot_row_count": 180,
        "technical_snapshot_indicator_version": "technical-entry-v1",
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


def test_run_live_quant_drill_accepts_ai_dynamic_settings(tmp_path, monkeypatch):
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

    captured: dict = {}

    def fake_execute(*, run_id, context):
        captured["run_id"] = run_id
        captured["context"] = context
        return {"run_id": run_id, "summary": {}}

    service = QuantSimReplayService(db_file=str(live_db_file), replay_db_file=str(replay_db_file))
    monkeypatch.setattr(service, "_execute_live_quant_drill", fake_execute)

    result = service.run_live_quant_drill(
        start_datetime=datetime(2026, 1, 5, 9, 30),
        end_datetime=datetime(2026, 1, 6, 15, 0),
        timeframe="30m",
        market="CN",
        strategy_profile_id="aggressive",
        initial_cash=100000,
        ai_dynamic_strategy="hybrid",
        ai_dynamic_strength=0.6,
        ai_dynamic_lookback=36,
        seed_current_quant_universe=True,
        generate_historical_candidate_events=False,
    )

    assert result["run_id"] == captured["run_id"]
    assert captured["context"]["ai_dynamic_strategy"] == "hybrid"
    assert captured["context"]["ai_dynamic_strength"] == 0.6
    assert captured["context"]["ai_dynamic_lookback"] == 36


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


def test_live_quant_drill_prepares_historical_snapshots_before_scan(tmp_path):
    live_db_file = tmp_path / "live.db"
    replay_db_file = tmp_path / "replay.db"
    live_db = QuantSimDB(str(live_db_file))
    live_db.configure_account(50000)
    live_db.add_watch(stock_code="600519", stock_name="贵州茅台", source="manual")
    live_db.upsert_quant_universe_state("600519", {"quant_status": "active", "health_score": 85.0})
    snapshot_provider = PreparedOnlyDrillSnapshotProvider()

    service = QuantSimReplayService(
        db_file=str(live_db_file),
        replay_db_file=str(replay_db_file),
        snapshot_provider=snapshot_provider,
        adapter=DrillHoldAdapter(),
    )
    result = service.run_live_quant_drill(
        start_datetime=datetime(2026, 1, 5, 10, 0),
        end_datetime=datetime(2026, 1, 5, 10, 30),
        timeframe="30m",
        market="CN",
        initial_cash=50000,
        seed_current_quant_universe=True,
        generate_historical_candidate_events=False,
        execute_trades=False,
    )

    replay_signals = service.db.get_sim_run_signals(result["run_id"], limit=10)
    assert snapshot_provider.prepared == [(("600519",), datetime(2026, 1, 5, 10, 0), datetime(2026, 1, 5, 10, 30), "30m")]
    assert len(replay_signals) >= 1
    assert {signal["stock_code"] for signal in replay_signals} == {"600519"}


def test_live_quant_drill_main_scan_creates_checkpoint_signal(tmp_path):
    temp_db_file = tmp_path / "temp.db"
    temp_db = QuantSimDB(str(temp_db_file))
    temp_db.configure_account(50000)
    temp_db.add_watch(stock_code="600519", stock_name="贵州茅台", source="manual")
    temp_db.add_candidate(
        {
            "stock_code": "600519",
            "stock_name": "贵州茅台",
            "source": "manual_seed",
            "status": "active",
            "latest_price": 10.0,
        }
    )
    temp_db.upsert_quant_universe_state(
        "600519",
        {"stock_name": "贵州茅台", "quant_status": "active", "health_score": 90.0},
    )

    service = QuantSimReplayService(db_file=str(tmp_path / "live.db"), replay_db_file=str(tmp_path / "replay.db"))
    service.snapshot_provider = DrillSnapshotProvider()
    engine = QuantSimEngine(db_file=str(temp_db_file), adapter=DrillHoldAdapter(), stock_analysis_context_enabled=False)
    portfolio = PortfolioService(db_file=str(temp_db_file))
    manager = QuantUniverseManager(
        db=temp_db,
        profile_id="stable",
        policy=engine._quant_lifecycle_policy_from_binding({"profile_id": "stable"}),
        drill_mode=True,
    )

    result = service._run_live_quant_drill_main_scan(
        checkpoint=datetime(2026, 1, 5, 10, 0),
        context={
            "timeframe": "30m",
            "market": "CN",
            "strategy_mode": "live_quant_drill",
            "execute_trades": False,
        },
        temp_db=temp_db,
        engine=engine,
        portfolio=portfolio,
        manager=manager,
    )

    assert result["candidates_scanned"] == 1
    assert result["signals_created"] == 1
    assert result["signals"][0]["stock_code"] == "600519"
    assert result["signals"][0]["action"] == "HOLD"


def test_live_quant_drill_runs_cooling_review_before_main_scan(tmp_path, monkeypatch):
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

    assert call_order == ["cooling_review", "main_scan"]


def test_live_quant_drill_cooling_review_uses_checkpoint_snapshot(tmp_path):
    service = QuantSimReplayService(
        db_file=str(tmp_path / "live.db"),
        replay_db_file=str(tmp_path / "replay.db"),
        snapshot_provider=DrillSnapshotProvider(),
        adapter=DrillHoldAdapter(),
    )
    temp_db_file = tmp_path / "temp.db"
    temp_db = QuantSimDB(str(temp_db_file))
    CandidatePoolService(db_file=str(temp_db_file)).add_manual_candidate("600519", "贵州茅台", "manual")
    temp_db.upsert_quant_universe_state("600519", {"quant_status": "cooling", "health_score": 20})
    engine = QuantSimEngine(
        db_file=str(temp_db_file),
        adapter=DrillHoldAdapter(),
        stock_analysis_context_enabled=False,
    )
    portfolio = PortfolioService(db_file=str(temp_db_file))
    manager = QuantUniverseManager(
        db=temp_db,
        profile_id="stable",
        policy=engine._quant_lifecycle_policy_from_binding({"profile_id": "stable"}),
        drill_mode=True,
    )
    captured: dict[str, object] = {}
    original = engine.build_candidate_review_signal

    def capture_snapshot(candidate, **kwargs):
        captured["market_snapshot"] = kwargs.get("market_snapshot")
        return original(candidate, **kwargs)

    engine.build_candidate_review_signal = capture_snapshot

    result = service._run_live_quant_drill_cooling_review(
        checkpoint=datetime(2026, 1, 5, 10, 0),
        context={"timeframe": "30m", "market": "CN", "strategy_mode": "live_quant_drill"},
        temp_db=temp_db,
        engine=engine,
        portfolio=portfolio,
        manager=manager,
    )

    assert result["reviewed"] == 1
    assert captured["market_snapshot"]["current_price"] == 10.0
    assert temp_db.get_quant_universe_state("600519")["last_health_evaluated_at"] == "2026-01-05T10:00:00Z"


def test_live_quant_drill_records_cooling_review_not_restored_diagnostics(tmp_path):
    service = QuantSimReplayService(
        db_file=str(tmp_path / "live.db"),
        replay_db_file=str(tmp_path / "replay.db"),
        snapshot_provider=DrillSnapshotProvider(),
        adapter=DrillHoldAdapter(),
    )
    run_id = service.db.create_sim_run(
        mode="live_quant_drill",
        timeframe="30m",
        market="CN",
        start_datetime="2026-01-05 10:00:00",
        end_datetime="2026-01-05 10:30:00",
        initial_cash=100000,
        status="running",
    )
    temp_db_file = tmp_path / "temp.db"
    temp_db = QuantSimDB(str(temp_db_file))
    CandidatePoolService(db_file=str(temp_db_file)).add_manual_candidate("600519", "贵州茅台", "manual")
    temp_db.upsert_quant_universe_state("600519", {"quant_status": "cooling", "health_score": 20})
    engine = QuantSimEngine(
        db_file=str(temp_db_file),
        adapter=DrillHoldAdapter(),
        stock_analysis_context_enabled=False,
    )
    portfolio = PortfolioService(db_file=str(temp_db_file))
    manager = QuantUniverseManager(
        db=temp_db,
        profile_id="aggressive",
        policy=engine._quant_lifecycle_policy_from_binding({"profile_id": "aggressive"}),
        drill_mode=True,
    )
    result = service._run_live_quant_drill_cooling_review(
        checkpoint=datetime(2026, 1, 5, 10, 0),
        context={"timeframe": "30m", "market": "CN", "strategy_mode": "live_quant_drill"},
        temp_db=temp_db,
        engine=engine,
        portfolio=portfolio,
        manager=manager,
    )
    service._persist_live_quant_drill_quant_snapshot(
        run_id=run_id,
        checkpoint=datetime(2026, 1, 5, 10, 0),
        context={"market": "CN"},
        temp_db=temp_db,
        checkpoint_metadata={"cooling_review": {"diagnostic_count": len(result.get("diagnostics") or [])}},
    )

    events = service.db.list_sim_run_quant_events(
        run_id,
        event_type="cooling_review_not_restored",
        stock="600519",
    )
    assert events["total"] >= 1
    event = events["items"][0]
    assert event["from_status"] == "cooling"
    assert event["to_status"] == "cooling"
    assert event["reason_code"] in {"cooling_recovery_not_confirmed", "cooling_downtrend_soft_gate"}
    assert event["evidence_json"]["review_signal_action"] == "HOLD"


def test_live_quant_drill_throttles_repeated_cooling_soft_gate_events(tmp_path):
    service = QuantSimReplayService(
        db_file=str(tmp_path / "live.db"),
        replay_db_file=str(tmp_path / "replay.db"),
        snapshot_provider=DrillSnapshotProvider(),
        adapter=DrillHoldAdapter(),
    )
    temp_db_file = tmp_path / "temp.db"
    temp_db = QuantSimDB(str(temp_db_file))
    CandidatePoolService(db_file=str(temp_db_file)).add_manual_candidate("600519", "贵州茅台", "manual")
    temp_db.upsert_quant_universe_state("600519", {"quant_status": "cooling", "health_score": 20})
    engine = QuantSimEngine(
        db_file=str(temp_db_file),
        adapter=DrillHoldAdapter(),
        stock_analysis_context_enabled=False,
    )
    portfolio = PortfolioService(db_file=str(temp_db_file))
    manager = QuantUniverseManager(
        db=temp_db,
        profile_id="aggressive",
        policy=engine._quant_lifecycle_policy_from_binding({"profile_id": "aggressive"}),
        drill_mode=True,
    )
    context = {"timeframe": "30m", "market": "CN", "strategy_mode": "live_quant_drill"}

    first = service._run_live_quant_drill_cooling_review(
        checkpoint=datetime(2026, 1, 5, 10, 0),
        context=context,
        temp_db=temp_db,
        engine=engine,
        portfolio=portfolio,
        manager=manager,
    )
    second = service._run_live_quant_drill_cooling_review(
        checkpoint=datetime(2026, 1, 5, 10, 30),
        context=context,
        temp_db=temp_db,
        engine=engine,
        portfolio=portfolio,
        manager=manager,
    )

    events = [
        event
        for event in temp_db.list_quant_universe_events(limit=20)
        if event["stock_code"] == "600519" and event["event_type"] == "cooling_review_not_restored"
    ]
    assert first["reviewed"] == 1
    assert second["reviewed"] == 1
    assert len(first["diagnostics"]) == 1
    assert len(second["diagnostics"]) == 1
    assert len(events) == 1
    assert events[0]["reason_code"] in {"cooling_recovery_not_confirmed", "cooling_downtrend_soft_gate"}


def test_live_quant_drill_cooling_diagnostic_records_once_per_stock_reason_across_run(tmp_path):
    service = QuantSimReplayService(
        db_file=str(tmp_path / "live.db"),
        replay_db_file=str(tmp_path / "replay.db"),
        snapshot_provider=DrillSnapshotProvider(),
        adapter=DrillHoldAdapter(),
    )
    temp_db_file = tmp_path / "temp.db"
    temp_db = QuantSimDB(str(temp_db_file))
    CandidatePoolService(db_file=str(temp_db_file)).add_manual_candidate("600519", "贵州茅台", "manual")
    temp_db.upsert_quant_universe_state("600519", {"quant_status": "cooling", "health_score": 20})
    engine = QuantSimEngine(
        db_file=str(temp_db_file),
        adapter=DrillHoldAdapter(),
        stock_analysis_context_enabled=False,
    )
    portfolio = PortfolioService(db_file=str(temp_db_file))
    manager = QuantUniverseManager(
        db=temp_db,
        profile_id="aggressive",
        policy=engine._quant_lifecycle_policy_from_binding({"profile_id": "aggressive"}),
        drill_mode=True,
    )
    context = {"timeframe": "30m", "market": "CN", "strategy_mode": "live_quant_drill"}

    service._run_live_quant_drill_cooling_review(
        checkpoint=datetime(2026, 1, 5, 10, 0),
        context=context,
        temp_db=temp_db,
        engine=engine,
        portfolio=portfolio,
        manager=manager,
    )
    service._run_live_quant_drill_cooling_review(
        checkpoint=datetime(2026, 1, 6, 10, 0),
        context=context,
        temp_db=temp_db,
        engine=engine,
        portfolio=portfolio,
        manager=manager,
    )

    events = [
        event
        for event in temp_db.list_quant_universe_events(limit=20)
        if event["stock_code"] == "600519" and event["event_type"] == "cooling_review_not_restored"
    ]
    assert len(events) == 1
    assert context["_live_quant_drill_cooling_diagnostic_counts"][("600519", events[0]["reason_code"])] == 2


def test_live_quant_drill_cooling_review_respects_cooling_until(tmp_path):
    service = QuantSimReplayService(
        db_file=str(tmp_path / "live.db"),
        replay_db_file=str(tmp_path / "replay.db"),
        snapshot_provider=DrillSnapshotProvider(),
        adapter=DrillHoldAdapter(),
    )
    temp_db_file = tmp_path / "temp.db"
    temp_db = QuantSimDB(str(temp_db_file))
    CandidatePoolService(db_file=str(temp_db_file)).add_manual_candidate("600519", "贵州茅台", "manual")
    temp_db.upsert_quant_universe_state(
        "600519",
        {
            "quant_status": "cooling",
            "health_score": 20,
            "cooling_until": "2026-01-06T10:00:00Z",
        },
    )
    engine = QuantSimEngine(
        db_file=str(temp_db_file),
        adapter=DrillHoldAdapter(),
        stock_analysis_context_enabled=False,
    )
    portfolio = PortfolioService(db_file=str(temp_db_file))
    manager = QuantUniverseManager(
        db=temp_db,
        profile_id="stable",
        policy=engine._quant_lifecycle_policy_from_binding({"profile_id": "stable"}),
        drill_mode=True,
    )
    engine.build_candidate_review_signal = Mock(side_effect=AssertionError("cooling review should be skipped"))

    result = service._run_live_quant_drill_cooling_review(
        checkpoint=datetime(2026, 1, 5, 10, 0),
        context={"timeframe": "30m", "market": "CN", "strategy_mode": "live_quant_drill"},
        temp_db=temp_db,
        engine=engine,
        portfolio=portfolio,
        manager=manager,
    )

    assert result["reviewed"] == 0


def test_live_quant_drill_daily_first_cooling_review_covers_all_due_cooling(tmp_path):
    service = QuantSimReplayService(
        db_file=str(tmp_path / "live.db"),
        replay_db_file=str(tmp_path / "replay.db"),
        snapshot_provider=DrillSnapshotProvider(),
        adapter=DrillHoldAdapter(),
    )
    temp_db_file = tmp_path / "temp.db"
    temp_db = QuantSimDB(str(temp_db_file))
    candidate_pool = CandidatePoolService(db_file=str(temp_db_file))
    for index in range(12):
        code = f"6001{index:02d}"
        candidate_pool.add_manual_candidate(code, code, "manual")
        temp_db.upsert_quant_universe_state(
            code,
            {
                "quant_status": "cooling",
                "health_score": 20 + index,
                "last_health_evaluated_at": f"2026-01-04T0{index % 10}:00:00Z",
            },
        )
    engine = QuantSimEngine(
        db_file=str(temp_db_file),
        adapter=DrillHoldAdapter(),
        stock_analysis_context_enabled=False,
    )
    portfolio = PortfolioService(db_file=str(temp_db_file))
    manager = QuantUniverseManager(
        db=temp_db,
        profile_id="conservative",
        policy=engine._quant_lifecycle_policy_from_binding({"profile_id": "conservative"}),
        drill_mode=True,
    )

    result = service._run_live_quant_drill_cooling_review(
        checkpoint=datetime(2026, 1, 5, 10, 0),
        context={"timeframe": "30m", "market": "CN", "strategy_mode": "live_quant_drill"},
        temp_db=temp_db,
        engine=engine,
        portfolio=portfolio,
        manager=manager,
    )

    assert result["reviewed"] == 12


def test_live_quant_drill_main_scan_supplements_cooling_to_min_coverage(tmp_path):
    service = QuantSimReplayService(
        db_file=str(tmp_path / "live.db"),
        replay_db_file=str(tmp_path / "replay.db"),
        snapshot_provider=DrillSnapshotProvider(),
        adapter=DrillHoldAdapter(),
    )
    temp_db_file = tmp_path / "temp.db"
    temp_db = QuantSimDB(str(temp_db_file))
    candidate_pool = CandidatePoolService(db_file=str(temp_db_file))
    for code, status, health, score in [
        ("600001", "trial", 70, 0.0),
        ("600002", "active", 80, 0.0),
        ("600003", "cooling", 55, 0.80),
        ("600004", "cooling", 85, 0.70),
        ("600005", "cooling", 40, 0.90),
        ("600006", "cooling", 95, 0.10),
        ("600007", "cooling", 45, 0.60),
    ]:
        candidate_pool.add_manual_candidate(code, code, "manual")
        temp_db.upsert_quant_universe_state(
            code,
            {
                "quant_status": status,
                "health_score": health,
                "candidate_score": score,
                "last_health_evaluated_at": f"2026-01-04T00:0{int(code[-1])}:00Z",
            },
        )
    engine = QuantSimEngine(
        db_file=str(temp_db_file),
        adapter=DrillHoldAdapter(),
        stock_analysis_context_enabled=False,
    )
    portfolio = PortfolioService(db_file=str(temp_db_file))
    manager = QuantUniverseManager(
        db=temp_db,
        profile_id="aggressive",
        policy=engine._quant_lifecycle_policy_from_binding({"profile_id": "aggressive"}),
        drill_mode=True,
    )

    result = service._run_live_quant_drill_main_scan(
        checkpoint=datetime(2026, 1, 5, 10, 0),
        context={"timeframe": "30m", "market": "CN", "strategy_mode": "live_quant_drill", "execute_trades": False},
        temp_db=temp_db,
        engine=engine,
        portfolio=portfolio,
        manager=manager,
    )

    assert result["candidates_scanned"] == manager.policy.min_scan_coverage
    cooling_signals = [
        signal for signal in result["signals"]
        if signal["stock_code"] in {"600003", "600004", "600005", "600007"}
    ]
    assert len(cooling_signals) == 4
    assert all(
        signal["strategy_profile"]["lifecycle_gate"]["mode"] == "cooling_supplemental"
        for signal in cooling_signals
    )


def test_live_quant_drill_new_trial_is_scanned_in_same_checkpoint(tmp_path, monkeypatch):
    service = QuantSimReplayService(
        db_file=str(tmp_path / "live.db"),
        replay_db_file=str(tmp_path / "replay.db"),
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
                "evidence_json": _passing_low_price_evidence(),
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
                "evidence_json": _passing_low_price_evidence(),
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
                "evidence_json": _passing_low_price_evidence(),
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
                "evidence_json": _passing_low_price_evidence(),
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
