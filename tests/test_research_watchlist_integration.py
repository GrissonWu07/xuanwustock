from research_watchlist_integration import (
    add_research_stock_to_watchlist,
    add_research_stocks_to_watchlist,
)
from watchlist_service import WatchlistService


def test_add_research_stock_to_watchlist_accepts_code_name_shape(tmp_path):
    db_file = tmp_path / "watchlist.db"

    success, message, watch_id = add_research_stock_to_watchlist(
        stock={
            "code": "301291",
            "name": "明阳电气",
            "price": 52.96,
            "sector": "电气设备",
            "reason": "资金关注度高",
        },
        source="longhubang",
        db_file=db_file,
    )

    service = WatchlistService(db_file=db_file)
    row = service.get_watch("301291")

    assert success is True
    assert "已加入关注池" in message
    assert watch_id > 0
    assert row["stock_name"] == "明阳电气"
    assert row["latest_price"] == 52.96
    assert row["metadata"]["industry"] == "电气设备"


def test_add_research_stocks_to_watchlist_accepts_mixed_shapes(tmp_path):
    db_file = tmp_path / "watchlist.db"
    service = WatchlistService(db_file=db_file)

    summary = add_research_stocks_to_watchlist(
        stocks=[
            {
                "code": "301291",
                "name": "明阳电气",
                "price": 52.96,
                "sector": "电气设备",
            },
            {
                "股票代码": "002824",
                "股票名称": "和胜股份",
                "最新价": 22.97,
                "所属行业": "消费电子",
            },
        ],
        source="macro_analysis",
        db_file=db_file,
    )

    watchlist = {row["stock_code"]: row for row in service.list_watches()}

    assert summary == {"attempted": 2, "success_count": 2, "failures": []}
    assert set(watchlist) == {"301291", "002824"}
    assert watchlist["002824"]["metadata"]["industry"] == "消费电子"
