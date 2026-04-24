from datetime import datetime


def test_dual_track_resolver_full_resonance_returns_full_buy_position():
    from app.quant_kernel.config import QuantKernelConfig
    from app.quant_kernel.decision_engine import DualTrackResolver
    from app.quant_kernel.models import ContextualScore, Decision

    resolver = DualTrackResolver(QuantKernelConfig.default().dual_track)
    tech_decision = Decision(
        code="300390",
        action="BUY",
        confidence=0.88,
        price=61.99,
        timestamp=datetime(2026, 4, 9, 10, 0, 0),
        reason="技术面强势",
        tech_score=0.82,
    )
    context_score = ContextualScore(
        score=0.66,
        signal="BUY",
        confidence=0.74,
        components={},
        reason="环境偏强",
    )

    final = resolver.resolve(
        tech_decision=tech_decision,
        context_score=context_score,
        stock_code="300390",
        current_time=datetime(2026, 4, 9, 10, 0, 0),
    )

    assert final.action == "BUY"
    assert final.position_ratio == 1.0
    assert final.decision_type == "dual_track_resonance"


def test_dual_track_resolver_context_veto_blocks_buy():
    from app.quant_kernel.config import QuantKernelConfig
    from app.quant_kernel.decision_engine import DualTrackResolver
    from app.quant_kernel.models import ContextualScore, Decision

    resolver = DualTrackResolver(QuantKernelConfig.default().dual_track)
    tech_decision = Decision(
        code="301291",
        action="BUY",
        confidence=0.81,
        price=52.96,
        timestamp=datetime(2026, 4, 9, 10, 30, 0),
        reason="技术面给出买入",
        tech_score=0.77,
    )
    context_score = ContextualScore(
        score=-0.61,
        signal="SELL",
        confidence=0.72,
        components={},
        reason="外部环境极弱",
    )

    final = resolver.resolve(
        tech_decision=tech_decision,
        context_score=context_score,
        stock_code="301291",
        current_time=datetime(2026, 4, 9, 10, 30, 0),
    )

    assert final.action == "HOLD"
    assert final.position_ratio == 0.0
    assert final.decision_type == "context_veto"


def test_dual_track_resolver_extreme_context_delays_sell_exit():
    from app.quant_kernel.config import QuantKernelConfig
    from app.quant_kernel.decision_engine import DualTrackResolver
    from app.quant_kernel.models import ContextualScore, Decision

    resolver = DualTrackResolver(QuantKernelConfig.default().dual_track)
    tech_decision = Decision(
        code="600000",
        action="SELL",
        confidence=0.76,
        price=10.25,
        timestamp=datetime(2026, 4, 9, 14, 30, 0),
        reason="技术面走弱",
        tech_score=-0.32,
    )
    context_score = ContextualScore(
        score=0.83,
        signal="BUY",
        confidence=0.69,
        components={},
        reason="环境极强",
    )

    final = resolver.resolve(
        tech_decision=tech_decision,
        context_score=context_score,
        stock_code="600000",
        current_time=datetime(2026, 4, 9, 14, 30, 0),
    )

    assert final.action == "HOLD"
    assert final.position_ratio == 0.0
    assert final.decision_type == "dual_track_divergence"


def test_kernel_runtime_context_score_changes_with_dynamic_market_context():
    from app.quant_kernel.runtime import KernelStrategyRuntime

    runtime = KernelStrategyRuntime()
    candidate = {
        "stock_code": "300390",
        "stock_name": "天华新能",
        "source": "main_force",
        "sources": ["main_force"],
        "latest_price": 10.0,
    }

    bullish_snapshot = {
        "current_price": 10.6,
        "ma5": 10.3,
        "ma20": 10.0,
        "ma60": 9.7,
        "macd": 0.7,
        "rsi12": 57.0,
        "volume_ratio": 1.8,
        "trend": "up",
    }
    bearish_snapshot = {
        "current_price": 9.2,
        "ma5": 9.5,
        "ma20": 9.8,
        "ma60": 10.1,
        "macd": -0.9,
        "rsi12": 41.0,
        "volume_ratio": 0.7,
        "trend": "down",
    }

    bullish = runtime.evaluate_candidate(
        candidate=candidate,
        market_snapshot=bullish_snapshot,
        current_time=datetime(2026, 4, 9, 10, 0, 0),
    )
    bearish = runtime.evaluate_candidate(
        candidate=candidate,
        market_snapshot=bearish_snapshot,
        current_time=datetime(2026, 4, 10, 10, 0, 0),
    )

    assert bullish.context_score > bearish.context_score


def test_kernel_runtime_derives_dynamic_strategy_profile():
    from app.quant_kernel.runtime import KernelStrategyRuntime

    runtime = KernelStrategyRuntime()
    candidate = {
        "stock_code": "300390",
        "stock_name": "天华新能",
        "source": "profit_growth",
        "sources": ["profit_growth"],
        "latest_price": 10.0,
        "metadata": {
            "profit_growth_pct": 35.0,
            "pe_ratio": 18.0,
            "pb_ratio": 2.1,
            "roe_pct": 19.0,
        },
    }
    market_snapshot = {
        "current_price": 10.6,
        "ma5": 10.3,
        "ma20": 10.0,
        "ma60": 9.7,
        "macd": 0.7,
        "rsi12": 57.0,
        "volume_ratio": 1.8,
        "trend": "up",
    }

    decision = runtime.evaluate_candidate(
        candidate=candidate,
        market_snapshot=market_snapshot,
        current_time=datetime(2026, 4, 9, 14, 30, 0),
        analysis_timeframe="30m",
    )

    strategy_profile = decision.strategy_profile
    assert strategy_profile is not None
    assert strategy_profile["market_regime"]["label"] == "牛市"
    assert strategy_profile["fundamental_quality"]["label"] == "强基本面"
    assert strategy_profile["risk_style"]["label"] == "激进"
    assert strategy_profile["analysis_timeframe"]["key"] == "30m"
    assert strategy_profile["effective_thresholds"]["allow_pyramiding"] is True
