from datetime import date
from datetime import datetime
from pathlib import Path

from streamlit_flash import consume_flash_messages
from quant_sim import ui
from quant_sim.db import QuantSimDB


class DummyScheduler:
    def __init__(self):
        self.config_updates = []
        self.started = False
        self.stopped = False
        self.last_run_reason = None

    def run_once(self, run_reason="scheduled_scan"):
        self.last_run_reason = run_reason
        return {
            "candidates_scanned": 3,
            "signals_created": 2,
            "positions_checked": 1,
            "auto_executed": 1,
            "total_equity": 100321.5,
        }

    def update_config(self, **kwargs):
        self.config_updates.append(kwargs)

    def start(self):
        self.started = True
        return True

    def stop(self):
        self.stopped = True
        return True


class DummyPortfolioService:
    def __init__(self):
        self.updated_cash = None
        self.confirmed_buy = None
        self.reset_cash = None

    def configure_account(self, initial_cash):
        self.updated_cash = initial_cash

    def reset_account(self, initial_cash=None):
        self.reset_cash = initial_cash

    def confirm_buy(self, signal_id, price, quantity, note):
        self.confirmed_buy = {
            "signal_id": signal_id,
            "price": price,
            "quantity": quantity,
            "note": note,
        }


def test_handle_manual_scan_queues_success_flash_message():
    state = {}
    scheduler = DummyScheduler()

    summary = ui.handle_manual_scan(scheduler, state=state)
    flashes = consume_flash_messages(state, ui.QUANT_SIM_FLASH_NAMESPACE)

    assert scheduler.last_run_reason == "manual_scan"
    assert summary["signals_created"] == 2
    assert flashes == [
        {
            "level": "success",
            "message": "✅ 已扫描 3 只候选股，生成 2 条信号，自动执行 1 条，总权益 100321.50",
        }
    ]


def test_handle_scheduler_start_queues_feedback_and_updates_config():
    state = {}
    scheduler = DummyScheduler()

    started = ui.handle_scheduler_start(
        scheduler,
        enabled=True,
        auto_execute=True,
        interval_minutes=15,
        trading_hours_only=True,
        analysis_timeframe="30m",
        start_date="2026-04-10",
        market="CN",
        state=state,
    )
    flashes = consume_flash_messages(state, ui.QUANT_SIM_FLASH_NAMESPACE)

    assert started is True
    assert scheduler.started is True
    assert scheduler.config_updates == [
        {
            "enabled": True,
            "auto_execute": True,
            "interval_minutes": 15,
            "trading_hours_only": True,
            "analysis_timeframe": "30m",
            "start_date": "2026-04-10",
            "market": "CN",
        }
    ]
    assert flashes == [{"level": "success", "message": "✅ 定时分析已启动"}]


def test_handle_account_update_queues_success_flash_message():
    state = {}
    portfolio_service = DummyPortfolioService()

    ui.handle_account_update(portfolio_service, 200000.0, state=state)
    flashes = consume_flash_messages(state, ui.QUANT_SIM_FLASH_NAMESPACE)

    assert portfolio_service.updated_cash == 200000.0
    assert flashes == [{"level": "success", "message": "✅ 资金池已更新"}]


def test_handle_account_reset_queues_success_flash_message():
    state = {}
    portfolio_service = DummyPortfolioService()

    ui.handle_account_reset(portfolio_service, 150000.0, state=state)
    flashes = consume_flash_messages(state, ui.QUANT_SIM_FLASH_NAMESPACE)

    assert portfolio_service.reset_cash == 150000.0
    assert flashes == [{"level": "success", "message": "✅ 已重置模拟账户并重建资金池"}]


def test_quant_sim_ui_exposes_single_scheduler_control_area():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")

    assert 'key="quant_sim_start_scheduler_top"' not in ui_source
    assert 'key="quant_sim_scan_now"' not in ui_source
    assert 'key="quant_sim_manual_scan_config"' not in ui_source
    assert "⏹️ 停止定时分析" in ui_source


