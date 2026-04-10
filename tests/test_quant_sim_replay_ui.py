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
    assert "开始区间模拟" in ui_source
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

    assert "🕰️ 历史回放" in app_source
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
    assert "render_replay_status_panel" in replay_block
    assert "render_replay_run_overview_list" in replay_block
    assert "render_replay_run_detail_panel" in replay_block


def test_quant_replay_page_mentions_report_sections_and_delete_action():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    replay_block = ui_source.split("def display_quant_replay()", 1)[1]

    assert "回放总览" in replay_block
    assert "信号执行记录" in replay_block
    assert "每股持仓结果" in replay_block
    assert "成交明细" in replay_block
    assert "选择回放任务" in replay_block
    assert "删除回放任务" in replay_block
    assert "所有回放任务" in replay_block
    assert "当前回放任务" in replay_block
    assert "信号ID" in replay_block
    assert "成交ID" in replay_block
    assert "最近一次回放事件" not in replay_block
    assert "##### 最近事件" not in replay_block


def test_quant_replay_signal_table_uses_row_selection_for_detail_view():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    replay_block = ui_source.split("#### 信号执行记录", 1)[1]

    assert 'on_select="rerun"' in replay_block
    assert 'selection_mode="single-row"' in replay_block
    assert "点击表格中的任意一行查看详情" in replay_block
    assert "查看策略信号详情" not in replay_block
    assert '"详情": "点击行查看"' not in replay_block
