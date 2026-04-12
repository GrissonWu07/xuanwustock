from pathlib import Path


def test_main_force_history_entry_is_not_rendered_in_page_header():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/main_force_ui.py").read_text(encoding="utf-8")

    assert 'col_title, col_history = st.columns([4, 1])' not in ui_source
    assert 'if st.button("📚 批量分析历史", width=\'content\')' not in ui_source
    assert 'if st.button("📚 查看历史", key="main_force_view_history_inline", use_container_width=True):' in ui_source


def test_main_force_recent_results_are_rendered_before_long_strategy_description():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/main_force_ui.py").read_text(encoding="utf-8")

    assert ui_source.index('if current_result and current_result.get("success"):') > ui_source.index('if st.button("🚀 开始主力选股"')


def test_main_force_candidate_list_supports_watchlist_sync():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/main_force_ui.py").read_text(encoding="utf-8")

    assert "sync_selector_dataframe_to_watchlist" in ui_source
    assert 'main_force_candidate_editor' in ui_source
    assert 'main_force_candidate_watchlist_selected_button' in ui_source
    assert 'main_force_candidate_watchlist_sync' in ui_source


def test_main_force_candidate_list_is_rendered_before_ai_analyst_reports():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/main_force_ui.py").read_text(encoding="utf-8")

    assert ui_source.index('main_force_batch_watchlist_sync_button') < ui_source.index('### 📋 候选股票列表（筛选后）')
    assert ui_source.index('### 📋 候选股票列表（筛选后）') < ui_source.index('### ⭐ 精选推荐')
    assert ui_source.index('### ⭐ 精选推荐') < ui_source.index('### 🤖 AI分析师团队完整报告')
