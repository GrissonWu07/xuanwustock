from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from app.local_market_data_store import LocalMarketDataStore


def _ohlcv_frame(start: str, periods: int, symbol: str = "000001") -> pd.DataFrame:
    dates = pd.date_range(start, periods=periods, freq="D")
    return pd.DataFrame(
        {
            "symbol": [symbol] * periods,
            "datetime": dates,
            "open": [10.0 + index for index in range(periods)],
            "high": [10.5 + index for index in range(periods)],
            "low": [9.5 + index for index in range(periods)],
            "close": [10.2 + index for index in range(periods)],
            "volume": [1000 + index for index in range(periods)],
            "amount": [10000 + index for index in range(periods)],
        }
    )


def test_path_for_separates_source_dataset_symbol_and_params(tmp_path):
    store = LocalMarketDataStore(tmp_path)

    ak_path = store.path_for("akshare", "hist_daily", "000001", {"adjust": "qfq"})
    tdx_path = store.path_for("tdx", "hist_daily", "000001", {"adjust": "qfq"})
    none_path = store.path_for("akshare", "hist_daily", "000001", {"adjust": ""})

    assert ak_path != tdx_path
    assert ak_path.as_posix().endswith("akshare/hist_daily/adjust=qfq/000001.parquet")
    assert none_path.as_posix().endswith("akshare/hist_daily/adjust=none/000001.parquet")


def test_read_range_hit_avoids_remote_fetch(tmp_path):
    store = LocalMarketDataStore(tmp_path)
    store.merge_frame(
        "akshare",
        "hist_daily",
        "000001",
        _ohlcv_frame("2026-01-01", 5),
        params={"adjust": "qfq"},
        key_columns=["symbol", "datetime"],
    )
    calls = []

    result = store.fetch_range(
        "akshare",
        "hist_daily",
        "000001",
        start="2026-01-02",
        end="2026-01-04",
        params={"adjust": "qfq"},
        remote_fetcher=lambda start, end: calls.append((start, end)) or _ohlcv_frame("2026-01-02", 3),
        key_columns=["symbol", "datetime"],
    )

    assert calls == []
    assert result.cache_status == "hit"
    assert result.cache_source == "local_akshare"
    assert result.data["datetime"].dt.strftime("%Y-%m-%d").tolist() == ["2026-01-02", "2026-01-03", "2026-01-04"]


def test_partial_range_fetches_remote_and_merges_without_duplicate_dates(tmp_path):
    store = LocalMarketDataStore(tmp_path)
    store.merge_frame(
        "tdx",
        "kline",
        "000001",
        _ohlcv_frame("2026-01-01", 2),
        params={"kline_type": "day"},
        key_columns=["symbol", "datetime"],
    )
    calls = []

    result = store.fetch_range(
        "tdx",
        "kline",
        "000001",
        start="2026-01-01",
        end="2026-01-04",
        params={"kline_type": "day"},
        remote_fetcher=lambda start, end: calls.append((start, end)) or _ohlcv_frame("2026-01-02", 3),
        key_columns=["symbol", "datetime"],
    )
    persisted = store.read_frame("tdx", "kline", "000001", params={"kline_type": "day"})

    assert len(calls) == 1
    assert result.cache_status == "partial"
    assert result.data["datetime"].dt.strftime("%Y-%m-%d").tolist() == ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]
    assert persisted is not None
    assert persisted["datetime"].dt.strftime("%Y-%m-%d").tolist() == ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]


def test_fetch_latest_uses_fresh_local_quote_without_remote(tmp_path):
    store = LocalMarketDataStore(tmp_path)
    now = datetime(2026, 4, 24, 10, 30)
    store.merge_frame(
        "tdx",
        "realtime_quote",
        "000001",
        pd.DataFrame([{"symbol": "000001", "current_price": 12.3, "quote_time": now, "fetched_at": now}]),
        key_columns=["symbol", "quote_time"],
    )
    calls = []

    result = store.fetch_latest(
        "tdx",
        "realtime_quote",
        "000001",
        ttl_seconds=60,
        now=now + timedelta(seconds=30),
        remote_fetcher=lambda: calls.append("remote") or pd.DataFrame([{"symbol": "000001", "current_price": 12.5}]),
        key_columns=["symbol", "quote_time"],
    )

    assert calls == []
    assert result.cache_status == "hit"
    assert result.data.iloc[0]["current_price"] == 12.3


def test_fetch_latest_refreshes_stale_quote_and_persists(tmp_path):
    store = LocalMarketDataStore(tmp_path)
    old = datetime(2026, 4, 24, 10, 30)
    new = datetime(2026, 4, 24, 10, 32)
    store.merge_frame(
        "tdx",
        "realtime_quote",
        "000001",
        pd.DataFrame([{"symbol": "000001", "current_price": 12.3, "quote_time": old, "fetched_at": old}]),
        key_columns=["symbol", "quote_time"],
    )

    result = store.fetch_latest(
        "tdx",
        "realtime_quote",
        "000001",
        ttl_seconds=30,
        now=new,
        remote_fetcher=lambda: pd.DataFrame([{"symbol": "000001", "current_price": 12.8, "quote_time": new}]),
        key_columns=["symbol", "quote_time"],
    )
    persisted = store.read_frame("tdx", "realtime_quote", "000001")

    assert result.cache_status == "stale"
    assert result.cache_source == "remote_tdx"
    assert result.data.iloc[0]["current_price"] == 12.8
    assert persisted is not None
    assert persisted["current_price"].tolist() == [12.3, 12.8]


def test_corrupt_local_file_falls_back_to_remote(tmp_path):
    store = LocalMarketDataStore(tmp_path)
    path = store.path_for("akshare", "hist_daily", "000001", {"adjust": "qfq"})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not parquet", encoding="utf-8")

    result = store.fetch_range(
        "akshare",
        "hist_daily",
        "000001",
        start="2026-01-01",
        end="2026-01-02",
        params={"adjust": "qfq"},
        remote_fetcher=lambda start, end: _ohlcv_frame("2026-01-01", 2),
        key_columns=["symbol", "datetime"],
    )

    assert result.cache_status == "miss"
    assert result.cache_source == "remote_akshare"
    assert result.data["datetime"].dt.strftime("%Y-%m-%d").tolist() == ["2026-01-01", "2026-01-02"]
