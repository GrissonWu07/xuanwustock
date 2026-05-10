import pandas as pd

from app.local_market_data_clients import TdxLocalClient
from app.local_market_data_store import LocalMarketDataStore
from app.smart_monitor_tdx_data import SmartMonitorTDXDataFetcher


def test_get_realtime_quote_normalizes_pytdx_fields(monkeypatch):
    fetcher = SmartMonitorTDXDataFetcher(host="127.0.0.1", port=7709, fallback_hosts=[])

    monkeypatch.setattr(
        fetcher,
        "_fetch_quote_data",
        lambda market, code: {
            "price": 12.34,
            "last_close": 12.0,
            "open": 12.1,
            "high": 12.5,
            "low": 11.8,
            "vol": 123456,
            "amount": 9876543.21,
            "servertime": "14:35:12.000",
        },
    )
    monkeypatch.setattr(fetcher, "_get_stock_name", lambda stock_code: "平安银行")

    quote = fetcher.get_realtime_quote("000001")

    assert quote["code"] == "000001"
    assert quote["name"] == "平安银行"
    assert quote["current_price"] == 12.34
    assert quote["pre_close"] == 12.0
    assert quote["change_amount"] == 0.34
    assert round(quote["change_pct"], 2) == 2.83
    assert quote["volume"] == 123456
    assert quote["amount"] == 9876543.21
    assert quote["high"] == 12.5
    assert quote["low"] == 11.8
    assert quote["open"] == 12.1
    assert quote["data_source"] == "tdx"
    assert quote["update_time"].endswith("14:35:12")


def test_get_kline_data_sorts_and_limits_pytdx_bars(monkeypatch):
    fetcher = SmartMonitorTDXDataFetcher(host="127.0.0.1", port=7709, fallback_hosts=[])
    fetcher.local_client = TdxLocalClient(store=LocalMarketDataStore(enabled=False))

    monkeypatch.setattr(
        fetcher,
        "_fetch_kline_data",
        lambda market, code, category, start, count: [
            {
                "datetime": "2024-01-03 15:00",
                "open": 10.3,
                "close": 10.5,
                "high": 10.8,
                "low": 10.1,
                "vol": 3000,
                "amount": 33000.0,
            },
            {
                "datetime": "2024-01-02 15:00",
                "open": 10.0,
                "close": 10.2,
                "high": 10.4,
                "low": 9.9,
                "vol": 2000,
                "amount": 22000.0,
            },
            {
                "datetime": "2024-01-01 15:00",
                "open": 9.8,
                "close": 10.0,
                "high": 10.1,
                "low": 9.7,
                "vol": 1000,
                "amount": 10000.0,
            },
        ],
    )

    df = fetcher.get_kline_data("000001", kline_type="day", limit=2)

    assert list(df.columns) == ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"]
    assert pd.api.types.is_datetime64_any_dtype(df["日期"])
    assert df["日期"].dt.strftime("%Y-%m-%d").tolist() == ["2024-01-02", "2024-01-03"]
    assert df["收盘"].tolist() == [10.2, 10.5]
    assert df["成交量"].tolist() == [2000, 3000]


def test_get_kline_data_range_aggregates_pages_and_filters_dates(monkeypatch):
    fetcher = SmartMonitorTDXDataFetcher(host="127.0.0.1", port=7709, fallback_hosts=[])

    def fake_fetch(market, code, category, start, count):
        if start == 0:
            return [
                {
                    "datetime": "2024-01-03 15:00",
                    "open": 10.3,
                    "close": 10.5,
                    "high": 10.8,
                    "low": 10.1,
                    "vol": 3000,
                    "amount": 33000.0,
                },
                {
                    "datetime": "2024-01-02 15:00",
                    "open": 10.0,
                    "close": 10.2,
                    "high": 10.4,
                    "low": 9.9,
                    "vol": 2000,
                    "amount": 22000.0,
                },
            ]
        if start == 800:
            return [
                {
                    "datetime": "2024-01-01 15:00",
                    "open": 9.8,
                    "close": 10.0,
                    "high": 10.1,
                    "low": 9.7,
                    "vol": 1000,
                    "amount": 10000.0,
                }
            ]
        return []

    monkeypatch.setattr(fetcher, "_fetch_kline_data", fake_fetch)

    df = fetcher.get_kline_data_range(
        "000001",
        kline_type="day",
        start_datetime="2024-01-02 00:00:00",
        end_datetime="2024-01-03 23:59:59",
        max_bars=1600,
    )

    assert df["日期"].dt.strftime("%Y-%m-%d").tolist() == ["2024-01-02", "2024-01-03"]
    assert df["收盘"].tolist() == [10.2, 10.5]


