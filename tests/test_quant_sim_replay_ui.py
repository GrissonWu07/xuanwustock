from datetime import date, datetime, time
from pathlib import Path

from streamlit_flash import consume_flash_messages
from quant_sim import ui


class DummyReplayService:
    def __init__(self):
        self.calls = []

    def run_historical_range(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "run_id": 7,
            "status": "completed",
            "trade_count": 4,
            "checkpoint_count": 8,
            "total_return_pct": 6.25,
        }

    def run_past_to_live(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "run_id": 9,
            "status": "completed",
            "trade_count": 5,
            "checkpoint_count": 9,
            "total_return_pct": 7.5,
            "handoff_to_live": True,
        }


def test_handle_historical_replay_queues_success_feedback():
    state = {}
    replay_service = DummyReplayService()

    summary = ui.handle_historical_replay(
        replay_service,
        start_datetime="2026-01-01 00:00:00",
        end_datetime="2026-01-31 15:00:00",
        timeframe="1d",
        market="CN",
        state=state,
    )
    flashes = consume_flash_messages(state, ui.QUANT_SIM_FLASH_NAMESPACE)

    assert summary["run_id"] == 7
    assert replay_service.calls == [
        {
            "start_datetime": "2026-01-01 00:00:00",
            "end_datetime": "2026-01-31 15:00:00",
            "timeframe": "1d",
            "market": "CN",
        }
    ]
    assert flashes == [
        {
            "level": "success",
            "message": "✅ 历史区间模拟完成：8 个检查点，4 笔交易，收益率 6.25%",
        }
    ]


def test_handle_historical_replay_allows_open_ended_end_datetime():
    state = {}
    replay_service = DummyReplayService()

    summary = ui.handle_historical_replay(
        replay_service,
        start_datetime="2026-01-01 00:00:00",
        end_datetime=None,
        timeframe="1d",
        market="CN",
        state=state,
    )
    flashes = consume_flash_messages(state, ui.QUANT_SIM_FLASH_NAMESPACE)

    assert summary["run_id"] == 7
    assert replay_service.calls == [
        {
            "start_datetime": "2026-01-01 00:00:00",
            "end_datetime": None,
            "timeframe": "1d",
            "market": "CN",
        }
    ]
    assert flashes[0]["level"] == "success"


def test_handle_continuous_replay_queues_success_feedback():
    state = {}
    replay_service = DummyReplayService()

    summary = ui.handle_continuous_replay(
        replay_service,
        start_datetime="2026-01-01 00:00:00",
        end_datetime="2026-01-31 15:00:00",
        timeframe="1d",
        market="CN",
        overwrite_live=True,
        auto_start_scheduler=False,
        state=state,
    )
    flashes = consume_flash_messages(state, ui.QUANT_SIM_FLASH_NAMESPACE)

    assert summary["run_id"] == 9
    assert replay_service.calls == [
        {
            "start_datetime": "2026-01-01 00:00:00",
            "end_datetime": "2026-01-31 15:00:00",
            "timeframe": "1d",
            "market": "CN",
            "overwrite_live": True,
            "auto_start_scheduler": False,
        }
    ]
    assert flashes == [
        {
            "level": "success",
            "message": "✅ 连续模拟完成：9 个检查点，5 笔交易，收益率 7.50%，已接入实时模拟账户。",
        }
    ]


def test_handle_continuous_replay_allows_open_ended_end_datetime():
    state = {}
    replay_service = DummyReplayService()

    summary = ui.handle_continuous_replay(
        replay_service,
        start_datetime="2026-01-01 00:00:00",
        end_datetime=None,
        timeframe="1d",
        market="CN",
        overwrite_live=True,
        auto_start_scheduler=False,
        state=state,
    )
    flashes = consume_flash_messages(state, ui.QUANT_SIM_FLASH_NAMESPACE)

    assert summary["run_id"] == 9
    assert replay_service.calls == [
        {
            "start_datetime": "2026-01-01 00:00:00",
            "end_datetime": None,
            "timeframe": "1d",
            "market": "CN",
            "overwrite_live": True,
            "auto_start_scheduler": False,
        }
    ]
    assert flashes[0]["level"] == "success"


def test_build_replay_datetime_preserves_time_component():
    assert ui.build_replay_datetime(date(2026, 1, 5), time(10, 30)) == datetime(2026, 1, 5, 10, 30)


