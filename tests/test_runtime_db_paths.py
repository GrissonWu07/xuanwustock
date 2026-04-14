from pathlib import Path
import importlib.util
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_module(relative_path: str, module_name: str):
    path = PROJECT_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_package(name: str, package_dir: str):
    init_path = PROJECT_ROOT / package_dir / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        name,
        init_path,
        submodule_search_locations=[str(PROJECT_ROOT / package_dir)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_load_package("app", "app")
runtime_paths = _load_module("app/runtime_paths.py", "app.runtime_paths")
database = _load_module("app/database.py", "app.database")
watchlist_db = _load_module("app/watchlist_db.py", "app.watchlist_db")
quant_db = _load_module("app/quant_sim/db.py", "app.quant_sim.db")

default_log_path = runtime_paths.default_log_path
managed_db_path = runtime_paths.managed_db_path
migrate_known_root_logs = runtime_paths.migrate_known_root_logs


def test_managed_db_path_uses_data_directory(tmp_path):
    path = managed_db_path(
        "watchlist.db",
        project_root=tmp_path,
        data_dir=tmp_path / "data",
    )

    assert path == tmp_path / "data" / "watchlist.db"


def test_managed_db_path_moves_legacy_root_db_into_data(tmp_path):
    legacy_db = tmp_path / "watchlist.db"
    legacy_db.write_text("legacy", encoding="utf-8")

    path = managed_db_path(
        "watchlist.db",
        project_root=tmp_path,
        data_dir=tmp_path / "data",
    )

    assert path.exists()
    assert path.read_text(encoding="utf-8") == "legacy"
    assert not legacy_db.exists()


def test_managed_db_path_replaces_existing_data_db_with_backup(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    existing_db = data_dir / "watchlist.db"
    existing_db.write_text("existing", encoding="utf-8")
    legacy_db = tmp_path / "watchlist.db"
    legacy_db.write_text("legacy", encoding="utf-8")

    path = managed_db_path(
        "watchlist.db",
        project_root=tmp_path,
        data_dir=data_dir,
    )

    backups = list(data_dir.glob("watchlist.db.bak-*"))
    assert path.read_text(encoding="utf-8") == "legacy"
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "existing"


def test_default_runtime_db_constants_point_into_data_dir():
    assert Path(database.DEFAULT_DB_PATH).parent.name == "data"
    assert Path(watchlist_db.DEFAULT_DB_FILE).parent.name == "data"
    assert Path(quant_db.DEFAULT_DB_FILE).parent.name == "data"


def test_default_log_path_uses_logs_directory(tmp_path):
    path = default_log_path("app.log", logs_dir=tmp_path / "logs")
    assert path == tmp_path / "logs" / "app.log"


def test_migrate_known_root_logs_moves_root_logs_into_logs_dir(tmp_path):
    root_log = tmp_path / "app.log"
    root_err = tmp_path / "app.err.log"
    root_log.write_text("stdout", encoding="utf-8")
    root_err.write_text("stderr", encoding="utf-8")

    migrated = migrate_known_root_logs(project_root=tmp_path, logs_dir=tmp_path / "logs")

    assert tmp_path.joinpath("logs", "app.log").read_text(encoding="utf-8") == "stdout"
    assert tmp_path.joinpath("logs", "app.err.log").read_text(encoding="utf-8") == "stderr"
    assert not root_log.exists()
    assert not root_err.exists()
    assert len(migrated) == 2
