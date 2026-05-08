from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RESET_FILENAMES = {
    "xuanwu_stock.db",
    "xuanwu_stock_replay.db",
    "quant_sim.db",
    "quant_sim_replay.db",
    "watchlist.db",
    "portfolio_stocks.db",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset stock-universe deployment databases.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--yes", action="store_true", help="Confirm deletion.")
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    if not args.yes:
        print("Refusing to reset databases without --yes.")
        return 2
    if not data_dir.exists():
        print(f"Data directory does not exist: {data_dir}")
        return 0

    removed: list[Path] = []
    for name in RESET_FILENAMES:
        target = data_dir / name
        if target.exists():
            target.unlink()
            removed.append(target)
        for backup in data_dir.glob(f"{name}.backup*"):
            backup.unlink()
            removed.append(backup)
        for backup in data_dir.glob(f"{name}.bak-*"):
            backup.unlink()
            removed.append(backup)

    for path in removed:
        print(f"removed {path}")
    print(f"reset complete, removed={len(removed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