def test_quant_sim_ui_exposes_replay_controls_and_results_copy():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")

    assert "历史区间回放" in ui_source
    assert "开始日期" in ui_source
    assert "结束日期" in ui_source
    assert "开始时间" in ui_source
    assert "结束时间" in ui_source
    assert "结束时间留空则回放到当前时刻" in ui_source
    assert 'replay_button_label = "回放"' in ui_source
    assert "回放结果" in ui_source
    assert "从过去接续到实时自动模拟" in ui_source
    assert '"回放粒度"' in ui_source
    assert '"30m"' in ui_source
    assert '"1d+30m"' in ui_source


def test_quant_sim_ui_defaults_replay_timeframe_to_30m():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")

    assert 'options=["30m", "1d", "1d+30m"]' in ui_source


def test_quant_sim_replay_start_does_not_force_extra_rerun():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    start_block = ui_source.split('key="quant_sim_run_replay"', 1)[1].split("def render_replay_results", 1)[0]

    assert "st.rerun()" not in start_block


def test_app_navigation_exposes_quant_replay_page():
    app_source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")

    assert '"label": "历史回放"' in app_source
    assert '"key": "nav_quant_replay"' in app_source
    assert "show_quant_replay" in app_source


def test_quant_sim_page_no_longer_contains_replay_section():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    quant_sim_block = ui_source.split("def display_quant_sim()", 1)[1].split("def display_quant_replay()", 1)[0]

    assert "历史区间回放" not in quant_sim_block


def test_quant_replay_page_exposes_direct_configuration_without_expander():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    replay_block = ui_source.split("def display_quant_replay()", 1)[1]

    assert "开始日期" in replay_block
    assert "开始时间" in replay_block
    assert "回放模式" in replay_block
    assert "策略模式" in replay_block
    assert 'with st.expander("🕰️ 历史区间回放"' not in replay_block


def test_quant_replay_page_uses_same_two_column_layout_style_as_realtime():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    replay_block = ui_source.split("def display_quant_replay()", 1)[1].split("def render_replay_configuration", 1)[0]

    assert "render_quant_sim_layout_styles()" in replay_block
    assert 'st.columns([1.0, 2.25], gap="large")' in replay_block
    assert "render_replay_candidate_pool_summary" in replay_block
    assert "render_replay_status_panel" in replay_block
    assert "render_replay_run_overview_list" in replay_block
    assert "render_replay_run_detail_panel" in replay_block


def test_quant_replay_page_exposes_read_only_candidate_pool_summary():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    replay_block = ui_source.split("def display_quant_replay()", 1)[1]

    assert "### 量化候选池" in replay_block
    assert "股票代码" in replay_block
    assert "股票名称" in replay_block
    assert "最新价格" in replay_block
    assert "先在工作台的“我的关注”里挑选股票，再推进到共享量化候选池。" in replay_block


def test_quant_replay_page_mentions_report_sections_and_delete_action():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    replay_block = ui_source.split("def display_quant_replay()", 1)[1]

    assert "回放总览" in replay_block
    assert "信号执行记录" in replay_block
    assert "每股持仓结果" in replay_block
    assert "成交明细" in replay_block
    assert "选择回放任务" in replay_block
    assert 'st.button("删除"' in replay_block
    assert "所有回放任务" in replay_block
    assert "当前回放任务" in replay_block
    assert "信号ID" in replay_block
    assert "成交ID" in replay_block
    assert "最近一次回放事件" not in replay_block
    assert "##### 最近事件" not in replay_block


def test_quant_replay_page_uses_compact_trade_analysis_cards():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    replay_block = ui_source.split("def display_quant_replay()", 1)[1]

    assert "render_replay_trade_analysis_cards(" in replay_block
    assert "quant-sim-trade-analysis-grid" in ui_source


def test_quant_replay_signal_table_uses_row_selection_for_detail_view():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    replay_block = ui_source.split("#### 信号执行记录", 1)[1]

    assert 'on_select="rerun"' in replay_block
    assert 'selection_mode="single-row"' in replay_block
    assert "点击表格中的任意一行查看详情" in replay_block
    assert "查看策略信号详情" not in replay_block
    assert '"详情": "点击行查看"' not in replay_block


