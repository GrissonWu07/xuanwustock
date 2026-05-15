from datetime import date, datetime, timezone
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

from app.quant_kernel import replay_engine
from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.signal_center_service import SignalCenterService
from app.quant_sim.scheduler import QuantSimScheduler
from app.quant_sim.quant_universe_lifecycle import QuantUniverseLifecyclePolicy, QuantUniverseManager


def test_scheduler_trading_time_uses_market_timezone_for_cn_hk_and_us():
    assert QuantSimScheduler._is_trading_time(
        "CN",
        now_utc=datetime(2026, 5, 6, 2, 0, tzinfo=timezone.utc),
    )
    assert QuantSimScheduler._is_trading_time(
        "HK",
        now_utc=datetime(2026, 5, 4, 7, 0, tzinfo=timezone.utc),
    )
    assert QuantSimScheduler._is_trading_time(
        "US",
        now_utc=datetime(2026, 5, 4, 14, 0, tzinfo=timezone.utc),
    )
    assert not QuantSimScheduler._is_trading_time(
        "US",
        now_utc=datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc),
    )


def test_scheduler_trading_time_reuses_cn_calendar_for_holidays(monkeypatch):
    monkeypatch.setattr(replay_engine, "HAS_CHINESE_CALENDAR", True)
    monkeypatch.setattr(
        replay_engine,
        "chinese_calendar",
        SimpleNamespace(is_workday=lambda value: False),
        raising=False,
    )

    assert not QuantSimScheduler._is_trading_time(
        "CN",
        now_utc=datetime(2026, 5, 4, 2, 0, tzinfo=timezone.utc),
    )


