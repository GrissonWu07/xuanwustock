from pathlib import Path


def test_discovery_hub_aggregates_selector_views():
    source = Path("C:/Projects/githubs/aiagents-stock/discovery_hub_ui.py").read_text(encoding="utf-8")

    assert "发现股票" in source
    assert "主力选股" in source
    assert "低价擒牛" in source
    assert "小市值" in source
    assert "净利增长" in source
    assert "低估值" in source


def test_app_routes_discovery_hub_from_watchlist_flow():
    source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")

    assert "show_discovery_hub" in source
    assert "display_discovery_hub" in source
