from quant_sim.candidate_pool_service import CandidatePoolService
from quant_sim.portfolio_service import PortfolioService
from quant_sim.signal_center_service import SignalCenterService


def test_confirm_sell_closes_simulated_position(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "quant_sim.db")

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
    candidate_service = CandidatePoolService(db_file=tmp_path / "quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "quant_sim.db")

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


def test_confirm_partial_sell_consumes_lot_quantity(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "quant_sim.db")

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
    portfolio_service.confirm_sell(
        sell_signal["id"],
        price=36.5,
        quantity=40,
        note="已减仓",
        executed_at="2026-04-08 10:00:00",
    )

    positions = portfolio_service.list_positions()
    lots = portfolio_service.list_position_lots(stock_code="600036")

    assert positions[0]["quantity"] == 60
    assert positions[0]["sellable_quantity"] == 60
    assert lots[0]["remaining_quantity"] == 60


def test_confirm_sell_rejects_oversell_and_locked_quantity(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "quant_sim.db")

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
    candidate_service = CandidatePoolService(db_file=tmp_path / "quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "quant_sim.db")

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
    candidate_service = CandidatePoolService(db_file=tmp_path / "quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "quant_sim.db")

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
