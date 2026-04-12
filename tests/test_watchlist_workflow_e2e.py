import pandas as pd

from quant_sim.candidate_pool_service import CandidatePoolService
from quant_sim.portfolio_service import PortfolioService
from quant_sim.scheduler import QuantSimScheduler
from quant_sim.signal_center_service import SignalCenterService
from research_watchlist_integration import add_research_stocks_to_watchlist
from watchlist_integration import add_watchlist_rows_to_quant_pool
from watchlist_selector_integration import sync_selector_dataframe_to_watchlist
from watchlist_service import WatchlistService


def test_discovery_rows_flow_into_watchlist_quant_pool_and_pending_signals(tmp_path, monkeypatch):
    watch_db = tmp_path / "watchlist.db"
    quant_db = tmp_path / "quant_sim.db"

    sync_selector_dataframe_to_watchlist(
        pd.DataFrame([{"股票代码": "002824.SZ", "股票简称": "和胜股份", "最新价": 22.97}]),
        source="main_force",
        db_file=watch_db,
    )

    watchlist = WatchlistService(db_file=watch_db)
    quant_pool = CandidatePoolService(db_file=quant_db)
    add_watchlist_rows_to_quant_pool(["002824"], watchlist, quant_pool)

    scheduler = QuantSimScheduler(db_file=quant_db, watchlist_db_file=watch_db)
    scheduler.update_config(enabled=True, auto_execute=False, analysis_timeframe="30m", strategy_mode="auto")

    monkeypatch.setattr(
        scheduler.engine.adapter,
        "analyze_candidate",
        lambda candidate, market_snapshot=None, analysis_timeframe="30m", strategy_mode="auto": {
            "action": "BUY",
            "confidence": 81,
            "reasoning": "发现股票后进入关注池并生成待执行买点",
            "position_size_pct": 35,
            "price": 23.5,
        },
    )

    summary = scheduler.run_once(run_reason="manual_scan")
    pending = SignalCenterService(db_file=quant_db).list_pending_signals()
    watch = watchlist.get_watch("002824")

    assert summary["signals_created"] == 1
    assert watch is not None
    assert watch["in_quant_pool"] is True
    assert watch["latest_signal"] == "BUY"
    assert watch["latest_price"] == 23.5
    assert len(pending) == 1
    assert pending[0]["stock_code"] == "002824"


def test_research_outputs_flow_into_watchlist_quant_and_holdings(tmp_path, monkeypatch):
    watch_db = tmp_path / "watchlist.db"
    quant_db = tmp_path / "quant_sim.db"

    add_research_stocks_to_watchlist(
        [
            {
                "股票代码": "301291",
                "股票名称": "明阳电气",
                "现价": 52.96,
                "行业": "电力设备",
                "推荐理由": "研究情报推荐",
            }
        ],
        source="macro_analysis",
        db_file=watch_db,
    )

    watchlist = WatchlistService(db_file=watch_db)
    quant_pool = CandidatePoolService(db_file=quant_db)
    add_watchlist_rows_to_quant_pool(["301291"], watchlist, quant_pool)

    scheduler = QuantSimScheduler(db_file=quant_db, watchlist_db_file=watch_db)
    scheduler.update_config(enabled=True, auto_execute=True, analysis_timeframe="30m", strategy_mode="auto")

    monkeypatch.setattr(
        scheduler.engine.adapter,
        "analyze_candidate",
        lambda candidate, market_snapshot=None, analysis_timeframe="30m", strategy_mode="auto": {
            "action": "BUY",
            "confidence": 86,
            "reasoning": "研究情报推荐转量化买入",
            "position_size_pct": 20,
            "price": 53.0,
        },
    )

    summary = scheduler.run_once(run_reason="manual_scan")
    positions = PortfolioService(db_file=quant_db).list_positions()
    watch = watchlist.get_watch("301291")

    assert summary["auto_executed"] == 1
    assert watch is not None
    assert watch["latest_signal"] == "BUY"
    assert watch["latest_price"] == 53.0
    assert len(positions) == 1
    assert positions[0]["stock_code"] == "301291"