def test_quant_sim_ui_no_longer_hides_realtime_controls_in_expander():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    realtime_block = ui_source.split("def display_quant_sim()", 1)[1].split("def display_quant_replay()", 1)[0]

    assert 'with st.expander("⚙️ 定时分析设置与资金池"' not in realtime_block


def test_quant_sim_ui_exposes_realtime_strategy_mode_and_auto_execution_copy():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    realtime_block = ui_source.split("def display_quant_sim()", 1)[1].split("def display_quant_replay()", 1)[0]

    assert "策略模式" in realtime_block
    assert "自动执行模拟交易" in realtime_block
    assert "不需要等待用户确认" in realtime_block
    assert "待执行信号" in realtime_block


def test_quant_sim_candidate_section_exposes_add_delete_and_inline_analyze_actions():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    realtime_block = ui_source.split("def display_quant_sim()", 1)[1].split("def display_quant_replay()", 1)[0]

    assert "➕ 添加股票" in realtime_block
    assert "删除" in realtime_block
    assert "立即分析该标的" not in realtime_block


def test_quant_sim_candidate_section_mentions_inline_analysis_detail_panel():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    realtime_block = ui_source.split("def display_quant_sim()", 1)[1].split("def display_quant_replay()", 1)[0]

    assert "候选股分析详情" in realtime_block
    assert "@st.dialog" in ui_source
    assert "render_quant_sim_inline_candidate_detail()" not in realtime_block


def test_quant_sim_candidate_analysis_detail_reuses_full_strategy_explanation_panel():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    realtime_block = ui_source.split("def display_quant_sim()", 1)[1].split("def display_quant_replay()", 1)[0]

    assert "render_quant_sim_candidate_analysis_dialog()" in realtime_block
    assert "当前交易策略" in ui_source
    assert "render_quant_sim_signal_detail(selected_signal)" in ui_source


def test_quant_sim_config_panel_exposes_update_and_reset_account_actions():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    realtime_block = ui_source.split("def display_quant_sim()", 1)[1].split("def display_quant_replay()", 1)[0]

    assert "💰 更新资金池" in realtime_block
    assert "🔄 重置模拟账户" in realtime_block


def test_quant_sim_realtime_ui_uses_b3_switching_layout_instead_of_legacy_six_tabs():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    realtime_block = ui_source.split("def display_quant_sim()", 1)[1].split("def display_quant_replay()", 1)[0]

    assert '["📥 候选池", "🧠 策略信号", "⏳ 待执行", "💼 模拟持仓", "📒 成交记录", "📈 权益快照"]' not in realtime_block
    assert "执行中心" in realtime_block
    assert "账户结果" in realtime_block
    assert "查看内容" in realtime_block
    assert 'options=["执行中心", "账户结果"]' in realtime_block


def test_quant_sim_realtime_ui_avoids_workspace_placeholder_labels():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    realtime_block = ui_source.split("def display_quant_sim()", 1)[1].split("def display_quant_replay()", 1)[0]

    assert "主工作区" not in realtime_block
    assert "工作区" not in realtime_block


def test_quant_sim_scheduler_buttons_use_explicit_keys():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")

    assert 'key="quant_sim_stop_scheduler_config"' in ui_source
    assert 'key="quant_sim_manual_scan_config"' not in ui_source
    assert 'key="quant_sim_scheduler_start_date"' in ui_source


def test_quant_sim_replay_ui_exposes_background_status_and_cancel_controls():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")

    assert "当前回放状态" in ui_source
    assert "取消回放任务" in ui_source


def test_quant_sim_replay_results_expose_latest_status():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")

    assert "任务信息" in ui_source


def test_quant_sim_replay_results_expose_report_sections():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")

    assert "回放总览" in ui_source
    assert "结束持仓" in ui_source
    assert "交易分析" in ui_source
    assert "当前交易策略" in ui_source


