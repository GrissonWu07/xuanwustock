import pandas as pd

from stock_data import StockDataFetcher


def test_get_chinese_stock_data_prefers_tdx_before_primary_sources(monkeypatch):
    fetcher = StockDataFetcher()
    call_order = []

    class DummyDataSourceManager:
        def get_stock_hist_data(self, **kwargs):
            call_order.append("primary")
            return pd.DataFrame(
                [
                    {
                        "date": pd.Timestamp("2026-04-10"),
                        "open": 10.0,
                        "close": 10.5,
                        "high": 10.8,
                        "low": 9.9,
                        "volume": 1000,
                    }
                ]
            )

    class DummyTDXFetcher:
        def get_kline_data(self, symbol, kline_type="day", limit=200):
            call_order.append("tdx")
            return pd.DataFrame(
                [
                    {
                        "日期": pd.Timestamp("2026-04-09"),
                        "开盘": 10.0,
                        "收盘": 10.2,
                        "最高": 10.3,
                        "最低": 9.9,
                        "成交量": 1000,
                        "成交额": 20000,
                    },
                    {
                        "日期": pd.Timestamp("2026-04-10"),
                        "开盘": 10.2,
                        "收盘": 10.5,
                        "最高": 10.7,
                        "最低": 10.1,
                        "成交量": 1200,
                        "成交额": 25000,
                    },
                ]
            )

    fetcher.data_source_manager = DummyDataSourceManager()
    monkeypatch.setattr("smart_monitor_tdx_data.SmartMonitorTDXDataFetcher", DummyTDXFetcher)

    df = fetcher._get_chinese_stock_data("301511", period="1y")

    assert call_order == ["tdx"]
    assert not isinstance(df, dict)
    assert list(df["股票代码"].unique()) == ["301511"]


def test_get_chinese_stock_data_falls_back_to_tdx_when_primary_sources_fail(monkeypatch):
    fetcher = StockDataFetcher()

    class DummyDataSourceManager:
        def get_stock_hist_data(self, **kwargs):
            return None

    class DummyTDXFetcher:
        def get_kline_data(self, symbol, kline_type="day", limit=200):
            return pd.DataFrame(
                [
                    {
                        "日期": pd.Timestamp("2026-04-09"),
                        "开盘": 10.0,
                        "收盘": 10.2,
                        "最高": 10.3,
                        "最低": 9.9,
                        "成交量": 1000,
                        "成交额": 20000,
                    },
                    {
                        "日期": pd.Timestamp("2026-04-10"),
                        "开盘": 10.2,
                        "收盘": 10.5,
                        "最高": 10.7,
                        "最低": 10.1,
                        "成交量": 1200,
                        "成交额": 25000,
                    },
                ]
            )

    fetcher.data_source_manager = DummyDataSourceManager()
    monkeypatch.setattr("smart_monitor_tdx_data.SmartMonitorTDXDataFetcher", DummyTDXFetcher)

    df = fetcher._get_chinese_stock_data("301511", period="1y")

    assert not isinstance(df, dict)
    assert list(df.columns[:5]) == ["Open", "Close", "High", "Low", "Volume"]
    assert list(df["股票代码"].unique()) == ["301511"]
    assert df.index.name == "Date"
