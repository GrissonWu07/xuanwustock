from watchlist_db import WatchlistDB


def test_watchlist_db_adds_and_lists_entries(tmp_path):
    db = WatchlistDB(tmp_path / "watchlist.db")

    watch_id = db.add_watch(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        latest_price=61.99,
        notes="主力选股第1名",
        metadata={"industry": "新能源"},
    )

    rows = db.list_watches()

    assert watch_id > 0
    assert len(rows) == 1
    assert rows[0]["stock_code"] == "300390"
    assert rows[0]["stock_name"] == "天华新能"
    assert rows[0]["source_summary"] == "main_force"
    assert rows[0]["latest_price"] == 61.99


def test_watchlist_db_merges_existing_stock_sources(tmp_path):
    db = WatchlistDB(tmp_path / "watchlist.db")
    db.add_watch("300390", "天华新能", "main_force", 61.99, None, {})
    db.add_watch("300390", "天华新能", "macro_analysis", 62.31, None, {})

    row = db.get_watch("300390")

    assert row["stock_code"] == "300390"
    assert row["latest_price"] == 62.31
    assert set(row["sources"]) == {"main_force", "macro_analysis"}


def test_watchlist_db_marks_quant_membership(tmp_path):
    db = WatchlistDB(tmp_path / "watchlist.db")
    db.add_watch("300390", "天华新能", "manual", 61.99, None, {})

    db.update_quant_membership("300390", True)
    row = db.get_watch("300390")
    assert row["in_quant_pool"] is True

    db.update_quant_membership("300390", False)
    row = db.get_watch("300390")
    assert row["in_quant_pool"] is False