def test_quant_sim_replay_ui_exposes_strategy_mode_options():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")

    assert "策略模式" in ui_source
    assert '"自动"' in ui_source
    assert '"激进"' in ui_source
    assert '"中性"' in ui_source
    assert '"稳健"' in ui_source


def test_reconcile_active_replay_run_marks_stale_background_job_failed(tmp_path, monkeypatch):
    db_file = tmp_path / "quant_sim.db"
    db = QuantSimDB(db_file)
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-01-01 09:30:00",
        end_datetime="2026-01-31 15:00:00",
        initial_cash=100000.0,
        status="running",
        progress_current=12,
        progress_total=100,
        status_message="执行中",
    )
    db.replace_sim_run_results(
        run_id,
        trades=[],
        snapshots=[
            {
                "initial_cash": 100000.0,
                "available_cash": 91234.0,
                "market_value": 5234.0,
                "total_equity": 96468.0,
                "realized_pnl": -3000.0,
                "unrealized_pnl": -532.0,
                "created_at": "2026-01-10 10:30:00",
            }
        ],
        positions=[],
        signals=[],
    )

    conn = db._connect()  # noqa: SLF001 - targeted stale-run regression coverage
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE sim_runs SET updated_at = ?, latest_checkpoint_at = ? WHERE id = ?",
        ("2026-01-10 10:30:00", "2026-01-10 10:30:00", run_id),
    )
    conn.commit()
    conn.close()

    class FakeRunner:
        def is_running(self, replay_run_id):
            assert replay_run_id == run_id
            return False

    monkeypatch.setattr(ui, "get_quant_sim_replay_runner", lambda db_file=None: FakeRunner())

    active_run = ui.reconcile_active_replay_run(
        db_file=str(db_file),
        now=datetime(2026, 1, 10, 10, 40, 0),
    )

    assert active_run is not None
    assert active_run["status"] == "failed"
    assert "停止响应" in str(active_run["status_message"])
    events = db.get_sim_run_events(run_id, limit=5)
    assert any("停止响应" in str(event["message"]) for event in events)


def test_build_scheduler_status_message_distinguishes_running_and_idle_states():
    running_level, running_message = ui.build_scheduler_status_message(
        {
            "running": True,
            "enabled": True,
            "auto_execute": True,
            "interval_minutes": 15,
            "analysis_timeframe": "30m",
            "start_date": "2026-04-10",
            "last_run_at": "2026-04-09 15:00:00",
            "next_run": "2026-04-09 15:15:00",
        }
    )
    configured_level, configured_message = ui.build_scheduler_status_message(
        {
            "running": False,
            "enabled": True,
            "auto_execute": False,
            "interval_minutes": 15,
            "analysis_timeframe": "30m",
            "start_date": "2026-04-10",
            "last_run_at": None,
            "next_run": None,
        }
    )
    disabled_level, disabled_message = ui.build_scheduler_status_message(
        {
            "running": False,
            "enabled": False,
            "auto_execute": False,
            "interval_minutes": 15,
            "analysis_timeframe": "30m",
            "start_date": "2026-04-10",
            "last_run_at": None,
            "next_run": None,
        }
    )

    assert running_level == "success"
    assert "运行中" in running_message
    assert "15 分钟" in running_message
    assert "自动执行已开启" in running_message
    assert configured_level == "warning"
    assert "已配置" in configured_message
    assert "未启动" in configured_message
    assert "自动执行已关闭" in configured_message
    assert disabled_level == "info"
    assert "未启用" in disabled_message
    assert "2026-04-10" in running_message


