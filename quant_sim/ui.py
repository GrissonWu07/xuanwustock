"""Streamlit UI for the unified quant simulation workflow."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from quant_sim.candidate_pool_service import CandidatePoolService
from quant_sim.engine import QuantSimEngine
from quant_sim.integration import add_stock_to_quant_sim
from quant_sim.portfolio_service import PortfolioService
from quant_sim.scheduler import get_quant_sim_scheduler
from quant_sim.signal_center_service import SignalCenterService


def display_quant_sim() -> None:
    """Render the end-to-end quant simulation workspace."""

    candidate_service = CandidatePoolService()
    signal_service = SignalCenterService()
    portfolio_service = PortfolioService()
    engine = QuantSimEngine()
    scheduler = get_quant_sim_scheduler()
    account_summary = portfolio_service.get_account_summary()
    scheduler_status = scheduler.get_status()

    st.title("🧪 量化模拟")
    st.caption("选股结果统一进入候选池，系统自动计算 BUY/SELL/HOLD，人工在券商端执行后再回填。")

    metric1, metric2, metric3, metric4, metric5 = st.columns(5)
    metric1.metric("初始资金池", f"{account_summary['initial_cash']:.2f}")
    metric2.metric("可用现金", f"{account_summary['available_cash']:.2f}")
    metric3.metric("持仓市值", f"{account_summary['market_value']:.2f}")
    metric4.metric("总权益", f"{account_summary['total_equity']:.2f}")
    metric5.metric("总盈亏", f"{account_summary['total_pnl']:.2f}")

    with st.expander("📖 使用流程", expanded=False):
        st.markdown(
            """
            1. 从主力选股、低价擒牛、净利增长、低估值页面把股票加入量化模拟。
            2. 在这里运行“立即分析候选池”，系统会生成 BUY / SELL / HOLD 信号。
            3. BUY / SELL 会进入“待执行信号”，由你手工下单。
            4. 下单后点“已买入 / 已卖出”，系统更新模拟持仓与后续跟踪。
            """
        )

    with st.expander("⚙️ 定时模拟与资金池", expanded=False):
        status_col1, status_col2, status_col3 = st.columns(3)
        status_col1.metric("定时状态", "运行中" if scheduler_status["running"] else "已停止")
        status_col2.metric("上次运行", scheduler_status["last_run_at"] or "暂无")
        status_col3.metric("下次运行", scheduler_status["next_run"] or "未启动")

        config_col1, config_col2, config_col3, config_col4 = st.columns(4)
        with config_col1:
            enabled = st.checkbox("启用定时模拟", value=bool(scheduler_status["enabled"]))
        with config_col2:
            interval_minutes = st.number_input(
                "间隔(分钟)",
                min_value=5,
                max_value=240,
                value=int(scheduler_status["interval_minutes"]),
                step=5,
            )
        with config_col3:
            trading_hours_only = st.checkbox(
                "仅交易时段运行",
                value=bool(scheduler_status["trading_hours_only"]),
            )
        with config_col4:
            market = st.selectbox(
                "市场",
                options=["CN", "HK", "US"],
                index=["CN", "HK", "US"].index(str(scheduler_status["market"])),
            )

        fund_col1, fund_col2 = st.columns([1.2, 1.0])
        with fund_col1:
            initial_cash = st.number_input(
                "初始资金池(元)",
                min_value=10000.0,
                value=float(account_summary["initial_cash"]),
                step=10000.0,
                disabled=account_summary["trade_count"] > 0 or account_summary["position_count"] > 0,
            )
        with fund_col2:
            st.caption("初始资金只能在未开始交易前调整。")

        action_col1, action_col2, action_col3, action_col4 = st.columns(4)
        with action_col1:
            if st.button("💾 保存配置", use_container_width=True):
                scheduler.update_config(
                    enabled=enabled,
                    interval_minutes=int(interval_minutes),
                    trading_hours_only=trading_hours_only,
                    market=market,
                )
                st.success("✅ 定时模拟配置已保存")
                st.rerun()
        with action_col2:
            if st.button("▶️ 启动定时模拟", use_container_width=True):
                scheduler.update_config(
                    enabled=enabled,
                    interval_minutes=int(interval_minutes),
                    trading_hours_only=trading_hours_only,
                    market=market,
                )
                if scheduler.start():
                    st.success("✅ 定时模拟已启动")
                else:
                    st.warning("定时模拟未启动，请先启用并保存配置")
                st.rerun()
        with action_col3:
            if st.button("⏹️ 停止定时模拟", use_container_width=True):
                if scheduler.stop():
                    st.info("⏹️ 定时模拟已停止")
                else:
                    st.warning("定时模拟当前未运行")
                st.rerun()
        with action_col4:
            if st.button("💰 更新资金池", use_container_width=True):
                try:
                    portfolio_service.configure_account(initial_cash)
                except ValueError as exc:
                    st.error(f"更新失败：{exc}")
                else:
                    st.success("✅ 资金池已更新")
                    st.rerun()

    with st.form("quant_sim_add_manual_candidate"):
        col1, col2, col3, col4 = st.columns([1.1, 1.4, 1.1, 1.0])
        with col1:
            stock_code = st.text_input("股票代码", placeholder="如 600000")
        with col2:
            stock_name = st.text_input("股票名称", placeholder="如 浦发银行")
        with col3:
            source = st.selectbox(
                "来源策略",
                options=["manual", "main_force", "low_price_bull", "profit_growth", "value_stock", "small_cap"],
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
            summary = scheduler.run_once(run_reason="manual_scan")
            st.success(
                f"✅ 已扫描 {summary['candidates_scanned']} 只候选股，生成 {summary['signals_created']} 条信号，总权益 {summary['total_equity']:.2f}"
            )
            st.rerun()
    with col_refresh:
        if st.button("🔄 刷新页面", use_container_width=True):
            st.rerun()

    tab_candidates, tab_signals, tab_pending, tab_positions, tab_trades, tab_equity = st.tabs(
        ["📥 候选池", "🧠 策略信号", "⏳ 待执行", "💼 模拟持仓", "📒 成交记录", "📈 权益快照"]
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
                    sources = candidate.get("sources") or [candidate.get("source", "manual")]
                    st.write(f"来源策略：{' / '.join(_format_source(source) for source in sources)}")
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
                                try:
                                    portfolio_service.confirm_buy(
                                        signal["id"],
                                        price=price,
                                        quantity=int(quantity),
                                        note=note or "已手工买入",
                                    )
                                except ValueError as exc:
                                    st.error(f"执行失败：{exc}")
                                else:
                                    st.success("✅ 已更新模拟持仓")
                                    st.rerun()
                    else:
                        with col1:
                            if st.button("✅ 标记已卖出", key=f"confirm_sell_{signal['id']}"):
                                try:
                                    portfolio_service.confirm_sell(
                                        signal["id"],
                                        price=price,
                                        quantity=int(quantity),
                                        note=note or "已手工卖出",
                                    )
                                except ValueError as exc:
                                    st.error(f"执行失败：{exc}")
                                else:
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

    with tab_trades:
        trades = portfolio_service.get_trade_history(limit=100)
        if not trades:
            st.info("当前还没有成交记录。")
        else:
            st.dataframe(trades, use_container_width=True, hide_index=True)

    with tab_equity:
        snapshots = portfolio_service.get_account_snapshots(limit=100)
        if not snapshots:
            st.info("当前还没有权益快照，先运行一次分析或确认一次交易。")
        else:
            snapshot_df = pd.DataFrame(list(reversed(snapshots)))
            snapshot_df["created_at"] = pd.to_datetime(snapshot_df["created_at"])
            chart_df = snapshot_df.set_index("created_at")[["total_equity", "available_cash", "market_value"]]
            st.line_chart(chart_df, use_container_width=True)
            st.dataframe(snapshot_df, use_container_width=True, hide_index=True)


def _format_source(source: str) -> str:
    return {
        "manual": "手工加入",
        "main_force": "主力选股",
        "low_price_bull": "低价擒牛",
        "profit_growth": "净利增长",
        "value_stock": "低估值策略",
        "small_cap": "小市值策略",
    }.get(source, source)
