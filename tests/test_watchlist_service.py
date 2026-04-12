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


def test_watchlist_service_add_manual_stock_skips_slow_name_resolution(tmp_path):
    resolver_calls = []
    service = WatchlistService(
        db_file=tmp_path / "watchlist.db",
        stock_name_resolver=lambda code: resolver_calls.append(code) or "天华新能",
    )

    summary = service.add_manual_stock("300390")
    watch = service.get_watch("300390")

    assert summary["created"] is True
    assert summary["watch_id"] > 0
    assert summary["stock_name"] == "300390"
    assert watch["stock_name"] == "300390"
    assert watch["source_summary"] == "manual"
    assert resolver_calls == []


def test_watchlist_service_refresh_quotes_updates_latest_price_and_name(tmp_path):
    quote_calls = []
    service = WatchlistService(
        db_file=tmp_path / "watchlist.db",
        quote_fetcher=lambda code, preferred_name=None: quote_calls.append((code, preferred_name)) or {
            "current_price": 62.35,
            "name": "天华新能",
        },
    )

    service.add_manual_stock("300390")
    summary = service.refresh_quotes()
    watch = service.get_watch("300390")

    assert summary["attempted"] == 1
    assert summary["success_count"] == 1
    assert summary["failures"] == []
    assert quote_calls == [("300390", None)]
    assert watch["latest_price"] == 62.35
    assert watch["stock_name"] == "天华新能"


def test_watchlist_service_refresh_quotes_ignores_placeholder_name_when_fetching_quote(tmp_path):
    quote_calls = []
    service = WatchlistService(
        db_file=tmp_path / "watchlist.db",
        quote_fetcher=lambda code, preferred_name=None: quote_calls.append((code, preferred_name)) or {
            "current_price": 1453.96,
            "name": "贵州茅台",
        },
    )

    service.add_stock(stock_code="600519", stock_name="N/A", source="manual")
    summary = service.refresh_quotes()
    watch = service.get_watch("600519")

    assert summary["success_count"] == 1
    assert quote_calls == [("600519", None)]
    assert watch["stock_name"] == "贵州茅台"
