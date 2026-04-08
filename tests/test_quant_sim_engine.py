from quant_sim.candidate_pool_service import CandidatePoolService
from quant_sim.engine import QuantSimEngine


def test_engine_generates_pending_buy_signal_for_candidate(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "quant_sim.db")
    candidate_service.add_manual_candidate(
        stock_code="600000",
        stock_name="浦发银行",
        source="main_force",
    )
    candidate = candidate_service.list_candidates()[0]

    engine = QuantSimEngine(db_file=tmp_path / "quant_sim.db")
    monkeypatch.setattr(
        engine.adapter,
        "analyze_candidate",
        lambda payload, market_snapshot=None: {
            "action": "BUY",
            "confidence": 82,
            "reasoning": "趋势确认",
            "position_size_pct": 20,
        },
    )

    signal = engine.analyze_candidate(candidate)
    signals = engine.signal_center.list_signals(stock_code="600000")

    assert signal["action"] == "BUY"
    assert signal["status"] == "pending"
    assert signals[0]["confidence"] == 82


def test_engine_records_hold_as_observed_signal(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "quant_sim.db")
    candidate_service.add_manual_candidate(
        stock_code="000001",
        stock_name="平安银行",
        source="value_stock",
    )
    candidate = candidate_service.list_candidates()[0]

    engine = QuantSimEngine(db_file=tmp_path / "quant_sim.db")
    monkeypatch.setattr(
        engine.adapter,
        "analyze_candidate",
        lambda payload, market_snapshot=None: {
            "action": "HOLD",
            "confidence": 61,
            "reasoning": "等待确认",
            "position_size_pct": 0,
        },
    )

    signal = engine.analyze_candidate(candidate)

    assert signal["action"] == "HOLD"
    assert signal["status"] == "observed"
