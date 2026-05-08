"""Background scheduler for interval-based quant simulation analysis."""

from __future__ import annotations

import threading
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import schedule

from app.db.runtime.registry import DatabaseRuntime
from app.quant_sim.db import DEFAULT_DB_FILE, QuantSimDB
from app.quant_sim.dynamic_strategy import (
    DEFAULT_AI_DYNAMIC_LOOKBACK,
    DEFAULT_AI_DYNAMIC_STRENGTH,
    DEFAULT_AI_DYNAMIC_STRATEGY,
)
from app.quant_sim.engine import QuantSimEngine
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.quant_universe_lifecycle import QuantUniverseManager
from app.quant_sim.time_utils import format_utc_iso_z, market_timezone
TRADING_HOURS = {
    "CN": [("09:30", "11:30"), ("13:00", "15:00")],
    "HK": [("09:30", "12:00"), ("13:00", "16:00")],
    "US": [("09:30", "16:00")],
}
TRADING_DAYS = {1, 2, 3, 4, 5}
_SCHEDULER_INSTANCES: dict[str, "QuantSimScheduler"] = {}
logger = logging.getLogger(__name__)


class QuantSimScheduler:
    """Run one-off or interval-based refresh cycles for quant simulation."""

    def __init__(
        self,
        db_file: str | Path = DEFAULT_DB_FILE,
        poll_seconds: float = 30.0,
        stock_analysis_db_file: str | Path | None = None,
        db_runtime: DatabaseRuntime | None = None,
    ):
        self.db_file = str(db_file)
        self.stock_analysis_db_file = str(stock_analysis_db_file or db_file)
        self.db_runtime = db_runtime
        self.db = QuantSimDB(db_file, db_runtime=db_runtime)
        self.engine = QuantSimEngine(
            db_file=db_file,
            stock_analysis_db_file=self.stock_analysis_db_file,
            db_runtime=db_runtime,
        )
        self.portfolio = PortfolioService(db_file=db_file, db_runtime=db_runtime)
        self.scheduler = schedule.Scheduler()
        self.poll_seconds = poll_seconds
        self.running = False
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.job_tag = f"quant_sim::{self.db_file}"
        self._restore_running_state()

    def run_once(self, run_reason: str = "scheduled_scan") -> dict[str, int | float]:
        config = self.db.get_scheduler_config()
        if not self._is_trading_time(str(config["market"])):
            return {
                "skipped": True,
                "skip_reason": "outside_trading_time",
                "candidates_scanned": 0,
                "signals_created": 0,
                "positions_checked": 0,
                "cooling_reviewed": 0,
                "auto_executed": 0,
                "snapshot_id": 0,
                "total_equity": self.portfolio.get_account_summary()["total_equity"],
            }
        analysis_timeframe = str(config["analysis_timeframe"])
        strategy_mode = str(config["strategy_mode"])
        market = str(config["market"])
        current_time = self._decision_time()
        if hasattr(self.engine.adapter, "set_market"):
            self.engine.adapter.set_market(market)
        configured_profile_id = str(config.get("strategy_profile_id") or "").strip()
        default_profile_id = self.db.get_default_strategy_profile_id()
        strategy_profile_id = configured_profile_id if configured_profile_id and configured_profile_id != default_profile_id else None
        lifecycle_profile_id = configured_profile_id or default_profile_id
        ai_dynamic_strategy = str(config.get("ai_dynamic_strategy") or DEFAULT_AI_DYNAMIC_STRATEGY).strip().lower()
        ai_dynamic_strength = float(config.get("ai_dynamic_strength") or DEFAULT_AI_DYNAMIC_STRENGTH)
        ai_dynamic_lookback = int(config.get("ai_dynamic_lookback") or DEFAULT_AI_DYNAMIC_LOOKBACK)
        positions = self.portfolio.list_positions()
        held_codes = {str(item.get("stock_code") or "").strip() for item in positions if str(item.get("stock_code") or "").strip()}
        candidates = [
            item for item in self.engine.list_live_scan_candidates(exclude_codes=held_codes)
        ]
        candidate_kwargs = {
            "analysis_timeframe": analysis_timeframe,
            "strategy_mode": strategy_mode,
            "ai_dynamic_strategy": ai_dynamic_strategy,
            "ai_dynamic_strength": ai_dynamic_strength,
            "ai_dynamic_lookback": ai_dynamic_lookback,
            "current_time": current_time,
        }
        if strategy_profile_id:
            candidate_kwargs["strategy_profile_id"] = strategy_profile_id
        if held_codes:
            candidate_kwargs["exclude_codes"] = held_codes
        candidate_signals = self.engine.analyze_active_candidates(
            **candidate_kwargs,
        )
        position_kwargs = {
            "analysis_timeframe": analysis_timeframe,
            "strategy_mode": strategy_mode,
            "ai_dynamic_strategy": ai_dynamic_strategy,
            "ai_dynamic_strength": ai_dynamic_strength,
            "ai_dynamic_lookback": ai_dynamic_lookback,
            "current_time": current_time,
        }
        if strategy_profile_id:
            position_kwargs["strategy_profile_id"] = strategy_profile_id
        position_signals = self.engine.analyze_positions(**position_kwargs)
        cooling_reviewed = self._opportunistic_cooling_review(lifecycle_profile_id)
        auto_executed = self._auto_execute_pending_signals()
        snapshot_id = self.db.add_account_snapshot(run_reason)
        self.db.update_scheduler_config(last_run_at=self._now())
        account_summary = self.portfolio.get_account_summary()
        return {
            "candidates_scanned": len(candidates),
            "signals_created": len(candidate_signals) + len(position_signals),
            "positions_checked": len(positions),
            "cooling_reviewed": cooling_reviewed,
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
        strategy_profile_id: str | None = None,
        ai_dynamic_strategy: str | None = None,
        ai_dynamic_strength: float | None = None,
        ai_dynamic_lookback: int | None = None,
        start_date: str | None = None,
        market: str | None = None,
        commission_rate: float | None = None,
        sell_tax_rate: float | None = None,
        capital_slot_enabled: bool | None = None,
        capital_pool_min_cash: float | None = None,
        capital_pool_max_cash: float | None = None,
        capital_slot_min_cash: float | None = None,
        capital_max_slots: int | None = None,
        capital_min_buy_slot_fraction: float | None = None,
        capital_full_buy_edge: float | None = None,
        capital_confidence_weight: float | None = None,
        capital_high_price_threshold: float | None = None,
        capital_high_price_max_slot_units: float | None = None,
        capital_sell_cash_reuse_policy: str | None = None,
    ) -> None:
        self.db.update_scheduler_config(
            enabled=enabled,
            auto_execute=auto_execute,
            interval_minutes=interval_minutes,
            trading_hours_only=trading_hours_only,
            analysis_timeframe=analysis_timeframe,
            strategy_mode=strategy_mode,
            strategy_profile_id=strategy_profile_id,
            ai_dynamic_strategy=ai_dynamic_strategy,
            ai_dynamic_strength=ai_dynamic_strength,
            ai_dynamic_lookback=ai_dynamic_lookback,
            start_date=start_date,
            market=market,
            commission_rate=commission_rate,
            sell_tax_rate=sell_tax_rate,
            capital_slot_enabled=capital_slot_enabled,
            capital_pool_min_cash=capital_pool_min_cash,
            capital_pool_max_cash=capital_pool_max_cash,
            capital_slot_min_cash=capital_slot_min_cash,
            capital_max_slots=capital_max_slots,
            capital_min_buy_slot_fraction=capital_min_buy_slot_fraction,
            capital_full_buy_edge=capital_full_buy_edge,
            capital_confidence_weight=capital_confidence_weight,
            capital_high_price_threshold=capital_high_price_threshold,
            capital_high_price_max_slot_units=capital_high_price_max_slot_units,
            capital_sell_cash_reuse_policy=capital_sell_cash_reuse_policy,
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
        next_run = format_utc_iso_z(jobs[0].next_run.astimezone()) if jobs else None
        return {
            "running": self.running,
            "enabled": config["enabled"],
            "auto_execute": config["auto_execute"],
            "interval_minutes": config["interval_minutes"],
            "trading_hours_only": config["trading_hours_only"],
            "analysis_timeframe": config["analysis_timeframe"],
            "strategy_mode": config["strategy_mode"],
            "strategy_profile_id": config.get("strategy_profile_id"),
            "ai_dynamic_strategy": config.get("ai_dynamic_strategy"),
            "ai_dynamic_strength": config.get("ai_dynamic_strength"),
            "ai_dynamic_lookback": config.get("ai_dynamic_lookback"),
            "start_date": config["start_date"],
            "market": config["market"],
            "commission_rate": config["commission_rate"],
            "sell_tax_rate": config["sell_tax_rate"],
            "capital_slot_enabled": config.get("capital_slot_enabled"),
            "capital_pool_min_cash": config.get("capital_pool_min_cash"),
            "capital_pool_max_cash": config.get("capital_pool_max_cash"),
            "capital_slot_min_cash": config.get("capital_slot_min_cash"),
            "capital_max_slots": config.get("capital_max_slots"),
            "capital_min_buy_slot_fraction": config.get("capital_min_buy_slot_fraction"),
            "capital_full_buy_edge": config.get("capital_full_buy_edge"),
            "capital_confidence_weight": config.get("capital_confidence_weight"),
            "capital_high_price_threshold": config.get("capital_high_price_threshold"),
            "capital_high_price_max_slot_units": config.get("capital_high_price_max_slot_units"),
            "capital_sell_cash_reuse_policy": config.get("capital_sell_cash_reuse_policy"),
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
            except Exception as exc:
                if "database is locked" in str(exc).lower():
                    logger.warning("quant sim scheduler skipped one cycle because database is locked; next cycle will continue")
                else:
                    logger.exception("quant sim scheduler cycle failed; next cycle will continue")
            finally:
                self.stop_event.wait(self.poll_seconds)

    def _run_scheduled_cycle(self) -> None:
        config = self.db.get_scheduler_config()
        market = str(config["market"])
        if not self._has_reached_start_date(str(config["start_date"]), market):
            return
        if not self._is_trading_time(market):
            return
        self.run_once(run_reason="scheduled_scan")

    def _auto_execute_pending_signals(self) -> int:
        config = self.db.get_scheduler_config()
        if not config["auto_execute"]:
            return 0

        return self.portfolio.auto_execute_pending_signals(self.engine.signal_center.list_pending_signals())

    def _opportunistic_cooling_review(self, strategy_profile_id: str | None = None) -> int:
        settings = self.db.get_quant_universe_settings()
        if not settings["quant_universe_lifecycle_enabled"] or not settings["auto_exit_enabled"]:
            return 0
        policy = self.engine._quant_lifecycle_policy_from_binding({"profile_id": strategy_profile_id or ""})
        rows = self.db.list_quant_universe_state(statuses=["cooling"], limit=1000)["items"]
        rows.sort(
            key=lambda item: (
                float(item.get("health_score") or 0),
                str(item.get("last_health_evaluated_at") or ""),
                str(item.get("stock_code") or ""),
            )
        )
        selected = rows[: min(5, len(rows))]
        if not selected:
            return 0
        manager = QuantUniverseManager(db=self.db, profile_id=policy.profile_id, policy=policy)
        for item in selected:
            manager.evaluate_candidate(str(item.get("stock_code") or ""))
        return len(selected)

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
    def _market_now(market: str, now_utc: datetime | None = None) -> datetime:
        base = now_utc or datetime.now(timezone.utc)
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        return base.astimezone(market_timezone(market))

    @classmethod
    def _is_trading_time(cls, market: str, *, now_utc: datetime | None = None) -> bool:
        now = cls._market_now(market, now_utc)
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
    def _decision_time() -> datetime:
        return datetime.now().replace(microsecond=0)

    @staticmethod
    def _now() -> str:
        return format_utc_iso_z()

    @classmethod
    def _has_reached_start_date(cls, start_date_text: str, market: str = "CN") -> bool:
        try:
            configured_date = date.fromisoformat(str(start_date_text))
        except ValueError:
            return True
        return cls._market_now(market).date() >= configured_date


def get_quant_sim_scheduler(
    db_file: str | Path = DEFAULT_DB_FILE,
    stock_analysis_db_file: str | Path | None = None,
    db_runtime: DatabaseRuntime | None = None,
) -> QuantSimScheduler:
    runtime_key = ""
    if db_runtime is not None:
        runtime_key = f"::{db_runtime.config.backend}:{db_runtime.config.primary_url}:{db_runtime.config.replay_url}"
    effective_stock_analysis_db_file = stock_analysis_db_file or db_file
    key = f"{db_file}::{effective_stock_analysis_db_file}{runtime_key}"
    scheduler = _SCHEDULER_INSTANCES.get(key)
    if scheduler is None:
        scheduler = QuantSimScheduler(
            db_file=db_file,
            stock_analysis_db_file=effective_stock_analysis_db_file,
            db_runtime=db_runtime,
        )
        _SCHEDULER_INSTANCES[key] = scheduler
    return scheduler
