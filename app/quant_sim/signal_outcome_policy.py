"""Strategy-profile defaults for signal outcome scoring and feedback."""

from __future__ import annotations

from typing import Any

DEFAULT_OUTCOME_HORIZONS = (3, 5, 10)

OUTCOME_POLICY_PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "aggressive": {
        "outcome_feedback_enabled": True,
        "outcome_horizons_checkpoints": list(DEFAULT_OUTCOME_HORIZONS),
        "buy_target_pct": 4.0,
        "buy_invalidation_mae_pct": -4.5,
        "sell_validation_drawdown_pct": 3.0,
        "missed_upside_penalty_pct": 5.0,
        "min_feedback_samples": 3,
        "feedback_lookback_days": 30,
        "poor_buy_score_threshold": 45,
        "good_sell_score_threshold": 65,
        "feedback_size_multiplier_floor": 0.30,
    },
    "stable": {
        "outcome_feedback_enabled": True,
        "outcome_horizons_checkpoints": list(DEFAULT_OUTCOME_HORIZONS),
        "buy_target_pct": 3.0,
        "buy_invalidation_mae_pct": -3.5,
        "sell_validation_drawdown_pct": 2.5,
        "missed_upside_penalty_pct": 4.0,
        "min_feedback_samples": 4,
        "feedback_lookback_days": 45,
        "poor_buy_score_threshold": 50,
        "good_sell_score_threshold": 70,
        "feedback_size_multiplier_floor": 0.25,
    },
    "conservative": {
        "outcome_feedback_enabled": True,
        "outcome_horizons_checkpoints": list(DEFAULT_OUTCOME_HORIZONS),
        "buy_target_pct": 2.5,
        "buy_invalidation_mae_pct": -2.8,
        "sell_validation_drawdown_pct": 2.0,
        "missed_upside_penalty_pct": 3.0,
        "min_feedback_samples": 5,
        "feedback_lookback_days": 60,
        "poor_buy_score_threshold": 55,
        "good_sell_score_threshold": 75,
        "feedback_size_multiplier_floor": 0.20,
    },
}


def normalize_signal_outcome_policy(
    raw: dict[str, Any] | None,
    *,
    profile_id: str | None = None,
) -> dict[str, Any]:
    key = str(profile_id or "").strip().lower()
    if "conservative" in key:
        policy = dict(OUTCOME_POLICY_PROFILE_DEFAULTS["conservative"])
    elif "stable" in key or "neutral" in key:
        policy = dict(OUTCOME_POLICY_PROFILE_DEFAULTS["stable"])
    else:
        policy = dict(OUTCOME_POLICY_PROFILE_DEFAULTS["aggressive"])
    if isinstance(raw, dict):
        policy.update(raw)
    policy["outcome_feedback_enabled"] = _truthy(policy.get("outcome_feedback_enabled"), True)
    policy["outcome_horizons_checkpoints"] = _horizons(policy.get("outcome_horizons_checkpoints"))
    policy["buy_target_pct"] = max(_float(policy.get("buy_target_pct"), 4.0), 0.1)
    policy["buy_invalidation_mae_pct"] = min(_float(policy.get("buy_invalidation_mae_pct"), -4.5), -0.1)
    policy["sell_validation_drawdown_pct"] = max(_float(policy.get("sell_validation_drawdown_pct"), 3.0), 0.1)
    policy["missed_upside_penalty_pct"] = max(_float(policy.get("missed_upside_penalty_pct"), 5.0), 0.1)
    policy["min_feedback_samples"] = max(1, int(_float(policy.get("min_feedback_samples"), 3)))
    policy["feedback_lookback_days"] = max(1, int(_float(policy.get("feedback_lookback_days"), 30)))
    policy["poor_buy_score_threshold"] = _clamp(_float(policy.get("poor_buy_score_threshold"), 45), 0.0, 100.0)
    policy["good_sell_score_threshold"] = _clamp(_float(policy.get("good_sell_score_threshold"), 65), 0.0, 100.0)
    policy["feedback_size_multiplier_floor"] = _clamp(
        _float(policy.get("feedback_size_multiplier_floor"), 0.3),
        0.0,
        1.0,
    )
    return policy


def _truthy(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _horizons(value: Any) -> list[int]:
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = list(DEFAULT_OUTCOME_HORIZONS)
    parsed = sorted({max(1, int(_float(item, 0))) for item in items if _float(item, 0) > 0})
    return parsed or list(DEFAULT_OUTCOME_HORIZONS)


def _float(value: Any, default: float) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
