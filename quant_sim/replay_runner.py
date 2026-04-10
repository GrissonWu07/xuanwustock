"""Background task runner for quant replay jobs."""

from __future__ import annotations

import ctypes
import multiprocessing
import os
import traceback
from pathlib import Path
from typing import Any, Callable

from quant_sim.db import DEFAULT_DB_FILE, QuantSimDB


_RUNNER_INSTANCES: dict[str, "QuantSimReplayRunner"] = {}


def _calculate_partial_metrics(
    *,
    initial_cash: float,
    trades: list[dict],
    snapshots: list[dict],
) -> dict[str, float]:
    snapshot_equity_curve = [float(snapshot.get("total_equity") or 0) for snapshot in snapshots]
    final_equity = snapshot_equity_curve[-1] if snapshot_equity_curve else float(initial_cash)

    peak = float(initial_cash)
    max_drawdown_pct = 0.0
    for equity in snapshot_equity_curve:
        peak = max(peak, equity)
        if peak <= 0:
            continue
        drawdown_pct = (peak - equity) / peak * 100
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

    sell_trades = [trade for trade in trades if str(trade.get("action") or "").upper() == "SELL"]
    profitable_trades = [trade for trade in sell_trades if float(trade.get("realized_pnl") or 0) > 0]
    win_rate = (len(profitable_trades) / len(sell_trades) * 100) if sell_trades else 0.0
    total_return_pct = ((final_equity - float(initial_cash)) / float(initial_cash) * 100) if initial_cash > 0 else 0.0
    return {
        "final_equity": round(final_equity, 4),
        "total_return_pct": round(total_return_pct, 4),
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "win_rate": round(win_rate, 4),
    }


def _mark_run_failed_from_worker_exit(
    db: QuantSimDB,
    run_id: int,
    *,
    exc: BaseException | None,
    silent_exit: bool,
) -> None:
    run = db.get_sim_run(run_id)
    if run is None:
        return

    status = str(run.get("status") or "").lower()
    if status not in {"queued", "running"}:
        return

    initial_cash = float(run.get("initial_cash") or 0)
    trades = db.get_sim_run_trades(run_id)
    snapshots = db.get_sim_run_snapshots(run_id)
    metrics = _calculate_partial_metrics(initial_cash=initial_cash, trades=trades, snapshots=snapshots)

    if silent_exit:
        status_message = "后台回放 worker 进程已退出，但任务未写入最终状态。"
        metadata: dict[str, Any] = {"error": "background replay worker exited without terminal status"}
    else:
        status_message = f"后台回放 worker 进程异常退出：{type(exc).__name__}: {exc}"
        metadata = {
            "error": str(exc),
            "error_type": type(exc).__name__,
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        }

    db.finalize_sim_run(
        run_id,
        status="failed",
        final_equity=float(metrics["final_equity"]),
        total_return_pct=float(metrics["total_return_pct"]),
        max_drawdown_pct=float(metrics["max_drawdown_pct"]),
        win_rate=float(metrics["win_rate"]),
        trade_count=len(trades),
        status_message=status_message,
        metadata=metadata,
    )
    db.append_sim_run_event(run_id, status_message, level="error")


def _worker_process_entry(
    db_file: str,
    run_id: int,
    target: Callable[..., None],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    db = QuantSimDB(db_file)
    db.set_sim_run_worker_pid(run_id, os.getpid())
    try:
        target(*args, **kwargs)
    except BaseException as exc:  # noqa: BLE001 - background worker must persist failures
        _mark_run_failed_from_worker_exit(db, run_id, exc=exc, silent_exit=False)
    else:
        _mark_run_failed_from_worker_exit(db, run_id, exc=None, silent_exit=True)


def _is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False

    if os.name == "nt":
        process_handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process_handle:
            return False
        ctypes.windll.kernel32.CloseHandle(process_handle)
        return True

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class QuantSimReplayRunner:
    """Run replay jobs in isolated worker processes and support cooperative cancellation."""

    def __init__(self, db_file: str | Path = DEFAULT_DB_FILE):
        self.db_file = str(db_file)
        self.db = QuantSimDB(db_file)
        self._ctx = multiprocessing.get_context("spawn")
        self._processes: dict[int, multiprocessing.Process] = {}
        self._lock = multiprocessing.Lock()

    def start_run(self, run_id: int, target: Callable[..., None], *args: Any, **kwargs: Any) -> bool:
        with self._lock:
            self._cleanup_finished_process_locked(run_id)
            if self._db_run_has_live_worker(run_id):
                return False

            process = self._ctx.Process(
                target=_worker_process_entry,
                args=(self.db_file, run_id, target, tuple(args), dict(kwargs)),
                daemon=False,
                name=f"quant-replay-{run_id}",
            )
            process.start()
            self._processes[run_id] = process
            self.db.set_sim_run_worker_pid(run_id, int(process.pid or 0))
            return True

    def cancel_run(self, run_id: int) -> bool:
        run = self.db.get_sim_run(run_id)
        if run is None:
            return False
        if str(run.get("status") or "") not in {"queued", "running"}:
            return False
        self.db.request_sim_run_cancel(run_id)
        self.db.append_sim_run_event(run_id, "已请求取消回放任务。", level="warning")
        return True

    def is_running(self, run_id: int) -> bool:
        with self._lock:
            self._cleanup_finished_process_locked(run_id)
            process = self._processes.get(run_id)
            if process is not None and process.is_alive():
                return True

        run = self.db.get_sim_run(run_id)
        if run is None:
            return False
        worker_pid = int(run.get("worker_pid") or 0)
        return _is_pid_running(worker_pid)

    def _cleanup_finished_process_locked(self, run_id: int) -> None:
        process = self._processes.get(run_id)
        if process is None:
            return
        if process.is_alive():
            return
        process.join(timeout=0)
        self._processes.pop(run_id, None)

    def _db_run_has_live_worker(self, run_id: int) -> bool:
        run = self.db.get_sim_run(run_id)
        if run is None:
            return False
        worker_pid = int(run.get("worker_pid") or 0)
        return _is_pid_running(worker_pid)


def get_quant_sim_replay_runner(db_file: str | Path = DEFAULT_DB_FILE) -> QuantSimReplayRunner:
    key = str(db_file)
    runner = _RUNNER_INSTANCES.get(key)
    if runner is None:
        runner = QuantSimReplayRunner(db_file=db_file)
        _RUNNER_INSTANCES[key] = runner
    return runner
