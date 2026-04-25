"""Compatibility wrapper for the existing Parquet-backed market-data store."""

from __future__ import annotations

from app.local_market_data_store import LocalMarketDataStore


class ParquetMarketDataStore(LocalMarketDataStore):
    """Canonical store name; implementation remains the existing single store."""


__all__ = ["ParquetMarketDataStore"]

