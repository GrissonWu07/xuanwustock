#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主力选股UI模块
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from selector_ui_state import load_main_force_state, save_main_force_state
from batch_deep_analysis import (
    display_batch_analysis_results,
    display_batch_deep_analysis_section,
    sort_main_force_batch_candidates,
)
from main_force_analysis import MainForceAnalyzer
from main_force_pdf_generator import display_report_download_section
from main_force_history_ui import display_batch_history
from watchlist_selector_integration import add_stock_to_watchlist
from watchlist_selector_integration import sync_selector_dataframe_to_watchlist


def update_main_force_progress_ui(status_widget, progress_bar, detail_placeholder, percent: int, message: str):
    """Render stage-by-stage progress for the main force selector."""
    progress_bar.progress(percent)
    detail_placeholder.caption(f"当前阶段：{message}")
    status_widget.update(label=message, state="running")


def _extract_main_force_latest_price(recommendation: dict) -> float | None:
    """Extract a numeric latest price from main-force recommendation payloads."""
    stock_data = recommendation.get("stock_data", {}) or {}
    for field_name in ("最新价", "股价"):
        value = stock_data.get(field_name)
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _find_first_matching_column(df: pd.DataFrame, patterns: list[str]) -> str | None:
    for pattern in patterns:
        matching = [col for col in df.columns if pattern in col]
        if matching:
            return matching[0]
    return None


def _extract_numeric_series(df: pd.DataFrame, patterns: list[str], *, scale: float = 1.0) -> pd.Series | None:
    column_name = _find_first_matching_column(df, patterns)
    if not column_name:
        return None
    series = pd.to_numeric(df[column_name], errors="coerce")
    if scale != 1.0:
        series = series / scale
    return series


def build_main_force_candidate_display_df(raw_df: pd.DataFrame) -> pd.DataFrame:
    candidate_df = pd.DataFrame(index=raw_df.index)
    candidate_df["加入关注池"] = False
    candidate_df["股票代码"] = raw_df.get("股票代码", pd.Series([""] * len(raw_df), index=raw_df.index))
    candidate_df["股票简称"] = raw_df.get("股票简称", pd.Series([""] * len(raw_df), index=raw_df.index))

    industry_col = _find_first_matching_column(raw_df, ["所属行业", "所属同花顺行业"])
    if industry_col:
        candidate_df["所属行业"] = raw_df[industry_col]
    else:
        candidate_df["所属行业"] = ""

    latest_price_series = _extract_numeric_series(raw_df, ["最新价", "股价"])
    if latest_price_series is not None:
        candidate_df["最新价"] = latest_price_series

    main_fund_series = _extract_numeric_series(
        raw_df,
        [
            "区间主力资金流向",
            "区间主力资金净流入",
            "主力资金流向",
            "主力资金净流入",
            "主力净流入",
            "主力资金",
        ],
        scale=100000000.0,
    )
    if main_fund_series is not None:
        candidate_df["主力资金(亿)"] = main_fund_series

    pct_series = _extract_numeric_series(
        raw_df,
        [
            "区间涨跌幅:前复权",
            "区间涨跌幅:前复权(%)",
            "区间涨跌幅(%)",
            "区间涨跌幅",
            "涨跌幅:前复权",
            "涨跌幅:前复权(%)",
            "涨跌幅(%)",
            "涨跌幅",
        ],
    )
    if pct_series is not None:
        candidate_df["区间涨跌幅(%)"] = pct_series

    market_cap_series = _extract_numeric_series(raw_df, ["总市值"], scale=100000000.0)
    if market_cap_series is not None:
        candidate_df["总市值(亿)"] = market_cap_series

    pe_series = _extract_numeric_series(raw_df, ["市盈率"])
    if pe_series is not None:
        candidate_df["市盈率"] = pe_series

    pb_series = _extract_numeric_series(raw_df, ["市净率"])
    if pb_series is not None:
        candidate_df["市净率"] = pb_series

    return candidate_df


