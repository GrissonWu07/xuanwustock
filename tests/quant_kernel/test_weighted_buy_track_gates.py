from __future__ import annotations

from app.quant_kernel.scoring import score_fusion


def test_weighted_buy_requires_enabled_track_gates() -> None:
    dual_track = {
        "mode": "weighted_only",
        "track_weights": {"tech": 1.0, "context": 1.0},
        "fusion_buy_threshold": 0.45,
        "fusion_sell_threshold": -0.2,
        "sell_precedence_gate": -0.5,
        "min_fusion_confidence": 0.3,
        "min_tech_score_for_buy": 0.4,
        "min_context_score_for_buy": 0.4,
        "min_tech_confidence_for_buy": 0.5,
        "min_context_confidence_for_buy": 0.5,
        "lambda_divergence": 0.6,
        "lambda_sign_conflict": 0.4,
        "sign_conflict_min_abs_score": 0.1,
        "threshold_mode": "static",
    }
    fusion = score_fusion(
        technical={"track": {"score": 0.9, "confidence": 0.9}},
        context={"track": {"score": 0.1, "confidence": 0.9}},
        dual_track=dual_track,
    )
    assert fusion["weighted_threshold_action"] == "BUY"
    assert fusion["weighted_action_raw"] == "HOLD"
    assert "context_score_below_min_for_buy" in fusion["weighted_gate_fail_reasons"]

