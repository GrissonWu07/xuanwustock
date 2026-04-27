from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.engine import QuantSimEngine
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.signal_center_service import SignalCenterService
from app.quant_kernel.models import Decision


def test_engine_generates_pending_buy_signal_for_candidate(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate(
        stock_code="600000",
        stock_name="浦发银行",
        source="main_force",
    )
    candidate = candidate_service.list_candidates()[0]

    engine = QuantSimEngine(db_file=tmp_path / "app.quant_sim.db")
    captured = {}

    def fake_analyze_candidate(payload, market_snapshot=None, analysis_timeframe="1d"):
        captured["analysis_timeframe"] = analysis_timeframe
        return {
            "action": "BUY",
            "confidence": 82,
            "reasoning": "趋势确认",
            "position_size_pct": 20,
        }

    monkeypatch.setattr(engine.adapter, "analyze_candidate", fake_analyze_candidate)

    signal = engine.analyze_candidate(candidate)
    signals = engine.signal_center.list_signals(stock_code="600000")

    assert signal["action"] == "BUY"
    assert signal["status"] == "pending"
    assert signals[0]["confidence"] == 82
    assert captured["analysis_timeframe"] == "1d"


def test_engine_injects_account_context_for_candidate_analysis(tmp_path, monkeypatch):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_manual_candidate("600000", "浦发银行", "main_force")
    candidate = candidate_service.list_candidates()[0]
    PortfolioService(db_file=db_file).configure_account(100000)

    engine = QuantSimEngine(db_file=db_file)
    captured = {}

    def fake_analyze_candidate(payload, **kwargs):
        captured["account_context"] = payload.get("_quant_account_context")
        return {
            "action": "HOLD",
            "confidence": 61,
            "reasoning": "等待确认",
            "position_size_pct": 0,
        }

    monkeypatch.setattr(engine.adapter, "analyze_candidate", fake_analyze_candidate)

    engine.analyze_candidate(candidate)

    assert captured["account_context"]["cash_ratio"] == 1.0


def test_engine_records_hold_as_observed_signal(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate(
        stock_code="000001",
        stock_name="平安银行",
        source="value_stock",
    )
    candidate = candidate_service.list_candidates()[0]

    engine = QuantSimEngine(db_file=tmp_path / "app.quant_sim.db")
    monkeypatch.setattr(
        engine.adapter,
        "analyze_candidate",
        lambda payload, market_snapshot=None, analysis_timeframe="1d": {
            "action": "HOLD",
            "confidence": 61,
            "reasoning": "等待确认",
            "position_size_pct": 0,
        },
    )

    signal = engine.analyze_candidate(candidate)

    assert signal["action"] == "HOLD"
    assert signal["status"] == "observed"


def test_engine_uses_embedded_stockpolicy_dual_track_decision(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate(
        stock_code="601318",
        stock_name="中国平安",
        source="main_force",
    )
    candidate = candidate_service.list_candidates()[0]

    engine = QuantSimEngine(db_file=tmp_path / "app.quant_sim.db")
    monkeypatch.setattr(
        engine.adapter,
        "analyze_candidate",
        lambda payload, market_snapshot=None, analysis_timeframe="1d": Decision(
            code=payload["stock_code"],
            action="BUY",
            confidence=0.86,
            price=52.3,
            timestamp=engine.adapter.now(),
            reason="双轨共振",
            tech_score=0.62,
            context_score=0.31,
            position_ratio=0.6,
            decision_type="dual_track_resonance",
            strategy_profile={"analysis_timeframe": {"key": analysis_timeframe}},
        ),
    )

    signal = engine.analyze_candidate(candidate)

    assert signal["decision_type"] == "dual_track_resonance"
    assert signal["tech_score"] == 0.62
    assert signal["context_score"] == 0.31
    assert signal["position_size_pct"] == 60.0
    assert signal["strategy_profile"]["analysis_timeframe"]["key"] == "1d"


def test_engine_resolves_dynamic_binding_per_candidate(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate("600000", "浦发银行", "main_force")
    candidate_service.add_manual_candidate("000001", "平安银行", "value_stock")

    engine = QuantSimEngine(db_file=tmp_path / "app.quant_sim.db")
    captured = []

    def fake_resolve(
        *,
        strategy_profile_id,
        ai_dynamic_strategy=None,
        ai_dynamic_strength=None,
        ai_dynamic_lookback=None,
        stock_code=None,
        stock_name=None,
    ):
        captured.append((stock_code, stock_name, ai_dynamic_strategy, ai_dynamic_strength, ai_dynamic_lookback))
        return {
            "profile_id": "aggressive",
            "profile_name": "积极",
            "version_id": 1,
            "version": 1,
            "config": {},
        }

    monkeypatch.setattr(engine, "_resolve_strategy_binding", fake_resolve)
    monkeypatch.setattr(
        engine.adapter,
        "analyze_candidate",
        lambda payload, **kwargs: {  # noqa: ARG005 - test seam
            "action": "HOLD",
            "confidence": 61,
            "reasoning": "等待确认",
            "position_size_pct": 0,
        },
    )

    engine.analyze_active_candidates(
        ai_dynamic_strategy="hybrid",
        ai_dynamic_strength=0.5,
        ai_dynamic_lookback=48,
    )

    assert sorted(captured) == sorted([
        ("600000", "浦发银行", "hybrid", 0.5, 48),
        ("000001", "平安银行", "hybrid", 0.5, 48),
    ])


def test_engine_resolves_dynamic_binding_per_position(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate("300750", "宁德时代", "main_force")
    candidate = candidate_service.list_candidates()[0]
    buy_signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 82,
            "reasoning": "建仓",
            "position_size_pct": 20,
        },
    )
    portfolio_service.confirm_buy(
        buy_signal["id"],
        price=201.5,
        quantity=100,
        note="已买入",
        executed_at="2026-04-07 10:00:00",
    )

    engine = QuantSimEngine(db_file=tmp_path / "app.quant_sim.db")
    captured = []

    def fake_resolve(
        *,
        strategy_profile_id,
        ai_dynamic_strategy=None,
        ai_dynamic_strength=None,
        ai_dynamic_lookback=None,
        stock_code=None,
        stock_name=None,
    ):
        captured.append((stock_code, stock_name, ai_dynamic_strategy, ai_dynamic_strength, ai_dynamic_lookback))
        return {
            "profile_id": "aggressive",
            "profile_name": "积极",
            "version_id": 1,
            "version": 1,
            "config": {},
        }

    monkeypatch.setattr(engine, "_resolve_strategy_binding", fake_resolve)
    monkeypatch.setattr(
        engine.adapter,
        "analyze_position",
        lambda candidate, position, **kwargs: {  # noqa: ARG001, ARG005 - test seam
            "action": "HOLD",
            "confidence": 63,
            "reasoning": "继续观察",
            "position_size_pct": 0,
        },
    )

    engine.analyze_positions(
        ai_dynamic_strategy="hybrid",
        ai_dynamic_strength=0.5,
        ai_dynamic_lookback=48,
    )

    assert captured == [
        ("300750", "宁德时代", "hybrid", 0.5, 48),
    ]
