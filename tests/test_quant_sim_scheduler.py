from datetime import date
import sqlite3
from unittest.mock import Mock

from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.signal_center_service import SignalCenterService
from app.quant_sim.scheduler import QuantSimScheduler


def test_scheduler_run_once_scans_candidates_and_creates_signals(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate("600000", "浦发银行", "main_force")
    candidate_service.add_manual_candidate("000001", "平安银行", "profit_growth")

    scheduler = QuantSimScheduler(db_file=tmp_path / "app.quant_sim.db")

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
    assert status_before["interval_minutes"] == 15
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


def test_scheduler_run_once_passes_strategy_mode_to_engine(tmp_path):
    scheduler = QuantSimScheduler(db_file=tmp_path / "app.quant_sim.db")
    scheduler.db.update_scheduler_config(strategy_mode="neutral")

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
    )
    scheduler.engine.analyze_positions.assert_called_once_with(
        analysis_timeframe="30m",
        strategy_mode="neutral",
        ai_dynamic_strategy="off",
        ai_dynamic_strength=0.5,
        ai_dynamic_lookback=48,
    )


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
