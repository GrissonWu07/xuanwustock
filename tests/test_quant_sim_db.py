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
