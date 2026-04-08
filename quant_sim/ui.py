"""Streamlit UI for the unified quant simulation workflow."""

from __future__ import annotations

import streamlit as st

from quant_sim.candidate_pool_service import CandidatePoolService
from quant_sim.engine import QuantSimEngine
from quant_sim.integration import add_stock_to_quant_sim
from quant_sim.portfolio_service import PortfolioService
from quant_sim.scheduler import QuantSimScheduler
from quant_sim.signal_center_service import SignalCenterService


def display_quant_sim() -> None:
    """Render the end-to-end quant simulation workspace."""

    candidate_service = CandidatePoolService()
    signal_service = SignalCenterService()
    portfolio_service = PortfolioService()
    engine = QuantSimEngine()
    scheduler = QuantSimScheduler()

    st.title("🧪 量化模拟")
    st.caption("选股结果统一进入候选池，系统自动计算 BUY/SELL/HOLD，人工在券商端执行后再回填。")

    with st.expander("📖 使用流程", expanded=False):
        st.markdown(
            """
            1. 从主力选股、低价擒牛、净利增长、低估值页面把股票加入量化模拟。
            2. 在这里运行“立即分析候选池”，系统会生成 BUY / SELL / HOLD 信号。
            3. BUY / SELL 会进入“待执行信号”，由你手工下单。
            4. 下单后点“已买入 / 已卖出”，系统更新模拟持仓与后续跟踪。
            """
        )

    with st.form("quant_sim_add_manual_candidate"):
        col1, col2, col3, col4 = st.columns([1.1, 1.4, 1.1, 1.0])
        with col1:
            stock_code = st.text_input("股票代码", placeholder="如 600000")
        with col2:
            stock_name = st.text_input("股票名称", placeholder="如 浦发银行")
        with col3:
            source = st.selectbox(
                "来源策略",
                options=["manual", "main_force", "low_price_bull", "profit_growth", "value_stock"],
                format_func=_format_source,
            )
        with col4:
            latest_price = st.number_input("参考价格", min_value=0.0, value=0.0, step=0.01)

        notes = st.text_input("备注", placeholder="可选")
        submitted = st.form_submit_button("➕ 手动加入候选池", use_container_width=True)
        if submitted:
            success, message, _ = add_stock_to_quant_sim(
                stock_code=stock_code,
                stock_name=stock_name,
                source=source,
                latest_price=latest_price or None,
                notes=notes or None,
            )
            if success:
                st.success(message)
                st.rerun()
            st.error(message)

    col_run, col_refresh = st.columns(2)
    with col_run:
        if st.button("⚡ 立即分析候选池", type="primary", use_container_width=True):
            summary = scheduler.run_once()
            st.success(
                f"✅ 已扫描 {summary['candidates_scanned']} 只候选股，生成 {summary['signals_created']} 条信号"
            )
            st.rerun()
    with col_refresh:
        if st.button("🔄 刷新页面", use_container_width=True):
            st.rerun()

    tab_candidates, tab_signals, tab_pending, tab_positions = st.tabs(
        ["📥 候选池", "🧠 策略信号", "⏳ 待执行", "💼 模拟持仓"]
    )

    with tab_candidates:
        candidates = candidate_service.list_candidates(status="active")
        if not candidates:
            st.info("候选池为空，可以从选股页加入标的，或在上方手动添加。")
        else:
            st.dataframe(candidates, use_container_width=True, hide_index=True)
            st.markdown("---")
            for candidate in candidates:
                with st.expander(f"{candidate['stock_code']} - {candidate.get('stock_name') or '未命名'}"):
                    st.write(f"来源策略：{_format_source(candidate.get('source', 'manual'))}")
                    st.write(f"参考价格：{candidate.get('latest_price', 0) or 0:.2f}")
                    if st.button("立即分析该标的", key=f"analyze_candidate_{candidate['id']}"):
                        signal = engine.analyze_candidate(candidate)
                        st.success(
                            f"✅ 已生成信号：{signal['action']} / 置信度 {signal['confidence']}%"
                        )
                        st.rerun()

    with tab_signals:
        signals = signal_service.list_signals(limit=50)
        if not signals:
            st.info("暂无信号记录。")
        else:
            for signal in signals:
                with st.expander(
                    f"{signal['action']} | {signal['stock_code']} - {signal.get('stock_name') or ''} | {signal['status']}"
                ):
                    st.markdown(f"**置信度**：{signal.get('confidence', 0)}%")
                    st.markdown(f"**建议仓位**：{signal.get('position_size_pct', 0)}%")
                    st.markdown(f"**推理**：{signal.get('reasoning') or '暂无'}")
                    st.caption(
                        f"创建时间：{signal.get('created_at')} | 执行状态：{signal.get('status')}"
                    )

    with tab_pending:
        pending_signals = signal_service.list_pending_signals()
        if not pending_signals:
            st.info("当前没有待执行信号。")
        else:
            for signal in pending_signals:
                with st.expander(
                    f"{signal['action']} | {signal['stock_code']} - {signal.get('stock_name') or ''}",
                    expanded=True,
                ):
                    st.markdown(f"**推理**：{signal.get('reasoning') or '暂无'}")
                    st.markdown(f"**建议仓位**：{signal.get('position_size_pct', 0)}%")

                    price = st.number_input(
                        "成交价",
                        min_value=0.0,
                        value=0.0,
                        step=0.01,
                        key=f"pending_price_{signal['id']}",
                    )
                    quantity = st.number_input(
                        "成交数量",
                        min_value=0,
                        value=100,
                        step=100,
                        key=f"pending_quantity_{signal['id']}",
                    )
                    note = st.text_input(
                        "执行备注",
                        value="",
                        placeholder="如：已在券商端下单",
                        key=f"pending_note_{signal['id']}",
                    )

                    col1, col2, col3 = st.columns(3)
                    if signal["action"] == "BUY":
                        with col1:
                            if st.button("✅ 标记已买入", key=f"confirm_buy_{signal['id']}"):
                                portfolio_service.confirm_buy(
                                    signal["id"],
                                    price=price,
                                    quantity=int(quantity),
                                    note=note or "已手工买入",
                                )
                                st.success("✅ 已更新模拟持仓")
                                st.rerun()
                    else:
                        with col1:
                            if st.button("✅ 标记已卖出", key=f"confirm_sell_{signal['id']}"):
                                portfolio_service.confirm_sell(
                                    signal["id"],
                                    price=price,
                                    quantity=int(quantity),
                                    note=note or "已手工卖出",
                                )
                                st.success("✅ 已更新模拟持仓")
                                st.rerun()

                    with col2:
                        if st.button("⏰ 延后处理", key=f"delay_signal_{signal['id']}"):
                            portfolio_service.delay_signal(signal["id"], note=note or "延后处理")
                            st.info("已延后，信号会继续保留在待执行列表。")
                            st.rerun()

                    with col3:
                        if st.button("🚫 忽略信号", key=f"ignore_signal_{signal['id']}"):
                            portfolio_service.ignore_signal(signal["id"], note=note or "人工忽略")
                            st.warning("已忽略该信号。")
                            st.rerun()

    with tab_positions:
        positions = portfolio_service.list_positions()
        if not positions:
            st.info("当前暂无模拟持仓。")
        else:
            st.dataframe(positions, use_container_width=True, hide_index=True)


def _format_source(source: str) -> str:
    return {
        "manual": "手工加入",
        "main_force": "主力选股",
        "low_price_bull": "低价擒牛",
        "profit_growth": "净利增长",
        "value_stock": "低估值策略",
    }.get(source, source)
