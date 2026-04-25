"""Unified business-facing market data and indicator service."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.data.indicators import TechnicalIndicatorEngine
from app.data.sources.registry import create_source


class MarketDataService:
    """Read provider-local market data and calculate canonical indicators."""

    def __init__(self, *, provider: str = "akshare", source: Any = None, indicator_engine: TechnicalIndicatorEngine | None = None):
        self.provider = str(provider or "akshare").strip().lower()
        self.source = source or create_source(self.provider)
        self.indicator_engine = indicator_engine or TechnicalIndicatorEngine()

    def get_ohlcv(
        self,
        symbol: str,
        *,
        start_date: Any = None,
        end_date: Any = None,
        adjust: str = "qfq",
        period: str = "daily",
        output: str = "canonical",
    ) -> pd.DataFrame | None:
        if self.provider == "tdx":
            frame = self.source.get_kline_data_range(
                symbol,
                kline_type=period,
                start_datetime=start_date,
                end_datetime=end_date,
                remote_fetcher=lambda: pd.DataFrame(),
            )
        else:
            frame = self.source.get_stock_hist_data(
                symbol,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
                period=period,
                output="data_source",
            )
        if output == "raw":
            return frame
        return self.indicator_engine.calculate(
            frame,
            symbol=symbol,
            source=self.provider,
            provider=self.provider,
            dataset="hist_daily" if self.provider != "tdx" else "kline",
            timeframe="1d" if period in {"daily", "day"} else str(period),
            adjust=adjust,
            cache_source=self.provider,
            strict=False,
        )

    def get_indicators(self, symbol: str, **kwargs: Any) -> pd.DataFrame:
        frame = self.get_ohlcv(symbol, **kwargs)
        return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()

    def get_latest_snapshot(self, symbol: str, **kwargs: Any) -> dict[str, Any]:
        indicators = self.get_indicators(symbol, **kwargs)
        return self.indicator_engine.latest_dict(indicators)


__all__ = ["MarketDataService"]
