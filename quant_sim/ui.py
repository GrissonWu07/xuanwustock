"""Streamlit UI for the unified quant simulation workflow."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st

from quant_sim.candidate_pool_service import CandidatePoolService
from quant_sim.db import DEFAULT_DB_FILE, QuantSimDB
from quant_sim.engine import QuantSimEngine
from quant_sim.portfolio_service import PortfolioService
from quant_sim.replay_runner import get_quant_sim_replay_runner
from quant_sim.replay_service import QuantSimReplayService
from quant_sim.scheduler import get_quant_sim_scheduler
from quant_sim.signal_center_service import SignalCenterService
from streamlit_flash import queue_flash_message, render_flash_messages


QUANT_SIM_FLASH_NAMESPACE = "quant_sim"
ANALYSIS_TIMEFRAME_OPTIONS = ["30m", "1d", "1d+30m"]
STRATEGY_MODE_OPTIONS = ["auto", "aggressive", "neutral", "defensive"]
REPLAY_STALE_TIMEOUT_SECONDS = 180


def _format_analysis_timeframe(value: str) -> str:
    labels = {
        "30m": "30分钟",
        "1d": "日线",
        "1d+30m": "日线方向 + 30分钟确认",
    }
    return labels.get(str(value), str(value))


def _format_strategy_mode(value: str) -> str:
    labels = {
        "auto": "自动",
        "aggressive": "激进",
        "neutral": "中性",
        "defensive": "稳健",
    }
    return labels.get(str(value), str(value))


def display_quant_sim() -> None:
    """Render the end-to-end quant simulation workspace."""

    candidate_service = CandidatePoolService()
    signal_service = SignalCenterService()
    portfolio_service = PortfolioService()
    engine = QuantSimEngine()
    scheduler = get_quant_sim_scheduler()
    account_summary = portfolio_service.get_account_summary()
    scheduler_status = scheduler.get_status()

    render_workspace_section_header(
        "🧪 量化模拟",
        "围绕量化候选池启动模拟、查看账户变化，并处理当前信号。",
    )
    render_flash_messages(QUANT_SIM_FLASH_NAMESPACE)

    render_workspace_metric_band(
        [
            ("初始资金池", f"{account_summary['initial_cash']:.2f}"),
            ("可用现金", f"{account_summary['available_cash']:.2f}"),
            ("持仓市值", f"{account_summary['market_value']:.2f}"),
            ("总权益", f"{account_summary['total_equity']:.2f}"),
            ("总盈亏", f"{account_summary['total_pnl']:.2f}"),
        ]
    )

    status_level, status_message = build_scheduler_status_message(scheduler_status)
    getattr(st, status_level)(status_message)
    render_quant_sim_layout_styles()
    config_col, results_col = st.columns([1.0, 2.25], gap="large")
    with config_col:
        render_quant_sim_config_panel(
            scheduler=scheduler,
            portfolio_service=portfolio_service,
            account_summary=account_summary,
            scheduler_status=scheduler_status,
        )
        render_quant_sim_status_snapshot(scheduler_status)
    with results_col:
        render_quant_sim_account_results(
            portfolio_service=portfolio_service,
            account_summary=account_summary,
        )
        render_quant_sim_candidate_pool(
            candidate_service=candidate_service,
            portfolio_service=portfolio_service,
            engine=engine,
            scheduler=scheduler,
        )
        render_quant_sim_execution_center(
            signal_service=signal_service,
            portfolio_service=portfolio_service,
            candidate_service=candidate_service,
        )
    if st.session_state.get("quant_sim_candidate_analysis_signal"):
        render_quant_sim_candidate_analysis_dialog()


def render_quant_sim_layout_styles() -> None:
    st.markdown(
        """
        <style>
        .workspace-section-header {
            margin-bottom: 1.15rem;
        }
        .workspace-section-title {
            font-size: 1.68rem;
            font-weight: 800;
            color: #23304d;
            margin: 0;
            letter-spacing: -0.03em;
        }
        .workspace-section-note {
            color: #71809a;
            font-size: 0.92rem;
            line-height: 1.6;
            margin: 0.45rem 0 0 0;
        }
        .workspace-metric-band {
            margin-bottom: 1rem;
        }
        div[data-testid="stMetric"] {
            background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
            border: 1px solid #e5e7eb;
            border-radius: 16px;
            padding: 0.65rem 0.85rem;
        }
        div[data-testid="stMetric"] label {
            color: #64748b;
        }
        div[data-testid="stMetricValue"] {
            color: #0f172a;
        }
        .quant-sim-panel-caption {
            color: #64748b;
            font-size: 0.93rem;
            margin-top: -0.15rem;
            margin-bottom: 0.75rem;
        }
        .quant-sim-status-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.55rem;
            margin-bottom: 0.65rem;
        }
        .quant-sim-status-card {
            background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
            border: 1px solid #e5e7eb;
            border-radius: 16px;
            padding: 0.68rem 0.8rem;
        }
        .quant-sim-status-label {
            color: #7c8aa5;
            font-size: 0.78rem;
            font-weight: 600;
            line-height: 1.2;
            margin-bottom: 0.3rem;
        }
        .quant-sim-status-value {
            color: #0f172a;
            font-size: 1.02rem;
            font-weight: 700;
            line-height: 1.15;
            letter-spacing: -0.02em;
        }
        .quant-sim-status-footnote {
            color: #64748b;
            font-size: 0.84rem;
            margin-top: 0.15rem;
        }
        .quant-sim-trade-analysis-grid {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 0.6rem;
            margin-bottom: 0.5rem;
        }
        .quant-sim-trade-analysis-card {
            background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
            border: 1px solid #e5e7eb;
            border-radius: 16px;
            padding: 0.7rem 0.85rem;
        }
        .quant-sim-trade-analysis-label {
            color: #7c8aa5;
            font-size: 0.78rem;
            font-weight: 600;
            line-height: 1.2;
            margin-bottom: 0.28rem;
        }
        .quant-sim-trade-analysis-value {
            color: #0f172a;
            font-size: 0.96rem;
            font-weight: 700;
            line-height: 1.18;
            letter-spacing: -0.01em;
        }
        .quant-sim-candidate-cell {
            color: #0f172a;
            font-size: 0.93rem;
            line-height: 1.25;
            padding: 0.1rem 0 0.12rem 0;
            min-height: 1.4rem;
            display: flex;
            align-items: center;
        }
        .quant-sim-candidate-cell.muted {
            color: #475569;
        }
        .quant-sim-row-divider {
            border-bottom: 1px solid #eef2f7;
            margin: 0.2rem 0 0.2rem 0;
        }
        .quant-icon-button + div[data-testid="stButton"] > button[kind="tertiary"] {
            min-height: 1.45rem;
            height: 1.45rem;
            width: 1.45rem;
            min-width: 1.45rem;
            max-width: 1.45rem;
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
        .quant-icon-button + div[data-testid="stButton"] > button[kind="tertiary"]:hover {
            background: #eef4ff !important;
            color: #2563eb !important;
        }
        .quant-icon-button + div[data-testid="stButton"] > button[kind="tertiary"] p {
            font-size: 0.88rem !important;
            line-height: 1 !important;
            margin: 0 !important;
        }
        .quant-icon-button + div[data-testid="stButton"]:has(> button[kind="tertiary"]) {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            min-height: 1.45rem;
            margin: 0 !important;
            padding: 0 !important;
        }
        .quant-footer-control-label {
            color: #7c8aa5;
            font-size: 0.76rem;
            font-weight: 600;
            margin: 0 0 0.18rem 0;
        }
        div.element-container:has(#quant-page-size-marker) + div.element-container [data-baseweb="select"] {
            min-height: 2.1rem !important;
        }
        div.element-container:has(#quant-page-size-marker) + div.element-container [data-baseweb="select"] * {
            font-size: 0.84rem !important;
        }
        div.element-container:has(#quant-page-marker) + div.element-container input {
            min-height: 2.1rem !important;
            font-size: 0.84rem !important;
        }
        div.element-container:has(#quant-page-marker) + div.element-container button {
            min-height: 2.1rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_workspace_section_header(title: str, description: str) -> None:
    st.markdown(
        f"""
        <div class="workspace-section-header">
            <div class="workspace-section-title">{title}</div>
            <p class="workspace-section-note">{description}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_workspace_metric_band(items: list[tuple[str, str]], *, gap: str = "small") -> None:
    metric_cols = st.columns(len(items), gap=gap)
    for col, (label, value) in zip(metric_cols, items, strict=False):
        col.metric(label, value)


def render_quant_sim_status_snapshot(scheduler_status: dict) -> None:
    render_workspace_section_header(
        "运行状态",
        "这里展示当前定时任务的运行状态和关键参数。",
    )
    cards_html = "".join(
        [
            _build_quant_status_card_html("定时状态", "运行中" if scheduler_status["running"] else "已停止"),
            _build_quant_status_card_html("分析粒度", _format_analysis_timeframe(str(scheduler_status["analysis_timeframe"]))),
            _build_quant_status_card_html("策略模式", _format_strategy_mode(str(scheduler_status["strategy_mode"]))),
            _build_quant_status_card_html("自动执行", "已开启" if scheduler_status["auto_execute"] else "关闭"),
        ]
    )
    st.markdown(f'<div class="quant-sim-status-grid">{cards_html}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="quant-sim-status-footnote">上次运行：{scheduler_status["last_run_at"] or "暂无"} | 下次运行：{scheduler_status["next_run"] or "未启动"}</div>',
        unsafe_allow_html=True,
    )


def _build_quant_status_card_html(label: str, value: str) -> str:
    return (
        '<div class="quant-sim-status-card">'
        f'<div class="quant-sim-status-label">{label}</div>'
        f'<div class="quant-sim-status-value">{value}</div>'
        "</div>"
    )


def render_replay_trade_analysis_cards(trade_analysis: dict) -> None:
    cards_html = "".join(
        [
            _build_quant_trade_analysis_card_html("总买入金额", f"{float(trade_analysis['total_buy_amount']):.2f}"),
            _build_quant_trade_analysis_card_html("总卖出金额", f"{float(trade_analysis['total_sell_amount']):.2f}"),
            _build_quant_trade_analysis_card_html("已实现盈亏", f"{float(trade_analysis['total_realized_pnl']):.2f}"),
            _build_quant_trade_analysis_card_html(
                "盈利/亏损笔数",
                f"{int(trade_analysis['winning_trade_count'])}/{int(trade_analysis['losing_trade_count'])}",
            ),
            _build_quant_trade_analysis_card_html("平均单笔盈亏", f"{float(trade_analysis['avg_realized_pnl']):.2f}"),
        ]
    )
    st.markdown(f'<div class="quant-sim-trade-analysis-grid">{cards_html}</div>', unsafe_allow_html=True)


def _build_quant_trade_analysis_card_html(label: str, value: str) -> str:
    return (
        '<div class="quant-sim-trade-analysis-card">'
        f'<div class="quant-sim-trade-analysis-label">{label}</div>'
        f'<div class="quant-sim-trade-analysis-value">{value}</div>'
        "</div>"
    )


def render_quant_sim_config_panel(*, scheduler, portfolio_service: PortfolioService, account_summary: dict, scheduler_status: dict) -> None:
    st.markdown("### 定时任务配置")
    interval_minutes = st.number_input(
        "间隔(分钟)",
        min_value=5,
        max_value=240,
        value=int(scheduler_status["interval_minutes"]),
        step=5,
    )
    trading_hours_only = st.checkbox("仅交易时段运行", value=bool(scheduler_status["trading_hours_only"]))
    analysis_timeframe = st.selectbox(
        "分析粒度",
        options=ANALYSIS_TIMEFRAME_OPTIONS,
        index=ANALYSIS_TIMEFRAME_OPTIONS.index(str(scheduler_status["analysis_timeframe"])),
        format_func=_format_analysis_timeframe,
    )
    strategy_mode = st.selectbox(
        "策略模式",
        options=STRATEGY_MODE_OPTIONS,
        index=STRATEGY_MODE_OPTIONS.index(str(scheduler_status["strategy_mode"])),
        format_func=_format_strategy_mode,
    )
    market = st.selectbox(
        "市场",
        options=["CN", "HK", "US"],
        index=["CN", "HK", "US"].index(str(scheduler_status["market"])),
    )
    auto_execute = st.checkbox("自动执行模拟交易", value=bool(scheduler_status["auto_execute"]))

    initial_cash = st.number_input(
        "初始资金池(元)",
        min_value=10000.0,
        value=float(account_summary["initial_cash"]),
        step=10000.0,
    )
    action_cols = st.columns([0.34, 0.34, 0.32], gap="small")
    with action_cols[0]:
        if render_compact_action_button("保存", key="quant_sim_save_scheduler_config", tone="neutral"):
            handle_scheduler_save(
                scheduler,
                portfolio_service=portfolio_service,
                initial_cash=float(initial_cash),
                auto_execute=auto_execute,
                interval_minutes=int(interval_minutes),
                trading_hours_only=trading_hours_only,
                analysis_timeframe=analysis_timeframe,
                strategy_mode=strategy_mode,
                market=market,
            )
            st.rerun()
    with action_cols[1]:
        if render_compact_action_button("重置", key="quant_sim_reset_account", tone="danger"):
            handle_account_reset(portfolio_service, initial_cash)
            st.rerun()

    if scheduler_status["running"]:
        if st.button("停止", key="quant_sim_stop_scheduler_config", use_container_width=True):
            handle_scheduler_stop(scheduler)
            st.rerun()
    else:
        if st.button("启动模拟", key="quant_sim_start_scheduler_config", type="primary", use_container_width=True):
            handle_scheduler_start(
                scheduler,
                portfolio_service=portfolio_service,
                initial_cash=float(initial_cash),
                auto_execute=auto_execute,
                interval_minutes=int(interval_minutes),
                trading_hours_only=trading_hours_only,
                analysis_timeframe=analysis_timeframe,
                strategy_mode=strategy_mode,
                market=market,
            )
            st.rerun()


def render_quant_sim_candidate_pool(*, candidate_service: CandidatePoolService, portfolio_service: PortfolioService, engine: QuantSimEngine, scheduler) -> None:
    st.markdown("### 候选池")

    candidates = candidate_service.list_candidates(status="active")
    if not candidates:
        st.info("量化候选池为空。请先到工作台的关注池里选择股票，再加入量化候选池。")
        return

    search_term = st.text_input("搜索股票", placeholder="输入代码或名称", key="quant_sim_candidate_search")
    page_size = int(st.session_state.get("quant_sim_candidate_page_size", 20))
    page = int(st.session_state.get("quant_sim_candidate_page", 1))

    filtered_candidates = filter_quant_candidates(candidates, search_term=search_term, selected_sources=None)
    total_candidates = len(filtered_candidates)
    if total_candidates == 0:
        st.info("当前筛选条件下没有候选股，试试清空搜索词。")
        return
    page_count = max(1, (total_candidates + int(page_size) - 1) // int(page_size))
    current_page = min(int(page), page_count)
    if current_page != int(page):
        st.session_state["quant_sim_candidate_page"] = current_page
    start_index = (current_page - 1) * int(page_size)
    end_index = start_index + int(page_size)
    visible_candidates = filtered_candidates[start_index:end_index]

    header_cols = st.columns([1.0, 1.3, 1.6, 0.9, 0.9], gap="small")
    header_cols[0].markdown("**股票代码**")
    header_cols[1].markdown("**股票名称**")
    header_cols[2].markdown("**来源策略**")
    header_cols[3].markdown("**参考价格**")
    header_cols[4].markdown("**操作**")
    st.markdown('<div class="quant-sim-row-divider"></div>', unsafe_allow_html=True)

    for candidate in visible_candidates:
        row_cols = st.columns([1.0, 1.3, 1.6, 0.9, 0.9], gap="small", vertical_alignment="center")
        sources = candidate.get("sources") or [candidate.get("source", "manual")]
        row_cols[0].markdown(f'<div class="quant-sim-candidate-cell">{candidate["stock_code"]}</div>', unsafe_allow_html=True)
        row_cols[1].markdown(
            f'<div class="quant-sim-candidate-cell">{candidate.get("stock_name") or "未命名"}</div>',
            unsafe_allow_html=True,
        )
        row_cols[2].markdown(
            f'<div class="quant-sim-candidate-cell muted">{" / ".join(_format_source(source) for source in sources)}</div>',
            unsafe_allow_html=True,
        )
        row_cols[3].markdown(
            f'<div class="quant-sim-candidate-cell">{candidate.get("latest_price", 0) or 0:.2f}</div>',
            unsafe_allow_html=True,
        )
        with row_cols[4]:
            action_cols = st.columns([0.08, 0.08], gap="small", vertical_alignment="center")
            with action_cols[0]:
                if _render_quant_icon_button("🔎", key=f"candidate_analyze_{candidate['id']}", help_text="分析候选股"):
                    analyze_config = scheduler.db.get_scheduler_config()
                    signal = engine.analyze_candidate(
                        candidate,
                        analysis_timeframe=str(analyze_config["analysis_timeframe"]),
                        strategy_mode=str(analyze_config["strategy_mode"]),
                    )
                    st.session_state["quant_sim_candidate_analysis_signal"] = signal
                    handle_candidate_analysis_feedback(
                        portfolio_service=portfolio_service,
                        signal=signal,
                        auto_execute=bool(analyze_config["auto_execute"]),
                    )
            with action_cols[1]:
                if _render_quant_icon_button("🗑", key=f"candidate_delete_{candidate['id']}", help_text="从候选池删除"):
                    candidate_service.delete_candidate(candidate["stock_code"])
                    current_detail = st.session_state.get("quant_sim_candidate_analysis_signal")
                    if current_detail and current_detail.get("stock_code") == candidate["stock_code"]:
                        st.session_state.pop("quant_sim_candidate_analysis_signal", None)
                    queue_quant_sim_flash("warning", f"已从候选池删除 {candidate['stock_code']}。")
                    st.rerun()
        st.markdown('<div class="quant-sim-row-divider"></div>', unsafe_allow_html=True)

    footer_cols = st.columns([1.5, 0.8, 0.8], gap="small")
    footer_cols[0].caption(f"当前显示 {start_index + 1}-{min(end_index, total_candidates)} / {total_candidates} 只候选股。")
    with footer_cols[1]:
        st.markdown('<div class="quant-footer-control-label">每页显示</div><div id="quant-page-size-marker"></div>', unsafe_allow_html=True)
        st.selectbox(
            "每页显示",
            options=[10, 20, 50],
            index=[10, 20, 50].index(int(page_size)),
            key="quant_sim_candidate_page_size",
            label_visibility="collapsed",
        )
    with footer_cols[2]:
        st.markdown('<div class="quant-footer-control-label">页码</div><div id="quant-page-marker"></div>', unsafe_allow_html=True)
        st.number_input(
            "页码",
            min_value=1,
            max_value=page_count,
            value=current_page,
            step=1,
            key="quant_sim_candidate_page",
            label_visibility="collapsed",
        )


def render_quant_sim_execution_center(*, signal_service: SignalCenterService, portfolio_service: PortfolioService, candidate_service: CandidatePoolService) -> None:
    pending_signals = signal_service.list_pending_signals()
    signals = signal_service.list_signals(limit=100)

    st.markdown("### 执行中心")
    summary_cols = st.columns(4)
    summary_cols[0].metric("待执行", str(len(pending_signals)))
    summary_cols[1].metric("最近信号", str(len(signals)))
    summary_cols[2].metric("待买入", str(sum(1 for signal in pending_signals if str(signal.get("action")).upper() == "BUY")))
    summary_cols[3].metric("待卖出", str(sum(1 for signal in pending_signals if str(signal.get("action")).upper() == "SELL")))

    st.markdown("#### 待执行")
    selected_signal = None
    if pending_signals:
        pending_rows = pd.DataFrame(build_quant_signal_table_rows(pending_signals, include_status=False))
        pending_state = st.dataframe(
            pending_rows,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="quant_sim_pending_signal_table",
        )
        selected_rows = _extract_dataframe_selected_rows(pending_state)
        if selected_rows:
            selected_signal = pending_signals[int(selected_rows[0])]
            st.session_state["quant_sim_execution_signal_detail"] = selected_signal
    else:
        st.info("当前没有待执行信号。")

    st.markdown("#### 信号列表")
    if signals:
        signal_rows = pd.DataFrame(build_quant_signal_table_rows(signals))
        signal_state = st.dataframe(
            signal_rows,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="quant_sim_signal_table",
        )
        selected_rows = _extract_dataframe_selected_rows(signal_state)
        if selected_rows:
            selected_signal = signals[int(selected_rows[0])]
            st.session_state["quant_sim_execution_signal_detail"] = selected_signal
    else:
        st.info("暂无信号记录。")

    selected_signal = selected_signal or st.session_state.get("quant_sim_execution_signal_detail")
    if not selected_signal:
        st.info("点击上方待执行或信号列表中的任意一行，即可查看完整策略解释、阈值与执行建议。")
        return

    st.markdown("#### 信号详情")
    render_quant_sim_signal_detail(selected_signal)
    if str(selected_signal.get("status")) == "pending":
        render_quant_sim_pending_controls(
            signal=selected_signal,
            portfolio_service=portfolio_service,
            candidate_service=candidate_service,
        )


def render_quant_sim_account_results(*, portfolio_service: PortfolioService, account_summary: dict) -> None:
    positions = portfolio_service.list_positions()
    trades = portfolio_service.get_trade_history(limit=100)
    snapshots = portfolio_service.get_account_snapshots(limit=100)

    st.markdown("### 账户结果")
    summary_cols = st.columns(4)
    summary_cols[0].metric("持仓数量", str(account_summary["position_count"]))
    summary_cols[1].metric("成交笔数", str(account_summary["trade_count"]))
    summary_cols[2].metric("已实现盈亏", f"{account_summary['realized_pnl']:.2f}")
    summary_cols[3].metric("未实现盈亏", f"{account_summary['unrealized_pnl']:.2f}")

    account_view = st.radio(
        "账户结果视图",
        options=["持仓", "权益", "成交"],
        horizontal=True,
        key="quant_sim_account_view",
        label_visibility="collapsed",
    )
    if account_view == "持仓":
        if not positions:
            st.info("当前暂无模拟持仓。")
        else:
            st.dataframe(positions, use_container_width=True, hide_index=True)
    elif account_view == "权益":
        if not snapshots:
            st.info("当前还没有权益快照，先运行一次分析或确认一次交易。")
        else:
            snapshot_df = pd.DataFrame(list(reversed(snapshots)))
            snapshot_df["created_at"] = pd.to_datetime(snapshot_df["created_at"])
            chart_df = snapshot_df.set_index("created_at")[["total_equity", "available_cash", "market_value"]]
            st.line_chart(chart_df, use_container_width=True)
            st.dataframe(snapshot_df, use_container_width=True, hide_index=True)
    else:
        if not trades:
            st.info("当前还没有成交记录。")
        else:
            st.dataframe(trades, use_container_width=True, hide_index=True)


def render_quant_sim_candidate_detail() -> None:
    st.markdown("### 候选股详情")
    selected_signal = st.session_state.get("quant_sim_candidate_analysis_signal")
    if not selected_signal:
        st.info("先在候选池里点一只股票的“立即分析”，这里会显示对应的完整策略说明。")
        return
    render_quant_sim_signal_detail(selected_signal)


@st.dialog("候选股分析详情", width="large")
def render_quant_sim_candidate_analysis_dialog() -> None:
    selected_signal = st.session_state.get("quant_sim_candidate_analysis_signal")
    if not selected_signal:
        st.info("当前没有可展示的候选股分析结果。")
        return
    st.caption("这里展示你刚刚从候选池发起的单票分析结果，不会打断主页面布局。")
    render_quant_sim_signal_detail(selected_signal)
    if st.button("关闭", key="quant_sim_close_candidate_analysis_dialog", use_container_width=True):
        st.session_state.pop("quant_sim_candidate_analysis_signal", None)
        st.rerun()


def _render_quant_icon_button(icon: str, *, key: str, help_text: str) -> bool:
    st.markdown('<div class="quant-icon-button"></div>', unsafe_allow_html=True)
    return st.button(icon, key=key, help=help_text, type="tertiary")


def render_quant_sim_signal_detail(signal: dict) -> None:
    st.markdown(render_action_badge_html(signal.get("action", "HOLD")), unsafe_allow_html=True)
    overview_cols = st.columns(4)
    overview_cols[0].metric("标的", str(signal.get("stock_code") or "未知"))
    overview_cols[1].metric("置信度", f"{signal.get('confidence', 0)}%")
    overview_cols[2].metric("建议仓位", f"{signal.get('position_size_pct', 0)}%")
    overview_cols[3].metric("执行状态", str(signal.get("status") or "observed"))
    st.markdown(f"**标的名称**：{signal.get('stock_name') or '未命名'}")
    st.markdown("#### 当前交易策略")
    strategy_summary = render_strategy_profile_summary(signal.get("strategy_profile"))
    if strategy_summary:
        st.markdown(strategy_summary)
    explainability_summary = render_strategy_explainability_summary(
        signal.get("strategy_profile"),
        signal=signal,
    )
    if explainability_summary:
        st.markdown(explainability_summary)
    st.info(_build_replay_signal_detail_summary(signal))
    st.markdown(f"**推理**：{signal.get('reasoning') or '暂无'}")
    st.caption(
        f"创建时间：{signal.get('created_at') or '刚刚'} | 股票：{signal.get('stock_code') or '未知'} | 状态：{signal.get('status') or 'observed'}"
    )


def render_quant_sim_pending_controls(*, signal: dict, portfolio_service: PortfolioService, candidate_service: CandidatePoolService) -> None:
    st.markdown("#### 手动执行")
    default_price = resolve_pending_signal_default_price(
        signal,
        candidate_service=candidate_service,
        portfolio_service=portfolio_service,
    )
    control_cols = st.columns(3)
    with control_cols[0]:
        price = st.number_input("成交价", min_value=0.01, value=float(default_price), step=0.01, key=f"pending_price_{signal['id']}")
    with control_cols[1]:
        quantity = st.number_input("成交数量", min_value=0, value=100, step=100, key=f"pending_quantity_{signal['id']}")
    with control_cols[2]:
        note = st.text_input("执行备注", value="", placeholder="如：已在券商端下单", key=f"pending_note_{signal['id']}")

    action_cols = st.columns(4)
    if str(signal.get("action")).upper() == "BUY":
        with action_cols[0]:
            if render_colored_action_button("买入", key=f"confirm_buy_{signal['id']}", tone="buy"):
                handle_confirm_buy(
                    portfolio_service,
                    signal_id=signal["id"],
                    price=price,
                    quantity=int(quantity),
                    note=note or "已手工买入",
                )
                st.rerun()
    else:
        with action_cols[0]:
            if render_colored_action_button("卖出", key=f"confirm_sell_{signal['id']}", tone="sell"):
                handle_confirm_sell(
                    portfolio_service,
                    signal_id=signal["id"],
                    price=price,
                    quantity=int(quantity),
                    note=note or "已手工卖出",
                )
                st.rerun()

    with action_cols[1]:
        if st.button("延后", key=f"delay_signal_{signal['id']}"):
            portfolio_service.delay_signal(signal["id"], note=note or "延后处理")
            queue_quant_sim_flash("info", "已延后，信号会继续保留在待执行列表。")
            st.rerun()
    with action_cols[2]:
        if st.button("忽略", key=f"ignore_signal_{signal['id']}"):
            portfolio_service.ignore_signal(signal["id"], note=note or "人工忽略")
            queue_quant_sim_flash("warning", "已忽略该信号。")
            st.rerun()


def filter_quant_candidates(candidates: list[dict], *, search_term: str, selected_sources: list[str]) -> list[dict]:
    normalized_search = search_term.strip().lower()
    filtered: list[dict] = []
    for candidate in candidates:
        sources = candidate.get("sources") or [candidate.get("source", "manual")]
        source_labels = [_format_source(source) for source in sources]
        stock_code = str(candidate.get("stock_code") or "")
        stock_name = str(candidate.get("stock_name") or "")
        if normalized_search and normalized_search not in stock_code.lower() and normalized_search not in stock_name.lower():
            continue
        if selected_sources and not set(source_labels).intersection(selected_sources):
            continue
        filtered.append(candidate)
    return filtered


def build_quant_signal_table_rows(signals: list[dict], *, include_status: bool = True) -> list[dict]:
    rows: list[dict] = []
    for signal in signals:
        row = {
            "动作": format_action_label(str(signal.get("action") or "HOLD")),
            "股票代码": signal.get("stock_code"),
            "股票名称": signal.get("stock_name") or "未命名",
            "置信度": f"{signal.get('confidence', 0)}%",
            "时间框架": _format_analysis_timeframe(str((signal.get("strategy_profile") or {}).get("timeframe") or "30m")),
            "策略模式": _format_strategy_mode(str(((signal.get("strategy_profile") or {}).get("strategy_mode") or {}).get("mode") or "auto")),
            "建议仓位": f"{signal.get('position_size_pct', 0)}%",
            "创建时间": signal.get("created_at") or "刚刚",
        }
        if include_status:
            row["状态"] = signal.get("status") or "observed"
        rows.append(row)
    return rows

def display_quant_replay() -> None:
    """Render the dedicated historical replay workspace."""

    candidate_service = CandidatePoolService()
    replay_service = QuantSimReplayService()
    scheduler_status = get_quant_sim_scheduler().get_status()

    render_workspace_section_header(
        "🕰️ 历史回放",
        "直接配置历史区间回放，查看回放进度、完整策略信号执行记录、持仓结果和收益分析。",
    )
    render_flash_messages(QUANT_SIM_FLASH_NAMESPACE)
    render_quant_sim_layout_styles()

    replay_left_col, replay_right_col = st.columns([1.0, 2.25], gap="large")
    with replay_left_col:
        render_replay_configuration(
            replay_service=replay_service,
            default_market=str(scheduler_status["market"]),
        )
        render_replay_candidate_pool_summary(candidate_service)
        render_workspace_section_header(
            "运行概况",
            "左侧集中配置回放、查看运行情况和任务列表；右侧选择一个历史任务并查看完整结果与明细。",
        )
        render_replay_status_panel(candidate_service.db.db_file)
        render_replay_run_overview_list(candidate_service.db.db_file)
    with replay_right_col:
        selected_run_id = get_selected_replay_run_id(candidate_service.db.db_file)
        render_replay_run_detail_panel(candidate_service.db.db_file, selected_run_id=selected_run_id)


def render_replay_configuration(*, replay_service, default_market: str) -> None:
    st.markdown("### ⚙️ 回放配置")

    replay_mode = st.selectbox(
        "回放模式",
        options=["historical_range", "continuous_to_live"],
        format_func=lambda value: "历史区间回放" if value == "historical_range" else "从过去接续到实时自动模拟",
        key="quant_sim_replay_mode",
    )
    replay_until_now = st.checkbox(
        "结束时间留空则回放到当前时刻",
        value=False,
        key="quant_sim_replay_until_now",
    )

    replay_date_col1, replay_date_col2 = st.columns(2)
    with replay_date_col1:
        replay_start_date = st.date_input(
            "开始日期",
            value=(datetime.now() - timedelta(days=30)).date(),
            key="quant_sim_replay_start_date",
        )
    with replay_date_col2:
        if replay_until_now:
            replay_end_date = None
            st.caption("当前模式下结束日期自动取当前日期时间。")
        else:
            replay_end_date = st.date_input(
                "结束日期",
                value=datetime.now().date(),
                key="quant_sim_replay_end_date",
            )

    replay_time_col1, replay_time_col2, replay_time_col3 = st.columns(3)
    with replay_time_col1:
        replay_start_time = st.time_input(
            "开始时间",
            value=time(9, 30),
            step=timedelta(minutes=30),
            key="quant_sim_replay_start_time",
        )
    with replay_time_col2:
        if replay_until_now:
            replay_end_time = None
            st.caption("结束时间将自动取当前时刻。")
        else:
            replay_end_time = st.time_input(
                "结束时间",
                value=time(15, 0),
                step=timedelta(minutes=30),
                key="quant_sim_replay_end_time",
            )
    with replay_time_col3:
        replay_timeframe = st.selectbox(
            "回放粒度",
            options=["30m", "1d", "1d+30m"],
            index=0,
            format_func=_format_analysis_timeframe,
            key="quant_sim_replay_timeframe",
        )

    market_col1, market_col2 = st.columns(2)
    with market_col1:
        replay_market = st.selectbox(
            "市场",
            options=["CN", "HK", "US"],
            index=["CN", "HK", "US"].index(default_market if default_market in {"CN", "HK", "US"} else "CN"),
            key="quant_sim_replay_market",
        )
    overwrite_live = False
    auto_start_scheduler = True
    with market_col2:
        replay_strategy_mode = st.selectbox(
            "策略模式",
            options=STRATEGY_MODE_OPTIONS,
            index=0,
            format_func=_format_strategy_mode,
            key="quant_sim_replay_strategy_mode",
        )
    mode_help_col1, mode_help_col2 = st.columns(2)
    with mode_help_col1:
        if replay_mode == "continuous_to_live":
            st.caption("从过去接续到实时自动模拟：先完成历史回放，再把最终模拟账户状态接入当前实时量化模拟。")
        else:
            st.caption("历史区间回放：独立回放指定区间，不会改写当前实时量化模拟账户。")
    with mode_help_col2:
        st.caption("策略模式支持自动、激进、中性、稳健。自动模式会根据市场状态和标的基本面动态推导。")

    if replay_mode == "continuous_to_live":
        replay_flag_col1, replay_flag_col2 = st.columns(2)
        with replay_flag_col1:
            overwrite_live = st.checkbox(
                "覆盖当前实时模拟账户",
                value=False,
                key="quant_sim_replay_overwrite_live",
            )
        with replay_flag_col2:
            auto_start_scheduler = st.checkbox(
                "回放完成后自动启动定时分析",
                value=True,
                key="quant_sim_replay_auto_start_scheduler",
            )

    replay_button_label = "回放" if replay_mode == "historical_range" else "接续"
    if st.button(replay_button_label, type="primary", use_container_width=True, key="quant_sim_run_replay"):
        start_datetime = build_replay_datetime(replay_start_date, replay_start_time)
        end_datetime = None
        if not replay_until_now and replay_end_date is not None and replay_end_time is not None:
            end_datetime = build_replay_datetime(replay_end_date, replay_end_time)
        if replay_mode == "historical_range":
            queue_historical_replay(
                replay_service,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                timeframe=replay_timeframe,
                market=replay_market,
                strategy_mode=replay_strategy_mode,
            )
        else:
            queue_continuous_replay(
                replay_service,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                timeframe=replay_timeframe,
                market=replay_market,
                strategy_mode=replay_strategy_mode,
                overwrite_live=overwrite_live,
                auto_start_scheduler=auto_start_scheduler,
            )


def render_replay_candidate_pool_summary(candidate_service: CandidatePoolService) -> None:
    st.markdown("### 量化候选池")
    st.caption("先在工作台的“我的关注”里挑选股票，再推进到共享量化候选池。历史回放会基于这份候选池运行。")
    candidates = candidate_service.list_candidates(status="active")
    if not candidates:
        st.info("当前量化候选池为空。")
        return

    summary_rows = [
        {
            "股票代码": candidate.get("stock_code"),
            "股票名称": candidate.get("stock_name") or "未命名",
            "最新价格": f'{(candidate.get("latest_price") or 0):.2f}',
        }
        for candidate in candidates
    ]
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)


def render_replay_results(db_file: str, *, selected_run_id: int | None = None) -> None:
    st.markdown("### 📊 回放结果")
    reconcile_active_replay_run(db_file=db_file)
    db = QuantSimDB(db_file)
    replay_runs = db.get_sim_runs(limit=20)
    if not replay_runs:
        st.info("还没有历史区间模拟结果。先在上方运行一次历史区间回放。")
        return

    run_lookup = {int(run["id"]): run for run in replay_runs}
    if selected_run_id is None or int(selected_run_id) not in run_lookup:
        selected_run_id = int(replay_runs[0]["id"])
    latest_run = run_lookup[int(selected_run_id)]
    replay_snapshots = db.get_sim_run_snapshots(int(latest_run["id"]))
    replay_trades = db.get_sim_run_trades(int(latest_run["id"]))
    replay_positions = db.get_sim_run_positions(int(latest_run["id"]))
    replay_signals = db.get_sim_run_signals(int(latest_run["id"]))
    replay_events = db.get_sim_run_events(int(latest_run["id"]), limit=20)
    replay_report = build_replay_report_payload(
        run=latest_run,
        snapshots=replay_snapshots,
        trades=replay_trades,
        positions=replay_positions,
        signals=replay_signals,
        events=[],
    )

    st.markdown("#### 回放总览")
    replay_metric1, replay_metric2, replay_metric3, replay_metric4 = st.columns(4)
    replay_metric1.metric("初始资金", f"{float(replay_report['initial_cash']):.2f}")
    replay_metric2.metric("最终可用现金", f"{float(replay_report['final_available_cash']):.2f}")
    replay_metric3.metric("最终持仓市值", f"{float(replay_report['final_market_value']):.2f}")
    replay_metric4.metric("最终总权益", f"{float(replay_report['final_total_equity']):.2f}")

    replay_metric5, replay_metric6, replay_metric7, replay_metric8 = st.columns(4)
    replay_metric5.metric("总收益率", f"{float(replay_report['total_return_pct']):.2f}%")
    replay_metric6.metric("最大回撤", f"{float(replay_report['max_drawdown_pct']):.2f}%")
    replay_metric7.metric("胜率", f"{float(replay_report['win_rate']):.2f}%")
    replay_metric8.metric("交易笔数", str(int(replay_report["trade_count"])))

    overview_col1, overview_col2, overview_col3, overview_col4, overview_col5 = st.columns(5)
    overview_col1.caption(f"模式：{replay_report['mode_label']}")
    overview_col2.caption(f"市场：{replay_report['market']}")
    overview_col3.caption(f"粒度：{_format_analysis_timeframe(str(replay_report['timeframe']))}")
    overview_col4.caption(f"区间：{replay_report['start_datetime']} -> {replay_report['end_datetime']}")
    overview_col5.caption(f"策略模式：{_format_strategy_mode(str(replay_report['selected_strategy_mode']))}")

    st.markdown("#### 交易分析")
    render_replay_trade_analysis_cards(replay_report["trade_analysis"])

    if replay_snapshots:
        st.markdown("#### 资金曲线")
        replay_snapshot_df = pd.DataFrame(replay_snapshots)
        replay_snapshot_df["created_at"] = pd.to_datetime(replay_snapshot_df["created_at"])
        replay_chart_df = replay_snapshot_df.set_index("created_at")[["total_equity", "available_cash", "market_value"]]
        st.line_chart(replay_chart_df, use_container_width=True)
        st.dataframe(replay_snapshot_df, use_container_width=True, hide_index=True)

    st.markdown("#### 每股持仓结果（结束持仓）")
    if replay_positions:
        st.dataframe(replay_positions, use_container_width=True, hide_index=True)
    else:
        st.info("本次回放结束时没有持仓。")

    st.markdown("#### 成交明细")
    if replay_trades:
        replay_trade_df = pd.DataFrame(replay_trades).rename(
            columns={
                "id": "成交ID",
                "signal_id": "信号ID",
                "stock_code": "股票代码",
                "stock_name": "股票名称",
                "action": "动作",
                "price": "成交价格",
                "quantity": "成交数量",
                "amount": "成交金额",
                "realized_pnl": "已实现盈亏",
                "note": "备注",
                "executed_at": "成交时间",
                "created_at": "创建时间",
            }
        )
        if "动作" in replay_trade_df.columns:
            replay_trade_df["动作"] = replay_trade_df["动作"].map(format_action_label)
        st.dataframe(replay_trade_df, use_container_width=True, hide_index=True)
    else:
        st.info("本次回放没有成交记录。")

    st.markdown("#### 信号执行记录")
    if replay_signals:
        replay_signal_df = pd.DataFrame(replay_report["strategy_signal_rows"])
        st.caption("表格仅展示摘要；点击表格中的任意一行查看详情。")
        replay_signal_state = st.dataframe(
            replay_signal_df,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=f"quant_sim_replay_signal_table_{latest_run['id']}",
        )
        selected_rows = _extract_dataframe_selected_rows(replay_signal_state)
        if selected_rows:
            selected_signal = replay_report["strategy_signals"][int(selected_rows[0])]
            st.markdown("#### 当前交易策略")
            strategy_summary = render_strategy_profile_summary(selected_signal.get("strategy_profile"))
            if strategy_summary:
                st.markdown(strategy_summary)
            explainability_summary = render_strategy_explainability_summary(
                selected_signal.get("strategy_profile"),
                signal=selected_signal,
            )
            if explainability_summary:
                st.markdown(explainability_summary)
            st.info(_build_replay_signal_detail_summary(selected_signal))
        else:
            st.info("点击上方信号执行记录中的任意一行，即可查看完整策略解释、阈值与推理说明。")
    else:
        st.info("本次回放未产出可展示的策略信号。")


def get_selected_replay_run_id(db_file: str) -> int | None:
    db = QuantSimDB(db_file)
    replay_runs = db.get_sim_runs(limit=20)
    if not replay_runs:
        return None
    run_lookup = {int(run["id"]): run for run in replay_runs}
    raw_selected = st.session_state.get("quant_sim_replay_run_selector")
    if raw_selected is None:
        selected_run_id = int(replay_runs[0]["id"])
        st.session_state["quant_sim_replay_run_selector"] = selected_run_id
        return selected_run_id
    try:
        selected_run_id = int(raw_selected)
    except (TypeError, ValueError):
        selected_run_id = int(replay_runs[0]["id"])
    if selected_run_id not in run_lookup:
        selected_run_id = int(replay_runs[0]["id"])
        st.session_state["quant_sim_replay_run_selector"] = selected_run_id
    return selected_run_id


def render_replay_run_overview_list(db_file: str) -> None:
    db = QuantSimDB(db_file)
    replay_runs = db.get_sim_runs(limit=50)
    if not replay_runs:
        st.info("还没有回放任务，先在上方配置一个区间并启动回放。")
        return

    active_runs = [
        run for run in replay_runs if str(run.get("status") or "").lower() in {"queued", "running", "cancelling"}
    ]

    st.markdown("#### 当前回放任务")
    if active_runs:
        for run in active_runs[:3]:
            progress_current = int(run.get("progress_current") or 0)
            progress_total = int(run.get("progress_total") or 0)
            progress_ratio = (progress_current / progress_total) if progress_total else 0.0
            st.markdown(
                f"**#{int(run.get('id') or 0)} · {_format_replay_status(run)}**  "
                f"{_format_analysis_timeframe(str(run.get('timeframe') or '30m'))}"
            )
            st.caption(
                f"{run.get('start_datetime') or '未知开始'} -> {run.get('end_datetime') or '当前时刻'}"
            )
            st.progress(min(max(progress_ratio, 0.0), 1.0))
            if run.get("latest_checkpoint_at"):
                st.caption(f"最近检查点：{run.get('latest_checkpoint_at')}")
    else:
        st.caption("当前没有运行中的回放任务。")

    st.markdown("#### 所有回放任务")
    replay_run_rows: list[dict] = []
    for run in replay_runs:
        replay_run_rows.append(
            {
                "任务": f"#{int(run.get('id') or 0)}",
                "状态": _format_replay_status(run),
                "模式": "历史区间" if str(run.get("mode") or "") == "historical_range" else "接续到实时",
                "粒度": _format_analysis_timeframe(str(run.get("timeframe") or "30m")),
                "区间": f"{run.get('start_datetime') or '未知开始'} -> {run.get('end_datetime') or '当前时刻'}",
                "进度": f"{int(run.get('progress_current') or 0)}/{int(run.get('progress_total') or 0)}",
            }
        )
    st.dataframe(pd.DataFrame(replay_run_rows), use_container_width=True, hide_index=True)


def render_replay_run_detail_panel(db_file: str, *, selected_run_id: int | None = None) -> None:
    st.markdown("### 回放任务")
    db = QuantSimDB(db_file)
    replay_runs = db.get_sim_runs(limit=50)
    if not replay_runs:
        st.info("还没有可查看的回放任务。")
        return

    run_lookup = {int(run["id"]): run for run in replay_runs}
    if selected_run_id is None or int(selected_run_id) not in run_lookup:
        selected_run_id = int(replay_runs[0]["id"])

    selected_run_id = st.selectbox(
        "选择回放任务",
        options=list(run_lookup.keys()),
        index=list(run_lookup.keys()).index(int(selected_run_id)),
        format_func=lambda run_id: format_replay_run_option(run_lookup[int(run_id)]),
        key="quant_sim_replay_run_selector",
    )
    selected_run = run_lookup[int(selected_run_id)]

    st.markdown("#### 任务信息")
    info_cols = st.columns(4)
    info_cols[0].metric("状态", _format_replay_status(selected_run))
    info_cols[1].metric(
        "检查点",
        f"{int(selected_run.get('progress_current') or 0)}/{int(selected_run.get('progress_total') or 0)}",
    )
    info_cols[2].metric("粒度", _format_analysis_timeframe(str(selected_run.get("timeframe") or "30m")))
    info_cols[3].metric(
        "策略模式",
        _format_strategy_mode(str(((selected_run.get("metadata") or {}).get("strategy_mode")) or "auto")),
    )
    st.caption(f"模式：{'历史区间回放' if str(selected_run.get('mode') or '') == 'historical_range' else '从过去接续到实时'}")
    st.caption(
        f"区间：{selected_run.get('start_datetime') or '未知开始'} -> {selected_run.get('end_datetime') or '当前时刻'}"
    )
    if selected_run.get("latest_checkpoint_at"):
        st.caption(f"最近检查点：{selected_run.get('latest_checkpoint_at')}")
    if selected_run.get("status_message"):
        st.info(str(selected_run.get("status_message")))
    if str(selected_run.get("status") or "").lower() in {"completed", "failed", "cancelled"}:
        if st.button("删除", use_container_width=True, key=f"delete_replay_run_{selected_run['id']}"):
            try:
                db.delete_sim_run(int(selected_run["id"]))
            except ValueError as exc:
                queue_quant_sim_flash("warning", str(exc))
            else:
                queue_quant_sim_flash("success", f"✅ 已删除回放任务 #{int(selected_run['id'])}")
                st.session_state.pop("quant_sim_replay_run_selector", None)
            st.rerun()

    render_replay_results(db_file, selected_run_id=int(selected_run_id))


def render_replay_run_sidebar(db_file: str) -> None:
    st.markdown("### 回放任务")
    db = QuantSimDB(db_file)
    replay_runs = db.get_sim_runs(limit=20)
    if not replay_runs:
        st.info("还没有可查看的回放任务。")
        return

    run_lookup = {int(run["id"]): run for run in replay_runs}
    default_run_id = get_selected_replay_run_id(db_file)
    selected_run_id = st.selectbox(
        "选择回放任务",
        options=list(run_lookup.keys()),
        index=list(run_lookup.keys()).index(int(default_run_id)) if default_run_id in run_lookup else 0,
        format_func=lambda run_id: format_replay_run_option(run_lookup[int(run_id)]),
        key="quant_sim_replay_run_selector",
    )
    selected_run = run_lookup[int(selected_run_id)]
    st.markdown("#### 任务信息")
    info_cols = st.columns(2)
    info_cols[0].metric("状态", _format_replay_status(selected_run))
    info_cols[1].metric(
        "检查点",
        f"{int(selected_run.get('progress_current') or 0)}/{int(selected_run.get('progress_total') or 0)}",
    )
    st.caption(f"最近检查点：{selected_run.get('latest_checkpoint_at') or '暂无'}")
    st.caption(f"模式：{selected_run.get('mode') or 'historical_range'}")
    st.caption(f"粒度：{_format_analysis_timeframe(str(selected_run.get('timeframe') or '30m'))}")
    st.caption(
        f"区间：{selected_run.get('start_datetime') or '未知开始'} -> {selected_run.get('end_datetime') or '当前时刻'}"
    )
    if selected_run.get("status_message"):
        st.info(str(selected_run.get("status_message")))
    if str(selected_run.get("status") or "").lower() in {"completed", "failed", "cancelled"}:
        if st.button("删除", use_container_width=True, key=f"delete_replay_run_{selected_run['id']}"):
            try:
                db.delete_sim_run(int(selected_run["id"]))
            except ValueError as exc:
                queue_quant_sim_flash("warning", str(exc))
            else:
                queue_quant_sim_flash("success", f"✅ 已删除回放任务 #{int(selected_run['id'])}")
                st.session_state.pop("quant_sim_replay_run_selector", None)
            st.rerun()

def _format_source(source: str) -> str:
    return {
        "manual": "手工加入",
        "main_force": "主力选股",
        "low_price_bull": "低价擒牛",
        "profit_growth": "净利增长",
        "value_stock": "低估值策略",
        "small_cap": "小市值策略",
    }.get(source, source)


def _extract_dataframe_selected_rows(dataframe_state: object) -> list[int]:
    if not dataframe_state:
        return []
    selection: object
    if hasattr(dataframe_state, "get"):
        selection = dataframe_state.get("selection", {})
    else:
        selection = getattr(dataframe_state, "selection", {}) or {}
    if hasattr(selection, "get"):
        rows = selection.get("rows", [])
    else:
        rows = getattr(selection, "rows", [])
    if not rows:
        return []
    return [int(index) for index in rows]


def render_action_badge_html(action: str) -> str:
    normalized = str(action or "HOLD").upper()
    palette = {
        "BUY": {"bg": "#fde8e8", "fg": "#d94b4b", "border": "#f3b3b3"},
        "SELL": {"bg": "#e8f7ee", "fg": "#1a9b5b", "border": "#9fd7b5"},
        "HOLD": {"bg": "#f3f4f6", "fg": "#6b7280", "border": "#d1d5db"},
    }.get(normalized, {"bg": "#f3f4f6", "fg": "#6b7280", "border": "#d1d5db"})
    return (
        "<div style='margin:0 0 0.5rem 0;'>"
        f"<span style='display:inline-block;padding:0.25rem 0.65rem;border-radius:999px;"
        f"font-weight:700;font-size:0.92rem;background:{palette['bg']};color:{palette['fg']};"
        f"border:1px solid {palette['border']};'>{normalized}</span>"
        "</div>"
    )


def format_signal_expander_label(signal: dict) -> str:
    action = str(signal.get("action") or "HOLD").upper()
    marker = {"BUY": "🔴", "SELL": "🟢", "HOLD": "⚪"}.get(action, "⚪")
    stock_code = str(signal.get("stock_code") or "").strip()
    stock_name = str(signal.get("stock_name") or "").strip()
    if stock_name:
        return f"{marker} {action} | {stock_code} - {stock_name}"
    return f"{marker} {action} | {stock_code}"


def format_action_label(action: str) -> str:
    normalized = str(action or "HOLD").upper()
    marker = {"BUY": "🔴", "SELL": "🟢", "HOLD": "⚪"}.get(normalized, "⚪")
    return f"{marker} {normalized}"


def format_replay_run_option(run: dict) -> str:
    run_id = int(run.get("id") or 0)
    status = _format_replay_status(run)
    timeframe = _format_analysis_timeframe(str(run.get("timeframe") or "30m"))
    start_datetime = str(run.get("start_datetime") or "未知开始")
    end_datetime = str(run.get("end_datetime") or "当前时刻")
    return f"#{run_id} | {status} | {timeframe} | {start_datetime} -> {end_datetime}"


def build_replay_report_payload(
    *,
    run: dict,
    snapshots: list[dict],
    trades: list[dict],
    positions: list[dict],
    signals: list[dict],
    events: list[dict],
) -> dict:
    initial_cash = float(
        (snapshots[0].get("initial_cash") if snapshots else None)
        or run.get("initial_cash")
        or 0
    )
    final_snapshot = snapshots[-1] if snapshots else {}
    final_available_cash = float(final_snapshot.get("available_cash") or initial_cash)
    final_market_value = float(final_snapshot.get("market_value") or 0)
    final_total_equity = float(final_snapshot.get("total_equity") or run.get("final_equity") or initial_cash)
    trade_analysis = _build_replay_trade_analysis(trades)
    trade_lookup_by_signal_id = _build_replay_trade_lookup_by_signal_id(trades)
    strategy_signal_rows = [_build_replay_signal_row(signal, linked_trade=trade_lookup_by_signal_id.get(int(signal.get("id") or 0))) for signal in signals]
    selected_strategy_mode = str(((run.get("metadata") or {}).get("strategy_mode")) or "auto")
    return {
        "run_id": int(run.get("id") or 0),
        "mode": str(run.get("mode") or "historical_range"),
        "mode_label": "历史区间回放" if str(run.get("mode") or "") == "historical_range" else "从过去接续到实时",
        "status": str(run.get("status") or "unknown"),
        "market": str(run.get("market") or "CN"),
        "timeframe": str(run.get("timeframe") or "30m"),
        "start_datetime": str(run.get("start_datetime") or "未知"),
        "end_datetime": str(run.get("end_datetime") or "当前时刻"),
        "initial_cash": initial_cash,
        "final_available_cash": final_available_cash,
        "final_market_value": final_market_value,
        "final_total_equity": final_total_equity,
        "total_return_pct": float(run.get("total_return_pct") or 0),
        "max_drawdown_pct": float(run.get("max_drawdown_pct") or 0),
        "win_rate": float(run.get("win_rate") or 0),
        "trade_count": int(run.get("trade_count") or len(trades)),
        "selected_strategy_mode": selected_strategy_mode,
        "ending_position_count": len(positions),
        "trade_analysis": trade_analysis,
        "positions": positions,
        "trades": trades,
        "snapshots": snapshots,
        "strategy_signals": signals,
        "strategy_signal_rows": strategy_signal_rows,
        "events": events,
    }


def _build_replay_trade_analysis(trades: list[dict]) -> dict:
    total_buy_amount = sum(float(trade.get("amount") or 0) for trade in trades if str(trade.get("action") or "").upper() == "BUY")
    sell_trades = [trade for trade in trades if str(trade.get("action") or "").upper() == "SELL"]
    total_sell_amount = sum(float(trade.get("amount") or 0) for trade in sell_trades)
    realized_values = [float(trade.get("realized_pnl") or 0) for trade in sell_trades]
    winning_trade_count = sum(1 for value in realized_values if value > 0)
    losing_trade_count = sum(1 for value in realized_values if value < 0)
    total_realized_pnl = sum(realized_values)
    avg_realized_pnl = total_realized_pnl / len(sell_trades) if sell_trades else 0.0
    return {
        "total_buy_amount": round(total_buy_amount, 4),
        "total_sell_amount": round(total_sell_amount, 4),
        "total_realized_pnl": round(total_realized_pnl, 4),
        "winning_trade_count": winning_trade_count,
        "losing_trade_count": losing_trade_count,
        "avg_realized_pnl": round(avg_realized_pnl, 4),
    }


def _build_replay_trade_lookup_by_signal_id(trades: list[dict]) -> dict[int, dict]:
    lookup: dict[int, dict] = {}
    for trade in trades:
        signal_id = trade.get("signal_id")
        if signal_id in (None, ""):
            continue
        normalized_signal_id = int(signal_id)
        existing = lookup.get(normalized_signal_id)
        if existing is None:
            lookup[normalized_signal_id] = trade
            continue
        existing_time = str(existing.get("executed_at") or existing.get("created_at") or "")
        current_time = str(trade.get("executed_at") or trade.get("created_at") or "")
        if current_time >= existing_time:
            lookup[normalized_signal_id] = trade
    return lookup


def _build_replay_signal_row(signal: dict, *, linked_trade: dict | None = None) -> dict:
    strategy_profile = signal.get("strategy_profile") or {}
    market_regime = strategy_profile.get("market_regime") or {}
    fundamental_quality = strategy_profile.get("fundamental_quality") or {}
    risk_style = strategy_profile.get("risk_style") or {}
    analysis_timeframe = strategy_profile.get("analysis_timeframe") or {}
    return {
        "信号ID": int(signal.get("id") or 0),
        "成交ID": int(linked_trade.get("id") or 0) if linked_trade else "",
        "时间": signal.get("checkpoint_at") or signal.get("created_at"),
        "股票代码": signal.get("stock_code"),
        "股票名称": signal.get("stock_name"),
        "动作": format_action_label(signal.get("action")),
        "置信度": signal.get("confidence"),
        "是否执行": "是" if linked_trade else "否",
        "市场状态": market_regime.get("label", "未知"),
        "基本面质量": fundamental_quality.get("label", "未知"),
        "当前风格": risk_style.get("label", "未知"),
        "时间框架": analysis_timeframe.get("key", "未知"),
        "决策类型": signal.get("decision_type") or "",
    }


def _build_replay_signal_detail_summary(signal: dict) -> str:
    strategy_profile = signal.get("strategy_profile") or {}
    market_regime = strategy_profile.get("market_regime") or {}
    fundamental_quality = strategy_profile.get("fundamental_quality") or {}
    risk_style = strategy_profile.get("risk_style") or {}
    auto_inferred_risk_style = strategy_profile.get("auto_inferred_risk_style") or {}
    analysis_timeframe = strategy_profile.get("analysis_timeframe") or {}
    effective_thresholds = strategy_profile.get("effective_thresholds") or {}
    strategy_mode = strategy_profile.get("strategy_mode") or {}

    details: list[str] = [
        f"策略模式：{strategy_mode.get('label', '自动')}",
        f"市场状态：{market_regime.get('label', '未知')}",
        f"基本面质量：{fundamental_quality.get('label', '未知')}",
        f"自动推导风格：{auto_inferred_risk_style.get('label', risk_style.get('label', '未知'))}",
        f"实际执行风格：{risk_style.get('label', '未知')}",
        f"时间框架：{analysis_timeframe.get('key', '未知')}",
    ]

    max_position_ratio = effective_thresholds.get("max_position_ratio")
    if max_position_ratio is not None:
        details.append(f"建议仓位：{float(max_position_ratio) * 100:.1f}%")

    buy_threshold = effective_thresholds.get("buy_threshold")
    sell_threshold = effective_thresholds.get("sell_threshold")
    if buy_threshold is not None and sell_threshold is not None:
        details.append(f"阈值：买入 {float(buy_threshold):.2f} / 卖出 {float(sell_threshold):.2f}")

    confirmation = effective_thresholds.get("confirmation")
    if confirmation:
        details.append(f"确认机制：{confirmation}")

    explainability_summary = _format_explainability_inline_summary(
        _resolve_signal_explainability(signal, strategy_profile)
    )
    if explainability_summary:
        details.extend(explainability_summary)

    reasoning = str(signal.get("reasoning") or "").strip()
    if reasoning:
        details.append(f"推理：{reasoning}")

    return " | ".join(details)


def render_strategy_profile_summary(strategy_profile: dict | None) -> str:
    if not strategy_profile:
        return ""

    market_regime = strategy_profile.get("market_regime") or {}
    fundamental_quality = strategy_profile.get("fundamental_quality") or {}
    risk_style = strategy_profile.get("risk_style") or {}
    auto_inferred_risk_style = strategy_profile.get("auto_inferred_risk_style") or {}
    strategy_mode = strategy_profile.get("strategy_mode") or {}
    analysis_timeframe = strategy_profile.get("analysis_timeframe") or {}
    effective_thresholds = strategy_profile.get("effective_thresholds") or {}

    lines = [
        "**策略概览**",
        f"- 策略模式：{strategy_mode.get('label', '自动')}",
        f"- 市场状态：{market_regime.get('label', '未知')}",
        f"- 基本面质量：{fundamental_quality.get('label', '未知')}",
        f"- 自动推导风格：{auto_inferred_risk_style.get('label', risk_style.get('label', '未知'))}",
        f"- 当前风格：{risk_style.get('label', '未知')}",
        f"- 时间框架：{analysis_timeframe.get('key', '未知')}",
    ]

    max_position_ratio = effective_thresholds.get("max_position_ratio")
    if max_position_ratio is not None:
        lines.append(f"- 建议仓位：{float(max_position_ratio) * 100:.1f}%")

    buy_threshold = effective_thresholds.get("buy_threshold")
    sell_threshold = effective_thresholds.get("sell_threshold")
    if buy_threshold is not None and sell_threshold is not None:
        lines.append(
            f"- 阈值：买入 {float(buy_threshold):.2f} / 卖出 {float(sell_threshold):.2f}"
        )

    confirmation = effective_thresholds.get("confirmation")
    if confirmation:
        lines.append(f"- 确认机制：{confirmation}")

    return "\n".join(lines)


def render_strategy_explainability_summary(
    strategy_profile: dict | None,
    *,
    signal: dict | None = None,
) -> str:
    if not strategy_profile:
        return ""
    explainability = _resolve_signal_explainability(signal or {}, strategy_profile)
    lines: list[str] = []

    if explainability.get("_fallback_source") == "legacy_reconstructed":
        lines.append(
            "> 历史旧记录兼容重建：原始逐因子投票未落库，以下内容基于当时保留的策略概览、推理摘要与检查点信息重建。"
        )

    tech_votes = explainability.get("tech_votes") or []
    if tech_votes:
        lines.append("**技术投票**")
        for vote in tech_votes:
            lines.append(
                f"- {vote.get('factor', '未知')} -> {vote.get('signal', 'HOLD')} "
                f"({float(vote.get('score') or 0):+.2f})：{vote.get('reason', '')}"
            )

    context_votes = explainability.get("context_votes") or []
    if context_votes:
        lines.append("**环境投票**")
        for vote in context_votes:
            lines.append(
                f"- {vote.get('component', '未知')} ({float(vote.get('score') or 0):+.2f})：{vote.get('reason', '')}"
            )

    dual_track = explainability.get("dual_track") or {}
    if dual_track:
        lines.append("**双轨裁决**")
        lines.append(
            "- 技术信号：{tech}；环境信号：{ctx}；规则：{rule}；共振类型：{res}; 仓位比例：{ratio:.0%}".format(
                tech=dual_track.get("tech_signal", "未知"),
                ctx=dual_track.get("context_signal", "未知"),
                rule=dual_track.get("rule_hit", "未知"),
                res=dual_track.get("resonance_type", "未知"),
                ratio=float(dual_track.get("position_ratio") or 0),
            )
        )

    return "\n".join(lines)


def _format_explainability_inline_summary(explainability: dict | None) -> list[str]:
    if not explainability:
        return []

    details: list[str] = []
    tech_votes = explainability.get("tech_votes") or []
    if tech_votes:
        tech_parts = [
            f"{vote.get('factor', '未知')} -> {vote.get('signal', 'HOLD')} ({float(vote.get('score') or 0):+.2f})"
            for vote in tech_votes
        ]
        details.append(f"技术投票：{'; '.join(tech_parts)}")

    context_votes = explainability.get("context_votes") or []
    if context_votes:
        context_parts = [
            f"{vote.get('component', '未知')} ({float(vote.get('score') or 0):+.2f})"
            for vote in context_votes
        ]
        details.append(f"环境投票：{'; '.join(context_parts)}")

    dual_track = explainability.get("dual_track") or {}
    if dual_track:
        details.append(
            "双轨裁决：{tech} / {ctx} / {rule} / {res} / 仓位 {ratio:.0%}".format(
                tech=dual_track.get("tech_signal", "未知"),
                ctx=dual_track.get("context_signal", "未知"),
                rule=dual_track.get("rule_hit", "未知"),
                res=dual_track.get("resonance_type", "未知"),
                ratio=float(dual_track.get("position_ratio") or 0),
            )
        )

    return details


def _resolve_signal_explainability(signal: dict | None, strategy_profile: dict | None) -> dict:
    profile = strategy_profile or {}
    explainability = profile.get("explainability") or {}
    if explainability:
        return explainability
    return _build_legacy_signal_explainability(signal or {}, profile)


def _build_legacy_signal_explainability(signal: dict, strategy_profile: dict) -> dict:
    reasoning = str(signal.get("reasoning") or "").strip()
    metrics = _parse_legacy_signal_metrics(reasoning)
    effective_thresholds = strategy_profile.get("effective_thresholds") or {}
    market_regime = strategy_profile.get("market_regime") or {}
    fundamental_quality = strategy_profile.get("fundamental_quality") or {}

    tech_votes: list[dict[str, object]] = []
    price = metrics.get("price")
    ma5 = metrics.get("ma5")
    ma20 = metrics.get("ma20")
    ma60 = metrics.get("ma60")
    if None not in (price, ma5, ma20, ma60):
        if price > ma5 > ma20 > ma60 > 0:
            tech_votes.append(
                {
                    "factor": "均线结构",
                    "signal": "BUY",
                    "score": 0.18,
                    "reason": f"历史记录兼容重建：多头排列 {price:.2f}>{ma5:.2f}>{ma20:.2f}>{ma60:.2f}",
                }
            )
        elif price < ma5 < ma20 < ma60 and ma60 > 0:
            tech_votes.append(
                {
                    "factor": "均线结构",
                    "signal": "SELL",
                    "score": -0.18,
                    "reason": f"历史记录兼容重建：空头排列 {price:.2f}<{ma5:.2f}<{ma20:.2f}<{ma60:.2f}",
                }
            )
        elif price > ma20:
            tech_votes.append(
                {
                    "factor": "均线结构",
                    "signal": "BUY",
                    "score": 0.08,
                    "reason": f"历史记录兼容重建：价格 {price:.2f} 仍位于 MA20 {ma20:.2f} 上方",
                }
            )
        else:
            tech_votes.append(
                {
                    "factor": "均线结构",
                    "signal": "SELL",
                    "score": -0.08,
                    "reason": f"历史记录兼容重建：价格 {price:.2f} 位于 MA20 {ma20:.2f} 下方",
                }
            )

    macd = metrics.get("macd")
    if macd is not None:
        tech_votes.append(
            {
                "factor": "MACD",
                "signal": "BUY" if macd > 0 else ("SELL" if macd < 0 else "HOLD"),
                "score": 0.18 if macd > 0 else (-0.18 if macd < 0 else 0.0),
                "reason": f"历史记录兼容重建：MACD {macd:.3f}{' 为正，动量偏强' if macd > 0 else (' 为负，动量偏弱' if macd < 0 else ' 接近中性')}",
            }
        )

    rsi12 = metrics.get("rsi12")
    if rsi12 is not None:
        if rsi12 >= 78:
            signal_name, score, reason = "SELL", -0.12, f"RSI12 {rsi12:.2f} 偏高，短线过热"
        elif rsi12 <= 28:
            signal_name, score, reason = "BUY", 0.10, f"RSI12 {rsi12:.2f} 偏低，存在修复空间"
        elif 48 <= rsi12 <= 68:
            signal_name, score, reason = "BUY", 0.06, f"RSI12 {rsi12:.2f} 处于健康区间"
        else:
            signal_name, score, reason = "HOLD", 0.0, f"RSI12 {rsi12:.2f} 中性"
        tech_votes.append(
            {
                "factor": "RSI",
                "signal": signal_name,
                "score": score,
                "reason": f"历史记录兼容重建：{reason}",
            }
        )

    volume_ratio = metrics.get("volume_ratio")
    if volume_ratio is not None:
        if volume_ratio >= 1.8:
            signal_name, score, reason = "BUY", 0.08, f"量比 {volume_ratio:.2f} 放大，资金参与度高"
        elif volume_ratio >= 1.2:
            signal_name, score, reason = "BUY", 0.04, f"量比 {volume_ratio:.2f} 偏强，量能配合尚可"
        elif volume_ratio <= 0.7:
            signal_name, score, reason = "SELL", -0.08, f"量比 {volume_ratio:.2f} 偏弱，流动性不足"
        elif volume_ratio <= 0.9:
            signal_name, score, reason = "SELL", -0.04, f"量比 {volume_ratio:.2f} 偏低，资金跟随有限"
        else:
            signal_name, score, reason = "HOLD", 0.0, f"量比 {volume_ratio:.2f} 中性"
        tech_votes.append(
            {
                "factor": "量比",
                "signal": signal_name,
                "score": score,
                "reason": f"历史记录兼容重建：{reason}",
            }
        )

    context_votes: list[dict[str, object]] = []
    source = str(metrics.get("source") or signal.get("source") or "")
    source_score = {
        "main_force": 0.28,
        "low_price_bull": 0.22,
        "profit_growth": 0.20,
        "value_stock": 0.16,
        "small_cap": 0.14,
        "manual": 0.10,
    }.get(source, 0.10)
    context_votes.append(
        {
            "component": "source_prior",
            "score": source_score,
            "reason": (
                f"历史记录兼容重建：来源策略为 {source}"
                if source
                else "历史记录兼容重建：原始记录未保留来源策略，按默认来源先验处理"
            ),
        }
    )

    market_reason = str(market_regime.get("reason") or "")
    trend_value = _extract_text_group(r"趋势=([a-zA-Z_]+)", market_reason)
    if trend_value:
        trend_score = 0.16 if trend_value == "up" else (-0.16 if trend_value == "down" else 0.0)
        context_votes.append(
            {
                "component": "trend_regime",
                "score": trend_score,
                "reason": f"历史记录兼容重建：趋势状态 {trend_value}",
            }
        )

    if None not in (price, ma20, ma60):
        structure_score = 0.14 if price > ma20 > ma60 else (-0.14 if price < ma20 < ma60 else 0.0)
        context_votes.append(
            {
                "component": "price_structure",
                "score": structure_score,
                "reason": f"历史记录兼容重建：价格结构 {price:.2f}/{ma20:.2f}/{ma60:.2f}",
            }
        )
    else:
        structure_reason = _extract_text_group(r"价格结构=([0-9./+-]+)", market_reason)
        if structure_reason:
            context_votes.append(
                {
                    "component": "price_structure",
                    "score": 0.0,
                    "reason": f"历史记录兼容重建：价格结构 {structure_reason}",
                }
            )

    if macd is not None:
        context_votes.append(
            {
                "component": "momentum",
                "score": max(-0.12, min(0.12, macd * 0.18)),
                "reason": f"历史记录兼容重建：MACD {macd:.3f}",
            }
        )

    if volume_ratio is None:
        volume_ratio = _extract_float_group(r"量比=([+-]?\d+(?:\.\d+)?)", market_reason)

    if volume_ratio is not None:
        liquidity_score = 0.09 if volume_ratio >= 1.8 else (0.05 if volume_ratio >= 1.2 else (-0.08 if volume_ratio <= 0.7 else (-0.04 if volume_ratio <= 0.9 else 0.0)))
        context_votes.append(
            {
                "component": "liquidity",
                "score": liquidity_score,
                "reason": f"历史记录兼容重建：量比 {volume_ratio:.2f}",
            }
        )

    signal_time = _extract_signal_datetime(signal)
    if signal_time is not None:
        session_score = 0.03 if signal_time.time() >= time(14, 30) else (0.02 if signal_time.time() <= time(10, 0) else 0.0)
        context_votes.append(
            {
                "component": "session",
                "score": session_score,
                "reason": f"历史记录兼容重建：检查点时间 {signal_time.strftime('%Y-%m-%d %H:%M:%S')}",
            }
        )

    fundamental_reason = str(fundamental_quality.get("reason") or "")
    if fundamental_reason:
        context_votes.append(
            {
                "component": "fundamental_quality",
                "score": float(fundamental_quality.get("score") or 0.0),
                "reason": f"历史记录兼容重建：{fundamental_reason}",
            }
        )

    tech_score = metrics.get("tech_score")
    if tech_score is None and tech_votes:
        tech_score = round(sum(float(v.get("score") or 0.0) for v in tech_votes), 4)
    context_score = metrics.get("context_score")
    if context_score is None and context_votes:
        context_score = round(sum(float(v.get("score") or 0.0) for v in context_votes), 4)

    tech_signal = _infer_legacy_track_signal(float(tech_score or 0.0), effective_thresholds)
    context_signal = _infer_legacy_context_signal(float(context_score or 0.0))
    final_action = str(signal.get("action") or "HOLD").upper()
    if tech_signal == context_signal:
        resonance_type = "legacy_resonance" if tech_signal != "HOLD" else "legacy_observation"
    else:
        resonance_type = "legacy_divergence"

    dual_track = {
        "tech_signal": tech_signal,
        "context_signal": context_signal,
        "resonance_type": resonance_type,
        "rule_hit": f"历史旧记录兼容重建-{final_action.lower()}",
        "position_ratio": float(effective_thresholds.get("max_position_ratio") or 0.0),
        "decision_type": final_action,
        "final_action": final_action,
        "final_reason": "历史旧记录兼容重建：依据保留的摘要字段恢复投票明细。",
    }

    return {
        "_fallback_source": "legacy_reconstructed",
        "tech_votes": tech_votes,
        "context_votes": context_votes,
        "dual_track": dual_track,
    }


def _parse_legacy_signal_metrics(reasoning: str) -> dict[str, float | str]:
    metrics: dict[str, float | str] = {}
    if not reasoning:
        return metrics

    source = _extract_text_group(r"来源策略为\s*([a-zA-Z0-9_]+)", reasoning)
    if source:
        metrics["source"] = source

    for key, pattern in {
        "price": r"(?:价格|现价)\s*([+-]?\d+(?:\.\d+)?)",
        "cost_price": r"成本\s*([+-]?\d+(?:\.\d+)?)",
        "ma20": r"MA20\s*([+-]?\d+(?:\.\d+)?)",
        "macd": r"MACD\s*([+-]?\d+(?:\.\d+)?)",
        "rsi12": r"RSI12\s*([+-]?\d+(?:\.\d+)?)",
        "volume_ratio": r"量比\s*([+-]?\d+(?:\.\d+)?)",
        "tech_score": r"技术评分\s*([+-]?\d+(?:\.\d+)?)",
        "context_score": r"(?:上下文评分|ContextScore=)\s*([+-]?\d+(?:\.\d+)?)",
    }.items():
        value = _extract_float_group(pattern, reasoning)
        if value is not None:
            metrics[key] = value

    ma_match = re.search(
        r"MA5/MA20/MA60\s*为\s*([+-]?\d+(?:\.\d+)?)\/([+-]?\d+(?:\.\d+)?)\/([+-]?\d+(?:\.\d+)?)",
        reasoning,
    )
    if ma_match:
        metrics["ma5"] = float(ma_match.group(1))
        metrics["ma20"] = float(ma_match.group(2))
        metrics["ma60"] = float(ma_match.group(3))

    return metrics


def _extract_float_group(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def _extract_text_group(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    if not match:
        return ""
    return str(match.group(1)).strip()


def _extract_signal_datetime(signal: dict) -> datetime | None:
    for key in ("checkpoint_at", "created_at", "executed_at"):
        value = signal.get(key)
        if not value:
            continue
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            continue
    return None


def _infer_legacy_track_signal(score: float, effective_thresholds: dict) -> str:
    buy_threshold = float(effective_thresholds.get("buy_threshold") or 0.65)
    sell_threshold = float(effective_thresholds.get("sell_threshold") or -0.2)
    if score >= buy_threshold:
        return "BUY"
    if score <= sell_threshold:
        return "SELL"
    return "HOLD"


def _infer_legacy_context_signal(score: float) -> str:
    if score >= 0.25:
        return "BUY"
    if score <= -0.15:
        return "SELL"
    return "HOLD"


def build_action_button_style_css(key: str, tone: str) -> str:
    marker_id = f"{key}_marker"
    palette = {
        "buy": {
            "bg": "#d94b4b",
            "bg_soft": "#fde8e8",
            "hover": "#c53d3d",
            "shadow": "rgba(217, 75, 75, 0.28)",
        },
        "sell": {
            "bg": "#1a9b5b",
            "bg_soft": "#e8f7ee",
            "hover": "#13804a",
            "shadow": "rgba(26, 155, 91, 0.24)",
        },
    }[tone]
    return f"""
<div id="{marker_id}"></div>
<style>
div.element-container:has(#{marker_id}) + div.element-container button {{
    background: linear-gradient(135deg, {palette['bg_soft']} 0%, {palette['bg']} 100%) !important;
    color: #ffffff !important;
    border: 1px solid {palette['bg']} !important;
    box-shadow: 0 4px 15px {palette['shadow']} !important;
}}
div.element-container:has(#{marker_id}) + div.element-container button:hover {{
    background: linear-gradient(135deg, {palette['bg']} 0%, {palette['hover']} 100%) !important;
    color: #ffffff !important;
    box-shadow: 0 6px 20px {palette['shadow']} !important;
}}
</style>
"""


def render_colored_action_button(label: str, *, key: str, tone: str, use_container_width: bool = False) -> bool:
    st.markdown(build_action_button_style_css(key, tone), unsafe_allow_html=True)
    return st.button(label, key=key, use_container_width=use_container_width)


def build_compact_action_button_style_css(key: str, tone: str) -> str:
    marker_id = f"{key}_compact_marker"
    palette = {
        "primary": {
            "bg": "#eef2ff",
            "fg": "#4338ca",
            "border": "#c7d2fe",
            "hover": "#e0e7ff",
        },
        "neutral": {
            "bg": "#f8fafc",
            "fg": "#334155",
            "border": "#cbd5e1",
            "hover": "#f1f5f9",
        },
        "success": {
            "bg": "#ecfdf5",
            "fg": "#047857",
            "border": "#a7f3d0",
            "hover": "#d1fae5",
        },
        "danger": {
            "bg": "#fef2f2",
            "fg": "#dc2626",
            "border": "#fecaca",
            "hover": "#fee2e2",
        },
    }[tone]
    return f"""
<div id="{marker_id}"></div>
<style>
div.element-container:has(#{marker_id}) + div.element-container button {{
    background: {palette['bg']} !important;
    color: {palette['fg']} !important;
    border: 1px solid {palette['border']} !important;
    border-radius: 999px !important;
    padding: 0.16rem 0.62rem !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    min-height: 1.72rem !important;
    line-height: 1.05 !important;
}}
div.element-container:has(#{marker_id}) + div.element-container button:hover {{
    background: {palette['hover']} !important;
    color: {palette['fg']} !important;
}}
div.element-container:has(#{marker_id}) + div.element-container {{
    margin-top: 0 !important;
    margin-bottom: 0 !important;
}}
</style>
"""


def render_compact_action_button(label: str, *, key: str, tone: str) -> bool:
    st.markdown(build_compact_action_button_style_css(key, tone), unsafe_allow_html=True)
    return st.button(label, key=key, use_container_width=False)


def queue_quant_sim_flash(level: str, message: str, state=None) -> None:
    flash_state = st.session_state if state is None else state
    queue_flash_message(flash_state, QUANT_SIM_FLASH_NAMESPACE, level, message)


def build_replay_datetime(selected_date, selected_time) -> datetime:
    return datetime.combine(selected_date, selected_time).replace(microsecond=0)


def reconcile_active_replay_run(
    *,
    db_file: str = DEFAULT_DB_FILE,
    now: datetime | None = None,
) -> dict | None:
    db = QuantSimDB(db_file)
    active_run = db.get_active_sim_run()
    if active_run is None:
        return None

    status = str(active_run.get("status") or "").lower()
    if status not in {"queued", "running"}:
        return active_run

    run_id = int(active_run["id"])
    updated_at = _parse_optional_datetime(active_run.get("updated_at"))
    current_time = now or datetime.now()
    if updated_at is None:
        return active_run
    if (current_time - updated_at).total_seconds() < REPLAY_STALE_TIMEOUT_SECONDS:
        return active_run

    runner = get_quant_sim_replay_runner(db_file=db_file)
    if runner.is_running(run_id):
        return active_run

    snapshots = db.get_sim_run_snapshots(run_id)
    trades = db.get_sim_run_trades(run_id)
    metrics = _calculate_replay_summary_metrics(
        initial_cash=float(active_run.get("initial_cash") or 0),
        trades=trades,
        snapshots=snapshots,
    )
    status_message = "后台回放任务已停止响应，请重新启动回放。"
    db.finalize_sim_run(
        run_id,
        status="failed",
        final_equity=float(metrics["final_equity"]),
        total_return_pct=float(metrics["total_return_pct"]),
        max_drawdown_pct=float(metrics["max_drawdown_pct"]),
        win_rate=float(metrics["win_rate"]),
        trade_count=int(len(trades)),
        status_message=status_message,
        metadata={"error": "stale_background_replay"},
    )
    db.append_sim_run_event(run_id, status_message, level="error")
    return db.get_sim_run(run_id)


def _parse_optional_datetime(value) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _calculate_replay_summary_metrics(*, initial_cash: float, trades: list[dict], snapshots: list[dict]) -> dict:
    snapshot_equity_curve = [float(snapshot.get("total_equity") or 0) for snapshot in snapshots]
    final_equity = snapshot_equity_curve[-1] if snapshot_equity_curve else float(initial_cash)
    peak = float(initial_cash)
    max_drawdown_pct = 0.0
    for equity in snapshot_equity_curve:
        peak = max(peak, equity)
        if peak <= 0:
            continue
        drawdown_pct = (peak - equity) / peak * 100
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

    sell_trades = [trade for trade in trades if str(trade.get("action") or "").upper() == "SELL"]
    profitable_trades = [trade for trade in sell_trades if float(trade.get("realized_pnl") or 0) > 0]
    win_rate = (len(profitable_trades) / len(sell_trades) * 100) if sell_trades else 0.0
    total_return_pct = ((final_equity - float(initial_cash)) / float(initial_cash) * 100) if initial_cash > 0 else 0.0
    return {
        "final_equity": final_equity,
        "total_return_pct": total_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "win_rate": win_rate,
    }


@st.fragment(run_every=5)
def render_replay_status_panel(db_file: str = DEFAULT_DB_FILE) -> None:
    db = QuantSimDB(db_file)
    active_run = reconcile_active_replay_run(db_file=db_file)

    st.markdown("#### 当前回放状态")
    if active_run is None:
        st.info("当前回放状态：暂无运行中的回放任务。")
        return

    run_id = int(active_run["id"])
    progress_current = int(active_run.get("progress_current") or 0)
    progress_total = int(active_run.get("progress_total") or 0)
    progress_ratio = min(progress_current / progress_total, 1.0) if progress_total > 0 else 0.0
    status_label = _format_replay_status(active_run)
    status_message = str(active_run.get("status_message") or "等待执行")
    latest_checkpoint = active_run.get("latest_checkpoint_at") or "暂无"

    status_col1, status_col2, status_col3 = st.columns(3)
    status_col1.metric("任务", f"#{run_id}")
    status_col2.metric("状态", status_label)
    status_col3.metric("最近检查点", str(latest_checkpoint))

    st.progress(progress_ratio, text=f"当前进度：{progress_current}/{progress_total}")
    st.caption(status_message)

    if st.button("取消", key=f"quant_sim_cancel_replay_{run_id}", use_container_width=True):
        runner = get_quant_sim_replay_runner(db_file=db_file)
        if runner.cancel_run(run_id):
            queue_quant_sim_flash("warning", f"已请求取消回放任务 #{run_id}")
        else:
            queue_quant_sim_flash("info", f"回放任务 #{run_id} 当前不可取消")
        st.rerun()

def _format_replay_status(run: dict) -> str:
    status = str(run.get("status") or "").lower()
    return {
        "queued": "等待中",
        "running": "运行中",
        "completed": "已完成",
        "failed": "已失败",
        "cancelled": "已取消",
    }.get(status, status or "未知")


def build_scheduler_status_message(status: dict) -> tuple[str, str]:
    auto_execute_label = "自动执行已开启" if status.get("auto_execute") else "自动执行已关闭"
    timeframe_label = _format_analysis_timeframe(str(status.get("analysis_timeframe") or "30m"))
    strategy_mode_label = _format_strategy_mode(str(status.get("strategy_mode") or "auto"))
    if status.get("running"):
        return (
            "success",
            f"🟢 定时模拟运行中，当前按每 {status.get('interval_minutes', 0)} 分钟执行一次。"
            f" 当前策略粒度：{timeframe_label}。策略模式：{strategy_mode_label}。"
            f"{auto_execute_label}。下次运行：{status.get('next_run') or '计算中'}。",
        )
    if status.get("enabled"):
        return (
            "warning",
            f"🟡 定时任务配置已保存，但当前还未启动。计划间隔 {status.get('interval_minutes', 0)} 分钟，"
            f"当前策略粒度：{timeframe_label}，策略模式：{strategy_mode_label}，"
            f"{auto_execute_label}，请点击“启动模拟”。",
        )
    return (
        "info",
        f"⚪ 当前尚未启动定时模拟。先保存参数，再按需要启动。"
        f"当前策略粒度：{timeframe_label}。策略模式：{strategy_mode_label}。{auto_execute_label}。",
    )


def handle_manual_scan(scheduler, state=None) -> dict:
    summary = scheduler.run_once(run_reason="manual_scan")
    queue_quant_sim_flash(
        "success",
        f"✅ 已扫描 {summary['candidates_scanned']} 只候选股，生成 {summary['signals_created']} 条信号，"
        f"自动执行 {summary.get('auto_executed', 0)} 条，总权益 {summary['total_equity']:.2f}",
        state=state,
    )
    return summary


def handle_scheduler_save(
    scheduler,
    *,
    portfolio_service,
    initial_cash: float,
    auto_execute: bool = False,
    interval_minutes: int,
    trading_hours_only: bool,
    analysis_timeframe: str,
    strategy_mode: str | None = None,
    market: str,
    state=None,
) -> None:
    update_payload = dict(
        enabled=True,
        auto_execute=auto_execute,
        interval_minutes=interval_minutes,
        trading_hours_only=trading_hours_only,
        analysis_timeframe=analysis_timeframe,
        start_date=date.today().isoformat(),
        market=market,
    )
    if strategy_mode is not None:
        update_payload["strategy_mode"] = strategy_mode
    scheduler.update_config(**update_payload)
    cash_error = _sync_initial_cash_if_possible(portfolio_service, initial_cash)
    if cash_error:
        queue_quant_sim_flash("warning", f"✅ 参数已保存；资金池未更新：{cash_error}", state=state)
        return
    queue_quant_sim_flash("success", "✅ 参数已保存", state=state)


def handle_scheduler_start(
    scheduler,
    *,
    portfolio_service,
    initial_cash: float,
    auto_execute: bool = False,
    interval_minutes: int,
    trading_hours_only: bool,
    analysis_timeframe: str,
    strategy_mode: str | None = None,
    market: str,
    state=None,
) -> bool:
    update_payload = dict(
        enabled=True,
        auto_execute=auto_execute,
        interval_minutes=interval_minutes,
        trading_hours_only=trading_hours_only,
        analysis_timeframe=analysis_timeframe,
        start_date=date.today().isoformat(),
        market=market,
    )
    if strategy_mode is not None:
        update_payload["strategy_mode"] = strategy_mode
    scheduler.update_config(**update_payload)
    cash_error = _sync_initial_cash_if_possible(portfolio_service, initial_cash)
    started = scheduler.start()
    if started:
        if cash_error:
            queue_quant_sim_flash("warning", f"✅ 定时模拟已启动；资金池未更新：{cash_error}", state=state)
        else:
            queue_quant_sim_flash("success", "✅ 定时模拟已启动", state=state)
    else:
        queue_quant_sim_flash("warning", "定时模拟未启动，请先保存参数后重试", state=state)
    return started


def handle_scheduler_stop(scheduler, state=None) -> bool:
    stopped = scheduler.stop()
    if stopped:
        queue_quant_sim_flash("info", "⏹️ 定时模拟已停止", state=state)
    else:
        queue_quant_sim_flash("warning", "定时模拟当前未运行", state=state)
    return stopped


def _sync_initial_cash_if_possible(portfolio_service, initial_cash: float) -> str | None:
    try:
        portfolio_service.configure_account(initial_cash)
    except ValueError as exc:
        return str(exc)
    return None


def handle_account_update(portfolio_service, initial_cash: float, state=None) -> bool:
    try:
        portfolio_service.configure_account(initial_cash)
    except ValueError as exc:
        queue_quant_sim_flash("error", f"更新失败：{exc}", state=state)
        return False
    queue_quant_sim_flash("success", "✅ 资金池已更新", state=state)
    return True


def handle_account_reset(portfolio_service, initial_cash: float, state=None) -> bool:
    try:
        portfolio_service.reset_account(initial_cash=initial_cash)
    except ValueError as exc:
        queue_quant_sim_flash("error", f"重置失败：{exc}", state=state)
        return False
    queue_quant_sim_flash("success", "✅ 已重置模拟账户并重建资金池", state=state)
    return True


def handle_candidate_analysis_feedback(*, portfolio_service, signal: dict, auto_execute: bool, state=None) -> None:
    action = str(signal.get("action") or "HOLD").upper()
    if auto_execute and action in {"BUY", "SELL"}:
        executed = portfolio_service.auto_execute_signal(signal)
        if executed:
            queue_quant_sim_flash(
                "success",
                f"✅ 已分析 {signal.get('stock_code')}，并按策略自动执行模拟{action}。",
                state=state,
            )
            return
        queue_quant_sim_flash(
            "info",
            f"已分析 {signal.get('stock_code')}，结果为 {action}，但当前没有可执行的模拟成交。",
            state=state,
        )
        return
    if action in {"BUY", "SELL"}:
        queue_quant_sim_flash(
            "success",
            f"✅ 已分析 {signal.get('stock_code')}，生成信号 {action}，BUY / SELL 已进入待执行信号。",
            state=state,
        )
        return
    queue_quant_sim_flash(
        "info",
        f"已分析 {signal.get('stock_code')}，当前结果为 HOLD，继续观察。",
        state=state,
    )


def queue_historical_replay(
    replay_service,
    *,
    start_datetime,
    end_datetime=None,
    timeframe: str,
    market: str,
    strategy_mode: str = "auto",
    state=None,
) -> int | None:
    try:
        run_id = replay_service.enqueue_historical_range(
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            timeframe=timeframe,
            market=market,
            strategy_mode=strategy_mode,
        )
    except Exception as exc:
        queue_quant_sim_flash("error", f"启动失败：{exc}", state=state)
        return None
    queue_quant_sim_flash(
        "success",
        f"✅ 历史区间回放任务已创建（#{run_id}），请在“当前回放状态”查看进度。",
        state=state,
    )
    return run_id


def queue_continuous_replay(
    replay_service,
    *,
    start_datetime,
    end_datetime=None,
    timeframe: str,
    market: str,
    strategy_mode: str = "auto",
    overwrite_live: bool,
    auto_start_scheduler: bool,
    state=None,
) -> int | None:
    try:
        run_id = replay_service.enqueue_past_to_live(
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            timeframe=timeframe,
            market=market,
            strategy_mode=strategy_mode,
            overwrite_live=overwrite_live,
            auto_start_scheduler=auto_start_scheduler,
        )
    except Exception as exc:
        queue_quant_sim_flash("error", f"启动失败：{exc}", state=state)
        return None
    queue_quant_sim_flash(
        "success",
        f"✅ 接续回放任务已创建（#{run_id}），请在“当前回放状态”查看进度。",
        state=state,
    )
    return run_id


def handle_historical_replay(
    replay_service,
    *,
    start_datetime,
    end_datetime=None,
    timeframe: str,
    market: str,
    state=None,
) -> dict:
    summary = replay_service.run_historical_range(
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        timeframe=timeframe,
        market=market,
    )
    queue_quant_sim_flash(
        "success",
        f"✅ 历史区间模拟完成：{summary['checkpoint_count']} 个检查点，"
        f"{summary['trade_count']} 笔交易，收益率 {summary['total_return_pct']:.2f}%",
        state=state,
    )
    return summary


def handle_continuous_replay(
    replay_service,
    *,
    start_datetime,
    end_datetime=None,
    timeframe: str,
    market: str,
    overwrite_live: bool,
    auto_start_scheduler: bool,
    state=None,
) -> dict:
    summary = replay_service.run_past_to_live(
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        timeframe=timeframe,
        market=market,
        overwrite_live=overwrite_live,
        auto_start_scheduler=auto_start_scheduler,
    )
    queue_quant_sim_flash(
        "success",
        f"✅ 连续模拟完成：{summary['checkpoint_count']} 个检查点，"
        f"{summary['trade_count']} 笔交易，收益率 {summary['total_return_pct']:.2f}%，已接入实时模拟账户。",
        state=state,
    )
    return summary


def resolve_pending_signal_default_price(signal: dict, candidate_service, portfolio_service) -> float:
    stock_code = signal.get("stock_code")
    if stock_code and candidate_service is not None:
        candidate = candidate_service.db.get_candidate(stock_code)
        if candidate:
            try:
                latest_price = float(candidate.get("latest_price") or 0)
                if latest_price > 0:
                    return latest_price
            except (TypeError, ValueError):
                pass

    if stock_code and portfolio_service is not None:
        for position in portfolio_service.list_positions():
            if position.get("stock_code") == stock_code:
                try:
                    latest_price = float(position.get("latest_price") or position.get("avg_price") or 0)
                    if latest_price > 0:
                        return latest_price
                except (TypeError, ValueError):
                    break

    return 0.01


def handle_confirm_buy(portfolio_service, *, signal_id: int, price: float, quantity: int, note: str, state=None) -> bool:
    try:
        portfolio_service.confirm_buy(
            signal_id,
            price=price,
            quantity=quantity,
            note=note,
        )
    except ValueError as exc:
        queue_quant_sim_flash("error", f"执行失败：{exc}", state=state)
        return False
    queue_quant_sim_flash("success", "✅ 已更新模拟持仓", state=state)
    return True


def handle_confirm_sell(portfolio_service, *, signal_id: int, price: float, quantity: int, note: str, state=None) -> bool:
    try:
        portfolio_service.confirm_sell(
            signal_id,
            price=price,
            quantity=quantity,
            note=note,
        )
    except ValueError as exc:
        queue_quant_sim_flash("error", f"执行失败：{exc}", state=state)
        return False
    queue_quant_sim_flash("success", "✅ 已更新模拟持仓", state=state)
    return True
