import os

import pandas as pd

from data_source_manager import DataSourceManager


def test_get_stock_hist_data_temporarily_disables_proxy_env(monkeypatch):
    manager = DataSourceManager()
    manager.tushare_available = False

    captured = {}

    def fake_hist(**kwargs):
        captured["http_proxy"] = os.environ.get("HTTP_PROXY")
        captured["https_proxy"] = os.environ.get("HTTPS_PROXY")
        return pd.DataFrame(
            [
                {
                    "日期": "2026-04-10",
                    "开盘": 10.0,
                    "收盘": 10.5,
                    "最高": 10.8,
                    "最低": 9.9,
                    "成交量": 1000,
                    "成交额": 10000,
                    "振幅": 1.0,
                    "涨跌幅": 1.2,
                    "涨跌额": 0.1,
                    "换手率": 3.2,
                }
            ]
        )

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9999")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    monkeypatch.setattr("akshare.stock_zh_a_hist", fake_hist)

    df = manager.get_stock_hist_data("301511", start_date="20260101", end_date="20260410")

    assert not df.empty
    assert captured == {"http_proxy": None, "https_proxy": None}
    assert os.environ.get("HTTP_PROXY") == "http://127.0.0.1:9999"
    assert os.environ.get("HTTPS_PROXY") == "http://127.0.0.1:9999"