def test_scheduler_run_once_scans_candidates_and_creates_signals(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate("600000", "浦发银行", "main_force")
    candidate_service.add_manual_candidate("000001", "平安银行", "profit_growth")

    scheduler = QuantSimScheduler(db_file=tmp_path / "app.quant_sim.db")
    monkeypatch.setattr(scheduler, "_is_trading_time", lambda market: True)

    def fake_analyze(candidate, market_snapshot=None):
        if candidate["stock_code"] == "600000":
            return {
                "action": "BUY",
                "confidence": 81,
                "reasoning": "趋势修复",
                "position_size_pct": 20,
            }
        return {
            "action": "HOLD",
            "confidence": 60,
            "reasoning": "继续观察",
            "position_size_pct": 0,
        }

    monkeypatch.setattr(scheduler.engine.adapter, "analyze_candidate", fake_analyze)

    result = scheduler.run_once()

    assert result["candidates_scanned"] == 2
    assert result["signals_created"] == 2
    assert result["positions_checked"] == 0


def test_scheduler_run_once_skips_when_market_is_closed(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate("600000", "浦发银行", "main_force")

    scheduler = QuantSimScheduler(db_file=tmp_path / "app.quant_sim.db")
    monkeypatch.setattr(scheduler, "_is_trading_time", lambda market: False)

    result = scheduler.run_once()

    assert result["skipped"] is True
    assert result["skip_reason"] == "outside_trading_time"
    assert result["candidates_scanned"] == 0
    assert result["signals_created"] == 0
    assert scheduler.engine.candidate_pool.db.get_signals(limit=10) == []


def test_scheduler_tracks_positions_and_generates_followup_signals(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate("600000", "浦发银行", "main_force")
    candidate = candidate_service.list_candidates()[0]
    buy_signal = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 81, "reasoning": "建仓", "position_size_pct": 20},
    )
    portfolio_service.confirm_buy(
        buy_signal["id"],
        price=10.2,
        quantity=100,
        note="已买入",
        executed_at="2026-04-07 10:00:00",
    )

    scheduler = QuantSimScheduler(db_file=tmp_path / "app.quant_sim.db")
    monkeypatch.setattr(scheduler, "_is_trading_time", lambda market: True)

    monkeypatch.setattr(
        scheduler.engine.adapter,
        "analyze_position",
        lambda candidate, position, market_snapshot=None: {
            "action": "SELL",
            "confidence": 74,
            "reasoning": "走弱退出",
            "position_size_pct": 0,
            "decision_type": "dual_track_divergence",
            "tech_score": -0.32,
            "context_score": 0.1,
        },
    )

    result = scheduler.run_once()
    signals = signal_service.list_signals(stock_code="600000")

    assert result["positions_checked"] == 1
    assert result["candidates_scanned"] == 0
    assert result["signals_created"] == 1
    assert signals[0]["action"] == "SELL"
    assert signals[0]["status"] == "pending"


def test_scheduler_supports_background_start_stop_and_persists_run_metadata(tmp_path):
    scheduler = QuantSimScheduler(db_file=tmp_path / "app.quant_sim.db")

    status_before = scheduler.get_status()
    assert status_before["running"] is False
    assert status_before["enabled"] is False
    assert status_before["interval_minutes"] == 10
    assert status_before["analysis_timeframe"] == "30m"
    assert status_before["start_date"] == date.today().isoformat()

    scheduler.update_config(enabled=True, interval_minutes=20, analysis_timeframe="1d+30m", start_date="2026-04-12")
    status_after_config = scheduler.get_status()
    assert status_after_config["enabled"] is True
    assert status_after_config["interval_minutes"] == 20
    assert status_after_config["analysis_timeframe"] == "1d+30m"
    assert status_after_config["start_date"] == "2026-04-12"

    started = scheduler.start()
    status_running = scheduler.get_status()
    assert started is True
    assert status_running["running"] is True

    stopped = scheduler.stop()
    status_stopped = scheduler.get_status()
    assert stopped is True
    assert status_stopped["running"] is False


def test_scheduler_run_once_records_account_snapshot(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate("600000", "浦发银行", "main_force")

    scheduler = QuantSimScheduler(db_file=tmp_path / "app.quant_sim.db")
    monkeypatch.setattr(scheduler, "_is_trading_time", lambda market: True)
    monkeypatch.setattr(
        scheduler.engine.adapter,
        "analyze_candidate",
        lambda candidate, market_snapshot=None: {
            "action": "BUY",
            "confidence": 82,
            "reasoning": "趋势修复",
            "position_size_pct": 20,
        },
    )

    summary = scheduler.run_once()
    snapshots = scheduler.engine.candidate_pool.db.get_account_snapshots(limit=5)

    assert summary["signals_created"] == 1
    assert len(snapshots) == 1
    assert snapshots[0]["run_reason"] == "scheduled_scan"


def test_scheduler_run_once_uses_configured_analysis_timeframe(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate("600000", "浦发银行", "main_force")

    scheduler = QuantSimScheduler(db_file=tmp_path / "app.quant_sim.db")
    scheduler.update_config(enabled=True, analysis_timeframe="1d+30m")
    monkeypatch.setattr(scheduler, "_is_trading_time", lambda market: True)
    captured = {}

    def fake_analyze(candidate, market_snapshot=None, analysis_timeframe="1d"):
        captured["analysis_timeframe"] = analysis_timeframe
        return {
            "action": "BUY",
            "confidence": 82,
            "reasoning": "趋势修复",
            "position_size_pct": 20,
        }

    monkeypatch.setattr(scheduler.engine.adapter, "analyze_candidate", fake_analyze)

    scheduler.run_once()

    assert captured["analysis_timeframe"] == "1d+30m"


def test_scheduler_run_once_passes_one_live_current_time_to_candidate_and_position_analysis(tmp_path, monkeypatch):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)
    portfolio_service = PortfolioService(db_file=db_file)
    candidate_service.add_manual_candidate("600000", "浦发银行", "main_force")
    candidate_service.add_manual_candidate("300750", "宁德时代", "main_force")
    held_candidate = next(item for item in candidate_service.list_candidates() if item["stock_code"] == "300750")
    buy_signal = signal_service.create_signal(
        held_candidate,
        {
            "action": "BUY",
            "confidence": 82,
            "reasoning": "建仓",
            "position_size_pct": 20,
        },
    )
    portfolio_service.confirm_buy(
        buy_signal["id"],
        price=201.5,
        quantity=100,
        note="已买入",
        executed_at="2026-04-07 10:00:00",
    )
    scheduler = QuantSimScheduler(db_file=db_file)
    scheduler.update_config(enabled=True, analysis_timeframe="30m")
    current_time = datetime(2026, 5, 8, 10, 30)
    captured = {"candidate": [], "position": []}

    monkeypatch.setattr(scheduler, "_is_trading_time", lambda market: True)
    monkeypatch.setattr(scheduler, "_decision_time", lambda: current_time)

    def fake_analyze_candidate(payload, **kwargs):
        captured["candidate"].append(kwargs.get("current_time"))
        return {
            "action": "HOLD",
            "confidence": 61,
            "reasoning": "等待确认",
            "position_size_pct": 0,
        }

    def fake_analyze_position(candidate, position, **kwargs):
        del candidate, position
        captured["position"].append(kwargs.get("current_time"))
        return {
            "action": "HOLD",
            "confidence": 63,
            "reasoning": "继续观察",
            "position_size_pct": 0,
        }

    monkeypatch.setattr(scheduler.engine.adapter, "analyze_candidate", fake_analyze_candidate)
    monkeypatch.setattr(scheduler.engine.adapter, "analyze_position", fake_analyze_position)

    scheduler.run_once()

    assert captured == {"candidate": [current_time], "position": [current_time]}


def test_scheduled_cycle_skips_before_start_date(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate("600000", "浦发银行", "main_force")

    scheduler = QuantSimScheduler(db_file=tmp_path / "app.quant_sim.db")
    scheduler.update_config(enabled=True, start_date="2099-01-01")
    called = {"count": 0}

    def fail_if_called(*args, **kwargs):
        called["count"] += 1
        raise AssertionError("run_once should not execute before configured start_date")

    monkeypatch.setattr(scheduler, "run_once", fail_if_called)

    scheduler._run_scheduled_cycle()

    assert called["count"] == 0


def test_scheduled_cycle_always_skips_outside_trading_time(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate("600000", "浦发银行", "main_force")

    scheduler = QuantSimScheduler(db_file=tmp_path / "app.quant_sim.db")
    scheduler.update_config(enabled=True, trading_hours_only=False, start_date="2000-01-01")
    called = {"count": 0}

    def fail_if_called(*args, **kwargs):
        called["count"] += 1
        raise AssertionError("scheduled live simulation must not run outside trading time")

    monkeypatch.setattr(scheduler, "_is_trading_time", lambda market: False)
    monkeypatch.setattr(scheduler, "run_once", fail_if_called)

    scheduler._run_scheduled_cycle()

    assert called["count"] == 0


def test_scheduler_run_once_passes_strategy_mode_to_engine(tmp_path, monkeypatch):
    scheduler = QuantSimScheduler(db_file=tmp_path / "app.quant_sim.db")
    scheduler.db.update_scheduler_config(strategy_mode="neutral")
    current_time = datetime(2026, 5, 8, 10, 30)
    monkeypatch.setattr(scheduler, "_is_trading_time", lambda market: True)
    monkeypatch.setattr(scheduler, "_decision_time", lambda: current_time)

    scheduler.engine.analyze_active_candidates = Mock(return_value=[])
    scheduler.engine.analyze_positions = Mock(return_value=[])
    scheduler.portfolio.list_positions = Mock(return_value=[])

    scheduler.run_once("manual_scan")

    scheduler.engine.analyze_active_candidates.assert_called_once_with(
        analysis_timeframe="30m",
        strategy_mode="neutral",
        ai_dynamic_strategy="off",
        ai_dynamic_strength=0.5,
        ai_dynamic_lookback=48,
        current_time=current_time,
        candidates_override=[],
    )
    scheduler.engine.analyze_positions.assert_called_once_with(
        analysis_timeframe="30m",
        strategy_mode="neutral",
        ai_dynamic_strategy="off",
        ai_dynamic_strength=0.5,
        ai_dynamic_lookback=48,
        current_time=current_time,
    )


def test_scheduler_run_once_sets_adapter_market_before_analysis(tmp_path, monkeypatch):
    scheduler = QuantSimScheduler(db_file=tmp_path / "app.quant_sim.db")
    scheduler.db.update_scheduler_config(market="US")
    monkeypatch.setattr(scheduler, "_is_trading_time", lambda market: True)
    captured: dict[str, str] = {}

    def capture_market(market):
        captured["market"] = market

    monkeypatch.setattr(scheduler.engine.adapter, "set_market", capture_market)
    scheduler.engine.analyze_active_candidates = Mock(return_value=[])
    scheduler.engine.analyze_positions = Mock(return_value=[])
    scheduler.portfolio.list_positions = Mock(return_value=[])

    scheduler.run_once("manual_scan")

    assert captured["market"] == "US"


def test_scheduler_opportunistic_review_rotates_cooling_stocks_by_oldest_review(tmp_path, monkeypatch):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    for index in range(7):
        code = f"60010{index}"
        candidate_service.add_manual_candidate(code, code, "manual")
        candidate_service.db.upsert_quant_universe_state(
            code,
            {
                "quant_status": "cooling",
                "health_score": 20 + index,
                "last_health_evaluated_at": f"2026-05-08T00:0{index}:00Z",
            },
        )
    scheduler = QuantSimScheduler(db_file=db_file)
    monkeypatch.setattr(scheduler, "_is_trading_time", lambda market: True)
    scheduler.engine.analyze_active_candidates = Mock(return_value=[])
    scheduler.engine.analyze_positions = Mock(return_value=[])
    scheduler.portfolio.list_positions = Mock(return_value=[])
    reviewed: list[str] = []

    def fake_build_review_signal(candidate, **kwargs):
        del kwargs
        reviewed.append(candidate["stock_code"])
        return {
            "id": 0,
            "stock_code": candidate["stock_code"],
            "stock_name": candidate.get("stock_name"),
            "action": "HOLD",
            "tech_score": -0.5,
            "context_score": 0.0,
            "strategy_profile": {},
            "status": "review",
        }

    monkeypatch.setattr(scheduler.engine, "build_candidate_review_signal", fake_build_review_signal)

    result = scheduler.run_once("manual_scan")

    assert result["cooling_reviewed"] == 7
    assert reviewed == ["600100", "600101", "600102", "600103", "600104", "600105", "600106"]


def test_live_scan_supplements_cooling_when_below_min_coverage(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    for code, status, health, score in [
        ("600001", "trial", 70, 0.0),
        ("600002", "active", 80, 0.0),
        ("600003", "cooling", 55, 0.80),
        ("600004", "cooling", 85, 0.70),
        ("600005", "cooling", 40, 0.90),
        ("600006", "cooling", 95, 0.10),
        ("600007", "cooling", 45, 0.60),
    ]:
        candidate_service.add_manual_candidate(code, code, "manual")
        candidate_service.db.upsert_quant_universe_state(
            code,
            {
                "quant_status": status,
                "health_score": health,
                "candidate_score": score,
                "last_health_evaluated_at": f"2026-05-08T00:0{int(code[-1])}:00Z",
            },
        )
    scheduler = QuantSimScheduler(db_file=db_file)
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()

    candidates = scheduler.engine.list_live_scan_candidates(policy=policy)

    assert len(candidates) == policy.min_scan_coverage
    assert [item["stock_code"] for item in candidates[:2]] == ["600002", "600001"]
    supplemental = candidates[2:]
    assert {item["quant_status"] for item in supplemental} == {"cooling"}
    assert all(item["lifecycle_gate"]["mode"] == "cooling_supplemental" for item in supplemental)
    assert [item["stock_code"] for item in supplemental] == ["600005", "600003", "600004", "600007"]


def test_scheduler_opportunistic_review_keeps_cooling_without_consecutive_confirmation(tmp_path, monkeypatch):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_manual_candidate("600000", "浦发银行", "manual")
    candidate_service.db.upsert_quant_universe_state("600000", {"quant_status": "cooling", "health_score": 100})
    scheduler = QuantSimScheduler(db_file=db_file)
    monkeypatch.setattr(scheduler, "_is_trading_time", lambda market: True)
    scheduler.engine.analyze_active_candidates = Mock(return_value=[])
    scheduler.engine.analyze_positions = Mock(return_value=[])
    scheduler.portfolio.list_positions = Mock(return_value=[])

    def fake_build_review_signal(candidate, **kwargs):
        del kwargs
        return {
            "id": 0,
            "stock_code": candidate["stock_code"],
            "stock_name": candidate.get("stock_name"),
            "action": "BUY",
            "tech_score": 0.7,
            "context_score": 0.1,
            "price": 12.0,
            "ma20": 11.5,
            "ma20_slope": 0.05,
            "strategy_profile": {
                "explainability": {"fusion_breakdown": {"fusion_score": 0.75, "fusion_score_delta": 0.2}},
                "portfolio_execution_guard": {"status": "strong_buy", "buy_strength_score": 0.7},
            },
            "status": "review",
        }

    monkeypatch.setattr(scheduler.engine, "build_candidate_review_signal", fake_build_review_signal)

    result = scheduler.run_once("manual_scan")

    assert result["candidates_scanned"] == 1
    assert result["cooling_reviewed"] == 1
    assert candidate_service.db.get_quant_universe_state("600000")["quant_status"] == "cooling"


def test_scheduler_opportunistic_review_skips_cooling_until_and_recent_reviews(tmp_path, monkeypatch):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    rows = {
        "600001": {"cooling_until": "2026-05-08T00:30:00Z", "last_health_evaluated_at": "2026-05-07T20:00:00Z"},
        "600002": {"last_health_evaluated_at": "2026-05-08T00:05:00Z"},
        "600003": {"last_health_evaluated_at": "2026-05-07T20:00:00Z"},
    }
    for code, state in rows.items():
        candidate_service.add_manual_candidate(code, code, "manual")
        candidate_service.db.upsert_quant_universe_state(
            code,
            {
                "quant_status": "cooling",
                "health_score": 20,
                **state,
            },
        )
    scheduler = QuantSimScheduler(db_file=db_file)
    monkeypatch.setattr(scheduler, "_is_trading_time", lambda market: True)
    monkeypatch.setattr(scheduler, "_decision_time", lambda: datetime(2026, 5, 8, 0, 10))
    scheduler.engine.analyze_active_candidates = Mock(return_value=[])
    scheduler.engine.analyze_positions = Mock(return_value=[])
    scheduler.portfolio.list_positions = Mock(return_value=[])
    reviewed: list[str] = []

    def fake_build_review_signal(candidate, **kwargs):
        del kwargs
        reviewed.append(candidate["stock_code"])
        return {
            "id": 0,
            "stock_code": candidate["stock_code"],
            "stock_name": candidate.get("stock_name"),
            "action": "HOLD",
            "decision_time": "2026-05-08T00:10:00Z",
            "tech_score": -0.5,
            "context_score": 0.0,
            "strategy_profile": {},
            "status": "review",
        }

    monkeypatch.setattr(scheduler.engine, "build_candidate_review_signal", fake_build_review_signal)

    result = scheduler.run_once("manual_scan")

    assert result["cooling_reviewed"] == 1
    assert reviewed == ["600003"]


def test_scheduler_forces_cooling_review_when_candidate_event_is_queued(tmp_path, monkeypatch):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_manual_candidate("600000", "浦发银行", "manual")
    candidate_service.db.update_quant_universe_settings(
        {"auto_entry_mode": "auto_trial", "quant_universe_lifecycle_enabled": True, "auto_exit_enabled": True}
    )
    candidate_service.db.upsert_quant_universe_state(
        "600000",
        {
            "quant_status": "cooling",
            "health_score": 72,
            "candidate_score": 0.0,
            "cooling_until": "2099-01-01T00:00:00Z",
            "last_health_evaluated_at": "2026-05-08T00:05:00Z",
        },
    )
    manager = QuantUniverseManager(
        db=candidate_service.db,
        policy=QuantUniverseLifecyclePolicy.aggressive_defaults(),
        profile_id="aggressive",
    )
    decision = manager.ingest_candidate_event(
        {
            "stock_code": "600000",
            "source_type": "low_price",
            "source_score": 0.92,
            "confidence": 0.9,
            "trend": "up",
            "occurred_at": "2026-05-08T00:10:00Z",
            "payload_json": {
                "price": 8.8,
                "ma5": 9.2,
                "ma10": 9.0,
                "ma20": 8.6,
                "ma20_slope": 0.02,
                "amount": 80_000_000,
                "volume_ratio": 1.5,
                "rsi": 62,
                "macd": 0.05,
            },
        }
    )
    assert decision["decision"] == "cooling_review_queued"

    scheduler = QuantSimScheduler(db_file=db_file)
    monkeypatch.setattr(scheduler, "_is_trading_time", lambda market: True)
    monkeypatch.setattr(scheduler, "_decision_time", lambda: datetime(2026, 5, 8, 0, 10, tzinfo=timezone.utc))
    scheduler.engine.analyze_active_candidates = Mock(return_value=[])
    scheduler.engine.analyze_positions = Mock(return_value=[])
    scheduler.portfolio.list_positions = Mock(return_value=[])
    reviewed: list[str] = []

    def fake_build_review_signal(candidate, **kwargs):
        del kwargs
        reviewed.append(candidate["stock_code"])
        return {
            "id": 0,
            "stock_code": candidate["stock_code"],
            "stock_name": candidate.get("stock_name"),
            "action": "BUY",
            "tech_score": 0.72,
            "context_score": 0.18,
            "price": 12.0,
            "ma20": 11.2,
            "ma20_slope": 0.05,
            "strategy_profile": {
                "portfolio_execution_guard": {"buy_tier": "normal_buy", "buy_strength_score": 0.68},
                "execution_sizing_plan": {"effective_position_pct": 0.06, "final_budget": 24000.0},
            },
            "status": "review",
        }

    monkeypatch.setattr(scheduler.engine, "build_candidate_review_signal", fake_build_review_signal)

    result = scheduler.run_once("manual_scan")

    assert result["cooling_reviewed"] == 1
    assert reviewed == ["600000"]
    assert candidate_service.db.get_quant_universe_state("600000")["quant_status"] == "trial"


def test_scheduler_restores_background_job_from_persisted_config(tmp_path, monkeypatch):
    first_scheduler = QuantSimScheduler(db_file=tmp_path / "app.quant_sim.db")
    first_scheduler.update_config(enabled=True, interval_minutes=20, analysis_timeframe="30m")
    first_scheduler.stop()

    started = {"count": 0}

    def fake_start(self):
        started["count"] += 1
        self.running = True
        return True

    monkeypatch.setattr(QuantSimScheduler, "start", fake_start)

    restored_scheduler = QuantSimScheduler(db_file=tmp_path / "app.quant_sim.db")

    assert started["count"] == 1
    assert restored_scheduler.get_status()["enabled"] is True
    assert restored_scheduler.get_status()["running"] is True


def test_schedule_loop_survives_transient_database_lock(tmp_path, monkeypatch):
    scheduler = QuantSimScheduler(db_file=tmp_path / "app.quant_sim.db", poll_seconds=0)
    calls = {"count": 0}

    def fake_run_pending():
        calls["count"] += 1
        if calls["count"] == 1:
            raise sqlite3.OperationalError("database is locked")
        scheduler.running = False
        scheduler.stop_event.set()

    monkeypatch.setattr(scheduler.scheduler, "run_pending", fake_run_pending)

    scheduler.running = True
    scheduler._schedule_loop()

    assert calls["count"] == 2