def test_sidebar_navigation_uses_grouped_cards_instead_of_expanders():
    app_source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")
    sidebar_block = app_source.split("with st.sidebar:", 1)[1].split("# 检查是否显示历史记录", 1)[0]

    assert "render_sidebar_navigation()" in app_source
    assert 'with st.expander("🎯 选股板块"' not in sidebar_block
    assert 'with st.expander("📊 策略分析"' not in sidebar_block
    assert 'with st.expander("💼 投资管理"' not in sidebar_block


def test_sidebar_navigation_removes_current_model_block():
    app_source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")
    sidebar_block = app_source.split("with st.sidebar:", 1)[1].split("# 检查是否显示历史记录", 1)[0]

    assert "show_current_model_info()" not in app_source
    assert "当前模型:" not in sidebar_block
    assert "🤖 AI模型" not in sidebar_block


def test_sidebar_navigation_exposes_card_group_css_helpers():
    app_source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")

    assert "render_sidebar_nav_styles" in app_source
    assert "sidebar-nav-card" in app_source
    assert "sidebar-nav-item" in app_source
    assert "sidebar-nav-item active" in app_source or "sidebar-nav-item active" in app_source.replace("'", '"')


def test_sidebar_navigation_lists_all_expected_groups_and_destinations():
    app_source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")

    for label in ["选股", "策略", "投资管理", "系统"]:
        assert label in app_source
    for destination in [
        "主力选股",
        "低价擒牛",
        "小市值策略",
        "净利增长",
        "低估值策略",
        "智策板块",
        "智瞰龙虎",
        "新闻流量",
        "宏观分析",
        "宏观周期",
        "持仓分析",
        "量化模拟",
        "历史回放",
        "AI盯盘",
        "实时监测",
        "历史记录",
        "环境配置",
    ]:
        assert destination in app_source


def test_app_uses_unified_workbench_page_header_copy():
    app_source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")

    assert "render_workbench_page_header" in app_source
    assert ".workbench-shell" in app_source
    assert ".top-nav" not in app_source


def test_quant_sim_and_replay_use_shared_layout_helpers():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")

    assert "render_quant_sim_layout_styles()" in ui_source
    assert "render_workspace_section_header(" in ui_source
    assert "render_workspace_metric_band(" in ui_source


def test_home_page_uses_single_stock_analysis_module_without_result_workbench_panel():
    app_source = Path("C:/Projects/githubs\\aiagents-stock/app.py").read_text(encoding="utf-8")

    assert "股票分析" in app_source
    assert "分析工作区" not in app_source
    assert "统一结果工作台" not in app_source
    assert "选择分析师团队" not in app_source
    assert "分析师团队" in app_source


def test_home_page_orders_analysts_before_mode_before_stock_input():
    app_source = Path("C:/Projects/githubs\\aiagents-stock/app.py").read_text(encoding="utf-8")

    analysts_index = app_source.index("#### 👥 分析师团队")
    mode_index = app_source.index('analysis_mode = st.radio(')
    input_index = app_source.index('stock_input = st.text_input(')
    analyze_index = app_source.index('analyze_button = st.button("分析"')

    assert analysts_index < mode_index < input_index < analyze_index


def test_home_page_no_longer_includes_quickstart_reference_blocks():
    app_source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")

    assert "show_example_interface" not in app_source
    assert "快速上手" not in app_source
    assert "如何使用" not in app_source
    assert "分析维度" not in app_source
    assert "示例股票代码" not in app_source
    assert "市场支持说明" not in app_source


def test_home_header_and_beginner_tip_no_longer_render_before_page_routing():
    app_source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")
    main_block = app_source.split("def main():", 1)[1].split("# 检查是否显示历史记录", 1)[0]

    assert "render_workbench_page_header(" not in main_block
    assert "新手必看干货" not in main_block


def test_global_button_style_no_longer_uses_heavy_purple_gradient_cta():
    app_source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")

    assert ".stButton>button[kind=\"primary\"]" in app_source
    assert ".stButton>button[kind=\"secondary\"]" in app_source
    assert "linear-gradient(135deg, #667eea 0%, #764ba2 100%)" not in app_source


def test_home_page_header_no_longer_renders_placeholder_actions():
    app_source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")

    assert 'secondary_action_label="演示模式"' not in app_source
    assert 'primary_action_label="开始分析"' not in app_source
