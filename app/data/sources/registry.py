"""Source factory helpers."""

from __future__ import annotations

from typing import Any

from app.data.sources import AkshareMarketDataSource, TdxMarketDataSource, TushareMarketDataSource


def create_source(provider: str, **kwargs: Any):
    key = str(provider or "").strip().lower()
    if key == "akshare":
        return AkshareMarketDataSource(**kwargs)
    if key == "tdx":
        return TdxMarketDataSource(**kwargs)
    if key == "tushare":
        return TushareMarketDataSource(**kwargs)
    raise ValueError(f"unsupported market data provider: {provider}")


__all__ = ["create_source"]
