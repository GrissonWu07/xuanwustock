from __future__ import annotations

from typing import Callable

import pandas as pd
import streamlit as st

from watchlist_service import WatchlistService


def _render_section_header(title: str, description: str) -> None:
    st.markdown(
        f"""
        <div class="workbench-section-header">
            <div class="workbench-section-title">{title}</div>
            <div class="workbench-section-note">{description}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def display_watchlist_workbench(activate_view: Callable[[str | None], None]) -> None:
    service = WatchlistService()
    watches = service.list_watches()

    top_left, top_right = st.columns([2.15, 1.0], gap="large")

    with top_left:
        _render_section_header(
            "关注池",
            "先看你真正关心的股票：实时价格、来源和状态都汇总在这里，后续股票分析与量化都从这里发起。",
        )
        _render_watchlist_actions(service)
        _render_watchlist_table(watches)

    with top_right:
        _render_section_header(
            "下一步",
            "从关注池继续走向持仓分析、监控、发现股票、研究情报与量化验证，不需要在侧边栏里来回找。",
        )
        _render_next_step_buttons(activate_view)


def _render_watchlist_actions(service: WatchlistService) -> None:
    with st.form("watchlist_add_form", clear_on_submit=True):
        code_col, name_col, source_col, action_col = st.columns([1.15, 1.35, 1.05, 0.7], gap="small")
        with code_col:
            stock_code = st.text_input("股票代码", placeholder="例如 300390")
        with name_col:
            stock_name = st.text_input("股票名称", placeholder="例如 天华新能")
        with source_col:
            source = st.text_input("来源", value="manual")
        with action_col:
            st.markdown('<div style="height: 1.85rem;"></div>', unsafe_allow_html=True)
            submitted = st.form_submit_button("添加", type="primary", use_container_width=True)

        if submitted:
            if stock_code and stock_name and source:
                service.add_stock(stock_code=stock_code, stock_name=stock_name, source=source)
                st.success(f"✅ {stock_code} - {stock_name} 已加入关注池")
                st.rerun()
            else:
                st.warning("请完整填写股票代码、名称和来源。")


def _render_watchlist_table(watches: list[dict]) -> None:
    if not watches:
        st.info("关注池还是空的。你可以手工添加，也可以先去发现股票或研究情报页挑股票。")
        return

    metric_cols = st.columns(3)
    metric_cols[0].metric("关注股票", len(watches))
    metric_cols[1].metric("量化候选", sum(1 for row in watches if row.get("in_quant_pool")))
    metric_cols[2].metric("最近更新", watches[0]["updated_at"][:16].replace("T", " "))

    rows = [
        {
            "代码": row["stock_code"],
            "名称": row["stock_name"],
            "现价": row["latest_price"],
            "来源": row["source_summary"],
            "量化候选": "是" if row["in_quant_pool"] else "否",
            "最近分析": row["latest_signal"] or "-",
        }
        for row in watches
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with st.expander("管理关注池", expanded=False):
        delete_code = st.selectbox(
            "删除股票",
            options=[row["stock_code"] for row in watches],
            format_func=lambda code: f"{code} - {next(item['stock_name'] for item in watches if item['stock_code'] == code)}",
        )
        if st.button("删除", key="watchlist_delete_button", use_container_width=True):
            service = WatchlistService()
            service.delete_stock(delete_code)
            st.success(f"已从关注池移除 {delete_code}")
            st.rerun()


def _render_next_step_buttons(activate_view: Callable[[str | None], None]) -> None:
    next_steps = [
        ("持仓分析", "show_portfolio"),
        ("实时监控", "show_monitor"),
        ("AI盯盘", "show_smart_monitor"),
        ("发现股票", "show_main_force"),
        ("研究情报", "show_sector_strategy"),
        ("量化模拟", "show_quant_sim"),
        ("历史回放", "show_quant_replay"),
    ]
    for label, flag in next_steps:
        if st.button(label, key=f"watchlist_next_{flag}", use_container_width=True):
            activate_view(flag)
            st.rerun()
