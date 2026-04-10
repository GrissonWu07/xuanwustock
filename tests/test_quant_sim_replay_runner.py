import json
import time
from pathlib import Path

from quant_sim.db import QuantSimDB
from quant_sim.replay_runner import get_quant_sim_replay_runner


def _raise_system_exit_worker() -> None:
    raise SystemExit("synthetic replay crash")


def _silent_exit_worker() -> None:
    return None


def _sleep_worker(seconds: float) -> None:
    time.sleep(seconds)


def _wait_for_terminal_status(db: QuantSimDB, run_id: int, *, timeout_seconds: float = 2.0) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last_run = db.get_sim_run(run_id)
    while time.monotonic() < deadline:
        current = db.get_sim_run(run_id)
        if current is not None:
            last_run = current
            if str(current.get("status") or "").lower() not in {"queued", "running"}:
                return current
        time.sleep(0.02)
    if last_run is None:
        raise AssertionError(f"sim_run #{run_id} was not persisted")
    return last_run


def _wait_for_matching_event(db: QuantSimDB, run_id: int, expected_text: str, *, timeout_seconds: float = 2.0) -> list[dict]:
    deadline = time.monotonic() + timeout_seconds
    events: list[dict] = []
    while time.monotonic() < deadline:
        events = db.get_sim_run_events(run_id, limit=10)
        if any(expected_text in str(event["message"]) for event in events):
            return events
        time.sleep(0.02)
    return events


def test_replay_runner_persists_worker_pid_and_reports_running(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    db = QuantSimDB(db_file)
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-01-01 09:30:00",
        end_datetime="2026-01-01 15:00:00",
        initial_cash=100000.0,
        status="running",
        progress_total=10,
        status_message="执行中",
    )

    runner = get_quant_sim_replay_runner(db_file=db_file)
    assert runner.start_run(run_id, _sleep_worker, 0.5)

    current = db.get_sim_run(run_id)
    assert int(current.get("worker_pid") or 0) > 0
    assert runner.is_running(run_id) is True


def test_replay_runner_marks_unhandled_worker_failure_as_failed(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    db = QuantSimDB(db_file)
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-01-01 09:30:00",
        end_datetime="2026-01-01 15:00:00",
        initial_cash=100000.0,
        status="running",
        progress_total=10,
        status_message="执行中",
    )

    runner = get_quant_sim_replay_runner(db_file=db_file)
    assert runner.start_run(run_id, _raise_system_exit_worker)

    terminal_run = _wait_for_terminal_status(db, run_id)
    events = _wait_for_matching_event(db, run_id, "worker 进程异常退出")

    assert terminal_run["status"] == "failed"
    assert "worker 进程异常退出" in str(terminal_run["status_message"])
    metadata = json.loads(terminal_run["metadata_json"] or "{}")
    assert metadata["error_type"] == "SystemExit"
    assert any("worker 进程异常退出" in str(event["message"]) for event in events)


def test_replay_runner_marks_silent_worker_exit_as_failed(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    db = QuantSimDB(db_file)
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-01-01 09:30:00",
        end_datetime="2026-01-01 15:00:00",
        initial_cash=100000.0,
        status="running",
        progress_total=10,
        status_message="执行中",
    )

    runner = get_quant_sim_replay_runner(db_file=db_file)
    assert runner.start_run(run_id, _silent_exit_worker)

    terminal_run = _wait_for_terminal_status(db, run_id)
    events = _wait_for_matching_event(db, run_id, "worker 进程已退出，但任务未写入最终状态")

    assert terminal_run["status"] == "failed"
    assert "worker 进程已退出，但任务未写入最终状态" in str(terminal_run["status_message"])
    assert any("worker 进程已退出，但任务未写入最终状态" in str(event["message"]) for event in events)