def test_handle_scheduler_save_queues_feedback_and_updates_start_date():
    state = {}
    scheduler = DummyScheduler()

    ui.handle_scheduler_save(
        scheduler,
        enabled=True,
        auto_execute=False,
        interval_minutes=20,
        trading_hours_only=False,
        analysis_timeframe="1d+30m",
        start_date="2026-04-12",
        market="CN",
        state=state,
    )
    flashes = consume_flash_messages(state, ui.QUANT_SIM_FLASH_NAMESPACE)

    assert scheduler.config_updates == [
        {
            "enabled": True,
            "auto_execute": False,
            "interval_minutes": 20,
            "trading_hours_only": False,
            "analysis_timeframe": "1d+30m",
            "start_date": "2026-04-12",
            "market": "CN",
        }
    ]
    assert flashes == [{"level": "success", "message": "✅ 定时分析配置已保存"}]


def test_resolve_pending_signal_default_price_prefers_candidate_latest_price():
    candidate_service = type(
        "DummyCandidateService",
        (),
        {
            "db": type(
                "DummyCandidateDB",
                (),
                {"get_candidate": staticmethod(lambda stock_code: {"latest_price": 61.99})},
            )()
        },
    )()

    default_price = ui.resolve_pending_signal_default_price(
        {"stock_code": "300390"},
        candidate_service=candidate_service,
        portfolio_service=None,
    )

    assert default_price == 61.99


def test_handle_confirm_buy_queues_success_flash_message():
    state = {}
    portfolio_service = DummyPortfolioService()

    success = ui.handle_confirm_buy(
        portfolio_service,
        signal_id=12,
        price=61.99,
        quantity=100,
        note="已手工买入",
        state=state,
    )
    flashes = consume_flash_messages(state, ui.QUANT_SIM_FLASH_NAMESPACE)

    assert success is True
    assert portfolio_service.confirmed_buy == {
        "signal_id": 12,
        "price": 61.99,
        "quantity": 100,
        "note": "已手工买入",
    }
    assert flashes == [{"level": "success", "message": "✅ 已更新模拟持仓"}]


def test_render_action_badge_html_uses_buy_red_sell_green_hold_gray():
    buy_badge = ui.render_action_badge_html("BUY")
    sell_badge = ui.render_action_badge_html("SELL")
    hold_badge = ui.render_action_badge_html("HOLD")

    assert "#d94b4b" in buy_badge
    assert "BUY" in buy_badge
    assert "#1a9b5b" in sell_badge
    assert "SELL" in sell_badge
    assert "#6b7280" in hold_badge
    assert "HOLD" in hold_badge


def test_format_signal_expander_label_includes_visual_action_marker():
    assert ui.format_signal_expander_label({"action": "BUY", "stock_code": "300390", "stock_name": "天华新能"}) == "🔴 BUY | 300390 - 天华新能"
    assert ui.format_signal_expander_label({"action": "SELL", "stock_code": "301291", "stock_name": "明阳电气"}) == "🟢 SELL | 301291 - 明阳电气"


def test_build_action_button_style_css_uses_red_for_buy_and_green_for_sell():
    buy_css = ui.build_action_button_style_css("confirm_buy_12", "buy")
    sell_css = ui.build_action_button_style_css("confirm_sell_34", "sell")

    assert "#d94b4b" in buy_css
    assert "#fde8e8" in buy_css
    assert "#1a9b5b" in sell_css
    assert "#e8f7ee" in sell_css
    assert "confirm_buy_12_marker" in buy_css
    assert "confirm_sell_34_marker" in sell_css


def test_quant_sim_ui_exposes_auto_execution_controls_and_status_copy():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")

    assert "自动执行模拟交易" in ui_source
    assert "自动执行" in ui_source


def test_render_strategy_profile_summary_shows_strategy_basics():
    summary = ui.render_strategy_profile_summary(
        {
            "market_regime": {"label": "牛市", "score": 0.66},
            "fundamental_quality": {"label": "强基本面", "score": 0.58},
            "risk_style": {"label": "激进", "max_position_ratio": 0.8},
            "analysis_timeframe": {"key": "30m"},
            "effective_thresholds": {
                "buy_threshold": 0.64,
                "sell_threshold": -0.25,
                "max_position_ratio": 0.5,
            },
        }
    )

    assert "市场状态" in summary
    assert "基本面质量" in summary
    assert "当前风格" in summary
    assert "时间框架" in summary
    assert "建议仓位" in summary


