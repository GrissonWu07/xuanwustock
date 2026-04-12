from pathlib import Path


def test_app_home_uses_watchlist_workbench():
    source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")
    assert "display_watchlist_workbench" in source
    assert "股票工作台" in source


def test_watchlist_ui_mentions_watchlist_stock_analysis_and_next_steps():
    source = Path("C:/Projects/githubs/aiagents-stock/watchlist_ui.py").read_text(encoding="utf-8")
    assert "我的关注" in source
    assert "持仓分析" in source
    assert "实时监控" in source
    assert "AI盯盘" in source
    assert "量化模拟" in source
    assert "历史回放" in source
    assert "_render_next_step_item" in source
    assert "watchlist-next-step" in source


def test_watchlist_ui_uses_wider_primary_layout_and_manual_code_only_input():
    source = Path("C:/Projects/githubs/aiagents-stock/watchlist_ui.py").read_text(encoding="utf-8")
    assert "st.columns([2.8, 0.9]" in source
    assert 'st.text_input("股票代码"' in source
    assert 'add_manual_stock' in source
    assert 'st.text_input("股票名称"' not in source
    assert 'st.text_input("来源"' not in source


def test_watchlist_ui_supports_watchlist_to_quant_actions_without_watchlist_analysis_controls():
    source = Path("C:/Projects/githubs/aiagents-stock/watchlist_ui.py").read_text(encoding="utf-8")
    assert "watchlist_row_add_quant_" in source
    assert "watchlist_row_delete_" in source
    assert "watchlist_bulk_add_quant" in source
    assert "watchlist_bulk_clear_selection" in source
    assert "watchlist_refresh_quotes" in source
    assert "watchlist_select_all_header" in source
    assert "watchlist_select_" in source
    assert "watchlist_row_analyze_" not in source
    assert "watchlist_row_remove_quant_" not in source
    assert "watchlist_bulk_remove_quant" not in source
    assert "选择关注股票" not in source
    assert "_render_watchlist_icon_button" in source
    assert '_render_watchlist_icon_button("↻"' in source
    assert '_render_watchlist_icon_button("🧪"' in source
    assert '_render_watchlist_icon_button("✕"' in source
    assert '_render_watchlist_icon_button("🗑"' in source
    assert "watchlist-icon-trigger" not in source
    assert "watchlist-toolbar-shell" not in source


def test_watchlist_ui_uses_select_all_callback_instead_of_pre_render_reset():
    source = Path("C:/Projects/githubs/aiagents-stock/watchlist_ui.py").read_text(encoding="utf-8")

    assert "_toggle_watchlist_select_all" in source
    assert 'on_change=_toggle_watchlist_select_all' in source
    assert 'watchlist_select_all_manual' in source
    assert 'st.session_state.get(header_key) != all_selected' not in source
