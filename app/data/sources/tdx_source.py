"""TDX local-first source wrapper."""

from __future__ import annotations

from app.local_market_data_clients import TdxLocalClient


class TdxMarketDataSource(TdxLocalClient):
    """Canonical source name; uses the existing TDX local client."""


__all__ = ["TdxMarketDataSource"]

