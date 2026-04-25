"""AKShare local-first source wrapper."""

from __future__ import annotations

from app.local_market_data_clients import AkshareLocalClient


class AkshareMarketDataSource(AkshareLocalClient):
    """Canonical source name; uses the existing AKShare local client."""


__all__ = ["AkshareMarketDataSource"]

