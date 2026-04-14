import pandas as pd

import app.stock_analysis_service as app_module


def test_get_stock_data_uses_fast_info_path(monkeypatch):
    call_order = []

    class FakeFetcher:
        def get_stock_data(self, symbol, period):
            call_order.append(("data", symbol, period))
            return pd.DataFrame([{"Close": 1.0}, {"Close": 1.2}])

        def get_fast_stock_info(self, symbol):
            call_order.append(("fast_info", symbol))
            return {"symbol": symbol, "name": "测试股"}

        def calculate_technical_indicators(self, stock_data):
            call_order.append(("indicators", len(stock_data)))
            return stock_data

        def get_latest_indicators(self, stock_data):
            call_order.append(("latest", len(stock_data)))
            return {"rsi": 55}

    monkeypatch.setattr(app_module, "StockDataFetcher", FakeFetcher)

    stock_info, stock_data, indicators = app_module.get_stock_data.__wrapped__("301511", "1y")

    assert stock_info["symbol"] == "301511"
    assert indicators == {"rsi": 55}
    assert call_order == [
        ("data", "301511", "1y"),
        ("fast_info", "301511"),
        ("indicators", 2),
        ("latest", 2),
    ]


def test_get_stock_data_preserves_data_source_error(monkeypatch):
    class FakeFetcher:
        def get_stock_data(self, symbol, period):
            return {"error": "所有数据源均无法获取历史数据"}

        def get_fast_stock_info(self, symbol):
            return {"symbol": symbol, "name": "测试股"}

    monkeypatch.setattr(app_module, "StockDataFetcher", FakeFetcher)

    stock_info, stock_data, indicators = app_module.get_stock_data.__wrapped__("301511", "1y")

    assert stock_data is None
    assert indicators is None
    assert stock_info["data_error"] == "所有数据源均无法获取历史数据"
