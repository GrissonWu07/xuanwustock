"""Selector-facing helpers for promoting stocks into the watchlist."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from watchlist_service import WatchlistService


def normalize_stock_code(stock_code: str) -> str:
    """Normalize selector output like 600000.SH -> 600000."""
    if not stock_code:
        return ""

    normalized = str(stock_code).strip().upper()
    for delimiter in (".", " "):
        if delimiter in normalized:
            normalized = normalized.split(delimiter)[0]
    return normalized


def add_stock_to_watchlist(
    stock_code: str,
    stock_name: str,
    source: str,
    latest_price: Optional[float] = None,
    notes: Optional[str] = None,
    metadata: Optional[dict[str, object]] = None,
    db_file: str | Path = "watchlist.db",
) -> tuple[bool, str, int]:
    """Add one selector result into the shared watchlist."""

    normalized_code = normalize_stock_code(stock_code)
    if not normalized_code or not stock_name:
        return False, "股票代码或名称为空，无法加入关注池。", 0

    service = WatchlistService(db_file=db_file)
    summary = service.add_stock(
        stock_code=normalized_code,
        stock_name=stock_name,
        source=source,
        latest_price=latest_price,
        notes=notes,
        metadata=metadata,
    )
    return True, f"✅ {normalized_code} - {stock_name} 已加入关注池", int(summary["watch_id"])


def extract_latest_price_from_row(row: dict | pd.Series) -> Optional[float]:
    """Extract the best-effort latest price from a selector row."""
    for field_name in ("最新价", "股价"):
        value = row.get(field_name)
        try:
            if value is not None and not pd.isna(value):
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _extract_float_from_row(row: dict | pd.Series, *field_names: str) -> Optional[float]:
    for field_name in field_names:
        value = row.get(field_name)
        try:
            if value is not None and not pd.isna(value):
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _extract_text_from_row(row: dict | pd.Series, *field_names: str) -> Optional[str]:
    for field_name in field_names:
        value = row.get(field_name)
        if value is None or pd.isna(value):
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def extract_metadata_from_row(row: dict | pd.Series) -> dict[str, object]:
    metadata: dict[str, object] = {}

    numeric_fields = {
        "profit_growth_pct": ("净利润增长率", "净利增长率", "净利润同比增长率", "利润增长率"),
        "revenue_growth_pct": ("营收增长率", "营业收入增长率"),
        "roe_pct": ("净资产收益率", "ROE"),
        "pe_ratio": ("市盈率", "PE", "滚动市盈率"),
        "pb_ratio": ("市净率", "PB"),
        "market_cap": ("总市值", "市值"),
    }
    for target_key, aliases in numeric_fields.items():
        value = _extract_float_from_row(row, *aliases)
        if value is not None:
            metadata[target_key] = value

    industry = _extract_text_from_row(row, "所属行业", "行业")
    if industry:
        metadata["industry"] = industry

    return metadata


def sync_selector_dataframe_to_watchlist(
    stocks_df: pd.DataFrame,
    source: str,
    note_prefix: Optional[str] = None,
    db_file: str | Path = "watchlist.db",
) -> dict[str, object]:
    """Sync a selector dataframe into the shared watchlist."""

    summary = {
        "attempted": 0,
        "success_count": 0,
        "failures": [],
    }

    if stocks_df is None or stocks_df.empty:
        return summary

    for _, row in stocks_df.iterrows():
        stock_code = normalize_stock_code(row.get("股票代码"))
        stock_name = str(row.get("股票简称", "") or "").strip()
        if not stock_code or not stock_name:
            continue

        summary["attempted"] += 1
        success, message, _ = add_stock_to_watchlist(
            stock_code=stock_code,
            stock_name=stock_name,
            source=source,
            latest_price=extract_latest_price_from_row(row),
            notes=note_prefix,
            metadata=extract_metadata_from_row(row),
            db_file=db_file,
        )
        if success:
            summary["success_count"] += 1
        else:
            summary["failures"].append(f"{stock_code}: {message}")

    return summary
