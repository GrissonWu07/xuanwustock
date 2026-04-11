from watchlist_service import WatchlistService


def test_watchlist_service_add_from_selector_row(tmp_path):
    service = WatchlistService(db_file=tmp_path / "watchlist.db")

    summary = service.add_stock(
        stock_code="002824",
        stock_name="和胜股份",
        source="main_force",
        latest_price=22.97,
        notes="来自主力选股",
        metadata={"industry": "消费电子"},
    )

    assert summary["created"] is True
    assert summary["watch_id"] > 0
    assert service.get_watch("002824")["stock_name"] == "和胜股份"


def test_watchlist_service_batch_add_returns_attempt_summary(tmp_path):
    service = WatchlistService(db_file=tmp_path / "watchlist.db")

    result = service.add_many(
        [
            {"stock_code": "002824", "stock_name": "和胜股份", "source": "main_force"},
            {"stock_code": "301291", "stock_name": "明阳电气", "source": "main_force"},
        ]
    )

    assert result["attempted"] == 2
    assert result["success_count"] == 2
    assert result["failures"] == []
