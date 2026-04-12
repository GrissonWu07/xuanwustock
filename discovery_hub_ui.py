"""Aggregate discovery experience for selector-style stock finders."""

from __future__ import annotations

import streamlit as st

from low_price_bull_ui import display_low_price_bull
from main_force_ui import display_main_force_selector


def display_discovery_hub() -> None:
    """Render the selector aggregate page."""

    st.markdown("## 🔎 发现股票")
    st.caption("把各个选股策略收在一个入口里。筛出来的股票留在策略结果里查看，并按需加入关注池。")
    st.markdown("---")

    tab_main_force, tab_low_price, tab_small_cap, tab_profit_growth, tab_value = st.tabs(
        ["💰 主力选股", "🐂 低价擒牛", "📊 小市值", "📈 净利增长", "💎 低估值"]
    )

    with tab_main_force:
        display_main_force_selector()

    with tab_low_price:
        display_low_price_bull()

    with tab_small_cap:
        from small_cap_ui import display_small_cap

        display_small_cap()

    with tab_profit_growth:
        from profit_growth_ui import display_profit_growth

        display_profit_growth()

    with tab_value:
        from value_stock_ui import display_value_stock

        display_value_stock()
