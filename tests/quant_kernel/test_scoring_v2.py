from __future__ import annotations

from app.quant_kernel.scoring import score_fusion, score_track


def test_group_local_normalization_is_applied_within_group_only() -> None:
    track_config = {
        "group_weights": {"g1": 1.0, "g2": 1.0},
        "dimension_groups": {"g1": ["a", "b"], "g2": ["c", "d"]},
        "dimension_weights": {"a": 1.0, "b": 3.0, "c": 1.0, "d": 1.0},
    }
    raw = {
        "a": {"score": 1.0, "available": True, "reason": "ok"},
        "b": {"score": -1.0, "available": True, "reason": "ok"},
        "c": {"score": 1.0, "available": True, "reason": "ok"},
        "d": {"score": 1.0, "available": True, "reason": "ok"},
    }
    scored = score_track(track_name="context", track_config=track_config, raw_dimensions=raw)
    groups = {row["id"]: row for row in scored["groups"]}
    assert groups["g1"]["score"] == -0.5
    assert groups["g2"]["score"] == 1.0
    assert scored["track"]["score"] == 0.25


def test_track_confidence_uses_group_coverage_formula() -> None:
    track_config = {
        "group_weights": {"g1": 2.0, "g2": 1.0},
        "dimension_groups": {"g1": ["a", "b"], "g2": ["c"]},
        "dimension_weights": {"a": 1.0, "b": 1.0, "c": 1.0},
    }
    raw = {
        "a": {"score": 0.4, "available": True, "reason": "ok"},
        "b": {"score": 0.0, "available": False, "reason": "missing_field"},
        "c": {"score": 0.7, "available": True, "reason": "ok"},
    }
    scored = score_track(track_name="context", track_config=track_config, raw_dimensions=raw)
    assert scored["track"]["confidence"] == 0.666667


def test_weighted_buy_requires_per_track_score_and_confidence_gates() -> None:
    technical = {"track": {"score": 0.85, "confidence": 0.9}}
    context = {"track": {"score": 0.2, "confidence": 0.45}}
    dual_track = {
        "mode": "weighted_only",
        "track_weights": {"tech": 1.0, "context": 1.0},
        "fusion_buy_threshold": 0.4,
        "fusion_sell_threshold": -0.2,
        "sell_precedence_gate": -0.5,
        "min_fusion_confidence": 0.3,
        "min_tech_score_for_buy": 0.4,
        "min_context_score_for_buy": 0.25,
        "min_tech_confidence_for_buy": 0.5,
        "min_context_confidence_for_buy": 0.5,
        "lambda_divergence": 0.6,
        "lambda_sign_conflict": 0.4,
        "sign_conflict_min_abs_score": 0.1,
        "threshold_mode": "static",
    }
    fusion = score_fusion(technical=technical, context=context, dual_track=dual_track)
    assert fusion["weighted_threshold_action"] == "BUY"
    assert fusion["weighted_action_raw"] == "HOLD"
    assert "context_score_below_min_for_buy" in fusion["weighted_gate_fail_reasons"]
    assert "context_confidence_below_min_for_buy" in fusion["weighted_gate_fail_reasons"]

