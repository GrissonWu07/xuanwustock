from __future__ import annotations

from typing import Callable
import streamlit as st

from quant_sim.candidate_pool_service import CandidatePoolService
from quant_sim.db import QuantSimDB
from quant_sim.portfolio_service import PortfolioService
from streamlit_flash import queue_flash_message, render_flash_messages
from watchlist_integration import add_watchlist_rows_to_quant_pool
from watchlist_service import WatchlistService

WATCHLIST_SELECTION_KEY = "watchlist_selected_codes"
WATCHLIST_FLASH_NAMESPACE = "watchlist_workbench"
WATCHLIST_SELECT_ALL_MANUAL_KEY = "watchlist_select_all_manual"


def _render_watchlist_styles() -> None:
    st.markdown(
        """
        <style>
        .watchlist-cell {
            color: #0f172a;
            font-size: 0.93rem;
            line-height: 1.2;
            padding: 0;
            min-height: 1.85rem;
            display: flex;
            align-items: center;
        }
        .watchlist-cell.muted {
            color: #475569;
        }
        .watchlist-cell.centered {
            justify-content: center;
            text-align: center;
        }
        .watchlist-toolbar-count {
            min-height: 1.85rem;
            display: flex;
            align-items: center;
            justify-content: flex-start;
            color: #64748b;
            font-size: 0.92rem;
            line-height: 1;
            margin: 0;
            padding: 0;
            white-space: nowrap;
        }
        .watchlist-row-divider {
            border-bottom: 1px solid #eef2f7;
            margin: 0.1rem 0 0.18rem 0;
        }
        div[data-testid="stButton"] > button[kind="tertiary"] {
            min-height: 1.35rem;
            height: 1.35rem;
            width: 1.35rem;
            min-width: 1.35rem;
            max-width: 1.35rem;
            padding: 0 !important;
            border: none !important;
            background: transparent !important;
            box-shadow: none !important;
            border-radius: 999px !important;
            color: #475569 !important;
            margin: 0 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
        }
        div[data-testid="stButton"] > button[kind="tertiary"]:hover {
            background: #eef4ff !important;
            color: #2563eb !important;
        }
        div[data-testid="stButton"] > button[kind="tertiary"] p {
            font-size: 0.84rem !important;
            line-height: 1 !important;
            margin: 0 !important;
        }
        div[data-testid="stButton"]:has(> button[kind="tertiary"]) {
            display: flex !important;
            align-items: center !important;
            justify-content: flex-start !important;
            min-height: 1.85rem;
            margin: 0 !important;
            padding: 0 !important;
        }
        .watchlist-checkbox-anchor + div[data-testid="stCheckbox"] {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            min-height: 1.85rem;
            margin: 0 !important;
            padding: 0 !important;
        }
        .watchlist-checkbox-anchor + div[data-testid="stCheckbox"] label {
            justify-content: center !important;
            width: 100% !important;
            margin: 0 !important;
        }
        .watchlist-checkbox-anchor + div[data-testid="stCheckbox"] [data-testid="stMarkdownContainer"] {
            display: none !important;
        }
        .watchlist-next-step + div[data-testid="stButton"] > button {
            width: 100% !important;
            min-height: 2.5rem;
            height: 2.5rem;
            padding: 0.45rem 0.85rem !important;
            border-radius: 0.9rem !important;
            border: 1px solid #dbe4f0 !important;
            background: #ffffff !important;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04) !important;
            color: #1e293b !important;
            justify-content: flex-start !important;
            text-align: left !important;
        }
        .watchlist-next-step + div[data-testid="stButton"] > button:hover {
            background: #f8fbff !important;
            border-color: #bfd4f6 !important;
            color: #0f172a !important;
        }
        .watchlist-next-step + div[data-testid="stButton"] > button p {
            font-size: 0.98rem !important;
            font-weight: 600 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


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


def _render_watchlist_icon_button(icon: str, *, key: str, help_text: str) -> bool:
    return st.button(icon, key=key, help=help_text, type="tertiary")


def _render_next_step_item(label: str, *, key: str) -> bool:
    st.markdown('<div class="watchlist-next-step"></div>', unsafe_allow_html=True)
    return st.button(label, key=key)


def display_watchlist_workbench(activate_view: Callable[[str | None], None]) -> None:
    service = WatchlistService()
    watches = service.list_watches()
    candidate_service = CandidatePoolService()
    portfolio_service = PortfolioService()
    quant_db = QuantSimDB()
    _render_watchlist_styles()

    top_left, top_right = st.columns([2.8, 0.9], gap="large")

    with top_left:
        render_flash_messages(WATCHLIST_FLASH_NAMESPACE)
        overview_metrics = _build_watchlist_overview_metrics(
            watches,
            candidate_service=candidate_service,
            portfolio_service=portfolio_service,
            quant_db=quant_db,
        )
        _render_watchlist_overview_metrics(overview_metrics)
        _render_section_header(
            "我的关注",
            "先看你真正关心的股票：实时价格、来源和状态都汇总在这里，后续股票分析与量化都从这里发起。",
        )
        _render_watchlist_actions(service)
        _render_watchlist_table(service, watches, candidate_service)

    with top_right:
        _render_section_header(
            "下一步",
            "从关注池继续走向持仓分析、监控、发现股票、研究情报与量化验证，不需要在侧边栏里来回找。",
        )
        _render_next_step_buttons(activate_view)


def _render_watchlist_actions(service: WatchlistService) -> None:
    with st.form("watchlist_add_form", clear_on_submit=True):
        code_col, action_col = st.columns([2.2, 0.65], gap="small")
        with code_col:
            stock_code = st.text_input("股票代码", placeholder="例如 300390")
        with action_col:
            st.markdown('<div style="height: 1.85rem;"></div>', unsafe_allow_html=True)
            submitted = st.form_submit_button("添加", type="primary", use_container_width=True)

        if submitted:
            if stock_code:
                normalized_code = str(stock_code).strip().upper()
                service.add_manual_stock(stock_code=normalized_code)
                queue_flash_message(
                    st.session_state,
                    WATCHLIST_FLASH_NAMESPACE,
                    "success",
                    f"✅ {normalized_code} 已加入我的关注",
                )
                st.rerun()
            else:
                st.warning("请先填写股票代码。")


def _build_watchlist_overview_metrics(
    watches: list[dict],
    *,
    candidate_service: CandidatePoolService,
    portfolio_service: PortfolioService,
    quant_db: QuantSimDB,
) -> dict[str, int]:
    account_summary = portfolio_service.get_account_summary()
    candidate_count = len(candidate_service.list_candidates())
    task_count = len(quant_db.get_sim_runs(limit=1000))
    return {
        "watch_count": len(watches),
        "position_count": int(account_summary.get("position_count") or 0),
        "quant_candidate_count": candidate_count,
        "quant_task_count": task_count,
    }


def _render_watchlist_overview_metrics(metrics: dict[str, int]) -> None:
    metric_cols = st.columns(4, gap="small")
    metric_cols[0].metric("我的关注", metrics["watch_count"])
    metric_cols[1].metric("我的持仓", metrics["position_count"])
    metric_cols[2].metric("量化候选", metrics["quant_candidate_count"])
    metric_cols[3].metric("量化任务", metrics["quant_task_count"])
    st.markdown("<div style='height: 0.35rem;'></div>", unsafe_allow_html=True)


def _render_watchlist_table(
    service: WatchlistService,
    watches: list[dict],
    candidate_service: CandidatePoolService,
) -> None:
    if not watches:
        st.info("我的关注还是空的。你可以手工添加，也可以先去发现股票或研究情报页挑股票。")
        return

    st.caption("报价支持手动刷新；量化调度运行时也会把最新价格和信号回写到这里。")
    selected_codes = _get_watchlist_selected_codes(watches)
    _render_watchlist_bulk_actions(
        selected_codes=selected_codes,
        watches=watches,
        service=service,
        candidate_service=candidate_service,
    )

    column_spec = [0.12, 0.86, 1.0, 0.62, 0.74, 0.74, 0.5]
    header_cols = st.columns(column_spec, gap="small", vertical_alignment="center")
    all_selected = len(selected_codes) == len(watches)
    header_key = "watchlist_select_all_header"
    if not st.session_state.pop(WATCHLIST_SELECT_ALL_MANUAL_KEY, False):
        st.session_state[header_key] = all_selected
    with header_cols[0]:
        st.markdown('<div class="watchlist-checkbox-anchor"></div>', unsafe_allow_html=True)
        st.checkbox(
            "全选当前页",
            key=header_key,
            label_visibility="collapsed",
            on_change=_toggle_watchlist_select_all,
            args=(watches, header_key),
        )
    header_titles = ["代码", "名称", "现价", "来源", "状态"]
    for col, title in zip(header_cols[1:6], header_titles, strict=False):
        col.markdown(f"**{title}**")
    header_cols[6].markdown('<div class="watchlist-cell centered"><strong>操作</strong></div>', unsafe_allow_html=True)

    for row in watches:
        stock_code = row["stock_code"]
        checkbox_key = f"watchlist_select_{stock_code}"
        if checkbox_key not in st.session_state:
            st.session_state[checkbox_key] = stock_code in selected_codes

        row_cols = st.columns(column_spec, gap="small", vertical_alignment="center")
        with row_cols[0]:
            st.markdown('<div class="watchlist-checkbox-anchor"></div>', unsafe_allow_html=True)
            checked = st.checkbox("选择", key=checkbox_key, label_visibility="collapsed")
        if checked:
            selected_codes.add(stock_code)
        else:
            selected_codes.discard(stock_code)

        row_cols[1].markdown(f'<div class="watchlist-cell">{stock_code}</div>', unsafe_allow_html=True)
        row_cols[2].markdown(f'<div class="watchlist-cell">{row["stock_name"]}</div>', unsafe_allow_html=True)
        price_text = "-" if not row.get("latest_price") else f'{row["latest_price"]:.2f}'
        row_cols[3].markdown(f'<div class="watchlist-cell">{price_text}</div>', unsafe_allow_html=True)
        row_cols[4].markdown(f'<div class="watchlist-cell muted">{row["source_summary"]}</div>', unsafe_allow_html=True)
        status_text = "量化中" if row.get("in_quant_pool") else (row.get("latest_signal") or "待分析")
        row_cols[5].markdown(f'<div class="watchlist-cell muted">{status_text}</div>', unsafe_allow_html=True)

        with row_cols[6]:
            action_cols = st.columns([0.12, 0.12], gap="small", vertical_alignment="center")
            with action_cols[0]:
                if row.get("in_quant_pool"):
                    st.markdown('<div class="watchlist-cell muted centered">✓</div>', unsafe_allow_html=True)
                else:
                    if _render_watchlist_icon_button("🧪", key=f"watchlist_row_add_quant_{stock_code}", help_text="加入量化池"):
                        summary = add_watchlist_rows_to_quant_pool([stock_code], service, candidate_service)
                        if summary["success_count"] > 0:
                            queue_flash_message(
                                st.session_state,
                                WATCHLIST_FLASH_NAMESPACE,
                                "success",
                                f"✅ {stock_code} 已加入量化池",
                            )
                        if summary["failures"]:
                            queue_flash_message(
                                st.session_state,
                                WATCHLIST_FLASH_NAMESPACE,
                                "warning",
                                "；".join(summary["failures"]),
                            )
                        st.rerun()
            with action_cols[1]:
                if _render_watchlist_icon_button("🗑", key=f"watchlist_row_delete_{stock_code}", help_text="从我的关注删除"):
                    service.delete_stock(stock_code)
                    _discard_watchlist_selection(stock_code)
                    queue_flash_message(
                        st.session_state,
                        WATCHLIST_FLASH_NAMESPACE,
                        "success",
                        f"已从我的关注移除 {stock_code}",
                    )
                    st.rerun()

        st.markdown('<div class="watchlist-row-divider"></div>', unsafe_allow_html=True)

    st.session_state[WATCHLIST_SELECTION_KEY] = sorted(selected_codes)


def _get_watchlist_selected_codes(watches: list[dict]) -> set[str]:
    current_codes = {row["stock_code"] for row in watches}
    selected_codes = {
        code
        for code in st.session_state.get(WATCHLIST_SELECTION_KEY, [])
        if code in current_codes
    }
    for stock_code in current_codes:
        checkbox_key = f"watchlist_select_{stock_code}"
        if checkbox_key not in st.session_state:
            continue
        if st.session_state[checkbox_key]:
            selected_codes.add(stock_code)
        else:
            selected_codes.discard(stock_code)
    st.session_state[WATCHLIST_SELECTION_KEY] = sorted(selected_codes)
    return selected_codes


def _render_watchlist_bulk_actions(
    *,
    selected_codes: set[str],
    watches: list[dict],
    service: WatchlistService,
    candidate_service: CandidatePoolService,
) -> None:
    toolbar_cols = st.columns([0.04, 0.04, 0.04, 0.18, 1.0], gap="small", vertical_alignment="center")
    with toolbar_cols[0]:
        if _render_watchlist_icon_button("↻", key="watchlist_refresh_quotes", help_text="刷新我的关注报价"):
            summary = service.refresh_quotes()
            if summary["success_count"] > 0:
                queue_flash_message(
                    st.session_state,
                    WATCHLIST_FLASH_NAMESPACE,
                    "success",
                    f"✅ 已刷新 {summary['success_count']} 只股票报价",
                )
            if summary["failures"]:
                queue_flash_message(
                    st.session_state,
                    WATCHLIST_FLASH_NAMESPACE,
                    "warning",
                    "；".join(summary["failures"][:3]),
                )
            st.rerun()
    with toolbar_cols[1]:
        if _render_watchlist_icon_button("🧪", key="watchlist_bulk_add_quant", help_text="批量加入量化池"):
            if not selected_codes:
                st.warning("请先选择股票。")
            else:
                summary = add_watchlist_rows_to_quant_pool(sorted(selected_codes), service, candidate_service)
                if summary["success_count"] > 0:
                    queue_flash_message(
                        st.session_state,
                        WATCHLIST_FLASH_NAMESPACE,
                        "success",
                        f"✅ 已将 {summary['success_count']} 只股票加入量化池",
                    )
                if summary["failures"]:
                    queue_flash_message(
                        st.session_state,
                        WATCHLIST_FLASH_NAMESPACE,
                        "warning",
                        "；".join(summary["failures"]),
                    )
                st.rerun()
    with toolbar_cols[2]:
        if _render_watchlist_icon_button("✕", key="watchlist_bulk_clear_selection", help_text="清空当前选择"):
            _set_watchlist_selection([], watches)
            st.rerun()
    with toolbar_cols[3]:
        st.markdown(
            f'<div class="watchlist-toolbar-count">已选 {len(selected_codes)} 只股票</div>',
            unsafe_allow_html=True,
        )
    st.markdown("<div style='height: 0.2rem;'></div>", unsafe_allow_html=True)


def _set_watchlist_selection(stock_codes: list[str], watches: list[dict]) -> None:
    selected_set = {str(code).strip().upper() for code in stock_codes}
    st.session_state[WATCHLIST_SELECTION_KEY] = sorted(selected_set)
    for row in watches:
        st.session_state[f"watchlist_select_{row['stock_code']}"] = row["stock_code"] in selected_set


def _toggle_watchlist_select_all(watches: list[dict], header_key: str) -> None:
    target_codes = [row["stock_code"] for row in watches] if st.session_state.get(header_key) else []
    _set_watchlist_selection(target_codes, watches)
    st.session_state[WATCHLIST_SELECT_ALL_MANUAL_KEY] = True


def _discard_watchlist_selection(stock_code: str) -> None:
    normalized_code = str(stock_code).strip().upper()
    selected_codes = {
        code for code in st.session_state.get(WATCHLIST_SELECTION_KEY, []) if code != normalized_code
    }
    st.session_state[WATCHLIST_SELECTION_KEY] = sorted(selected_codes)
    st.session_state.pop(f"watchlist_select_{normalized_code}", None)


def _render_next_step_buttons(activate_view: Callable[[str | None], None]) -> None:
    next_steps = [
        ("持仓分析", "show_portfolio"),
        ("实时监控", "show_monitor"),
        ("AI盯盘", "show_smart_monitor"),
        ("发现股票", "show_discovery_hub"),
        ("研究情报", "show_research_hub"),
        ("量化模拟", "show_quant_sim"),
        ("历史回放", "show_quant_replay"),
    ]
    st.markdown("<div style='height: 0.55rem;'></div>", unsafe_allow_html=True)
    for label, flag in next_steps:
        if _render_next_step_item(label, key=f"watchlist_next_{flag}"):
            activate_view(flag)
            st.rerun()
