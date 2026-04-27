from __future__ import annotations

from app.quant_kernel.scoring import score_fusion


def test_divergence_penalty_applies_only_when_both_tracks_enabled() -> None:
    dual_track = {
        "mode": "weighted_only",
        "track_weights": {"tech": 1.0, "context": 1.0},
        "fusion_buy_threshold": 0.6,
        "fusion_sell_threshold": -0.2,
        "sell_precedence_gate": -0.5,
        "min_fusion_confidence": 0.2,
        "min_tech_score_for_buy": 0.0,
        "min_context_score_for_buy": 0.0,
        "min_tech_confidence_for_buy": 0.0,
        "min_context_confidence_for_buy": 0.0,
        "lambda_divergence": 0.6,
        "lambda_sign_conflict": 0.4,
        "sign_conflict_min_abs_score": 0.1,
        "threshold_mode": "static",
    }
    both_enabled = score_fusion(
        technical={"track": {"score": 0.9, "confidence": 0.9}},
        context={"track": {"score": -0.9, "confidence": 0.9}},
        dual_track=dual_track,
    )
    context_disabled = score_fusion(
        technical={"track": {"score": 0.9, "confidence": 0.9}},
        context={"track": {"score": -0.9, "confidence": 0.9}},
        dual_track={**dual_track, "track_weights": {"tech": 1.0, "context": 0.0}},
    )

    assert both_enabled["divergence_penalty"] > 0
    assert context_disabled["divergence_penalty"] == 0
    assert context_disabled["sign_conflict"] == 0

