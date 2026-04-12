"""Helpers for promoting research-module stock outputs into the watchlist."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from watchlist_selector_integration import add_stock_to_watchlist, normalize_stock_code


def _pick_text(stock: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = stock.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _pick_float(stock: dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = stock.get(key)
        try:
            if value is not None and str(value).strip() != "":
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _build_metadata(stock: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}

    industry = _pick_text(stock, "sector", "行业", "所属行业", "板块")
    if industry:
        metadata["industry"] = industry

    target_space = _pick_text(stock, "target_space", "目标空间")
    if target_space:
        metadata["target_space"] = target_space

    risk_level = _pick_text(stock, "risk_level", "风险", "risk")
    if risk_level:
        metadata["risk_level"] = risk_level

    confidence = _pick_text(stock, "confidence", "确定性")
    if confidence:
        metadata["confidence"] = confidence

    return metadata


def add_research_stock_to_watchlist(
    stock: dict[str, Any],
    source: str,
    db_file: str | Path = "watchlist.db",
) -> tuple[bool, str, int]:
    """Promote one research output row into the watchlist."""

    stock_code = normalize_stock_code(_pick_text(stock, "code", "stock_code", "股票代码", "代码"))
    stock_name = _pick_text(stock, "name", "stock_name", "股票名称", "股票简称", "名称")
    latest_price = _pick_float(stock, "price", "latest_price", "最新价", "现价")
    notes = _pick_text(stock, "reason", "推荐理由", "strategy", "策略")

    return add_stock_to_watchlist(
        stock_code=stock_code,
        stock_name=stock_name,
        source=source,
        latest_price=latest_price,
        notes=notes,
        metadata=_build_metadata(stock),
        db_file=db_file,
    )


def add_research_stocks_to_watchlist(
    stocks: list[dict[str, Any]],
    source: str,
    db_file: str | Path = "watchlist.db",
) -> dict[str, Any]:
    """Promote multiple research output rows into the watchlist."""

    summary = {"attempted": 0, "success_count": 0, "failures": []}

    for stock in stocks or []:
        stock_code = normalize_stock_code(_pick_text(stock, "code", "stock_code", "股票代码", "代码"))
        stock_name = _pick_text(stock, "name", "stock_name", "股票名称", "股票简称", "名称")
        if not stock_code or not stock_name:
            continue

        summary["attempted"] += 1
        success, message, _ = add_research_stock_to_watchlist(stock=stock, source=source, db_file=db_file)
        if success:
            summary["success_count"] += 1
        else:
            summary["failures"].append(f"{stock_code}: {message}")

    return summary
