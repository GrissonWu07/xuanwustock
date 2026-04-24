from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from app.local_market_data_clients import AkshareLocalClient, TdxLocalClient, TushareLocalClient
from app.local_market_data_store import LocalMarketDataStore


def test_akshare_hist_local_hit_avoids_remote(tmp_path):
    store = LocalMarketDataStore(tmp_path)
    client = AkshareLocalClient(store=store, ak_api=object())
    store.merge_frame(
        "akshare",
        "hist_daily",
        "000001",
        pd.DataFrame(
            [
                {"symbol": "000001", "datetime": "2026-01-01", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "amount": 10000},
                {"symbol": "000001", "datetime": "2026-01-02", "open": 11, "high": 12, "low": 10, "close": 11.5, "volume": 1100, "amount": 11000},
            ]
        ),
        params={"period": "daily", "adjust": "qfq"},
        key_columns=["symbol", "datetime"],
    )

    df = client.get_stock_hist_data("000001", start_date="20260101", end_date="20260102", adjust="qfq")

    assert df["close"].tolist() == [10.5, 11.5]
    assert set(df["cache_source"]) == {"local_akshare"}
    assert set(df["cache_status"]) == {"hit"}


def test_akshare_hist_remote_refresh_is_written_to_local_source(tmp_path):
    calls = []

    class FakeAk:
        def stock_zh_a_hist(self, **kwargs):
            calls.append(kwargs)
            return pd.DataFrame(
                [
                    {"日期": "2026-01-01", "开盘": 10, "最高": 11, "最低": 9, "收盘": 10.5, "成交量": 1000, "成交额": 10000},
                    {"日期": "2026-01-02", "开盘": 11, "最高": 12, "最低": 10, "收盘": 11.5, "成交量": 1100, "成交额": 11000},
                ]
            )

    store = LocalMarketDataStore(tmp_path)
    client = AkshareLocalClient(store=store, ak_api=FakeAk())

    df = client.get_stock_hist_data("000001", start_date="20260101", end_date="20260102", adjust="qfq")
    persisted = store.read_frame("akshare", "hist_daily", "000001", params={"period": "daily", "adjust": "qfq"})

    assert len(calls) == 1
    assert df["close"].tolist() == [10.5, 11.5]
    assert set(df["cache_source"]) == {"remote_akshare"}
    assert persisted is not None
    assert persisted["close"].tolist() == [10.5, 11.5]


def test_tushare_hist_source_isolation_writes_only_tushare_namespace(tmp_path):
    class FakeTushare:
        def daily(self, **kwargs):
            return pd.DataFrame(
                [
                    {"ts_code": "000001.SZ", "trade_date": "20260102", "open": 11, "high": 12, "low": 10, "close": 11.5, "vol": 11, "amount": 11},
                    {"ts_code": "000001.SZ", "trade_date": "20260101", "open": 10, "high": 11, "low": 9, "close": 10.5, "vol": 10, "amount": 10},
                ]
            )

    store = LocalMarketDataStore(tmp_path)
    client = TushareLocalClient(store=store, tushare_api=FakeTushare())

    df = client.get_stock_hist_data("000001", start_date="20260101", end_date="20260102")

    assert df["close"].tolist() == [10.5, 11.5]
    assert store.path_for("tushare", "daily", "000001", {"adjust": "qfq"}).exists()
    assert not store.path_for("akshare", "hist_daily", "000001", {"period": "daily", "adjust": "qfq"}).exists()


def test_tdx_kline_local_hit_avoids_remote(tmp_path):
    store = LocalMarketDataStore(tmp_path)
    client = TdxLocalClient(store=store)
    store.merge_frame(
        "tdx",
        "kline",
        "000001",
        pd.DataFrame(
            [
                {"symbol": "000001", "datetime": "2026-01-01", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "amount": 10000},
                {"symbol": "000001", "datetime": "2026-01-02", "open": 11, "high": 12, "low": 10, "close": 11.5, "volume": 1100, "amount": 11000},
            ]
        ),
        params={"kline_type": "day"},
        key_columns=["symbol", "datetime"],
    )
    calls = []

    df = client.get_kline_data("000001", kline_type="day", limit=2, remote_fetcher=lambda: calls.append("remote") or pd.DataFrame())

    assert calls == []
    assert df["收盘"].tolist() == [10.5, 11.5]
    assert set(df["cache_source"]) == {"local_tdx"}


def test_tdx_quote_ttl_hit_avoids_remote(tmp_path):
    store = LocalMarketDataStore(tmp_path)
    client = TdxLocalClient(store=store)
    now = datetime(2026, 4, 24, 10, 30)
    store.merge_frame(
        "tdx",
        "realtime_quote",
        "000001",
        pd.DataFrame([{"symbol": "000001", "current_price": 12.3, "quote_time": now, "fetched_at": now, "name": "平安银行"}]),
        key_columns=["symbol", "quote_time"],
    )
    calls = []

    quote = client.get_realtime_quote(
        "000001",
        ttl_seconds=60,
        now=now + timedelta(seconds=20),
        remote_fetcher=lambda: calls.append("remote") or {"code": "000001", "current_price": 12.8},
    )

    assert calls == []
    assert quote["current_price"] == 12.3
    assert quote["data_source"] == "tdx"
    assert quote["cache_source"] == "local_tdx"


def test_tdx_remote_kline_can_feed_indicator_calculation_shape(tmp_path):
    store = LocalMarketDataStore(tmp_path)
    client = TdxLocalClient(store=store)

    df = client.get_kline_data(
        "000001",
        kline_type="day",
        limit=2,
        remote_fetcher=lambda: pd.DataFrame(
            [
                {"日期": "2026-01-01", "开盘": 10, "最高": 11, "最低": 9, "收盘": 10.5, "成交量": 1000, "成交额": 10000},
                {"日期": "2026-01-02", "开盘": 11, "最高": 12, "最低": 10, "收盘": 11.5, "成交量": 1100, "成交额": 11000},
            ]
        ),
    )

    assert list(df.columns[:7]) == ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"]
    assert set(df["cache_source"]) == {"remote_tdx"}
