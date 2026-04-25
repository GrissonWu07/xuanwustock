"""Bounded asynchronous stock-analysis refresh queue."""

from __future__ import annotations

from collections import deque
import os
import threading
from pathlib import Path
from typing import Any


DEFAULT_ANALYSIS_CONFIG = {
    "technical": True,
    "fundamental": True,
    "fund_flow": True,
    "risk": True,
    "sentiment": False,
    "news": False,
}


class StockAnalysisRefreshQueue:
    """Run missing stock-analysis refreshes outside the trading decision path."""

    def __init__(self, *, max_workers: int = 3, max_queue_size: int = 10):
        self.max_workers = max(1, int(max_workers))
        self.max_queue_size = max(1, int(max_queue_size))
        self._lock = threading.RLock()
        self._pending: deque[dict[str, Any]] = deque()
        self._active: set[str] = set()

    def enqueue(
        self,
        *,
        symbol: str,
        period: str = "1y",
        db_path: str | Path | None = None,
        reason: str = "missing_stock_analysis_context",
    ) -> dict[str, Any]:
        code = str(symbol or "").strip()
        if not code:
            return {"enqueued": False, "reason": "missing_symbol"}
        with self._lock:
            if code in self._active or any(item.get("symbol") == code for item in self._pending):
                return {"enqueued": False, "reason": "deduplicated"}
            if len(self._pending) + len(self._active) >= self.max_queue_size:
                return {"enqueued": False, "reason": "queue_full"}
            task = {"symbol": code, "period": period, "db_path": str(db_path) if db_path else None, "reason": reason}
            self._pending.append(task)
            self._drain_locked()
            return {"enqueued": True, "reason": reason}

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active": sorted(self._active),
                "queued": [item.get("symbol") for item in self._pending],
                "max_workers": self.max_workers,
                "max_queue_size": self.max_queue_size,
            }

    def _drain_locked(self) -> None:
        while self._pending and len(self._active) < self.max_workers:
            task = self._pending.popleft()
            symbol = str(task.get("symbol") or "")
            self._active.add(symbol)
            thread = threading.Thread(target=self._run_task, args=(task,), name=f"stock-analysis-refresh-{symbol}", daemon=True)
            thread.start()

    def _run_task(self, task: dict[str, Any]) -> None:
        symbol = str(task.get("symbol") or "")
        try:
            from app import stock_analysis_service

            stock_analysis_service.analyze_single_stock_for_batch(
                symbol,
                str(task.get("period") or "1y"),
                enabled_analysts_config=dict(DEFAULT_ANALYSIS_CONFIG),
                stock_analysis_db_path=task.get("db_path"),
            )
        finally:
            with self._lock:
                self._active.discard(symbol)
                self._drain_locked()


def refresh_enabled_by_env() -> bool:
    return os.getenv("STOCK_ANALYSIS_ASYNC_REFRESH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


stock_analysis_refresh_queue = StockAnalysisRefreshQueue(
    max_workers=int(os.getenv("STOCK_ANALYSIS_REFRESH_MAX_WORKERS", "3")),
    max_queue_size=int(os.getenv("STOCK_ANALYSIS_REFRESH_MAX_QUEUE", "10")),
)


__all__ = ["StockAnalysisRefreshQueue", "refresh_enabled_by_env", "stock_analysis_refresh_queue"]
