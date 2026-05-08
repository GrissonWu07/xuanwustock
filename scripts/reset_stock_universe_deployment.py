from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RESET_FILENAMES = (
    "xuanwu_stock.db",
    "xuanwu_stock_replay.db",
    "quant_sim.db",
    "quant_sim_replay.db",
    "watchlist.db",
    "portfolio_stocks.db",
)
SQLITE_SIDE_SUFFIXES = ("-wal", "-shm", "-journal")
RUNTIME_PRIMARY_DB = "xuanwu_stock.db"
RUNTIME_REPLAY_DB = "xuanwu_stock_replay.db"


def _remove_file(path: Path, removed: list[Path]) -> None:
    if path.exists():
        path.unlink()
        removed.append(path)


def _remove_database_family(data_dir: Path, name: str, removed: list[Path]) -> None:
    target = data_dir / name
    _remove_file(target, removed)
    for suffix in SQLITE_SIDE_SUFFIXES:
        _remove_file(data_dir / f"{name}{suffix}", removed)
    for backup in data_dir.glob(f"{name}.backup*"):
        _remove_file(backup, removed)
    for backup in data_dir.glob(f"{name}.bak-*"):
        _remove_file(backup, removed)


def _recreate_runtime_schema(data_dir: Path) -> list[Path]:
    from app.quant_sim.db import QuantSimDB, QuantSimReplayDB

    data_dir.mkdir(parents=True, exist_ok=True)
    primary = data_dir / RUNTIME_PRIMARY_DB
    replay = data_dir / RUNTIME_REPLAY_DB
    QuantSimDB(primary)
    QuantSimReplayDB(replay)
    return [primary, replay]


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset stock-universe deployment databases.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--yes", action="store_true", help="Confirm deletion.")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Create empty runtime primary and replay schemas after deletion.",
    )
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    if not args.yes:
        print("Refusing to reset databases without --yes.")
        return 2
    if not data_dir.exists() and not args.recreate:
        print(f"Data directory does not exist: {data_dir}")
        return 0

    removed: list[Path] = []
    for name in RESET_FILENAMES:
        _remove_database_family(data_dir, name, removed)

    for path in removed:
        print(f"removed {path}")
    recreated: list[Path] = []
    if args.recreate:
        recreated = _recreate_runtime_schema(data_dir)
        for path in recreated:
            print(f"recreated {path}")
    print(f"reset complete, removed={len(removed)}")
    if recreated:
        print(f"schema recreated, files={len(recreated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
