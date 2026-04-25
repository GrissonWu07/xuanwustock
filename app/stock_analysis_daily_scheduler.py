"""Daily pre-warm scheduler for stock-analysis context used by quant decisions."""

from __future__ import annotations

from datetime import datetime
import logging
import os
import threading
from typing import Any, Callable

import schedule

from app import stock_analysis_service
from app.data.analysis_context.refresh import DEFAULT_ANALYSIS_CONFIG
from app.watchlist_selector_integration import normalize_stock_code


DEFAULT_DAILY_ANALYSIS_AT = os.getenv("STOCK_ANALYSIS_DAILY_AT", "16:10")
DEFAULT_DAILY_ANALYSIS_POLL_SECONDS = float(os.getenv("STOCK_ANALYSIS_DAILY_POLL_SECONDS", "30"))
DEFAULT_DAILY_ANALYSIS_PERIOD = os.getenv("STOCK_ANALYSIS_DAILY_PERIOD", "1y")
DEFAULT_DAILY_ANALYSIS_VALID_HOURS = float(os.getenv("STOCK_ANALYSIS_DAILY_VALID_HOURS", "24"))
DEFAULT_DAILY_ANALYSIS_MAX_CODES = int(os.getenv("STOCK_ANALYSIS_DAILY_MAX_CODES", "200"))
_SCHEDULER_INSTANCE: "StockAnalysisDailyScheduler | None" = None
logger = logging.getLogger(__name__)


