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
    portfolio_service.confirm_buy(buy_signal["id"], price=35.2, quantity=100, note="已买入")

    sell_signal = signal_service.create_signal(
        candidate,
        {
            "action": "SELL",
            "confidence": 79,
            "reasoning": "止盈",
            "position_size_pct": 0,
        },
    )
    portfolio_service.confirm_sell(sell_signal["id"], price=36.5, quantity=100, note="已卖出")

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