def test_build_snapshot_from_history_computes_historical_replay_snapshot(monkeypatch):
    fetcher = SmartMonitorTDXDataFetcher(host="127.0.0.1", port=7709, fallback_hosts=[])
    monkeypatch.setattr(fetcher, "_get_stock_name", lambda stock_code: "平安银行")

    dates = pd.date_range("2024-01-01", periods=80, freq="D")
    history_df = pd.DataFrame(
        {
            "日期": dates,
            "开盘": [10 + index * 0.1 for index in range(80)],
            "收盘": [10.1 + index * 0.1 for index in range(80)],
            "最高": [10.2 + index * 0.1 for index in range(80)],
            "最低": [9.9 + index * 0.1 for index in range(80)],
            "成交量": [1000 + index * 10 for index in range(80)],
            "成交额": [10000 + index * 100 for index in range(80)],
        }
    )

    snapshot = fetcher.build_snapshot_from_history("000001", history_df)

    assert snapshot["code"] == "000001"
    assert snapshot["name"] == "平安银行"
    assert snapshot["data_source"] == "historical_replay"
    assert snapshot["current_price"] == history_df.iloc[-1]["收盘"]
    assert "ma5" in snapshot
    assert "macd" in snapshot


def test_build_snapshot_from_history_reuses_precomputed_indicator_frame(monkeypatch):
    fetcher = SmartMonitorTDXDataFetcher(host="127.0.0.1", port=7709, fallback_hosts=[])
    monkeypatch.setattr(fetcher, "_get_stock_name", lambda stock_code: "平安银行")

    dates = pd.date_range("2024-01-01", periods=80, freq="D")
    history_df = pd.DataFrame(
        {
            "日期": dates,
            "开盘": [10 + index * 0.1 for index in range(80)],
            "收盘": [10.1 + index * 0.1 for index in range(80)],
            "最高": [10.2 + index * 0.1 for index in range(80)],
            "最低": [9.9 + index * 0.1 for index in range(80)],
            "成交量": [1000 + index * 10 for index in range(80)],
            "成交额": [10000 + index * 100 for index in range(80)],
        }
    )
    indicator_frame = fetcher.build_indicator_history("000001", history_df, timeframe="day")

    def fail_recalculate(*args, **kwargs):
        raise AssertionError("should reuse indicator frame")

    monkeypatch.setattr(fetcher, "_calculate_all_indicators", fail_recalculate)

    snapshot = fetcher.build_snapshot_from_history("000001", history_df.tail(40), indicator_frame=indicator_frame)

    assert snapshot["current_price"] == history_df.iloc[-1]["收盘"]
    assert "ma5" in snapshot
    assert "macd" in snapshot


def test_build_snapshot_from_intraday_history_uses_previous_trading_day_close_for_limit_base(monkeypatch):
    fetcher = SmartMonitorTDXDataFetcher(host="127.0.0.1", port=7709, fallback_hosts=[])
    monkeypatch.setattr(fetcher, "_get_stock_name", lambda stock_code: "测试股票")

    dates = list(pd.date_range("2024-01-02 09:30:00", periods=8, freq="30min"))
    dates.extend(pd.date_range("2024-01-03 09:30:00", periods=8, freq="30min"))
    closes = [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 11.0, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7]
    history_df = pd.DataFrame(
        {
            "日期": dates,
            "开盘": closes,
            "收盘": closes,
            "最高": [value + 0.1 for value in closes],
            "最低": [value - 0.1 for value in closes],
            "成交量": [1000 + index * 10 for index in range(len(closes))],
            "成交额": [10000 + index * 100 for index in range(len(closes))],
        }
    )

    snapshot = fetcher.build_snapshot_from_history("600000", history_df)

    assert snapshot["pre_close"] == 11.6
    assert snapshot["prev_close"] == 10.7


def test_build_snapshot_from_history_uses_supplied_stock_name_without_lookup(monkeypatch):
    fetcher = SmartMonitorTDXDataFetcher(host="127.0.0.1", port=7709, fallback_hosts=[])
    monkeypatch.setattr(fetcher, "_get_stock_name", lambda stock_code: (_ for _ in ()).throw(AssertionError("should not lookup stock name")))

    dates = pd.date_range("2024-01-01", periods=80, freq="D")
    history_df = pd.DataFrame(
        {
            "日期": dates,
            "开盘": [10 + index * 0.1 for index in range(80)],
            "收盘": [10.1 + index * 0.1 for index in range(80)],
            "最高": [10.2 + index * 0.1 for index in range(80)],
            "最低": [9.9 + index * 0.1 for index in range(80)],
            "成交量": [1000 + index * 10 for index in range(80)],
            "成交额": [10000 + index * 100 for index in range(80)],
        }
    )

    snapshot = fetcher.build_snapshot_from_history("000001", history_df, stock_name="测试股票")

    assert snapshot["name"] == "测试股票"