def test_build_replay_report_payload_exposes_cash_positions_and_trade_analysis():
    payload = ui.build_replay_report_payload(
        run={
            "id": 4,
            "mode": "historical_range",
            "status": "completed",
            "timeframe": "30m",
            "market": "CN",
            "start_datetime": "2026-01-01 09:30:00",
            "end_datetime": "2026-01-31 15:00:00",
            "final_equity": 121552.0,
            "total_return_pct": 21.552,
            "max_drawdown_pct": 7.3259,
            "win_rate": 44.4444,
            "trade_count": 39,
            "status_message": "回放任务已完成",
        },
        snapshots=[
            {
                "initial_cash": 100000.0,
                "available_cash": 54330.0,
                "market_value": 67222.0,
                "total_equity": 121552.0,
                "realized_pnl": 18000.0,
                "unrealized_pnl": 3552.0,
                "created_at": "2026-01-31 15:00:00",
            }
        ],
        trades=[
            {
                "id": 21,
                "signal_id": 11,
                "action": "BUY",
                "amount": 30000.0,
                "realized_pnl": 0.0,
            },
            {
                "id": 22,
                "signal_id": 12,
                "action": "SELL",
                "amount": 35500.0,
                "realized_pnl": 5500.0,
            },
            {
                "id": 23,
                "signal_id": 13,
                "action": "SELL",
                "amount": 12000.0,
                "realized_pnl": -800.0,
            },
        ],
        positions=[
            {
                "stock_code": "300390",
                "stock_name": "天华新能",
                "quantity": 300,
                "avg_price": 61.99,
                "latest_price": 65.10,
                "market_value": 19530.0,
                "unrealized_pnl": 933.0,
                "sellable_quantity": 300,
                "locked_quantity": 0,
            }
        ],
        signals=[
            {
                "id": 11,
                "stock_code": "300390",
                "stock_name": "天华新能",
                "action": "BUY",
                "reasoning": "趋势共振",
                "strategy_profile": {
                    "market_regime": {"label": "牛市"},
                    "fundamental_quality": {"label": "强基本面"},
                    "risk_style": {"label": "激进"},
                    "analysis_timeframe": {"key": "30m"},
                    "effective_thresholds": {"buy_threshold": 0.64, "sell_threshold": 0.36},
                },
            }
        ],
        events=[{"message": "完成"}],
    )

    assert payload["initial_cash"] == 100000.0
    assert payload["final_available_cash"] == 54330.0
    assert payload["final_market_value"] == 67222.0
    assert payload["final_total_equity"] == 121552.0
    assert payload["ending_position_count"] == 1
    assert payload["trade_analysis"]["total_buy_amount"] == 30000.0
    assert payload["trade_analysis"]["total_sell_amount"] == 47500.0
    assert payload["trade_analysis"]["winning_trade_count"] == 1
    assert payload["trade_analysis"]["losing_trade_count"] == 1
    assert payload["strategy_signals"][0]["strategy_profile"]["risk_style"]["label"] == "激进"
    assert "详情" not in payload["strategy_signal_rows"][0]
    assert payload["strategy_signal_rows"][0]["信号ID"] == 11
    assert payload["strategy_signal_rows"][0]["成交ID"] == 21


