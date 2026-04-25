"""Provider column normalization for canonical OHLCV frames."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd


OHLCV_ALIASES: dict[str, tuple[str, ...]] = {
    "symbol": ("symbol", "code", "股票代码"),
    "datetime": ("datetime", "date", "Date", "日期", "trade_date"),
    "open": ("open", "Open", "开盘", "open_price"),
    "high": ("high", "High", "最高", "high_price"),
    "low": ("low", "Low", "最低", "low_price"),
    "close": ("close", "Close", "收盘", "price", "current_price"),
    "volume": ("volume", "Volume", "成交量", "vol"),
    "amount": ("amount", "成交额", "turnover"),
}


def _first_existing_column(df: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    for alias in aliases:
        if alias in df.columns:
            return alias
    return None


def normalize_ohlcv_frame(
    frame: pd.DataFrame | None,
    *,
    symbol: str | None = None,
    source: str = "unknown",
    dataset: str = "ohlcv",
    timeframe: str = "1d",
    adjust: str = "none",
    provider: str | None = None,
    cache_source: str = "memory",
    fetched_at: Any = None,
    strict: bool = True,
) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()

    raw = frame.copy()
    if raw.index.name or not isinstance(raw.index, pd.RangeIndex):
        raw = raw.reset_index()

    normalized = pd.DataFrame(index=raw.index)
    for canonical, aliases in OHLCV_ALIASES.items():
        column = _first_existing_column(raw, aliases)
        if column is not None:
            normalized[canonical] = raw[column]

    if "symbol" not in normalized.columns and symbol:
        normalized["symbol"] = str(symbol).split(".")[0]
    if "symbol" not in normalized.columns and not strict:
        normalized["symbol"] = "UNKNOWN"
    if "amount" not in normalized.columns:
        normalized["amount"] = 0.0

    required = {"symbol", "datetime", "open", "high", "low", "close", "volume", "amount"}
    missing = sorted(required - set(normalized.columns))
    if missing:
        if strict:
            raise ValueError(f"canonical OHLCV missing required columns: {missing}")
        return pd.DataFrame()

    normalized["symbol"] = normalized["symbol"].astype(str).str.strip().str.upper().str.split(".").str[0]
    normalized["datetime"] = pd.to_datetime(normalized["datetime"])
    for column in ("open", "high", "low", "close", "volume", "amount"):
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    normalized = normalized.dropna(subset=["datetime", "open", "high", "low", "close"]).sort_values("datetime")
    normalized["source"] = raw["source"] if "source" in raw.columns else source
    normalized["dataset"] = raw["dataset"] if "dataset" in raw.columns else dataset
    normalized["timeframe"] = raw["timeframe"] if "timeframe" in raw.columns else timeframe
    normalized["adjust"] = raw["adjust"] if "adjust" in raw.columns else (adjust or "none")
    normalized["provider"] = raw["provider"] if "provider" in raw.columns else (provider or source)
    normalized["cache_source"] = raw["cache_source"] if "cache_source" in raw.columns else cache_source
    normalized["fetched_at"] = (
        pd.to_datetime(raw["fetched_at"])
        if "fetched_at" in raw.columns
        else pd.Timestamp(fetched_at or datetime.now())
    )
    return normalized.reset_index(drop=True)


def canonical_to_stock_analysis_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["Date"] = pd.to_datetime(result["datetime"])
    result["Open"] = result["open"]
    result["High"] = result["high"]
    result["Low"] = result["low"]
    result["Close"] = result["close"]
    result["Volume"] = result["volume"]
    return result.set_index("Date", drop=False)


def canonical_to_tdx_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(
        {
            "日期": pd.to_datetime(frame["datetime"]),
            "开盘": frame["open"],
            "收盘": frame["close"],
            "最高": frame["high"],
            "最低": frame["low"],
            "成交量": frame["volume"],
            "成交额": frame["amount"],
        }
    )
    return result.reset_index(drop=True)


__all__ = ["normalize_ohlcv_frame", "canonical_to_stock_analysis_frame", "canonical_to_tdx_frame"]
