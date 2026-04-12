from pathlib import Path


def test_discovery_selector_sliders_have_unique_keys():
    files = {
        "low_price_bull": Path("C:/Projects/githubs/aiagents-stock/low_price_bull_ui.py"),
        "small_cap": Path("C:/Projects/githubs/aiagents-stock/small_cap_ui.py"),
        "profit_growth": Path("C:/Projects/githubs/aiagents-stock/profit_growth_ui.py"),
        "value_stock": Path("C:/Projects/githubs/aiagents-stock/value_stock_ui.py"),
    }

    expected_keys = {
        "low_price_bull": 'key="low_price_bull_top_n"',
        "small_cap": 'key="small_cap_top_n"',
        "profit_growth": 'key="profit_growth_top_n"',
        "value_stock": 'key="value_stock_top_n"',
    }

    for name, path in files.items():
        source = path.read_text(encoding="utf-8")
        assert 'st.slider(\n            "筛选数量"' in source
        assert expected_keys[name] in source


def test_discovery_selector_shared_buttons_have_page_specific_keys():
    source_small_cap = Path("C:/Projects/githubs/aiagents-stock/small_cap_ui.py").read_text(encoding="utf-8")
    source_profit = Path("C:/Projects/githubs/aiagents-stock/profit_growth_ui.py").read_text(encoding="utf-8")
    source_low_price = Path("C:/Projects/githubs/aiagents-stock/low_price_bull_ui.py").read_text(encoding="utf-8")

    assert 'key="small_cap_open_monitor"' in source_small_cap
    assert 'key="small_cap_send_dingtalk"' in source_small_cap
    assert 'key="profit_growth_open_monitor"' in source_profit
    assert 'key="profit_growth_send_dingtalk"' in source_profit
    assert 'key="low_price_bull_open_monitor"' in source_low_price
    assert 'key="low_price_bull_start_simulation"' in source_low_price
