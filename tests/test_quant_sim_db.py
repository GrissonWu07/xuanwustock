from quant_sim.db import QuantSimDB


def test_add_candidate_records_source_and_status(tmp_path):
    db = QuantSimDB(tmp_path / "quant_sim.db")

    candidate_id = db.add_candidate(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "source": "main_force",
            "latest_price": 10.52,
        }
    )

    rows = db.get_candidates()

    assert candidate_id > 0
    assert len(rows) == 1
    assert rows[0]["stock_code"] == "600000"
    assert rows[0]["stock_name"] == "浦发银行"
    assert rows[0]["source"] == "main_force"
    assert rows[0]["status"] == "active"
    assert rows[0]["sources"] == ["main_force"]


def test_add_candidate_preserves_multiple_sources(tmp_path):
    db = QuantSimDB(tmp_path / "quant_sim.db")

    db.add_candidate(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "source": "main_force",
            "latest_price": 10.52,
        }
    )
    db.add_candidate(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "source": "value_stock",
            "latest_price": 10.88,
        }
    )

    rows = db.get_candidates()

    assert len(rows) == 1
    assert rows[0]["source"] == "main_force"
    assert rows[0]["latest_price"] == 10.88
    assert rows[0]["sources"] == ["main_force", "value_stock"]


def test_confirm_buy_creates_simulated_position(tmp_path):
    db = QuantSimDB(tmp_path / "quant_sim.db")

    signal_id = db.add_signal(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "action": "BUY",
            "confidence": 78,
            "reasoning": "趋势改善",
            "status": "pending",
        }
    )

    db.confirm_signal(
        signal_id,
        executed_action="buy",
        price=10.5,
        quantity=100,
        note="手工买入",
    )

    positions = db.get_positions()
    signals = db.get_signals(stock_code="600000")

    assert len(positions) == 1
    assert positions[0]["stock_code"] == "600000"
    assert positions[0]["quantity"] == 100
    assert positions[0]["avg_price"] == 10.5
    assert signals[0]["status"] == "executed"
    assert signals[0]["execution_note"] == "手工买入"


def test_account_summary_and_trade_history_track_cash_and_realized_pnl(tmp_path):
    db = QuantSimDB(tmp_path / "quant_sim.db")

    buy_signal_id = db.add_signal(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "action": "BUY",
            "confidence": 80,
            "reasoning": "建仓",
            "status": "pending",
        }
    )
    db.confirm_signal(
        buy_signal_id,
        executed_action="buy",
        price=10.0,
        quantity=100,
        note="首次建仓",
        executed_at="2026-04-09 10:00:00",
    )

    after_buy = db.get_account_summary()
    trades_after_buy = db.get_trade_history()

    assert after_buy["initial_cash"] == 100000.0
    assert after_buy["available_cash"] == 99000.0
    assert after_buy["market_value"] == 1000.0
    assert after_buy["total_equity"] == 100000.0
    assert after_buy["realized_pnl"] == 0.0
    assert len(trades_after_buy) == 1
    assert trades_after_buy[0]["action"] == "buy"
    assert trades_after_buy[0]["amount"] == 1000.0

    sell_signal_id = db.add_signal(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "action": "SELL",
            "confidence": 78,
            "reasoning": "止盈",
            "status": "pending",
        }
    )
    db.confirm_signal(
        sell_signal_id,
        executed_action="sell",
        price=12.0,
        quantity=100,
        note="全部卖出",
        executed_at="2026-04-10 10:00:00",
    )

    after_sell = db.get_account_summary()
    trades_after_sell = db.get_trade_history()

    assert after_sell["available_cash"] == 100200.0
    assert after_sell["market_value"] == 0.0
    assert after_sell["total_equity"] == 100200.0
    assert after_sell["realized_pnl"] == 200.0
    assert len(trades_after_sell) == 2
    assert trades_after_sell[0]["action"] == "sell"
    assert trades_after_sell[0]["realized_pnl"] == 200.0
