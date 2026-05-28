from __future__ import annotations

from typing import Any


def strategy_filter_value(table_query: dict[str, Any] | None) -> str:
    raw = None
    if isinstance(table_query, dict):
        raw = table_query.get("strategy_key") or table_query.get("strategyKey") or table_query.get("strategy")
    value = str(raw or "").strip().lower()
    return "" if value in {"", "all"} else value


def filter_rows_by_strategy(rows: list[dict[str, Any]], strategy_filter: str) -> list[dict[str, Any]]:
    if not strategy_filter:
        return rows
    return [
        row
        for row in rows
        if strategy_filter
        in {
            _txt(row.get("strategyKey")).strip().lower(),
            _txt(row.get("strategyName")).strip().lower(),
            _txt(row.get("source")).strip().lower(),
        }
    ]


def _txt(value: Any) -> str:
    return "" if value is None else str(value)


__all__ = ["filter_rows_by_strategy", "strategy_filter_value"]
