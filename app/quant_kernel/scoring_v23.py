"""Quant explain weighted scoring pipeline."""

from __future__ import annotations

import math
from typing import Any, Mapping

from .config import CONTEXT_GROUP_DIMENSIONS, TECHNICAL_GROUP_DIMENSIONS


def _clamp(value: float) -> float:
    return min(1.0, max(-1.0, value))


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        if not math.isfinite(parsed):
            return default
        return parsed
    except (TypeError, ValueError):
        return default


def _resolve_groups(track_name: str, track_config: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    if track_name == "technical":
        return TECHNICAL_GROUP_DIMENSIONS
    dimension_groups = track_config.get("dimension_groups")
    if isinstance(dimension_groups, Mapping):
        groups: dict[str, tuple[str, ...]] = {}
        for group_id, dimensions in dimension_groups.items():
            if isinstance(dimensions, (list, tuple)):
                groups[str(group_id)] = tuple(str(item) for item in dimensions)
        if groups:
            return groups
    return CONTEXT_GROUP_DIMENSIONS


def _dimension_payload(raw: Any) -> tuple[float, int, str]:
    if not isinstance(raw, Mapping):
        return 0.0, 0, "missing_field"
    score_value = raw.get("score")
    try:
        parsed_score = float(score_value)
    except (TypeError, ValueError):
        return 0.0, 0, "invalid_value"
    if not math.isfinite(parsed_score):
        return 0.0, 0, "invalid_value"
    available = raw.get("available")
    if isinstance(available, bool):
        a_i = 1 if available else 0
    else:
        a_i = 1
    reason = str(raw.get("reason") or ("missing_field" if a_i == 0 else "ok"))
    return _clamp(parsed_score), a_i, reason


def score_track(
    *,
    track_name: str,
    track_config: Mapping[str, Any],
    raw_dimensions: Mapping[str, Any],
) -> dict[str, Any]:
    groups = _resolve_groups(track_name, track_config)
    group_weights = track_config.get("group_weights") if isinstance(track_config.get("group_weights"), Mapping) else {}
    optional_groups = {
        str(group)
        for group in (track_config.get("optional_groups") or [])
        if isinstance(group, (str, int, float))
    }
    dimension_weights = (
        track_config.get("dimension_weights")
        if isinstance(track_config.get("dimension_weights"), Mapping)
        else {}
    )

    dimensions_rows: list[dict[str, Any]] = []
    groups_rows: list[dict[str, Any]] = []
    group_state: dict[str, dict[str, Any]] = {}
    available_group_denominator = 0.0
    confidence_denominator = 0.0

    for group_id, dimensions in groups.items():
        dim_rows: list[dict[str, Any]] = []
        dim_weight_sum = 0.0
        dim_available_weight_sum = 0.0
        for dimension_id in dimensions:
            weight_raw = max(0.0, _to_float(dimension_weights.get(dimension_id), 0.0))
            score, a_i, reason = _dimension_payload(raw_dimensions.get(dimension_id))
            dim_weight_sum += weight_raw
            dim_available_weight_sum += weight_raw * a_i
            dim_rows.append(
                {
                    "id": dimension_id,
                    "group": group_id,
                    "score": score,
                    "available": bool(a_i),
                    "reason": reason,
                    "weight_raw": weight_raw,
                    "_w_eff": weight_raw * a_i,
                }
            )
        group_coverage = (dim_available_weight_sum / dim_weight_sum) if dim_weight_sum > 0 else 0.0
        group_available = group_coverage > 0
        group_weight_raw = max(0.0, _to_float(group_weights.get(group_id), 0.0))
        if group_available:
            available_group_denominator += group_weight_raw
        if group_available or group_id not in optional_groups:
            confidence_denominator += group_weight_raw
        denominator = sum(item["_w_eff"] for item in dim_rows)
        group_score_raw = 0.0
        for item in dim_rows:
            weight_norm = (item["_w_eff"] / denominator) if denominator > 0 else 0.0
            group_contribution = weight_norm * item["score"]
            item["weight_norm_in_group"] = round(weight_norm, 6)
            item["group_contribution"] = round(group_contribution, 6)
            group_score_raw += group_contribution
        group_score = _clamp(group_score_raw)
        group_state[group_id] = {
            "rows": dim_rows,
            "score": group_score,
            "available": group_available,
            "coverage": group_coverage,
            "weight_raw": group_weight_raw,
        }

    track_score_raw = 0.0
    track_confidence_numerator = 0.0
    for group_id, state in group_state.items():
        weight_raw = state["weight_raw"]
        weight_norm_in_track = (
            (weight_raw / available_group_denominator) if (state["available"] and available_group_denominator > 0) else 0.0
        )
        track_contribution = weight_norm_in_track * state["score"]
        state["weight_norm_in_track"] = weight_norm_in_track
        state["track_contribution"] = track_contribution
        track_score_raw += track_contribution
        track_confidence_numerator += weight_raw * state["coverage"]
        groups_rows.append(
            {
                "id": group_id,
                "score": round(state["score"], 6),
                "available": state["available"],
                "coverage": round(state["coverage"], 6),
                "weight_raw": round(weight_raw, 6),
                "weight_norm_in_track": round(weight_norm_in_track, 6),
                "track_contribution": round(track_contribution, 6),
            }
        )
        for row in state["rows"]:
            row["track_contribution"] = round(weight_norm_in_track * row["group_contribution"], 6)
            row.pop("_w_eff", None)
            dimensions_rows.append(row)

    track_score = _clamp(track_score_raw)
    track_confidence = (
        _clamp01(track_confidence_numerator / confidence_denominator) if confidence_denominator > 0 else 0.0
    )
    return {
        "dimensions": dimensions_rows,
        "groups": groups_rows,
        "track": {
            "score": round(track_score, 6),
            "confidence": round(track_confidence, 6),
            "available": any(item["available"] for item in groups_rows),
            "track_unavailable": not any(item["available"] for item in groups_rows),
        },
    }


def score_fusion(
    *,
    technical: Mapping[str, Any],
    context: Mapping[str, Any],
    dual_track: Mapping[str, Any],
    volatility_regime_score: float | None = None,
) -> dict[str, Any]:
    track_weights = dual_track.get("track_weights") if isinstance(dual_track.get("track_weights"), Mapping) else {}
    tech_weight_raw = max(0.0, _to_float(track_weights.get("tech"), 0.0))
    context_weight_raw = max(0.0, _to_float(track_weights.get("context"), 0.0))
    denominator = tech_weight_raw + context_weight_raw
    if denominator <= 0:
        raise ValueError("track weight denominator must be > 0")
    tech_weight_norm = tech_weight_raw / denominator
    context_weight_norm = context_weight_raw / denominator

    tech_enabled = tech_weight_raw > 0
    context_enabled = context_weight_raw > 0
    tech_score = _to_float((technical.get("track") or {}).get("score"), 0.0)
    context_score = _to_float((context.get("track") or {}).get("score"), 0.0)
    tech_confidence = _to_float((technical.get("track") or {}).get("confidence"), 0.0)
    context_confidence = _to_float((context.get("track") or {}).get("confidence"), 0.0)

    fusion_score = _clamp(tech_weight_norm * tech_score + context_weight_norm * context_score)
    fusion_confidence_base = _clamp01(tech_weight_norm * tech_confidence + context_weight_norm * context_confidence)

    if tech_enabled and context_enabled:
        sign_conflict_min_abs_score = max(0.0, _to_float(dual_track.get("sign_conflict_min_abs_score"), 0.0))
        sign_conflict = (
            1
            if (
                tech_score * context_score < 0
                and abs(tech_score) >= sign_conflict_min_abs_score
                and abs(context_score) >= sign_conflict_min_abs_score
            )
            else 0
        )
        divergence = abs(tech_score - context_score) / 2.0
        lambda_divergence = _clamp01(_to_float(dual_track.get("lambda_divergence"), 0.0))
        lambda_sign_conflict = _clamp01(_to_float(dual_track.get("lambda_sign_conflict"), 0.0))
        divergence_penalty = _clamp01(lambda_divergence * divergence + lambda_sign_conflict * sign_conflict)
    else:
        sign_conflict = 0
        divergence = 0.0
        divergence_penalty = 0.0

    fusion_confidence = _clamp01(fusion_confidence_base * (1 - divergence_penalty))
    threshold_mode = str(dual_track.get("threshold_mode") or "static")
    buy_threshold_base = _to_float(dual_track.get("fusion_buy_threshold"), 0.0)
    sell_threshold_base = _to_float(dual_track.get("fusion_sell_threshold"), 0.0)
    threshold_missing_reason: str | None = None
    if threshold_mode == "static":
        buy_threshold_eff = buy_threshold_base
        sell_threshold_eff = sell_threshold_base
        volatility_score = 0.0 if volatility_regime_score is None else _clamp(_to_float(volatility_regime_score))
    elif threshold_mode == "volatility_adjusted":
        if volatility_regime_score is None:
            missing_policy = str(dual_track.get("threshold_volatility_missing_policy") or "neutral_zero")
            if missing_policy == "fail_fast":
                raise ValueError("volatility_regime_score is required for threshold_mode=volatility_adjusted")
            threshold_missing_reason = "threshold_volatility_missing_neutral"
            volatility_score = 0.0
        else:
            volatility_score = _clamp(_to_float(volatility_regime_score))
        buy_vol_k = max(0.0, _to_float(dual_track.get("buy_vol_k"), 0.0))
        sell_vol_k = max(0.0, _to_float(dual_track.get("sell_vol_k"), 0.0))
        positive_vol = max(volatility_score, 0.0)
        buy_threshold_eff = buy_threshold_base + buy_vol_k * positive_vol
        sell_threshold_eff = sell_threshold_base - sell_vol_k * positive_vol
    else:
        raise ValueError(f"unsupported threshold_mode: {threshold_mode}")

    if buy_threshold_eff <= sell_threshold_eff:
        raise ValueError("effective thresholds are invalid: buy_threshold_eff must be greater than sell_threshold_eff")

    weighted_threshold_action = "HOLD"
    if fusion_score >= buy_threshold_eff:
        weighted_threshold_action = "BUY"
    elif fusion_score <= sell_threshold_eff:
        weighted_threshold_action = "SELL"

    weighted_action_raw = weighted_threshold_action
    gate_fail_reasons: list[str] = []
    min_fusion_confidence = _to_float(dual_track.get("min_fusion_confidence"), 0.0)
    if fusion_confidence < min_fusion_confidence:
        weighted_action_raw = "HOLD"
        gate_fail_reasons.append("fusion_confidence_below_min")
    elif weighted_threshold_action == "BUY":
        min_tech_score = _to_float(dual_track.get("min_tech_score_for_buy"), 0.0)
        min_context_score = _to_float(dual_track.get("min_context_score_for_buy"), 0.0)
        min_tech_confidence = _to_float(dual_track.get("min_tech_confidence_for_buy"), 0.0)
        min_context_confidence = _to_float(dual_track.get("min_context_confidence_for_buy"), 0.0)
        if tech_enabled and tech_score < min_tech_score:
            gate_fail_reasons.append("tech_score_below_min_for_buy")
        if context_enabled and context_score < min_context_score:
            gate_fail_reasons.append("context_score_below_min_for_buy")
        if tech_enabled and tech_confidence < min_tech_confidence:
            gate_fail_reasons.append("tech_confidence_below_min_for_buy")
        if context_enabled and context_confidence < min_context_confidence:
            gate_fail_reasons.append("context_confidence_below_min_for_buy")
        if gate_fail_reasons:
            weighted_action_raw = "HOLD"

    return {
        "mode": str(dual_track.get("mode") or "rule_only"),
        "tech_weight_raw": round(tech_weight_raw, 6),
        "context_weight_raw": round(context_weight_raw, 6),
        "tech_weight_norm": round(tech_weight_norm, 6),
        "context_weight_norm": round(context_weight_norm, 6),
        "tech_score": round(tech_score, 6),
        "context_score": round(context_score, 6),
        "fusion_score": round(fusion_score, 6),
        "tech_confidence": round(tech_confidence, 6),
        "context_confidence": round(context_confidence, 6),
        "fusion_confidence_base": round(fusion_confidence_base, 6),
        "fusion_confidence": round(fusion_confidence, 6),
        "sign_conflict": sign_conflict,
        "divergence": round(divergence, 6),
        "divergence_penalty": round(divergence_penalty, 6),
        "threshold_mode": threshold_mode,
        "volatility_regime_score": round(volatility_score, 6),
        "threshold_missing_reason": threshold_missing_reason,
        "buy_threshold_base": round(buy_threshold_base, 6),
        "sell_threshold_base": round(sell_threshold_base, 6),
        "buy_threshold_eff": round(buy_threshold_eff, 6),
        "sell_threshold_eff": round(sell_threshold_eff, 6),
        "sell_precedence_gate": round(_to_float(dual_track.get("sell_precedence_gate"), 0.0), 6),
        "weighted_threshold_action": weighted_threshold_action,
        "weighted_action_raw": weighted_action_raw,
        "weighted_gate_fail_reasons": gate_fail_reasons,
        "tech_enabled": tech_enabled,
        "context_enabled": context_enabled,
    }
