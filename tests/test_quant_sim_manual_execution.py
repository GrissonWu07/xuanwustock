from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.signal_center_service import SignalCenterService


def test_confirm_sell_closes_simulated_position(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate(
        stock_code="600036",
        stock_name="招商银行",
        source="value_stock",
    )
    candidate = candidate_service.list_candidates()[0]

    buy_signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 83,
            "reasoning": "建仓",
            "position_size_pct": 20,
        },
    )
    portfolio_service.confirm_buy(
        buy_signal["id"],
        price=35.2,
        quantity=100,
        note="已买入",
        executed_at="2026-04-07 10:00:00",
    )

    sell_signal = signal_service.create_signal(
        candidate,
        {
            "action": "SELL",
            "confidence": 79,
            "reasoning": "止盈",
            "position_size_pct": 0,
        },
    )
    portfolio_service.confirm_sell(
        sell_signal["id"],
        price=36.5,
        quantity=100,
        note="已卖出",
        executed_at="2026-04-08 10:00:00",
    )

    positions = portfolio_service.list_positions()
    history = signal_service.list_signals(stock_code="600036")

    assert positions == []
    assert history[0]["action"] == "SELL"
    assert history[0]["status"] == "executed"


def test_ignore_signal_removes_it_from_pending_queue(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate(
        stock_code="600887",
        stock_name="伊利股份",
        source="manual",
    )
    candidate = candidate_service.list_candidates()[0]
    signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 68,
            "reasoning": "等待确认",
            "position_size_pct": 10,
        },
    )

    portfolio_service.ignore_signal(signal["id"], note="今天不做")

    pending = signal_service.list_pending_signals()
    history = signal_service.list_signals(stock_code="600887")

    assert pending == []
    assert history[0]["status"] == "ignored"
    assert history[0]["execution_note"] == "今天不做"


def test_confirm_sell_rejects_split_odd_lot_quantity(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate("600036", "招商银行", "value_stock")
    candidate = candidate_service.list_candidates()[0]
    buy_signal = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 83, "reasoning": "建仓", "position_size_pct": 20},
    )
    portfolio_service.confirm_buy(
        buy_signal["id"],
        price=35.2,
        quantity=100,
        note="已买入",
        executed_at="2026-04-07 10:00:00",
    )

    sell_signal = signal_service.create_signal(
        candidate,
        {"action": "SELL", "confidence": 79, "reasoning": "减仓", "position_size_pct": 0},
    )

    import pytest

    with pytest.raises(ValueError, match="A-share sell quantity"):
        portfolio_service.confirm_sell(
            sell_signal["id"],
            price=36.5,
            quantity=40,
            note="非法拆分零股",
            executed_at="2026-04-08 10:00:00",
        )


def test_confirm_buy_rejects_non_board_lot_quantity(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate("600036", "招商银行", "value_stock")
    candidate = candidate_service.list_candidates()[0]
    buy_signal = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 83, "reasoning": "建仓", "position_size_pct": 20},
    )

    import pytest

    with pytest.raises(ValueError, match="A-share buy quantity"):
        portfolio_service.confirm_buy(
            buy_signal["id"],
            price=35.2,
            quantity=50,
            note="非整手买入",
            executed_at="2026-04-07 10:00:00",
        )


