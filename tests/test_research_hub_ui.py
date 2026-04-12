from pathlib import Path


def test_research_hub_aggregates_intelligence_views():
    source = Path("C:/Projects/githubs/aiagents-stock/research_hub_ui.py").read_text(encoding="utf-8")

    assert "研究情报" in source
    assert "智策板块" in source
    assert "智瞰龙虎" in source
    assert "新闻流量" in source
    assert "宏观分析" in source
    assert "宏观周期" in source


def test_app_routes_research_hub_from_watchlist_flow():
    source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")

    assert "show_research_hub" in source
    assert "display_research_hub" in source
