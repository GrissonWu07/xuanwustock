"""Tushare local-first source wrapper."""

from __future__ import annotations

from app.local_market_data_clients import TushareLocalClient


class TushareMarketDataSource(TushareLocalClient):
    """Canonical source name; uses the existing Tushare local client."""


__all__ = ["TushareMarketDataSource"]

