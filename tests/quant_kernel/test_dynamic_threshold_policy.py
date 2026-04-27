from __future__ import annotations

import pytest

from app.quant_kernel.scoring import score_fusion


def _base_dual_track() -> dict[str, float | str | dict[str, float]]:
    return {
        "mode": "weighted_only",
        "track_weights": {"tech": 1.0, "context": 1.0},
        "fusion_buy_threshold": 0.76,
        "fusion_sell_threshold": -0.17,
        "sell_precedence_gate": -0.5,
        "min_fusion_confidence": 0.2,
        "min_tech_score_for_buy": 0.0,
        "min_context_score_for_buy": 0.0,
        "min_tech_confidence_for_buy": 0.0,
        "min_context_confidence_for_buy": 0.0,
        "lambda_divergence": 0.6,
        "lambda_sign_conflict": 0.4,
        "sign_conflict_min_abs_score": 0.1,
    }


def test_static_threshold_policy_uses_base_thresholds() -> None:
    dual_track = {**_base_dual_track(), "threshold_mode": "static"}
    fusion = score_fusion(
        technical={"track": {"score": 0.5, "confidence": 0.8}},
        context={"track": {"score": 0.5, "confidence": 0.8}},
        dual_track=dual_track,
        volatility_regime_score=0.9,
    )
    assert fusion["buy_threshold_eff"] == fusion["buy_threshold_base"] == 0.76
    assert fusion["sell_threshold_eff"] == fusion["sell_threshold_base"] == -0.17


def test_volatility_adjusted_policy_updates_effective_thresholds() -> None:
    dual_track = {
        **_base_dual_track(),
        "threshold_mode": "volatility_adjusted",
        "buy_vol_k": 0.2,
        "sell_vol_k": 0.2,
        "threshold_volatility_missing_policy": "neutral_zero",
    }
    fusion = score_fusion(
        technical={"track": {"score": 0.5, "confidence": 0.8}},
        context={"track": {"score": 0.5, "confidence": 0.8}},
        dual_track=dual_track,
        volatility_regime_score=0.6,
    )
    assert fusion["buy_threshold_eff"] == 0.88
    assert fusion["sell_threshold_eff"] == -0.29


def test_volatility_adjusted_missing_score_neutral_zero() -> None:
    dual_track = {
        **_base_dual_track(),
        "threshold_mode": "volatility_adjusted",
        "buy_vol_k": 0.2,
        "sell_vol_k": 0.2,
        "threshold_volatility_missing_policy": "neutral_zero",
    }
    fusion = score_fusion(
        technical={"track": {"score": 0.5, "confidence": 0.8}},
        context={"track": {"score": 0.5, "confidence": 0.8}},
        dual_track=dual_track,
        volatility_regime_score=None,
    )
    assert fusion["threshold_missing_reason"] == "threshold_volatility_missing_neutral"
    assert fusion["buy_threshold_eff"] == 0.76
    assert fusion["sell_threshold_eff"] == -0.17


def test_volatility_adjusted_missing_score_fail_fast() -> None:
    dual_track = {
        **_base_dual_track(),
        "threshold_mode": "volatility_adjusted",
        "buy_vol_k": 0.2,
        "sell_vol_k": 0.2,
        "threshold_volatility_missing_policy": "fail_fast",
    }
    with pytest.raises(ValueError):
        score_fusion(
            technical={"track": {"score": 0.5, "confidence": 0.8}},
            context={"track": {"score": 0.5, "confidence": 0.8}},
            dual_track=dual_track,
            volatility_regime_score=None,
        )

