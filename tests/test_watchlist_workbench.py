from pathlib import Path


def test_app_home_uses_watchlist_workbench():
    source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")
    assert "display_watchlist_workbench" in source
    assert "股票工作台" in source


def test_watchlist_ui_mentions_watchlist_stock_analysis_and_next_steps():
    source = Path("C:/Projects/githubs/aiagents-stock/watchlist_ui.py").read_text(encoding="utf-8")
    assert "关注池" in source
    assert "股票分析" in source
    assert "持仓分析" in source
    assert "实时监控" in source
    assert "AI盯盘" in source
    assert "量化模拟" in source
    assert "历史回放" in source
