from quant_sim.candidate_pool_service import CandidatePoolService
from quant_sim.portfolio_service import PortfolioService
from quant_sim.scheduler import QuantSimScheduler
from quant_sim.signal_center_service import SignalCenterService
from watchlist_integration import add_watchlist_rows_to_quant_pool
from watchlist_service import WatchlistService


def test_scheduler_auto_executes_buy_signal_when_enabled(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "quant_sim.db")
    candidate_service.add_manual_candidate("300390", "天华新能", "main_force", latest_price=62.0)

    scheduler = QuantSimScheduler(db_file=tmp_path / "quant_sim.db")
    scheduler.update_config(enabled=True, auto_execute=True)

    monkeypatch.setattr(
        scheduler.engine.adapter,
        "analyze_candidate",
        lambda candidate, market_snapshot=None: {
            "action": "BUY",
            "confidence": 84,
            "reasoning": "双轨共振",
            "position_size_pct": 20,
            "price": 62.0,
        },
    )

    summary = scheduler.run_once(run_reason="manual_scan")
    portfolio_service = PortfolioService(db_file=tmp_path / "quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "quant_sim.db")

    positions = portfolio_service.list_positions()
    pending = signal_service.list_pending_signals()
    history = signal_service.list_signals(stock_code="300390")
    trades = portfolio_service.get_trade_history()

    assert summary["auto_executed"] == 1
    assert len(positions) == 1
    assert positions[0]["stock_code"] == "300390"
    assert pending == []
    assert history[0]["status"] == "executed"
    assert trades[0]["action"] == "buy"


def test_scheduler_auto_executes_buy_signal_from_watchlist_candidate_and_syncs_watchlist(tmp_path, monkeypatch):
    watch_db = tmp_path / "watchlist.db"
    quant_db = tmp_path / "quant_sim.db"

    watchlist = WatchlistService(db_file=watch_db)
    quant_pool = CandidatePoolService(db_file=quant_db)
    watchlist.add_stock("300390", "天华新能", "main_force", 62.0, None, {})
    add_watchlist_rows_to_quant_pool(["300390"], watchlist, quant_pool)

    scheduler = QuantSimScheduler(db_file=quant_db, watchlist_db_file=watch_db)
    scheduler.update_config(enabled=True, auto_execute=True)

    monkeypatch.setattr(
        scheduler.engine.adapter,
        "analyze_candidate",
        lambda candidate, market_snapshot=None, analysis_timeframe="1d", strategy_mode="auto": {
            "action": "BUY",
            "confidence": 84,
            "reasoning": "关注池量化建仓",
            "position_size_pct": 20,
            "price": 62.0,
        },
    )

    summary = scheduler.run_once(run_reason="manual_scan")
    portfolio_service = PortfolioService(db_file=quant_db)

    watch = watchlist.get_watch("300390")
    positions = portfolio_service.list_positions()

    assert summary["auto_executed"] == 1
    assert watch is not None
    assert watch["in_quant_pool"] is True
    assert watch["latest_signal"] == "BUY"
    assert watch["latest_price"] == 62.0
    assert len(positions) == 1
    assert positions[0]["stock_code"] == "300390"


def test_scheduler_auto_executes_sell_signal_when_enabled(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "quant_sim.db")

    candidate_service.add_manual_candidate("301291", "明阳电气", "main_force", latest_price=53.0)
    candidate = candidate_service.list_candidates()[0]
    buy_signal = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 82, "reasoning": "先建仓", "position_size_pct": 20},
    )
    portfolio_service.confirm_buy(
        buy_signal["id"],
        price=53.0,
        quantity=100,
        note="预先持仓",
        executed_at="2026-04-08 10:00:00",
    )

    scheduler = QuantSimScheduler(db_file=tmp_path / "quant_sim.db")
    scheduler.update_config(enabled=True, auto_execute=True)

    monkeypatch.setattr(
        scheduler.engine.adapter,
        "analyze_position",
        lambda candidate, position, market_snapshot=None: {
            "action": "SELL",
            "confidence": 78,
            "reasoning": "走弱退出",
            "position_size_pct": 0,
            "price": 52.5,
        },
    )

    summary = scheduler.run_once(run_reason="manual_scan")

    positions = portfolio_service.list_positions()
    pending = signal_service.list_pending_signals()
    history = signal_service.list_signals(stock_code="301291")
    trades = portfolio_service.get_trade_history()

    assert summary["auto_executed"] == 1
    assert positions == []
    assert pending == []
    assert history[0]["action"] == "SELL"
    assert history[0]["status"] == "executed"
    assert trades[0]["action"] == "sell"


def test_auto_execute_sell_clamps_quantity_to_historical_sellable_quantity(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "quant_sim.db")

    candidate_service.add_manual_candidate("301291", "明阳电气", "main_force", latest_price=53.0)
    candidate = candidate_service.list_candidates()[0]

    first_buy = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 82, "reasoning": "第一笔建仓", "position_size_pct": 20},
    )
    portfolio_service.confirm_buy(
        first_buy["id"],
        price=53.0,
        quantity=100,
        note="第一笔",
        executed_at="2026-04-08 10:00:00",
    )

    second_buy = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 80, "reasoning": "第二笔建仓", "position_size_pct": 20},
    )
    portfolio_service.confirm_buy(
        second_buy["id"],
        price=52.0,
        quantity=100,
        note="第二笔",
        executed_at="2026-04-09 10:00:00",
    )

    sell_signal = signal_service.create_signal(
        candidate,
        {"action": "SELL", "confidence": 78, "reasoning": "自动卖出", "position_size_pct": 0},
    )

    executed = portfolio_service.auto_execute_signal(
        sell_signal,
        note="历史回放自动卖出",
        executed_at="2026-04-09 10:30:00",
    )

    positions = portfolio_service.db.get_positions(as_of="2026-04-09 10:30:00")
    lots = portfolio_service.db.get_position_lots("301291", as_of="2026-04-09 10:30:00")
    trades = portfolio_service.get_trade_history()

    assert executed is True
    assert len(positions) == 1
    assert positions[0]["quantity"] == 100
    assert positions[0]["sellable_quantity"] == 0
    assert positions[0]["locked_quantity"] == 100
    assert len(lots) == 1
    assert lots[0]["remaining_quantity"] == 100
    assert trades[0]["action"] == "sell"
    assert trades[0]["quantity"] == 100
