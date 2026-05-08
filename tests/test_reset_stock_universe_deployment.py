import importlib.util
import sqlite3
import sys
from pathlib import Path

from app.quant_sim.db import QuantSimDB


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_reset_script():
    path = PROJECT_ROOT / "scripts" / "reset_stock_universe_deployment.py"
    spec = importlib.util.spec_from_file_location("reset_stock_universe_deployment", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["reset_stock_universe_deployment"] = module
    spec.loader.exec_module(module)
    return module


def _table_names(db_file: Path) -> set[str]:
    conn = sqlite3.connect(db_file)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    finally:
        conn.close()
    return {str(row[0]) for row in rows}


def _row_count(db_file: Path, table_name: str) -> int:
    conn = sqlite3.connect(db_file)
    try:
        row = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()
    finally:
        conn.close()
    return int(row[0])


def test_reset_script_removes_current_legacy_backup_and_sqlite_sidecar_files(tmp_path, monkeypatch):
    reset_script = _load_reset_script()
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    for name in reset_script.RESET_FILENAMES:
        (data_dir / name).write_text("db", encoding="utf-8")
        (data_dir / f"{name}.backup-before-reset").write_text("backup", encoding="utf-8")
        (data_dir / f"{name}.bak-20260508").write_text("backup", encoding="utf-8")
        (data_dir / f"{name}-wal").write_text("wal", encoding="utf-8")
        (data_dir / f"{name}-shm").write_text("shm", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reset_stock_universe_deployment.py",
            "--data-dir",
            str(data_dir),
            "--yes",
        ],
    )

    assert reset_script.main() == 0

    for name in reset_script.RESET_FILENAMES:
        assert not (data_dir / name).exists()
        assert not (data_dir / f"{name}.backup-before-reset").exists()
        assert not (data_dir / f"{name}.bak-20260508").exists()
        assert not (data_dir / f"{name}-wal").exists()
        assert not (data_dir / f"{name}-shm").exists()


def test_reset_script_can_recreate_empty_runtime_schema(tmp_path, monkeypatch):
    reset_script = _load_reset_script()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    old_primary = data_dir / "xuanwu_stock.db"
    old_primary.write_text("old", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reset_stock_universe_deployment.py",
            "--data-dir",
            str(data_dir),
            "--yes",
            "--recreate",
        ],
    )

    assert reset_script.main() == 0

    primary = data_dir / "xuanwu_stock.db"
    replay = data_dir / "xuanwu_stock_replay.db"
    assert primary.exists()
    assert replay.exists()

    primary_tables = _table_names(primary)
    assert {
        "stock_universe",
        "stock_universe_quant_state",
        "stock_universe_candidate_events",
        "stock_universe_quant_events",
        "quant_universe_settings",
    } <= primary_tables
    assert _row_count(primary, "stock_universe") == 0
    assert _row_count(primary, "stock_universe_quant_state") == 0
    assert _row_count(primary, "stock_universe_candidate_events") == 0
    assert _row_count(primary, "stock_universe_quant_events") == 0

    replay_tables = _table_names(replay)
    assert {
        "sim_runs",
        "sim_run_signals",
        "sim_run_trades",
    } <= replay_tables


def test_reset_script_recreate_creates_missing_data_directory(tmp_path, monkeypatch):
    reset_script = _load_reset_script()
    data_dir = tmp_path / "missing-data"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reset_stock_universe_deployment.py",
            "--data-dir",
            str(data_dir),
            "--yes",
            "--recreate",
        ],
    )

    assert reset_script.main() == 0

    assert data_dir.exists()
    assert (data_dir / "xuanwu_stock.db").exists()
    assert (data_dir / "xuanwu_stock_replay.db").exists()


def test_quant_sim_initialization_creates_empty_lifecycle_schema(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    QuantSimDB(db_file)

    assert {
        "stock_universe",
        "stock_universe_quant_state",
        "stock_universe_candidate_events",
        "stock_universe_quant_events",
        "quant_universe_settings",
    } <= _table_names(db_file)
    assert _row_count(db_file, "stock_universe") == 0
    assert _row_count(db_file, "stock_universe_quant_state") == 0
    assert _row_count(db_file, "stock_universe_candidate_events") == 0
    assert _row_count(db_file, "stock_universe_quant_events") == 0