def sync_main_force_recommendations_to_watchlist(recommendations: list[dict]) -> dict:
    """Sync selected recommendations into the shared watchlist."""
    summary = {
        "attempted": 0,
        "success_count": 0,
        "failures": [],
    }

    for recommendation in recommendations or []:
        stock_data = recommendation.get("stock_data", {}) or {}
        stock_code = (
            str(stock_data.get("股票代码") or recommendation.get("symbol") or "").split(".")[0].strip()
        )
        stock_name = str(stock_data.get("股票简称") or recommendation.get("name") or "").strip()
        if not stock_code or not stock_name:
            continue

        summary["attempted"] += 1
        latest_price = _extract_main_force_latest_price(recommendation)
        notes = f"主力选股第{recommendation.get('rank', '?')}名；亮点：{recommendation.get('highlights', 'N/A')}"
        success, message, _ = add_stock_to_watchlist(
            stock_code=stock_code,
            stock_name=stock_name,
            source="main_force",
            latest_price=latest_price,
            notes=notes,
        )
        if success:
            summary["success_count"] += 1
        else:
            summary["failures"].append(f"{stock_code}: {message}")

    return summary


def restore_main_force_state():
    """Restore the latest saved main-force result into the current session."""
    if st.session_state.get("main_force_result") is not None:
        return

    result, analyzer, selected_at = load_main_force_state()
    if result:
        st.session_state.main_force_result = result
        st.session_state.main_force_analyzer = analyzer
        st.session_state.main_force_selected_at = selected_at


def display_main_force_selector():
    """显示主力选股界面"""
    restore_main_force_state()

    # 检查是否查看历史记录
    if st.session_state.get('main_force_view_history'):
        display_batch_history()
        return

    # 页面标题
    st.markdown("## 🎯 主力选股 - 智能筛选优质标的")

    current_result = st.session_state.get("main_force_result")
    current_analyzer = st.session_state.get("main_force_analyzer")
    current_selected_at = st.session_state.get("main_force_selected_at")

    st.markdown("""
    ### 功能说明
    
    本功能通过以下步骤筛选优质股票：
    
    1. **数据获取**: 使用问财获取指定日期以来主力资金净流入前100名股票
    2. **智能筛选**: 过滤掉涨幅过高、市值不符的股票
    3. **AI分析**: 调用资金流向、行业板块、财务基本面三大分析师团队
    4. **综合决策**: 资深研究员综合评估，精选3-5只优质标的
    
    **筛选标准**:
    - ✅ 主力资金净流入较多
    - ✅ 区间涨跌幅适中（避免追高）
    - ✅ 财务基本面良好
    - ✅ 行业前景明朗
    - ✅ 综合素质优秀
    """)

    st.markdown("---")

    # 参数设置
    col1, col2, col3 = st.columns(3)

    with col1:
        date_option = st.selectbox(
            "选择时间区间",
            ["最近3个月", "最近6个月", "最近1年", "自定义日期"],
            key="main_force_date_option",
        )

        if date_option == "最近3个月":
            days_ago = 90
            start_date = None
        elif date_option == "最近6个月":
            days_ago = 180
            start_date = None
        elif date_option == "最近1年":
            days_ago = 365
            start_date = None
        else:
            custom_date = st.date_input(
                "选择开始日期",
                value=datetime.now() - timedelta(days=90),
                key="main_force_custom_date",
            )
            start_date = f"{custom_date.year}年{custom_date.month}月{custom_date.day}日"
            days_ago = None

    with col2:
        final_n = st.slider(
            "最终精选数量",
            min_value=3,
            max_value=10,
            value=5,
            step=1,
            help="最终推荐的股票数量",
            key="main_force_final_n",
        )

    with col3:
        st.info("💡 系统将获取前100名股票，进行整体分析后精选优质标的")

    # 高级选项
    with st.expander("⚙️ 高级筛选参数"):
        col1, col2, col3 = st.columns(3)

        with col1:
            max_change = st.number_input(
                "最大涨跌幅(%)",
                min_value=5.0,
                max_value=200.0,
                value=30.0,
                step=5.0,
                help="过滤掉涨幅过高的股票，避免追高"
            )

        with col2:
            min_cap = st.number_input(
                "最小市值(亿)",
                min_value=10.0,
                max_value=500.0,
                value=50.0,
                step=10.0
            )

        with col3:
            max_cap = st.number_input(
                "最大市值(亿)",
                min_value=50.0,
                max_value=50000.0,
                value=5000.0,
                step=100.0
            )

    st.markdown("---")

    # 开始分析按钮（使用.env中配置的默认模型）
    if st.button("🚀 开始主力选股", type="primary", width='content', key="main_force_start_selector"):
        status_widget = st.status("正在初始化主力选股分析...", expanded=True)
        progress_bar = st.progress(0)
        detail_placeholder = st.empty()

        update_main_force_progress_ui(
            status_widget,
            progress_bar,
            detail_placeholder,
            1,
            "正在准备分析参数...",
        )

        # 创建分析器（使用默认模型）
        analyzer = MainForceAnalyzer()

        # 运行分析
        result = analyzer.run_full_analysis(
            start_date=start_date,
            days_ago=days_ago,
            final_n=final_n,
            max_range_change=max_change,
            min_market_cap=min_cap,
            max_market_cap=max_cap,
            progress_callback=lambda percent, message: update_main_force_progress_ui(
                status_widget,
                progress_bar,
                detail_placeholder,
                percent,
                message,
            ),
        )

        # 保存结果到session_state
        st.session_state.main_force_result = result
        st.session_state.main_force_analyzer = analyzer

        # 显示结果
        if result['success']:
            selected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.session_state.main_force_selected_at = selected_at
            st.session_state.pop("main_force_batch_watchlist_sync", None)
            save_main_force_state(result=result, analyzer=analyzer, selected_at=selected_at)
            status_widget.update(label="主力选股分析完成", state="complete")
            progress_bar.progress(100)
            detail_placeholder.caption("当前阶段：主力选股分析完成")
            st.success(f"✅ 分析完成！共筛选出 {len(result['final_recommendations'])} 只优质标的")
            st.rerun()
        else:
            status_widget.update(label="主力选股分析失败", state="error")
            detail_placeholder.caption(f"当前阶段：分析失败 - {result.get('error', '未知错误')}")
            st.error(f"❌ 分析失败: {result.get('error', '未知错误')}")

    if current_result and current_result.get("success"):
        st.markdown("---")
        st.caption("最近一次主力选股结果会显示在这里，先完成参数设置，再查看候选和推荐会更顺手。")
        display_analysis_results(
            current_result,
            current_analyzer,
            current_selected_at,
        )

    # 显示分析结果
    if not (current_result and current_result.get("success")) and st.session_state.get('main_force_batch_results'):
        st.markdown("---")
        st.markdown("## 📊 批量深度分析结果")
        display_batch_analysis_results(
            st.session_state.main_force_batch_results,
            strategy_key="main_force",
        )

