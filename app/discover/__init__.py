from __future__ import annotations

__all__ = [
    "AIStockScanner",
    "AIStockScannerConfig",
    "ThemeInfo",
    "action_discover_batch",
    "action_discover_item",
    "action_discover_reset",
    "action_discover_run_strategy",
    "discover_task_manager",
    "snapshot_discover",
]


def __getattr__(name: str):
    if name in {"AIStockScanner", "AIStockScannerConfig", "ThemeInfo"}:
        from app.discover import ai_stock_scanner

        value = getattr(ai_stock_scanner, name)
        globals()[name] = value
        return value
    if name in {
        "action_discover_batch",
        "action_discover_item",
        "action_discover_reset",
        "action_discover_run_strategy",
        "discover_task_manager",
        "snapshot_discover",
    }:
        from app.discover import discover

        value = getattr(discover, name)
        globals()[name] = value
        return value
    raise AttributeError(name)
