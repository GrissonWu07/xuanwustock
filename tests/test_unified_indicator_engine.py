from __future__ import annotations

import inspect

import pandas as pd

from app.smart_monitor_tdx_data import SmartMonitorTDXDataFetcher
from app.stock_data import StockDataFetcher


def _canonical_history(rows: int = 90) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=rows, freq="D")
    return pd.DataFrame(
        {
            "symbol": ["000001"] * rows,
            "datetime": dates,
            "open": [10.0 + index * 0.12 for index in range(rows)],
            "high": [10.3 + index * 0.12 for index in range(rows)],
            "low": [9.8 + index * 0.12 for index in range(rows)],
            "close": [10.1 + index * 0.12 for index in range(rows)],
            "volume": [1000 + index * 11 for index in range(rows)],
            "amount": [10000 + index * 101 for index in range(rows)],
            "source": ["fixture"] * rows,
            "dataset": ["hist_daily"] * rows,
            "timeframe": ["1d"] * rows,
            "adjust": ["none"] * rows,
            "provider": ["fixture"] * rows,
            "cache_source": ["fixture"] * rows,
            "fetched_at": dates,
        }
    )


def test_stock_analysis_and_tdx_wrappers_share_indicator_engine() -> None:
    from app.data.indicators.engine import TechnicalIndicatorEngine

    canonical = _canonical_history()
    expected = TechnicalIndicatorEngine().calculate(canonical).iloc[-1]

    stock_df = canonical.rename(
        columns={
            "datetime": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    ).set_index("Date")
    stock_with_indicators = StockDataFetcher().calculate_technical_indicators(stock_df)
    stock_latest = StockDataFetcher().get_latest_indicators(stock_with_indicators)

    tdx_df = canonical.rename(
        columns={
            "datetime": "日期",
            "open": "开盘",
            "high": "最高",
            "low": "最低",
            "close": "收盘",
            "volume": "成交量",
            "amount": "成交额",
        }
    )
    tdx_latest = SmartMonitorTDXDataFetcher(host="127.0.0.1", fallback_hosts=[])._calculate_all_indicators(tdx_df, "000001")

    assert round(float(stock_latest["ma20"]), 6) == round(float(expected["ma20"]), 6)
    assert round(float(stock_latest["rsi"]), 6) == round(float(expected["rsi14"]), 6)
    assert round(float(stock_latest["macd"]), 6) == round(float(expected["macd"]), 6)
    assert round(float(stock_latest["volume_ratio"]), 6) == round(float(expected["volume_ratio"]), 6)
    assert round(float(tdx_latest["ma20"]), 6) == round(float(expected["ma20"]), 6)
    assert round(float(tdx_latest["rsi14"]), 6) == round(float(expected["rsi14"]), 6)
    assert round(float(tdx_latest["macd"]), 6) == round(float(expected["macd"]), 6)
    assert round(float(tdx_latest["volume_ratio"]), 6) == round(float(expected["volume_ratio"]), 6)


def test_business_wrappers_do_not_contain_indicator_formula_logic() -> None:
    import app.low_price_bull_service as low_price_bull_service
    import app.smart_monitor_data as smart_monitor_data
    import app.smart_monitor_tdx_data as smart_monitor_tdx_data
    import app.stock_data as stock_data
    import app.value_stock_strategy as value_stock_strategy

    forbidden = ("ta.", ".rolling(", ".ewm(")
    targets = [
        stock_data.StockDataFetcher.calculate_technical_indicators,
        smart_monitor_tdx_data.SmartMonitorTDXDataFetcher._calculate_all_indicators,
        smart_monitor_data.SmartMonitorDataFetcher._calculate_all_indicators,
        low_price_bull_service.LowPriceBullService._get_stock_data,
        value_stock_strategy.ValueStockStrategy.calculate_rsi,
    ]
    for target in targets:
        source = inspect.getsource(target)
        for token in forbidden:
            assert token not in source
