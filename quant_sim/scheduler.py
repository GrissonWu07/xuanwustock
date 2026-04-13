"""Background scheduler for interval-based quant simulation analysis."""

from __future__ import annotations

import threading
from datetime import date, datetime
from pathlib import Path

import schedule

from quant_sim.db import DEFAULT_DB_FILE, QuantSimDB
from quant_sim.engine import QuantSimEngine
from quant_sim.portfolio_service import PortfolioService


TRADING_HOURS = {
    "CN": [("09:30", "11:30"), ("13:00", "15:00")],
    "HK": [("09:30", "12:00"), ("13:00", "16:00")],
    "US": [("21:30", "04:00")],
}
TRADING_DAYS = {1, 2, 3, 4, 5}
_SCHEDULER_INSTANCES: dict[str, "QuantSimScheduler"] = {}


class QuantSimScheduler:
    """Run one-off or interval-based refresh cycles for quant simulation."""

    def __init__(
        self,
        db_file: str | Path = DEFAULT_DB_FILE,
        poll_seconds: float = 30.0,
        watchlist_db_file: str | Path = "watchlist.db",
    ):
        self.db_file = str(db_file)
        self.watchlist_db_file = str(watchlist_db_file)
        self.db = QuantSimDB(db_file)
        self.engine = QuantSimEngine(db_file=db_file, watchlist_db_file=watchlist_db_file)
        self.portfolio = PortfolioService(db_file=db_file)
        self.scheduler = schedule.Scheduler()
        self.poll_seconds = poll_seconds
        self.running = False
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.job_tag = f"quant_sim::{self.db_file}"
        self._restore_running_state()

    def run_once(self, run_reason: str = "scheduled_scan") -> dict[str, int | float]:
        config = self.db.get_scheduler_config()
        analysis_timeframe = str(config["analysis_timeframe"])
        strategy_mode = str(config["strategy_mode"])
        candidates = self.engine.candidate_pool.list_candidates(status="active")
        positions = self.portfolio.list_positions()
        candidate_signals = self.engine.analyze_active_candidates(
            analysis_timeframe=analysis_timeframe,
            strategy_mode=strategy_mode,
        )
        position_signals = self.engine.analyze_positions(
            analysis_timeframe=analysis_timeframe,
            strategy_mode=strategy_mode,
        )
        auto_executed = self._auto_execute_pending_signals()
        snapshot_id = self.db.add_account_snapshot(run_reason)
        self.db.update_scheduler_config(last_run_at=self._now())
        account_summary = self.portfolio.get_account_summary()
        return {
            "candidates_scanned": len(candidates),
            "signals_created": len(candidate_signals) + len(position_signals),
            "positions_checked": len(positions),
            "auto_executed": auto_executed,
            "snapshot_id": snapshot_id,
            "total_equity": account_summary["total_equity"],
        }

    def update_config(
        self,
        *,
        enabled: bool | None = None,
        auto_execute: bool | None = None,
        interval_minutes: int | None = None,
        trading_hours_only: bool | None = None,
        analysis_timeframe: str | None = None,
        strategy_mode: str | None = None,
        start_date: str | None = None,
        market: str | None = None,
    ) -> None:
        self.db.update_scheduler_config(
            enabled=enabled,
            auto_execute=auto_execute,
            interval_minutes=interval_minutes,
            trading_hours_only=trading_hours_only,
            analysis_timeframe=analysis_timeframe,
            strategy_mode=strategy_mode,
            start_date=start_date,
            market=market,
        )
        if self.running:
            config = self.db.get_scheduler_config()
            if not config["enabled"]:
                self.stop()
                return
            self._register_jobs(config["interval_minutes"])

    def get_status(self) -> dict[str, object]:
        config = self.db.get_scheduler_config()
        jobs = self.scheduler.get_jobs(self.job_tag)
        next_run = jobs[0].next_run.strftime("%Y-%m-%d %H:%M:%S") if jobs else None
        return {
            "running": self.running,
            "enabled": config["enabled"],
            "auto_execute": config["auto_execute"],
            "interval_minutes": config["interval_minutes"],
            "trading_hours_only": config["trading_hours_only"],
            "analysis_timeframe": config["analysis_timeframe"],
            "strategy_mode": config["strategy_mode"],
            "start_date": config["start_date"],
            "market": config["market"],
            "last_run_at": config["last_run_at"],
            "next_run": next_run,
        }

    def start(self) -> bool:
        if self.running:
            return False

        config = self.db.get_scheduler_config()
        if not config["enabled"]:
            return False

        self.running = True
        self.stop_event.clear()
        self._register_jobs(config["interval_minutes"])
        self.thread = threading.Thread(target=self._schedule_loop, daemon=True)
        self.thread.start()
        return True

    def stop(self) -> bool:
        if not self.running:
            self._clear_jobs()
            return False

        self.running = False
        self.stop_event.set()
        self._clear_jobs()
        if self.thread:
            self.thread.join(timeout=5)
            self.thread = None
        return True

    def _schedule_loop(self) -> None:
        while self.running and not self.stop_event.is_set():
            try:
                self.scheduler.run_pending()
            finally:
                self.stop_event.wait(self.poll_seconds)

    def _run_scheduled_cycle(self) -> None:
        config = self.db.get_scheduler_config()
        if not self._has_reached_start_date(str(config["start_date"])):
            return
        if config["trading_hours_only"] and not self._is_trading_time(config["market"]):
            return
        self.run_once(run_reason="scheduled_scan")

    def _auto_execute_pending_signals(self) -> int:
        config = self.db.get_scheduler_config()
        if not config["auto_execute"]:
            return 0

        executed = 0
        for signal in self.engine.signal_center.list_pending_signals():
            if self.portfolio.auto_execute_signal(signal):
                executed += 1
        return executed

    def _register_jobs(self, interval_minutes: int) -> None:
        self._clear_jobs()
        self.scheduler.every(interval_minutes).minutes.do(self._run_scheduled_cycle).tag(self.job_tag)

    def _clear_jobs(self) -> None:
        for job in self.scheduler.get_jobs(self.job_tag):
            self.scheduler.cancel_job(job)

    def _restore_running_state(self) -> None:
        config = self.db.get_scheduler_config()
        if config["enabled"] and not self.running:
            self.start()

    @staticmethod
    def _is_trading_time(market: str) -> bool:
        now = datetime.now()
        weekday = now.weekday() + 1
        if weekday not in TRADING_DAYS:
            return False

        current_time = now.time()
        for start_str, end_str in TRADING_HOURS.get(market or "CN", TRADING_HOURS["CN"]):
            start_time = datetime.strptime(start_str, "%H:%M").time()
            end_time = datetime.strptime(end_str, "%H:%M").time()
            if start_time <= end_time:
                if start_time <= current_time <= end_time:
                    return True
            else:
                if current_time >= start_time or current_time <= end_time:
                    return True
        return False

    @staticmethod
    def _now() -> str:
        return datetime.now().replace(microsecond=0).isoformat(sep=" ")

    @staticmethod
    def _has_reached_start_date(start_date_text: str) -> bool:
        try:
            configured_date = date.fromisoformat(str(start_date_text))
        except ValueError:
            return True
        return datetime.now().date() >= configured_date


def get_quant_sim_scheduler(
    db_file: str | Path = DEFAULT_DB_FILE,
    watchlist_db_file: str | Path = "watchlist.db",
) -> QuantSimScheduler:
    key = f"{db_file}::{watchlist_db_file}"
    scheduler = _SCHEDULER_INSTANCES.get(key)
    if scheduler is None:
        scheduler = QuantSimScheduler(db_file=db_file, watchlist_db_file=watchlist_db_file)
        _SCHEDULER_INSTANCES[key] = scheduler
    return scheduler
