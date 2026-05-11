from app.quant_kernel.config import QuantKernelConfig
from app.quant_kernel.models import ContextualScore, Decision
from app.quant_kernel.decision_engine import DualTrackResolver


def _resolved_buy(
    *,
    tech_score: float,
    context_score: float,
    snapshot: dict,
    profile: str = "aggressive",
) -> Decision:
    resolver = DualTrackResolver(QuantKernelConfig.default().dual_track)
    return resolver.resolve(
        tech_decision=Decision(
            code="300001",
            action="BUY",
            confidence=0.82,
            price=float(snapshot.get("current_price") or 10.0),
            timestamp=None,
            reason="test tech",
            tech_score=tech_score,
        ),
        context_score=ContextualScore(
            score=context_score,
            signal="BUY",
            confidence=0.74,
            components={},
            reason="test context",
        ),
        stock_code="300001",
        current_time=None,
        market_snapshot={
            "current_price": 10.0,
            "latest_price": 10.0,
            "ma5": 10.1,
            "ma10": 10.0,
            "ma20": 9.9,
            "ma60": 9.8,
            "ma20_slope": 0.01,
            "macd": 0.03,
            "rsi12": 60.0,
            "volume_ratio": 1.5,
            "recent_5d_return": 0.02,
            **snapshot,
        },
        strategy_profile_id=profile,
    )


def test_resonance_quality_defaults_are_profile_specific():
    cfg = QuantKernelConfig.default()
    policy = cfg.dual_track.resonance_quality_policy

    assert policy["aggressive"]["weights"] == {
        "tech_edge": 0.22,
        "context_edge": 0.18,
        "trend_structure": 0.28,
        "confirmation": 0.16,
        "volume": 0.16,
    }
    assert policy["stable"]["weights"]["context_edge"] == 0.20
    assert policy["conservative"]["weights"]["confirmation"] == 0.20

    assert policy["aggressive"]["position_ranges"]["resonance_full"] == {"min": 0.45, "max": 0.60}
    assert policy["stable"]["position_ranges"]["resonance_full"] == {"min": 0.36, "max": 0.50}
    assert policy["conservative"]["position_ranges"]["resonance_full"] == {"min": 0.28, "max": 0.40}
    assert policy["aggressive"]["position_ranges"]["resonance_standard"] == {"min": 0.12, "max": 0.45}


def test_standard_resonance_no_longer_outputs_fixed_50_percent():
    decision = _resolved_buy(
        tech_score=0.72,
        context_score=0.48,
        snapshot={
            "current_price": 10.0,
            "ma5": 10.01,
            "ma10": 10.0,
            "ma20": 9.99,
            "ma60": 9.95,
            "ma20_slope": 0.0,
            "rsi12": 84.0,
            "volume_ratio": 2.0,
            "trend_confirmed_checkpoints": 3,
        },
    )

    resonance = decision.dual_track_details["resonance_quality"]
    assert resonance["rule_hit"] == "resonance_standard"
    assert decision.position_ratio < 0.5
    assert resonance["quality_adjusted_position_ratio"] == decision.position_ratio
    assert "heat_penalty" in resonance["quality_penalties"]


def test_resonance_quality_confirmation_uses_recent_checkpoint_window():
    decision = _resolved_buy(
        tech_score=0.72,
        context_score=0.48,
        snapshot={
            "trend_confirmed_checkpoints": 0,
            "required_confirm_checkpoints": 3,
            "recent_checkpoints": [
                {"close": 9.95, "low": 9.9, "ma20": 9.9},
                {"close": 10.05, "low": 9.98, "ma20": 9.92},
                {"close": 10.10, "low": 10.02, "ma20": 9.94},
                {"close": 10.15, "low": 10.08, "ma20": 9.96},
            ],
        },
    )

    components = decision.dual_track_details["resonance_quality"]["quality_components"]
    assert components["confirmation_score"] == 1.0


def test_resonance_quality_trend_structure_has_middle_confirmation_score():
    decision = _resolved_buy(
        tech_score=0.72,
        context_score=0.48,
        snapshot={
            "ma5": 9.95,
            "ma10": 10.0,
            "ma20": 9.9,
            "ma20_slope": 0.0,
            "recent_checkpoints": [
                {"close": 9.95, "ma20": 9.85},
                {"close": 10.05, "ma20": 9.88},
                {"close": 10.10, "ma20": 9.90},
            ],
        },
    )

    components = decision.dual_track_details["resonance_quality"]["quality_components"]
    assert components["trend_structure_score"] == 0.5


def test_rsi_overheated_signal_gets_lower_position_than_clean_trend():
    clean = _resolved_buy(
        tech_score=0.8,
        context_score=0.66,
        snapshot={"rsi12": 62.0, "volume_ratio": 2.0, "recent_5d_return": 0.02, "trend_confirmed_checkpoints": 3},
    )
    hot = _resolved_buy(
        tech_score=0.8,
        context_score=0.66,
        snapshot={
            "ma5": 9.95,
            "ma10": 10.0,
            "rsi12": 91.0,
            "volume_ratio": 2.0,
            "recent_5d_return": 0.09,
            "trend_confirmed_checkpoints": 3,
        },
    )

    assert clean.position_ratio > hot.position_ratio
    assert hot.dual_track_details["resonance_quality"]["quality_penalties"]["heat_penalty"] >= 0.35
