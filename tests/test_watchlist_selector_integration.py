import pandas as pd

from watchlist_selector_integration import (
    add_stock_to_watchlist,
    sync_selector_dataframe_to_watchlist,
)
from watchlist_service import WatchlistService


def test_add_stock_to_watchlist_creates_watch_entry(tmp_path):
    db_file = tmp_path / "watchlist.db"

    success, message, watch_id = add_stock_to_watchlist(
        stock_code="300390.SZ",
        stock_name="天华新能",
        source="main_force",
        latest_price=61.99,
        notes="主力选股",
        metadata={"industry": "新能源"},
        db_file=db_file,
    )

    service = WatchlistService(db_file=db_file)
    row = service.get_watch("300390")

    assert success is True
    assert "已加入关注池" in message
    assert watch_id > 0
    assert row is not None
    assert row["stock_code"] == "300390"
    assert row["stock_name"] == "天华新能"
    assert row["latest_price"] == 61.99
    assert "main_force" in row["sources"]


def test_sync_selector_dataframe_to_watchlist_adds_rows_and_merges_sources(tmp_path):
    db_file = tmp_path / "watchlist.db"
    service = WatchlistService(db_file=db_file)
    service.add_stock(
        stock_code="002824",
        stock_name="和胜股份",
        source="manual",
        latest_price=22.10,
        notes="手工添加",
        metadata={"industry": "消费电子"},
    )

    stocks_df = pd.DataFrame(
        [
            {
                "股票代码": "002824.SZ",
                "股票简称": "和胜股份",
                "最新价": 22.97,
                "所属行业": "消费电子",
            },
            {
                "股票代码": "301291.SZ",
                "股票简称": "明阳电气",
                "最新价": 52.96,
                "所属行业": "电气设备",
            },
        ]
    )

    summary = sync_selector_dataframe_to_watchlist(
        stocks_df=stocks_df,
        source="main_force",
        note_prefix="主力选股",
        db_file=db_file,
    )

    watchlist = {row["stock_code"]: row for row in service.list_watches()}

    assert summary == {"attempted": 2, "success_count": 2, "failures": []}
    assert set(watchlist) == {"002824", "301291"}
    assert set(watchlist["002824"]["sources"]) == {"manual", "main_force"}
    assert watchlist["002824"]["latest_price"] == 22.97
    assert watchlist["301291"]["stock_name"] == "明阳电气"