def test_confirm_sell_uses_only_lots_unlocked_by_t_plus_one(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate("600036", "招商银行", "value_stock")
    candidate = candidate_service.list_candidates()[0]
    first_buy = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 83, "reasoning": "第一笔", "position_size_pct": 20},
    )
    portfolio_service.confirm_buy(
        first_buy["id"],
        price=35.2,
        quantity=100,
        note="第一笔",
        executed_at="2026-04-08 10:00:00",
    )
    second_buy = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 83, "reasoning": "第二笔", "position_size_pct": 20},
    )
    portfolio_service.confirm_buy(
        second_buy["id"],
        price=35.0,
        quantity=100,
        note="第二笔",
        executed_at="2026-04-09 10:00:00",
    )
    sell_signal = signal_service.create_signal(
        candidate,
        {"action": "SELL", "confidence": 79, "reasoning": "卖出", "position_size_pct": 0},
    )

    import pytest

    with pytest.raises(ValueError, match="sellable"):
        portfolio_service.confirm_sell(
            sell_signal["id"],
            price=36.5,
            quantity=200,
            note="尝试卖出未解锁持仓",
            executed_at="2026-04-09 10:30:00",
        )

    portfolio_service.confirm_sell(
        sell_signal["id"],
        price=36.5,
        quantity=100,
        note="只卖已解锁持仓",
        executed_at="2026-04-09 10:30:00",
    )

    positions = portfolio_service.db.get_positions(as_of="2026-04-09 10:30:00")
    lots = portfolio_service.db.get_position_lots("600036", as_of="2026-04-09 10:30:00")

    assert positions[0]["quantity"] == 100
    assert positions[0]["sellable_quantity"] == 0
    assert positions[0]["locked_quantity"] == 100
    assert len(lots) == 1
    assert lots[0]["is_sellable"] is False


def test_confirm_sell_rejects_oversell_and_locked_quantity(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate("600036", "招商银行", "value_stock")
    candidate = candidate_service.list_candidates()[0]
    buy_signal = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 83, "reasoning": "建仓", "position_size_pct": 20},
    )
    portfolio_service.confirm_buy(
        buy_signal["id"],
        price=35.2,
        quantity=100,
        note="已买入",
        executed_at="2026-04-08 10:00:00",
    )

    sell_signal = signal_service.create_signal(
        candidate,
        {"action": "SELL", "confidence": 79, "reasoning": "卖出", "position_size_pct": 0},
    )

    import pytest

    with pytest.raises(ValueError, match="sellable"):
        portfolio_service.confirm_sell(
            sell_signal["id"],
            price=36.5,
            quantity=40,
            note="当日卖出",
            executed_at="2026-04-08 10:30:00",
        )

    with pytest.raises(ValueError, match="quantity"):
        portfolio_service.confirm_sell(
            sell_signal["id"],
            price=36.5,
            quantity=1000,
            note="超额卖出",
            executed_at="2026-04-09 10:30:00",
        )


def test_confirm_buy_rejects_non_positive_trade_inputs(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate("600036", "招商银行", "value_stock")
    candidate = candidate_service.list_candidates()[0]
    buy_signal = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 83, "reasoning": "建仓", "position_size_pct": 20},
    )

    import pytest

    with pytest.raises(ValueError, match="price"):
        portfolio_service.confirm_buy(buy_signal["id"], price=0, quantity=100, note="bad")
    with pytest.raises(ValueError, match="quantity"):
        portfolio_service.confirm_buy(buy_signal["id"], price=35.2, quantity=0, note="bad")


def test_confirm_buy_rejects_insufficient_available_cash(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate("600036", "招商银行", "value_stock")
    candidate = candidate_service.list_candidates()[0]
    buy_signal = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 83, "reasoning": "建仓", "position_size_pct": 20},
    )

    portfolio_service.db.configure_account(initial_cash=1000)

    import pytest

    with pytest.raises(ValueError, match="cash"):
        portfolio_service.confirm_buy(
            buy_signal["id"],
            price=35.2,
            quantity=100,
            note="超出资金池",
            executed_at="2026-04-09 10:00:00",
        )


def test_confirm_buy_unlocks_on_next_trading_day_not_calendar_day(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate("600036", "招商银行", "value_stock")
    candidate = candidate_service.list_candidates()[0]
    buy_signal = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 83, "reasoning": "建仓", "position_size_pct": 20},
    )
    portfolio_service.confirm_buy(
        buy_signal["id"],
        price=35.2,
        quantity=100,
        note="周五买入",
        executed_at="2026-04-10 10:00:00",
    )

    saturday_lots = portfolio_service.db.get_position_lots("600036", as_of="2026-04-11 10:00:00")
    monday_lots = portfolio_service.db.get_position_lots("600036", as_of="2026-04-13 10:00:00")

    assert saturday_lots[0]["unlock_date"] == "2026-04-13"
    assert saturday_lots[0]["is_sellable"] is False
    assert monday_lots[0]["is_sellable"] is True
