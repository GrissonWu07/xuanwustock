"""Aggregate research and intelligence experience."""

from __future__ import annotations

import streamlit as st

from longhubang_ui import display_longhubang
from news_flow_ui import display_news_flow_monitor
from sector_strategy_ui import display_sector_strategy


def display_research_hub() -> None:
    """Render the research aggregate page."""

    st.markdown("## 🧠 研究情报")
    st.caption("把板块、龙虎榜、新闻、宏观和周期分析收在一个入口里。只有模块里出现明确股票输出时，才按需加入关注池。")
    st.markdown("---")

    tab_sector, tab_longhubang, tab_news, tab_macro, tab_cycle = st.tabs(
        ["🎯 智策板块", "🐉 智瞰龙虎", "📰 新闻流量", "🌏 宏观分析", "🧭 宏观周期"]
    )

    with tab_sector:
        display_sector_strategy()

    with tab_longhubang:
        display_longhubang()

    with tab_news:
        display_news_flow_monitor()

    with tab_macro:
        from macro_analysis_ui import display_macro_analysis

        display_macro_analysis()

    with tab_cycle:
        from macro_cycle_ui import display_macro_cycle

        display_macro_cycle()