def display_analysis_results(result: dict, analyzer, selected_at: str | None = None):
    """显示分析结果"""

    st.markdown("---")
    st.markdown("## 📊 分析结果")

    # 统计信息
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("获取股票数", result['total_stocks'])

    with col2:
        st.metric("筛选后", result['filtered_stocks'])

    with col3:
        st.metric("最终推荐", len(result['final_recommendations']))

    st.markdown("---")

    summary_col, history_col = st.columns([4.4, 1.0], gap="small")
    with summary_col:
        if selected_at:
            st.info(f"🕒 最近一次选股时间：{selected_at} | ⭐ 最终推荐：{len(result['final_recommendations'])} 只")
    with history_col:
        st.markdown('<div style="height: 0.35rem;"></div>', unsafe_allow_html=True)
        if st.button("📚 查看历史", key="main_force_view_history_inline", use_container_width=True):
            st.session_state.main_force_view_history = True
            st.rerun()

    batch_sync_summary = st.session_state.get("main_force_batch_watchlist_sync")
    if st.button("⭐ 批量加入关注池", key="main_force_batch_watchlist_sync_button", use_container_width=True):
        batch_sync_summary = sync_main_force_recommendations_to_watchlist(
            result.get("final_recommendations", [])
        )
        st.session_state.main_force_batch_watchlist_sync = batch_sync_summary
    if batch_sync_summary:
        if batch_sync_summary["success_count"] > 0:
            st.success(f"⭐ 已加入 {batch_sync_summary['success_count']} 只主力选股结果到关注池")
        if batch_sync_summary["failures"]:
            st.warning("；".join(batch_sync_summary["failures"]))

    # 显示候选股票列表
    if analyzer and analyzer.raw_stocks is not None and not analyzer.raw_stocks.empty:
        st.markdown("---")
        st.markdown("### 📋 候选股票列表（筛选后）")

        candidate_df = build_main_force_candidate_display_df(analyzer.raw_stocks)

        # 调试信息：显示找到的列名
        with st.expander("🔍 调试信息 - 查看数据列", expanded=False):
            st.caption("所有可用列:")
            cols_list = list(analyzer.raw_stocks.columns)
            st.write(cols_list)
            st.caption(f"\n候选表显示列: {list(candidate_df.columns)}")

        # 显示可勾选DataFrame
        editable_df = candidate_df.copy()
        selection_column = "加入关注池"
        edited_df = st.data_editor(
            editable_df,
            hide_index=True,
            width='stretch',
            height=400,
            key="main_force_candidate_editor",
            column_config={
                selection_column: st.column_config.CheckboxColumn(
                    selection_column,
                    help="勾选想加入我的关注的股票",
                    default=False,
                ),
                "最新价": st.column_config.NumberColumn("最新价", format="%.2f"),
                "主力资金(亿)": st.column_config.NumberColumn("主力资金(亿)", format="%.2f"),
                "区间涨跌幅(%)": st.column_config.NumberColumn("区间涨跌幅(%)", format="%.2f"),
                "总市值(亿)": st.column_config.NumberColumn("总市值(亿)", format="%.2f"),
                "市盈率": st.column_config.NumberColumn("市盈率", format="%.2f"),
                "市净率": st.column_config.NumberColumn("市净率", format="%.2f"),
            },
            disabled=[col for col in editable_df.columns if col != selection_column],
        )

        selected_rows = edited_df[edited_df[selection_column]].drop(columns=[selection_column])
        candidate_sync_summary = st.session_state.get("main_force_candidate_watchlist_sync")
        if st.button(
            "⭐ 加入所选关注池",
            key="main_force_candidate_watchlist_selected_button",
            use_container_width=True,
        ):
            if selected_rows.empty:
                st.warning("请先勾选候选股票。")
            else:
                candidate_sync_summary = sync_selector_dataframe_to_watchlist(
                    selected_rows,
                    source="main_force",
                    note_prefix="主力选股候选",
                )
                st.session_state.main_force_candidate_watchlist_sync = candidate_sync_summary
        if candidate_sync_summary:
            if candidate_sync_summary["success_count"] > 0:
                st.success(f"⭐ 已加入 {candidate_sync_summary['success_count']} 只候选股票到关注池")
            if candidate_sync_summary["failures"]:
                st.warning("；".join(candidate_sync_summary["failures"]))

        # 显示统计
        st.caption(f"共 {len(candidate_df)} 只候选股票，当前表格显示 {len(candidate_df.columns) - 1} 个核心字段")

        # 下载按钮
        csv = candidate_df.drop(columns=[selection_column]).to_csv(index=False, encoding='utf-8-sig')
        st.download_button(
            label="📥 下载候选列表CSV",
            data=csv,
            file_name=f"main_force_stocks_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )

        display_batch_deep_analysis_section(
            stocks_df=analyzer.raw_stocks,
            sorted_df=sort_main_force_batch_candidates(analyzer.raw_stocks),
            strategy_key="main_force",
            strategy_label="主力选股",
            default_count=min(20, len(analyzer.raw_stocks)),
        )

    # 显示推荐股票
    if result['final_recommendations']:
        st.markdown("---")
        st.markdown("### ⭐ 精选推荐")

        for rec in result['final_recommendations']:
            with st.expander(
                f"【第{rec['rank']}名】{rec['symbol']} - {rec['name']}",
                expanded=(rec['rank'] <= 3)
            ):
                display_recommendation_detail(rec)

    # 显示AI分析师完整报告
    if analyzer and hasattr(analyzer, 'fund_flow_analysis'):
        st.markdown("---")
        display_analyst_reports(analyzer)

    # 显示PDF报告下载区域
    if analyzer and result:
        display_report_download_section(analyzer, result)

def display_recommendation_detail(rec: dict):
    """显示单个推荐股票的详细信息"""

    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("#### 📌 推荐理由")
        for reason in rec.get('reasons', []):
            st.markdown(f"- {reason}")

        st.markdown("#### 💡 投资亮点")
        st.info(rec.get('highlights', 'N/A'))

    with col2:
        st.markdown("#### 📊 投资建议")
        st.markdown(f"**建议仓位**: {rec.get('position', 'N/A')}")
        st.markdown(f"**投资周期**: {rec.get('investment_period', 'N/A')}")

        st.markdown("#### ⚠️ 风险提示")
        st.warning(rec.get('risks', 'N/A'))

        stock_data = rec.get('stock_data', {}) or {}
        stock_code = str(stock_data.get('股票代码') or rec.get('symbol', '')).split('.')[0].strip()
        stock_name = str(stock_data.get('股票简称') or rec.get('name', '')).strip()
        if stock_code and stock_name:
            if st.button(f"⭐ 加入关注池", key=f"main_force_watchlist_{stock_code}", use_container_width=True):
                success, message, _ = add_stock_to_watchlist(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    source="main_force",
                    latest_price=_extract_main_force_latest_price(rec),
                    notes=f"主力选股第{rec.get('rank', '?')}名；亮点：{rec.get('highlights', 'N/A')}",
                )
                if success:
                    st.success(message)
                else:
                    st.error(message)

    # 显示股票详细数据
    if 'stock_data' in rec:
        st.markdown("---")
        st.markdown("#### 📊 股票详细数据")

        stock_data = rec['stock_data']

        # 创建数据展示
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("股票代码", stock_data.get('股票代码', 'N/A'))

            # 显示行业
            industry_keys = [k for k in stock_data.keys() if '行业' in k]
            if industry_keys:
                st.metric("所属行业", stock_data.get(industry_keys[0], 'N/A'))

        with col2:
            # 显示主力资金
            fund_keys = [k for k in stock_data.keys() if '主力' in k and '净流入' in k]
            if fund_keys:
                fund_value = stock_data.get(fund_keys[0], 'N/A')
                if isinstance(fund_value, (int, float)):
                    st.metric("主力资金净流入", f"{fund_value/100000000:.2f}亿")
                else:
                    st.metric("主力资金净流入", str(fund_value))

        with col3:
            # 显示涨跌幅
            change_keys = [k for k in stock_data.keys() if '涨跌幅' in k]
            if change_keys:
                change_value = stock_data.get(change_keys[0], 'N/A')
                if isinstance(change_value, (int, float)):
                    st.metric("区间涨跌幅", f"{change_value:.2f}%")
                else:
                    st.metric("区间涨跌幅", str(change_value))

        # 显示其他关键指标
        st.markdown("**其他关键指标：**")
        metrics_col1, metrics_col2, metrics_col3 = st.columns(3)

        with metrics_col1:
            if '市盈率' in stock_data or any('市盈率' in k for k in stock_data.keys()):
                pe_keys = [k for k in stock_data.keys() if '市盈率' in k]
                if pe_keys:
                    st.caption(f"市盈率: {stock_data.get(pe_keys[0], 'N/A')}")

        with metrics_col2:
            if '市净率' in stock_data or any('市净率' in k for k in stock_data.keys()):
                pb_keys = [k for k in stock_data.keys() if '市净率' in k]
                if pb_keys:
                    st.caption(f"市净率: {stock_data.get(pb_keys[0], 'N/A')}")

        with metrics_col3:
            if '总市值' in stock_data or any('总市值' in k for k in stock_data.keys()):
                cap_keys = [k for k in stock_data.keys() if '总市值' in k]
                if cap_keys:
                    st.caption(f"总市值: {stock_data.get(cap_keys[0], 'N/A')}")

def display_analyst_reports(analyzer):
    """显示AI分析师完整报告"""

    st.markdown("### 🤖 AI分析师团队完整报告")

    # 创建三个标签页
    tab1, tab2, tab3 = st.tabs(["💰 资金流向分析", "📊 行业板块分析", "📈 财务基本面分析"])

    with tab1:
        st.markdown("#### 💰 资金流向分析师报告")
        st.markdown("---")
        if hasattr(analyzer, 'fund_flow_analysis') and analyzer.fund_flow_analysis:
            st.markdown(analyzer.fund_flow_analysis)
        else:
            st.info("暂无资金流向分析报告")

    with tab2:
        st.markdown("#### 📊 行业板块及市场热点分析师报告")
        st.markdown("---")
        if hasattr(analyzer, 'industry_analysis') and analyzer.industry_analysis:
            st.markdown(analyzer.industry_analysis)
        else:
            st.info("暂无行业板块分析报告")

    with tab3:
        st.markdown("#### 📈 财务基本面分析师报告")
        st.markdown("---")
        if hasattr(analyzer, 'fundamental_analysis') and analyzer.fundamental_analysis:
            st.markdown(analyzer.fundamental_analysis)
        else:
            st.info("暂无财务基本面分析报告")

def format_number(value, unit='', suffix=''):
    """格式化数字显示"""
    if value is None or value == 'N/A':
        return 'N/A'

    try:
        num = float(value)

        # 如果单位是亿，需要转换
        if unit == '亿':
            if abs(num) >= 100000000:  # 大于1亿（以元为单位）
                num = num / 100000000
            elif abs(num) < 100:  # 小于100，可能已经是亿
                pass
            else:  # 100-100000000之间，可能是万
                num = num / 10000

        # 格式化显示
        if abs(num) >= 1000:
            formatted = f"{num:,.2f}"
        elif abs(num) >= 1:
            formatted = f"{num:.2f}"
        else:
            formatted = f"{num:.4f}"

        return f"{formatted}{suffix}"
    except (ValueError, TypeError):
        return str(value)

