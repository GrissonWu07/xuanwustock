from quant_sim.candidate_pool_service import CandidatePoolService
from watchlist_integration import add_watchlist_rows_to_quant_pool, remove_watchlist_rows_from_quant_pool
from watchlist_service import WatchlistService


def test_watchlist_rows_promote_into_quant_candidate_pool(tmp_path):
    watch_db = tmp_path / "watchlist.db"
    quant_db = tmp_path / "quant_sim.db"

    watchlist = WatchlistService(db_file=watch_db)
    quant_pool = CandidatePoolService(db_file=quant_db)

    watchlist.add_stock("002824", "和胜股份", "main_force", 22.97, None, {})
    watchlist.add_stock("301291", "明阳电气", "macro_analysis", 52.96, None, {})

    summary = add_watchlist_rows_to_quant_pool(
        stock_codes=["002824", "301291"],
        watchlist_service=watchlist,
        candidate_service=quant_pool,
    )

    assert summary["success_count"] == 2
    assert watchlist.get_watch("002824")["in_quant_pool"] is True
    assert watchlist.get_watch("301291")["in_quant_pool"] is True


def test_watchlist_quant_membership_clears_on_candidate_delete(tmp_path):
    watch_db = tmp_path / "watchlist.db"
    quant_db = tmp_path / "quant_sim.db"

    watchlist = WatchlistService(db_file=watch_db)
    quant_pool = CandidatePoolService(db_file=quant_db)

    watchlist.add_stock("002824", "和胜股份", "manual", 22.97, None, {})
    add_watchlist_rows_to_quant_pool(["002824"], watchlist, quant_pool)

    quant_pool.delete_candidate("002824")
    watchlist.sync_quant_membership(candidate_stock_codes=[])

    assert watchlist.get_watch("002824")["in_quant_pool"] is False


def test_watchlist_rows_can_be_removed_from_quant_candidate_pool(tmp_path):
    watch_db = tmp_path / "watchlist.db"
    quant_db = tmp_path / "quant_sim.db"

    watchlist = WatchlistService(db_file=watch_db)
    quant_pool = CandidatePoolService(db_file=quant_db)

    watchlist.add_stock("002824", "和胜股份", "manual", 22.97, None, {})
    add_watchlist_rows_to_quant_pool(["002824"], watchlist, quant_pool)

    summary = remove_watchlist_rows_from_quant_pool(
        stock_codes=["002824"],
        watchlist_service=watchlist,
        candidate_service=quant_pool,
    )

    assert summary == {"attempted": 1, "success_count": 1, "failures": []}
    assert watchlist.get_watch("002824")["in_quant_pool"] is False
    assert quant_pool.list_candidates(status="active") == []