def daily_analysis_enabled_by_env() -> bool:
    return os.getenv("STOCK_ANALYSIS_DAILY_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


class StockAnalysisDailyScheduler:
    """Run at most one stock-analysis refresh per stock per calendar day."""

    def __init__(
        self,
        context_provider: Callable[[], Any],
        *,
        run_at: str = DEFAULT_DAILY_ANALYSIS_AT,
        poll_seconds: float = DEFAULT_DAILY_ANALYSIS_POLL_SECONDS,
        period: str = DEFAULT_DAILY_ANALYSIS_PERIOD,
        valid_hours: float = DEFAULT_DAILY_ANALYSIS_VALID_HOURS,
        max_codes: int = DEFAULT_DAILY_ANALYSIS_MAX_CODES,
        enabled: bool | None = None,
    ) -> None:
        self._context_provider = context_provider
        self.run_at = str(run_at or DEFAULT_DAILY_ANALYSIS_AT)
        self.poll_seconds = max(float(poll_seconds), 1.0)
        self.period = str(period or DEFAULT_DAILY_ANALYSIS_PERIOD)
        self.valid_hours = max(float(valid_hours), 0.01)
        self.max_codes = max(int(max_codes), 1)
        self.enabled = daily_analysis_enabled_by_env() if enabled is None else bool(enabled)
        self.scheduler = schedule.Scheduler()
        self.running = False
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.job_tag = "stock_analysis_daily"
        self._run_lock = threading.Lock()
        self.last_run_at: str | None = None
        self.last_summary: dict[str, Any] | None = None

    def set_context_provider(self, provider: Callable[[], Any]) -> None:
        self._context_provider = provider

    def start(self) -> bool:
        if self.running or not self.enabled:
            return False
        self.running = True
        self.stop_event.clear()
        self._register_jobs()
        self.thread = threading.Thread(target=self._schedule_loop, daemon=True, name="stock-analysis-daily-scheduler")
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

    def get_status(self) -> dict[str, Any]:
        jobs = self.scheduler.get_jobs(self.job_tag)
        next_run = jobs[0].next_run.strftime("%Y-%m-%d %H:%M:%S") if jobs else None
        return {
            "running": self.running,
            "enabled": self.enabled,
            "run_at": self.run_at,
            "period": self.period,
            "valid_hours": self.valid_hours,
            "max_codes": self.max_codes,
            "last_run_at": self.last_run_at,
            "next_run": next_run,
            "last_summary": self.last_summary or {},
        }

    def run_once(self, *, context: Any | None = None, force: bool = False, run_reason: str = "scheduled") -> dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            return {"reason": run_reason, "updated": 0, "failed": 0, "skippedExisting": 0, "totalCodes": 0, "active": True, "updatedAt": _now()}
        try:
            ctx = context or self._context_provider()
            if ctx is None:
                return {"reason": run_reason, "updated": 0, "failed": 0, "skippedExisting": 0, "totalCodes": 0, "updatedAt": _now()}

            codes = sorted(self._collect_codes(ctx))[: self.max_codes]
            db = ctx.stock_analysis_db()
            today = datetime.now().date().isoformat()
            updated = 0
            failed = 0
            skipped_existing = 0
            failures: list[str] = []
            for code in codes:
                if not force and db.has_analysis_for_symbol_on_date(code, today):
                    skipped_existing += 1
                    continue
                try:
                    result = stock_analysis_service.analyze_single_stock_for_batch(
                        code,
                        self.period,
                        enabled_analysts_config=dict(DEFAULT_ANALYSIS_CONFIG),
                        selected_model=None,
                        progress_callback=None,
                        analysis_db=db,
                        valid_hours=self.valid_hours,
                        replace_same_day=True,
                    )
                except Exception as exc:
                    failed += 1
                    failures.append(f"{code}: {exc}")
                    continue
                if isinstance(result, dict) and result.get("success") and result.get("saved_to_db", True) is not False:
                    updated += 1
                else:
                    failed += 1
                    reason = result.get("error") or result.get("db_error") if isinstance(result, dict) else "invalid_result"
                    failures.append(f"{code}: {reason}")

            summary = {
                "reason": run_reason,
                "updated": updated,
                "failed": failed,
                "skippedExisting": skipped_existing,
                "totalCodes": len(codes),
                "updatedAt": _now(),
            }
            if failures:
                summary["failures"] = failures[:20]
            self.last_run_at = summary["updatedAt"]
            self.last_summary = summary
            return summary
        finally:
            self._run_lock.release()

    def _schedule_loop(self) -> None:
        while self.running and not self.stop_event.is_set():
            try:
                self.scheduler.run_pending()
            except Exception:
                logger.exception("stock analysis daily scheduler cycle failed; next cycle will continue")
            finally:
                self.stop_event.wait(self.poll_seconds)

    def _register_jobs(self) -> None:
        self._clear_jobs()
        self.scheduler.every().day.at(self.run_at).do(self._run_scheduled_cycle).tag(self.job_tag)

    def _clear_jobs(self) -> None:
        for job in self.scheduler.get_jobs(self.job_tag):
            self.scheduler.cancel_job(job)

    def _run_scheduled_cycle(self) -> None:
        context = self._context_provider()
        if context is None:
            return
        thread = threading.Thread(
            target=self.run_once,
            kwargs={"context": context, "force": False, "run_reason": "scheduled"},
            daemon=True,
            name="stock-analysis-daily-run",
        )
        thread.start()

    @staticmethod
    def _collect_codes(context: Any) -> set[str]:
        codes: set[str] = set()
        try:
            for item in context.watchlist().list_watches():
                code = normalize_stock_code(item.get("stock_code"))
                if code:
                    codes.add(code)
        except Exception:
            pass
        try:
            db = context.quant_db()
            for item in db.get_candidates(status="active"):
                code = normalize_stock_code(item.get("stock_code"))
                if code:
                    codes.add(code)
            for item in db.get_positions():
                code = normalize_stock_code(item.get("stock_code"))
                if code:
                    codes.add(code)
        except Exception:
            pass
        try:
            for item in context.portfolio_manager().get_all_stocks():
                code = normalize_stock_code(item.get("code") or item.get("symbol"))
                if code:
                    codes.add(code)
        except Exception:
            pass
        return codes


def get_stock_analysis_daily_scheduler(context: Any | None = None) -> StockAnalysisDailyScheduler:
    global _SCHEDULER_INSTANCE
    if _SCHEDULER_INSTANCE is None:
        if context is None:
            raise RuntimeError("context is required for initial scheduler creation")
        _SCHEDULER_INSTANCE = StockAnalysisDailyScheduler(lambda: context)
    elif context is not None:
        _SCHEDULER_INSTANCE.set_context_provider(lambda: context)
    return _SCHEDULER_INSTANCE


__all__ = [
    "StockAnalysisDailyScheduler",
    "daily_analysis_enabled_by_env",
    "get_stock_analysis_daily_scheduler",
]
