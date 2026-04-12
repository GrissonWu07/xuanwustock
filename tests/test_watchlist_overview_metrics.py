from quant_sim.candidate_pool_service import CandidatePoolService
from quant_sim.db import QuantSimDB
from quant_sim.portfolio_service import PortfolioService
from watchlist_service import WatchlistService
from watchlist_ui import _build_watchlist_overview_metrics


def test_build_watchlist_overview_metrics_counts_watch_positions_candidates_and_tasks(tmp_path):
    watch_db = tmp_path / "watchlist.db"
    quant_db = tmp_path / "quant_sim.db"

    watch_service = WatchlistService(db_file=watch_db)
    watch_service.add_manual_stock("300390")
    watch_service.add_manual_stock("600531")
    watches = watch_service.list_watches()

    candidate_service = CandidatePoolService(db_file=quant_db)
    candidate_service.add_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="manual",
        latest_price=10.0,
    )

    quant_db_client = QuantSimDB(quant_db)
    signal_id = quant_db_client.add_signal(
        {
            "stock_code": "300390",
            "stock_name": "天华新能",
            "action": "BUY",
            "confidence": 80,
            "reasoning": "测试建仓",
            "status": "pending",
        }
    )
    quant_db_client.confirm_signal(
        signal_id,
        executed_action="buy",
        price=10.0,
        quantity=100,
        note="测试持仓",
        executed_at="2026-04-12 09:30:00",
    )
    quant_db_client.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-03-11 09:30:00",
        end_datetime="2026-04-10 15:00:00",
        initial_cash=100000,
        metadata={"strategy_mode": "auto"},
    )

    metrics = _build_watchlist_overview_metrics(
        watches,
        candidate_service=candidate_service,
        portfolio_service=PortfolioService(db_file=quant_db),
        quant_db=quant_db_client,
    )

    assert metrics["watch_count"] == 2
    assert metrics["position_count"] == 1
    assert metrics["quant_candidate_count"] == 1
    assert metrics["quant_task_count"] == 1
