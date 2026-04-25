"""Common protocols for local-first market-data sources."""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd


class MarketDataSource(Protocol):
    """Provider source that can return OHLCV-like frames."""

    def get_stock_hist_data(self, symbol: str, **kwargs: Any) -> pd.DataFrame | None:
        """Return historical OHLCV data using provider-local cache first."""


__all__ = ["MarketDataSource"]
