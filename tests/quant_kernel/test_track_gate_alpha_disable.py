from __future__ import annotations

from app.quant_kernel.scoring import score_fusion


def test_buy_gates_skip_disabled_track_when_context_alpha_is_zero() -> None:
    technical = {"track": {"score": 0.9, "confidence": 0.9}}
    context = {"track": {"score": -0.8, "confidence": 0.1}}
    dual_track = {
        "mode": "weighted_only",
        "track_weights": {"tech": 1.0, "context": 0.0},
        "fusion_buy_threshold": 0.7,
        "fusion_sell_threshold": -0.2,
        "sell_precedence_gate": -0.5,
        "min_fusion_confidence": 0.3,
        "min_tech_score_for_buy": 0.4,
        "min_context_score_for_buy": 0.9,
        "min_tech_confidence_for_buy": 0.5,
        "min_context_confidence_for_buy": 0.9,
        "lambda_divergence": 0.6,
        "lambda_sign_conflict": 0.4,
        "sign_conflict_min_abs_score": 0.1,
        "threshold_mode": "static",
    }
    fusion = score_fusion(technical=technical, context=context, dual_track=dual_track)
    assert fusion["context_enabled"] is False
    assert fusion["weighted_threshold_action"] == "BUY"
    assert fusion["weighted_action_raw"] == "BUY"
    assert fusion["weighted_gate_fail_reasons"] == []