def test_build_replay_signal_detail_summary_exposes_rich_strategy_context():
    summary = ui._build_replay_signal_detail_summary(  # noqa: SLF001 - targeted UI summary coverage
        {
            "reasoning": "趋势共振，量价配合改善。",
            "strategy_profile": {
                "strategy_mode": {"label": "自动", "key": "auto"},
                "market_regime": {"label": "牛市"},
                "fundamental_quality": {"label": "强基本面"},
                "risk_style": {"label": "激进"},
                "auto_inferred_risk_style": {"label": "激进"},
                "analysis_timeframe": {"key": "30m"},
                "effective_thresholds": {
                    "buy_threshold": 0.64,
                    "sell_threshold": 0.36,
                    "max_position_ratio": 0.5,
                    "confirmation": "30分钟信号确认",
                },
                "explainability": {
                    "tech_votes": [
                        {"factor": "MACD", "signal": "BUY", "score": 0.18, "reason": "MACD为正，动量改善。"},
                        {"factor": "RSI", "signal": "SELL", "score": -0.12, "reason": "RSI偏高，短线过热。"},
                    ],
                    "context_votes": [
                        {"component": "source_prior", "score": 0.28, "reason": "主力选股来源先验偏正向。"},
                        {"component": "liquidity", "score": -0.08, "reason": "量比偏低，资金跟随有限。"},
                    ],
                    "dual_track": {
                        "tech_signal": "BUY",
                        "context_signal": "BUY",
                        "resonance_type": "moderate_resonance",
                        "rule_hit": "resonance_standard",
                        "position_ratio": 0.5,
                    },
                },
            },
        }
    )

    assert "策略模式：自动" in summary
    assert "市场状态：牛市" in summary
    assert "基本面质量：强基本面" in summary
    assert "自动推导风格：激进" in summary
    assert "实际执行风格：激进" in summary
    assert "时间框架：30m" in summary
    assert "建议仓位：50.0%" in summary
    assert "确认机制：30分钟信号确认" in summary
    assert "技术投票：" in summary
    assert "MACD -> BUY (+0.18)" in summary
    assert "环境投票：" in summary
    assert "source_prior (+0.28)" in summary
    assert "双轨裁决：" in summary
    assert "BUY / BUY / resonance_standard" in summary
    assert "推理：趋势共振，量价配合改善。" in summary


def test_render_strategy_explainability_summary_reconstructs_legacy_signal_votes():
    legacy_signal = {
        "action": "HOLD",
        "reasoning": (
            "002824 来源策略为 main_force；价格 22.97，MA5/MA20/MA60 为 22.60/20.88/20.17，"
            "MACD 0.532，RSI12 90.63，量比 0.15。技术评分 0.58，上下文评分 0.52。 | ContextScore=+0.52"
        ),
        "created_at": "2026-04-10 15:00:00",
        "strategy_profile": {
            "market_regime": {"label": "牛市", "score": 0.62, "reason": "趋势=up，价格结构=22.97/20.88/20.17，MACD=0.532，量比=0.15"},
            "fundamental_quality": {"label": "中性", "score": 0.0, "reason": "成长=NA，ROE=NA，PE=NA，PB=NA"},
            "risk_style": {"label": "稳重", "max_position_ratio": 0.5, "reason": "市场状态=牛市，基本面质量=中性"},
            "analysis_timeframe": {"key": "30m"},
            "effective_thresholds": {
                "buy_threshold": 0.68,
                "sell_threshold": -0.22,
                "max_position_ratio": 0.5,
                "confirmation": "30分钟信号确认",
            },
        },
    }

    summary = ui.render_strategy_explainability_summary(
        legacy_signal["strategy_profile"],
        signal=legacy_signal,
    )

    assert "**技术投票**" in summary
    assert "均线结构" in summary
    assert "MACD" in summary
    assert "RSI" in summary
    assert "量比" in summary
    assert "**环境投票**" in summary
    assert "source_prior" in summary
    assert "trend_regime" in summary
    assert "price_structure" in summary
    assert "liquidity" in summary
    assert "**双轨裁决**" in summary
    assert "技术信号" in summary
    assert "环境信号" in summary
    assert "历史旧记录兼容重建" in summary
