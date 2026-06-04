"""Execution sizing policy for quant BUY signals."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

BUY_TIER_ORDER = {"strong_buy": 0, "normal_buy": 1, "weak_buy": 2}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _profile_key(profile_id: str | None) -> str:
    text = str(profile_id or "").lower()
    if "aggressive" in text:
        return "aggressive"
    if "conservative" in text:
        return "conservative"
    return "stable"


def default_execution_position_cap_policy(profile_id: str | None = None) -> dict[str, Any]:
    key = _profile_key(profile_id)
    policies: dict[str, dict[str, Any]] = {
        "aggressive": {
            "buy_tier_cap_pct": {"weak_buy": 7.0, "normal_buy": 9.0, "strong_buy": 15.0},
            "lifecycle_cap_pct": {
                "trial": {"weak_buy": 3.0, "normal_buy": 6.0, "strong_buy": 10.0},
                "active": {"weak_buy": 7.0, "normal_buy": 9.0, "strong_buy": 15.0},
                "exit_only": {"weak_buy": 0.0, "normal_buy": 0.0, "strong_buy": 0.0},
            },
            "single_trade_risk_budget_pct": {"weak_buy": 0.30, "normal_buy": 0.45, "strong_buy": 0.65},
            "checkpoint_trial_risk_budget_pct": 0.80,
            "daily_trial_risk_budget_pct": 1.50,
            "trial_total_exposure_cap_pct": 20.0,
            "weak_buy_total_exposure_cap_pct": 12.0,
            "weak_buy_quality_reserve_cap_pct": 3.0,
            "weak_buy_min_execution_strength": 0.45,
            "active_guarded_confirmed_cap_pct": 9.0,
            "trial_guarded_confirmed_cap_pct": 6.0,
            "trial_guarded_strong_confirmed_cap_pct": 8.0,
            "trial_guarded_confirmed_positive_outcome_cap_pct": 8.0,
            "trial_guarded_strong_positive_outcome_cap_pct": 10.0,
            "trial_guarded_confirmed_positive_outcome_min_score": 55.0,
            "trial_guarded_confirmed_min_strength": 0.50,
            "trial_guarded_strong_confirmed_min_strength": 0.72,
            "trial_guarded_confirmed_min_confirmation": 0.75,
            "trial_guarded_confirmed_min_edge": 0.55,
            "trial_guarded_confirmed_min_volume_score": 0.60,
            "trial_guarded_confirmed_min_above_ma20": 4,
            "trial_guarded_confirmed_max_recent_return": 0.055,
            "trial_guarded_confirmed_max_ma20_distance": 0.045,
            "trial_guarded_confirmed_max_risk_penalty": 0.28,
            "recovery_probe_confirmed_floor_pct": 6.0,
            "recovery_probe_confirmed_cap_pct": 6.0,
            "recovery_probe_confirmed_quality_cap_pct": 8.0,
            "recovery_probe_confirmed_quality_min_strength": 0.55,
            "recovery_probe_confirmed_quality_min_confirmation": 0.65,
            "recovery_probe_confirmed_quality_min_above_ma20": 4,
            "recovery_probe_confirmed_quality_min_volume_score": 1.0,
            "recovery_probe_confirmed_quality_max_recent_return": 0.04,
            "recovery_probe_confirmed_quality_max_ma20_distance": 0.025,
            "recovery_probe_confirmed_positive_outcome_cap_pct": 12.5,
            "recovery_probe_confirmed_positive_outcome_min_score": 55.0,
            "recovery_probe_confirmed_positive_outcome_min_kernel_pct": 35.0,
            "recovery_probe_confirmed_risk_budget_pct": 0.625,
            "account_equity_tier_caps": [
                {"lt": 100000, "cap_pct": 18.0, "max_cash": 18000.0},
                {"lt": 300000, "cap_pct": 15.0, "max_cash": 35000.0},
                {"lt": 800000, "cap_pct": 12.5, "max_cash": 70000.0},
                {"lt": None, "cap_pct": 8.0, "max_cash": 100000.0},
            ],
        },
        "stable": {
            "buy_tier_cap_pct": {"weak_buy": 3.5, "normal_buy": 7.0, "strong_buy": 12.0},
            "lifecycle_cap_pct": {
                "trial": {"weak_buy": 2.0, "normal_buy": 4.5, "strong_buy": 8.0},
                "active": {"weak_buy": 3.5, "normal_buy": 7.0, "strong_buy": 12.0},
                "exit_only": {"weak_buy": 0.0, "normal_buy": 0.0, "strong_buy": 0.0},
            },
            "single_trade_risk_budget_pct": {"weak_buy": 0.20, "normal_buy": 0.35, "strong_buy": 0.50},
            "checkpoint_trial_risk_budget_pct": 0.50,
            "daily_trial_risk_budget_pct": 1.00,
            "trial_total_exposure_cap_pct": 12.0,
            "weak_buy_total_exposure_cap_pct": 8.0,
            "weak_buy_quality_reserve_cap_pct": 2.0,
            "weak_buy_min_execution_strength": 0.35,
            "active_guarded_confirmed_cap_pct": 7.0,
            "trial_guarded_confirmed_cap_pct": 5.0,
            "trial_guarded_strong_confirmed_cap_pct": 6.5,
            "trial_guarded_confirmed_positive_outcome_cap_pct": 6.0,
            "trial_guarded_strong_positive_outcome_cap_pct": 8.0,
            "trial_guarded_confirmed_positive_outcome_min_score": 62.0,
            "trial_guarded_confirmed_min_strength": 0.58,
            "trial_guarded_strong_confirmed_min_strength": 0.76,
            "trial_guarded_confirmed_min_confirmation": 0.75,
            "trial_guarded_confirmed_min_edge": 0.60,
            "trial_guarded_confirmed_min_volume_score": 0.70,
            "trial_guarded_confirmed_min_above_ma20": 4,
            "trial_guarded_confirmed_max_recent_return": 0.045,
            "trial_guarded_confirmed_max_ma20_distance": 0.035,
            "trial_guarded_confirmed_max_risk_penalty": 0.22,
            "recovery_probe_confirmed_floor_pct": 4.5,
            "recovery_probe_confirmed_cap_pct": 5.5,
            "recovery_probe_confirmed_quality_cap_pct": 6.5,
            "recovery_probe_confirmed_quality_min_strength": 0.65,
            "recovery_probe_confirmed_quality_min_confirmation": 0.70,
            "recovery_probe_confirmed_quality_min_above_ma20": 4,
            "recovery_probe_confirmed_quality_min_volume_score": 1.0,
            "recovery_probe_confirmed_quality_max_recent_return": 0.035,
            "recovery_probe_confirmed_quality_max_ma20_distance": 0.02,
            "recovery_probe_confirmed_positive_outcome_cap_pct": 7.5,
            "recovery_probe_confirmed_positive_outcome_min_score": 62.0,
            "recovery_probe_confirmed_positive_outcome_min_kernel_pct": 37.0,
            "recovery_probe_confirmed_risk_budget_pct": 0.40,
            "account_equity_tier_caps": [
                {"lt": 100000, "cap_pct": 14.0, "max_cash": 14000.0},
                {"lt": 300000, "cap_pct": 12.0, "max_cash": 28000.0},
                {"lt": 800000, "cap_pct": 10.0, "max_cash": 55000.0},
                {"lt": None, "cap_pct": 6.0, "max_cash": 75000.0},
            ],
        },
        "conservative": {
            "buy_tier_cap_pct": {"weak_buy": 2.0, "normal_buy": 5.0, "strong_buy": 9.0},
            "lifecycle_cap_pct": {
                "trial": {"weak_buy": 1.0, "normal_buy": 3.0, "strong_buy": 6.0},
                "active": {"weak_buy": 2.0, "normal_buy": 5.0, "strong_buy": 9.0},
                "exit_only": {"weak_buy": 0.0, "normal_buy": 0.0, "strong_buy": 0.0},
            },
            "single_trade_risk_budget_pct": {"weak_buy": 0.10, "normal_buy": 0.25, "strong_buy": 0.40},
            "checkpoint_trial_risk_budget_pct": 0.30,
            "daily_trial_risk_budget_pct": 0.60,
            "trial_total_exposure_cap_pct": 8.0,
            "weak_buy_total_exposure_cap_pct": 5.0,
            "weak_buy_quality_reserve_cap_pct": 1.0,
            "weak_buy_min_execution_strength": 0.45,
            "active_guarded_confirmed_cap_pct": 5.0,
            "trial_guarded_confirmed_cap_pct": 4.0,
            "trial_guarded_strong_confirmed_cap_pct": 5.0,
            "trial_guarded_confirmed_positive_outcome_cap_pct": 4.5,
            "trial_guarded_strong_positive_outcome_cap_pct": 6.0,
            "trial_guarded_confirmed_positive_outcome_min_score": 65.0,
            "trial_guarded_confirmed_min_strength": 0.65,
            "trial_guarded_strong_confirmed_min_strength": 0.80,
            "trial_guarded_confirmed_min_confirmation": 0.80,
            "trial_guarded_confirmed_min_edge": 0.65,
            "trial_guarded_confirmed_min_volume_score": 0.80,
            "trial_guarded_confirmed_min_above_ma20": 5,
            "trial_guarded_confirmed_max_recent_return": 0.035,
            "trial_guarded_confirmed_max_ma20_distance": 0.025,
            "trial_guarded_confirmed_max_risk_penalty": 0.16,
            "recovery_probe_confirmed_floor_pct": 3.5,
            "recovery_probe_confirmed_cap_pct": 3.5,
            "recovery_probe_confirmed_quality_cap_pct": 4.5,
            "recovery_probe_confirmed_quality_min_strength": 0.75,
            "recovery_probe_confirmed_quality_min_confirmation": 0.75,
            "recovery_probe_confirmed_quality_min_above_ma20": 5,
            "recovery_probe_confirmed_quality_min_volume_score": 1.0,
            "recovery_probe_confirmed_quality_max_recent_return": 0.03,
            "recovery_probe_confirmed_quality_max_ma20_distance": 0.015,
            "recovery_probe_confirmed_positive_outcome_cap_pct": 5.0,
            "recovery_probe_confirmed_positive_outcome_min_score": 65.0,
            "recovery_probe_confirmed_positive_outcome_min_kernel_pct": 40.0,
            "recovery_probe_confirmed_risk_budget_pct": 0.30,
            "account_equity_tier_caps": [
                {"lt": 100000, "cap_pct": 10.0, "max_cash": 10000.0},
                {"lt": 300000, "cap_pct": 8.0, "max_cash": 20000.0},
                {"lt": 800000, "cap_pct": 7.0, "max_cash": 40000.0},
                {"lt": None, "cap_pct": 4.0, "max_cash": 50000.0},
            ],
        },
    }
    return policies[key]


def _account_tier(policy: dict[str, Any], total_equity: float) -> dict[str, float]:
    for row in policy["account_equity_tier_caps"]:
        limit = row.get("lt")
        if limit is None or total_equity < float(limit):
            return {"cap_pct": float(row["cap_pct"]), "max_cash": float(row["max_cash"])}
    last = policy["account_equity_tier_caps"][-1]
    return {"cap_pct": float(last["cap_pct"]), "max_cash": float(last["max_cash"])}


def _buy_tier(signal: dict[str, Any]) -> str:
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    gate = profile.get("portfolio_execution_guard") if isinstance(profile.get("portfolio_execution_guard"), dict) else {}
    plan = profile.get("execution_sizing_plan") if isinstance(profile.get("execution_sizing_plan"), dict) else {}
    tier = str(plan.get("buy_tier") or gate.get("buy_tier") or gate.get("initial_buy_tier") or "normal_buy").strip().lower()
    return tier if tier in {"weak_buy", "normal_buy", "strong_buy"} else "normal_buy"


def _signal_plan(signal: dict[str, Any]) -> dict[str, Any]:
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    plan = profile.get("execution_sizing_plan") if isinstance(profile.get("execution_sizing_plan"), dict) else {}
    return plan


def _signal_quant_status(signal: dict[str, Any]) -> str:
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    plan = profile.get("execution_sizing_plan") if isinstance(profile.get("execution_sizing_plan"), dict) else {}
    return str(plan.get("quant_status_for_portfolio_budget") or profile.get("quant_status") or signal.get("quant_status") or "active").strip().lower()


def _outcome_feedback_score(signal: dict[str, Any]) -> float:
    feedback = _outcome_feedback_payload(signal)
    summary = feedback.get("summary") if isinstance(feedback.get("summary"), dict) else feedback
    return _float(summary.get("outcome_feedback_score") or feedback.get("feedback_score"), 50.0)


def _outcome_feedback_payload(signal: dict[str, Any]) -> dict[str, Any]:
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    feedback = profile.get("outcome_feedback") if isinstance(profile.get("outcome_feedback"), dict) else {}
    market = profile.get("market_snapshot") if isinstance(profile.get("market_snapshot"), dict) else {}
    if not feedback and isinstance(market.get("outcome_feedback"), dict):
        feedback = market["outcome_feedback"]
    return feedback if isinstance(feedback, dict) else {}


def _has_positive_recovery_outcome(signal: dict[str, Any], policy: dict[str, Any]) -> bool:
    feedback = _outcome_feedback_payload(signal)
    summary = feedback.get("summary") if isinstance(feedback.get("summary"), dict) else feedback
    score = _float(summary.get("outcome_feedback_score") or feedback.get("feedback_score"), 50.0)
    sample_count = int(_float(summary.get("sample_count") or feedback.get("sample_count"), 0.0))
    actionable = summary.get("actionable")
    if actionable is False:
        return False
    return bool(
        sample_count > 0
        and score >= _float(policy.get("recovery_probe_confirmed_positive_outcome_min_score"), 60.0)
    )


def _has_positive_trial_guarded_outcome(signal: dict[str, Any], policy: dict[str, Any]) -> bool:
    feedback = _outcome_feedback_payload(signal)
    summary = feedback.get("summary") if isinstance(feedback.get("summary"), dict) else feedback
    score = _float(summary.get("outcome_feedback_score") or feedback.get("feedback_score"), 50.0)
    sample_count = int(_float(summary.get("sample_count") or feedback.get("sample_count"), 0.0))
    actionable = summary.get("actionable")
    if actionable is False:
        return False
    return bool(
        sample_count > 0
        and score >= _float(policy.get("trial_guarded_confirmed_positive_outcome_min_score"), 60.0)
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "up", "bull", "bullish"}
    return bool(value)


def _ratio_value(value: Any) -> float | None:
    numeric = _float(value, None)
    if numeric is None:
        return None
    if abs(numeric) > 2.0:
        return numeric / 100.0
    return numeric


def _percent_field_ratio(value: Any) -> float | None:
    numeric = _float(value, None)
    if numeric is None:
        return None
    if abs(numeric) > 1.0:
        return numeric / 100.0
    return numeric


def _recovery_probe_quality_confirmed(signal: dict[str, Any], policy: dict[str, Any]) -> bool:
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    guard = profile.get("portfolio_execution_guard") if isinstance(profile.get("portfolio_execution_guard"), dict) else {}
    trend = guard.get("trend_confirmation") if isinstance(guard.get("trend_confirmation"), dict) else {}
    components = guard.get("score_components") if isinstance(guard.get("score_components"), dict) else {}
    strength = _float(guard.get("buy_strength_score"), 0.0)
    confirmation = _float(components.get("confirmation_score"), 0.0)
    volume_score = _float(components.get("volume_score"), 0.0)
    above_ma20 = int(_float(trend.get("above_ma20_checkpoints"), 0.0))
    min_strength = _float(policy.get("recovery_probe_confirmed_quality_min_strength"), 0.70)
    min_confirmation = _float(policy.get("recovery_probe_confirmed_quality_min_confirmation"), 0.65)
    min_above_ma20 = int(_float(policy.get("recovery_probe_confirmed_quality_min_above_ma20"), 4))
    min_volume_score = _float(policy.get("recovery_probe_confirmed_quality_min_volume_score"), 0.0)
    max_recent_return = _float(policy.get("recovery_probe_confirmed_quality_max_recent_return"), 0.04)
    max_ma20_distance = _float(policy.get("recovery_probe_confirmed_quality_max_ma20_distance"), 0.0)
    recent_return = _ratio_value(trend.get("recent_5d_return"))
    ma20_distance = _percent_field_ratio(trend.get("ma20_distance_pct"))
    if strength < min_strength or confirmation < min_confirmation:
        return False
    if volume_score < min_volume_score:
        return False
    if recent_return is not None and recent_return >= max_recent_return:
        return False
    if max_ma20_distance > 0 and ma20_distance is not None and ma20_distance >= max_ma20_distance:
        return False
    if _truthy(trend.get("retest_confirmed")):
        return True
    if _truthy(trend.get("ma_stack")) and _truthy(trend.get("ma20_rising")):
        return True
    return bool(_truthy(trend.get("ma20_rising")) and above_ma20 >= min_above_ma20)


def _trial_guarded_quality_confirmed(signal: dict[str, Any], policy: dict[str, Any]) -> bool:
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    guard = profile.get("portfolio_execution_guard") if isinstance(profile.get("portfolio_execution_guard"), dict) else {}
    tier = str(guard.get("buy_tier") or guard.get("status") or "").strip().lower()
    if tier not in {"normal_buy", "strong_buy"}:
        return False
    trend = guard.get("trend_confirmation") if isinstance(guard.get("trend_confirmation"), dict) else {}
    components = guard.get("score_components") if isinstance(guard.get("score_components"), dict) else {}
    strength = _float(guard.get("buy_strength_score"), 0.0)
    min_strength = _float(policy.get("trial_guarded_confirmed_min_strength"), 0.55)
    if tier == "strong_buy":
        min_strength = _float(policy.get("trial_guarded_strong_confirmed_min_strength"), min_strength)
    confirmation = _float(components.get("confirmation_score"), 0.0)
    edge = _float(components.get("edge_strength"), 0.0)
    volume_score = _float(components.get("volume_score"), 0.0)
    risk_penalty = _float(components.get("risk_penalty"), 0.0)
    above_ma20 = int(_float(trend.get("above_ma20_checkpoints"), 0.0))
    recent_return = _ratio_value(trend.get("recent_5d_return"))
    ma20_distance = _percent_field_ratio(trend.get("ma20_distance_pct"))
    if strength < min_strength:
        return False
    if confirmation < _float(policy.get("trial_guarded_confirmed_min_confirmation"), 0.75):
        return False
    if edge < _float(policy.get("trial_guarded_confirmed_min_edge"), 0.55):
        return False
    if volume_score < _float(policy.get("trial_guarded_confirmed_min_volume_score"), 0.60):
        return False
    if risk_penalty > _float(policy.get("trial_guarded_confirmed_max_risk_penalty"), 0.25):
        return False
    max_recent_return = _float(policy.get("trial_guarded_confirmed_max_recent_return"), 0.05)
    if recent_return is not None and recent_return > max_recent_return:
        return False
    max_ma20_distance = _float(policy.get("trial_guarded_confirmed_max_ma20_distance"), 0.04)
    if max_ma20_distance > 0 and ma20_distance is not None and ma20_distance > max_ma20_distance:
        return False
    if _truthy(trend.get("retest_confirmed")):
        return True
    if _truthy(trend.get("ma_stack")) and _truthy(trend.get("ma20_rising")):
        return True
    return bool(
        _truthy(trend.get("ma20_rising"))
        and above_ma20 >= int(_float(policy.get("trial_guarded_confirmed_min_above_ma20"), 4))
    )


def _execution_batch_risk_pct(signal: dict[str, Any], plan: dict[str, Any]) -> float:
    explicit = plan.get("batch_risk_pct")
    if explicit not in (None, ""):
        return max(_float(explicit), 0.0)
    effective_pct = _float(plan.get("effective_position_pct"), _float(signal.get("position_size_pct"), 0.0))
    stop_loss_pct = _float(plan.get("expected_stop_loss_pct"), _float(signal.get("stop_loss_pct"), 5.0))
    if effective_pct > 0 and stop_loss_pct > 0:
        return max(effective_pct * stop_loss_pct / 100.0, 0.0)
    return max(_float(plan.get("risk_budget_pct"), 0.0), 0.0)


def _batch_risk_pct_for_budget(signal: dict[str, Any], plan: dict[str, Any], *, total_equity: float, budget: float) -> float:
    if total_equity <= 0 or budget <= 0:
        return _execution_batch_risk_pct(signal, plan)
    stop_loss_pct = max(_float(plan.get("expected_stop_loss_pct"), _float(signal.get("stop_loss_pct"), 5.0)), 0.0)
    if stop_loss_pct <= 0:
        return _execution_batch_risk_pct(signal, plan)
    return max((budget / total_equity * 100.0) * stop_loss_pct / 100.0, 0.0)


def _trial_exposure_budget(signal: dict[str, Any], plan: dict[str, Any], final_budget: float) -> float:
    if _quality_limited_one_lot_priority(signal, plan):
        return max(float(final_budget or 0.0), _float(plan.get("one_lot_cost"), 0.0))
    return float(final_budget or 0.0)


def _replace_signal_plan(signal: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    adjusted = deepcopy(signal)
    profile = adjusted.setdefault("strategy_profile", {})
    if not isinstance(profile, dict):
        profile = {}
        adjusted["strategy_profile"] = profile
    plan = profile.setdefault("execution_sizing_plan", {})
    if not isinstance(plan, dict):
        plan = {}
        profile["execution_sizing_plan"] = plan
    plan.update(updates)
    return adjusted


def _clip_signal_budget(
    signal: dict[str, Any],
    plan: dict[str, Any],
    *,
    allowed_budget: float,
    total_equity: float,
    reason_code: str,
) -> tuple[dict[str, Any], dict[str, Any], float, float]:
    final_budget = max(_float(plan.get("final_budget"), 0.0), 0.0)
    allowed_budget = max(float(allowed_budget or 0.0), 0.0)
    if final_budget <= 0 or allowed_budget <= 0 or allowed_budget >= final_budget:
        batch_risk = _execution_batch_risk_pct(signal, plan)
        return signal, plan, final_budget, batch_risk
    stop_loss_pct = max(_float(plan.get("expected_stop_loss_pct"), _float(signal.get("stop_loss_pct"), 5.0)), 0.0)
    effective_pct = (allowed_budget / max(float(total_equity or 0.0), 0.0001)) * 100.0
    batch_risk = max(effective_pct * stop_loss_pct / 100.0, 0.0)
    updates = {
        "final_budget": round(allowed_budget, 6),
        "effective_position_pct": round(effective_pct, 6),
        "batch_risk_pct": round(batch_risk, 6),
        "batch_cap_adjustment": {
            "reason_code": reason_code,
            "original_final_budget": round(final_budget, 6),
            "adjusted_final_budget": round(allowed_budget, 6),
        },
    }
    adjusted_signal = _replace_signal_plan(signal, updates)
    adjusted_plan = _signal_plan(adjusted_signal)
    return adjusted_signal, adjusted_plan, allowed_budget, batch_risk


def _priority(signal: dict[str, Any]) -> tuple[int, int, float, float, float, int]:
    plan = _signal_plan(signal)
    tier = str(plan.get("buy_tier") or _buy_tier(signal)).strip().lower()
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    gate = profile.get("portfolio_execution_guard") if isinstance(profile.get("portfolio_execution_guard"), dict) else {}
    strength = _float(gate.get("buy_strength_score"), 0.0)
    feedback_score = _outcome_feedback_score(signal)
    confidence = _float(signal.get("confidence"), 0.0)
    signal_id = int(_float(signal.get("id"), 0.0))
    lifecycle_priority = 0 if _quality_limited_one_lot_priority(signal, plan) else _lifecycle_priority(plan)
    return (lifecycle_priority, BUY_TIER_ORDER.get(tier, 9), -feedback_score, -strength, -confidence, signal_id)


def _lifecycle_priority(plan: dict[str, Any]) -> int:
    mode = str(plan.get("lifecycle_gate_mode") or "").strip().lower()
    if mode == "recovery_probe_confirmed":
        return 0
    if mode in {"", "normal_scan", "trial_confirmed"}:
        return 1
    if mode == "trial_light":
        return 2
    if mode == "strong_recovery_confirmed":
        return 3
    if mode in {"cooling_supplemental", "recovery_probe", "recovery_probe_quality_limited"}:
        return 4
    return 1


def _score_component(signal: dict[str, Any], key: str, default: float = 0.0) -> float:
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    guard = profile.get("portfolio_execution_guard") if isinstance(profile.get("portfolio_execution_guard"), dict) else {}
    components = guard.get("score_components") if isinstance(guard.get("score_components"), dict) else {}
    return _float(components.get(key), default)


def _quality_limited_one_lot_priority(signal: dict[str, Any], plan: dict[str, Any]) -> bool:
    mode = str(plan.get("lifecycle_gate_mode") or "").strip().lower()
    tier = str(plan.get("buy_tier") or _buy_tier(signal)).strip().lower()
    if mode != "recovery_probe_quality_limited" or tier != "strong_buy":
        return False
    final_budget = _float(plan.get("final_budget"), 0.0)
    one_lot_cost = _float(plan.get("one_lot_cost"), 0.0)
    if one_lot_cost <= 0 or final_budget / one_lot_cost < 0.4:
        return False
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    guard = profile.get("portfolio_execution_guard") if isinstance(profile.get("portfolio_execution_guard"), dict) else {}
    trend = guard.get("trend_confirmation") if isinstance(guard.get("trend_confirmation"), dict) else {}
    market_snapshot = profile.get("market_snapshot") if isinstance(profile.get("market_snapshot"), dict) else {}
    strength = _float(guard.get("buy_strength_score"), 0.0)
    edge = _score_component(signal, "edge_strength", 0.0)
    confirmation = _score_component(signal, "confirmation_score", 0.0)
    rsi = _float(
        market_snapshot.get("rsi")
        or market_snapshot.get("rsi12")
        or market_snapshot.get("rsi_12")
        or trend.get("rsi"),
        50.0,
    )
    recent_return = _ratio_value(
        trend.get("recent_5d_return")
        if trend.get("recent_5d_return") not in (None, "")
        else market_snapshot.get("recent_5d_return")
    )
    if strength < 0.90 or edge < 0.90 or confirmation < 0.90:
        return False
    if rsi > 80.0:
        return False
    if recent_return is not None and recent_return > 0.08:
        return False
    return True


def _high_quality_weak_buy(signal: dict[str, Any]) -> bool:
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    guard = profile.get("portfolio_execution_guard") if isinstance(profile.get("portfolio_execution_guard"), dict) else {}
    trend = guard.get("trend_confirmation") if isinstance(guard.get("trend_confirmation"), dict) else {}
    strength = _float(guard.get("buy_strength_score"), 0.0)
    feedback_score = _outcome_feedback_score(signal)
    edge_strength = _score_component(signal, "edge_strength", 0.0)
    trend_score = _score_component(signal, "trend_structure_score", 0.0)
    confirmation_score = _score_component(signal, "confirmation_score", 0.0)
    volume_score = _score_component(signal, "volume_score", 0.0)
    risk_penalty = _score_component(signal, "risk_penalty", 0.0)
    above_ma20 = int(_float(trend.get("above_ma20_checkpoints"), 0.0))
    recent_return = _ratio_value(trend.get("recent_5d_return"))
    has_confirmed_structure = bool(
        _truthy(trend.get("retest_confirmed"))
        or (
            _truthy(trend.get("ma_stack"))
            and _truthy(trend.get("ma20_rising"))
            and above_ma20 >= 16
            and (recent_return is None or recent_return <= 0.05)
        )
    )
    return bool(
        strength >= 0.52
        and feedback_score >= 50.0
        and edge_strength >= 0.02
        and trend_score >= 0.9
        and confirmation_score >= 0.9
        and volume_score >= 0.6
        and risk_penalty <= 0.12
        and has_confirmed_structure
    )


def _confirmed_partial_weak_buy(signal: dict[str, Any]) -> bool:
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    guard = profile.get("portfolio_execution_guard") if isinstance(profile.get("portfolio_execution_guard"), dict) else {}
    trend = guard.get("trend_confirmation") if isinstance(guard.get("trend_confirmation"), dict) else {}
    strength = _float(guard.get("buy_strength_score"), 0.0)
    feedback_score = _outcome_feedback_score(signal)
    trend_score = _score_component(signal, "trend_structure_score", 0.0)
    confirmation_score = _score_component(signal, "confirmation_score", 0.0)
    volume_score = _score_component(signal, "volume_score", 0.0)
    risk_penalty = _score_component(signal, "risk_penalty", 0.0)
    above_ma20 = int(_float(trend.get("above_ma20_checkpoints"), 0.0))
    recent_return = _ratio_value(trend.get("recent_5d_return"))
    rsi = _float(trend.get("rsi"), 50.0)
    return bool(
        strength >= 0.60
        and feedback_score >= 50.0
        and trend_score >= 0.9
        and confirmation_score >= 0.9
        and volume_score >= 0.6
        and risk_penalty <= 0.08
        and _truthy(trend.get("ma_stack"))
        and _truthy(trend.get("ma20_rising"))
        and above_ma20 >= 8
        and rsi <= 72.0
        and (recent_return is None or recent_return <= 0.05)
    )


def _budget_is_below_one_lot(plan: dict[str, Any], budget: float) -> bool:
    one_lot_cost = _float(plan.get("one_lot_cost"), 0.0)
    return one_lot_cost > 0 and float(budget or 0.0) + 1e-9 < one_lot_cost


def apply_batch_execution_caps(
    *,
    signals: list[dict[str, Any]],
    total_equity: float,
    existing_trial_market_value: float,
    existing_weak_buy_market_value: float,
    day_trial_risk_used_pct: float,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    checkpoint_trial_risk = 0.0
    day_trial_risk = float(day_trial_risk_used_pct or 0.0)
    trial_exposure = float(existing_trial_market_value or 0.0)
    weak_exposure = float(existing_weak_buy_market_value or 0.0)
    trial_exposure_cap = float(total_equity) * float(policy["trial_total_exposure_cap_pct"]) / 100.0
    weak_exposure_cap = float(total_equity) * float(policy["weak_buy_total_exposure_cap_pct"]) / 100.0
    weak_quality_reserve_cap = float(total_equity) * float(policy.get("weak_buy_quality_reserve_cap_pct", 0.0)) / 100.0
    weak_quality_reserve_used = 0.0
    rows: list[dict[str, Any]] = []
    for original_signal in sorted(signals, key=_priority):
        signal = original_signal
        plan = _signal_plan(signal)
        tier = str(plan.get("buy_tier") or _buy_tier(signal)).strip().lower()
        status = _signal_quant_status(signal)
        final_budget = _float(plan.get("final_budget"), 0.0)
        batch_risk_pct = _execution_batch_risk_pct(signal, plan)
        trial_budget = _trial_exposure_budget(signal, plan, final_budget)
        if trial_budget > final_budget + 1e-9:
            batch_risk_pct = _batch_risk_pct_for_budget(
                signal,
                plan,
                total_equity=total_equity,
                budget=trial_budget,
            )
        reason_code = ""
        if tier == "weak_buy":
            profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
            guard = (
                profile.get("portfolio_execution_guard")
                if isinstance(profile.get("portfolio_execution_guard"), dict)
                else {}
            )
            min_strength = _float(policy.get("weak_buy_min_execution_strength"), 0.0)
            if _float(guard.get("buy_strength_score"), 0.0) < min_strength:
                reason_code = "weak_buy_strength_floor_not_met"
        if not reason_code and status == "trial":
            remaining_checkpoint_risk = float(policy["checkpoint_trial_risk_budget_pct"]) - checkpoint_trial_risk
            remaining_daily_risk = float(policy["daily_trial_risk_budget_pct"]) - day_trial_risk
            remaining_trial_exposure = trial_exposure_cap - trial_exposure
            if remaining_checkpoint_risk <= 1e-9:
                reason_code = "portfolio_trial_risk_budget_exhausted"
            elif checkpoint_trial_risk + batch_risk_pct > float(policy["checkpoint_trial_risk_budget_pct"]) + 1e-9:
                reason_code = "portfolio_trial_risk_budget_exhausted"
            elif remaining_daily_risk <= 1e-9:
                reason_code = "daily_trial_risk_budget_exhausted"
            elif day_trial_risk + batch_risk_pct > float(policy["daily_trial_risk_budget_pct"]) + 1e-9:
                reason_code = "daily_trial_risk_budget_exhausted"
            elif remaining_trial_exposure <= 1e-9:
                reason_code = "trial_exposure_cap_hit"
            else:
                allowed_budget = final_budget
                adjustment_reason = ""
                if trial_budget > remaining_trial_exposure + 1e-9 and trial_budget > final_budget + 1e-9:
                    reason_code = "trial_exposure_cap_hit"
                elif final_budget > remaining_trial_exposure + 1e-9:
                    allowed_budget = min(allowed_budget, remaining_trial_exposure)
                    adjustment_reason = "trial_exposure_cap_applied"
                if adjustment_reason:
                    signal, plan, final_budget, batch_risk_pct = _clip_signal_budget(
                        signal,
                        plan,
                        allowed_budget=allowed_budget,
                        total_equity=total_equity,
                        reason_code=adjustment_reason,
                    )
                    trial_budget = _trial_exposure_budget(signal, plan, final_budget)
                    if final_budget <= 1e-9:
                        reason_code = adjustment_reason.replace("_applied", "_hit")
                    elif _budget_is_below_one_lot(plan, final_budget) and not _quality_limited_one_lot_priority(
                        signal, plan
                    ):
                        reason_code = "trial_exposure_one_lot_insufficient"
        if not reason_code and tier == "weak_buy" and weak_exposure + final_budget > weak_exposure_cap + 1e-9:
            remaining_weak_exposure = weak_exposure_cap - weak_exposure
            remaining_quality_reserve = (
                weak_exposure_cap
                + weak_quality_reserve_cap
                - weak_exposure
                - weak_quality_reserve_used
            )
            if remaining_weak_exposure > 1e-9:
                if _budget_is_below_one_lot(plan, remaining_weak_exposure):
                    if _high_quality_weak_buy(signal) and remaining_quality_reserve > 1e-9:
                        if _budget_is_below_one_lot(plan, remaining_quality_reserve):
                            reason_code = "weak_buy_quality_reserve_one_lot_insufficient"
                        elif final_budget > remaining_quality_reserve + 1e-9:
                            signal, plan, final_budget, batch_risk_pct = _clip_signal_budget(
                                signal,
                                plan,
                                allowed_budget=remaining_quality_reserve,
                                total_equity=total_equity,
                                reason_code="weak_buy_quality_reserve_applied",
                            )
                        # If the original budget fits the reserve, keep it as is and account reserve below.
                    else:
                        reason_code = "weak_buy_exposure_one_lot_insufficient"
                else:
                    if _confirmed_partial_weak_buy(signal) and remaining_quality_reserve >= final_budget - 1e-9:
                        pass
                    elif _confirmed_partial_weak_buy(signal) and remaining_quality_reserve > remaining_weak_exposure + 1e-9:
                        signal, plan, final_budget, batch_risk_pct = _clip_signal_budget(
                            signal,
                            plan,
                            allowed_budget=remaining_quality_reserve,
                            total_equity=total_equity,
                            reason_code="weak_buy_quality_reserve_applied",
                        )
                    else:
                        signal, plan, final_budget, batch_risk_pct = _clip_signal_budget(
                            signal,
                            plan,
                            allowed_budget=remaining_weak_exposure,
                            total_equity=total_equity,
                            reason_code="weak_buy_exposure_cap_applied",
                        )
            else:
                if _high_quality_weak_buy(signal) and remaining_quality_reserve > 1e-9:
                    if _budget_is_below_one_lot(plan, remaining_quality_reserve):
                        reason_code = "weak_buy_quality_reserve_one_lot_insufficient"
                    elif final_budget > remaining_quality_reserve + 1e-9:
                        signal, plan, final_budget, batch_risk_pct = _clip_signal_budget(
                            signal,
                            plan,
                            allowed_budget=remaining_quality_reserve,
                            total_equity=total_equity,
                            reason_code="weak_buy_quality_reserve_applied",
                        )
                else:
                    reason_code = "weak_buy_exposure_cap_hit"
        if not reason_code and tier == "weak_buy" and _budget_is_below_one_lot(plan, final_budget):
            reason_code = "weak_buy_one_lot_exceeds_risk_budget"
        allowed = not reason_code
        if allowed:
            if status == "trial":
                checkpoint_trial_risk += batch_risk_pct
                day_trial_risk += batch_risk_pct
                trial_exposure += trial_budget
            if tier == "weak_buy":
                if weak_exposure + final_budget > weak_exposure_cap + 1e-9:
                    excess_budget = max(0.0, weak_exposure + final_budget - weak_exposure_cap)
                    weak_quality_reserve_used += excess_budget
                    weak_exposure = min(weak_exposure + final_budget, weak_exposure_cap)
                else:
                    weak_exposure += final_budget
        rows.append(
            {
                "signal_id": signal.get("id"),
                "allowed": allowed,
                "reason_code": reason_code,
                "batch_risk_pct": round(batch_risk_pct, 6),
                "signal": signal,
            }
        )
    return rows


def build_execution_sizing_plan(
    *,
    signal: dict[str, Any],
    total_equity: float,
    available_cash: float,
    slot_available_cash: float,
    quant_status: str,
    policy: dict[str, Any],
    price: float | None = None,
    lot_size: int = 100,
) -> dict[str, Any]:
    tier = _buy_tier(signal)
    status = str(quant_status or "active").strip().lower()
    if status not in {"trial", "active", "exit_only", "cooling", "guarded"}:
        status = "trial"

    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    lifecycle_gate = profile.get("lifecycle_gate") if isinstance(profile.get("lifecycle_gate"), dict) else {}
    stock_feedback_gate = (
        profile.get("stock_execution_feedback_gate")
        if isinstance(profile.get("stock_execution_feedback_gate"), dict)
        else {}
    )
    kernel_positioning = profile.get("kernel_positioning") if isinstance(profile.get("kernel_positioning"), dict) else {}
    if not kernel_positioning:
        explainability = profile.get("explainability") if isinstance(profile.get("explainability"), dict) else {}
        resonance = explainability.get("resonance") if isinstance(explainability.get("resonance"), dict) else {}
        quality_ratio = resonance.get("quality_adjusted_position_ratio")
        if quality_ratio is not None:
            kernel_positioning = {"quality_position_pct": _float(quality_ratio, 0.0) * 100.0}
    raw_kernel_pct = _float(kernel_positioning.get("quality_position_pct"), _float(signal.get("position_size_pct"), 0.0))
    kernel_pct = raw_kernel_pct
    stop_loss_pct = max(_float(signal.get("stop_loss_pct"), 5.0), 0.0001)
    lifecycle_gate_mode = str(lifecycle_gate.get("mode") or "").strip()
    stock_feedback_status = str(stock_feedback_gate.get("status") or "").strip().lower()
    stock_feedback_multiplier = _float(stock_feedback_gate.get("size_multiplier"), 1.0)
    stock_feedback_blocked = stock_feedback_status == "blocked"
    active_guarded_confirmed = (
        lifecycle_gate_mode == "active_guarded"
        and tier in {"normal_buy", "strong_buy"}
        and stock_feedback_status not in {"downgraded", "blocked"}
    )
    trial_guarded_quality_confirmed = (
        lifecycle_gate_mode == "trial_guarded"
        and tier in {"normal_buy", "strong_buy"}
        and not stock_feedback_blocked
        and _trial_guarded_quality_confirmed(signal, policy)
    )
    trial_guarded_confirmed_cap_pct = 0.0
    trial_guarded_positive_outcome = False
    trial_guarded_confirmed_cap_source = None
    if trial_guarded_quality_confirmed:
        key = "trial_guarded_strong_confirmed_cap_pct" if tier == "strong_buy" else "trial_guarded_confirmed_cap_pct"
        trial_guarded_confirmed_cap_pct = _float(policy.get(key), 0.0)
        trial_guarded_positive_outcome = _has_positive_trial_guarded_outcome(signal, policy)
        if trial_guarded_positive_outcome:
            positive_key = (
                "trial_guarded_strong_positive_outcome_cap_pct"
                if tier == "strong_buy"
                else "trial_guarded_confirmed_positive_outcome_cap_pct"
            )
            trial_guarded_confirmed_cap_pct = max(
                trial_guarded_confirmed_cap_pct,
                _float(policy.get(positive_key), trial_guarded_confirmed_cap_pct),
            )
            trial_guarded_confirmed_cap_source = "positive_outcome"
        else:
            trial_guarded_confirmed_cap_source = "quality_confirmed"
    risk_budget_pct = _float(policy["single_trade_risk_budget_pct"][tier])
    recovery_confirmed_cap_pct = 0.0
    recovery_positive_outcome = False
    recovery_quality_confirmed = False
    recovery_positive_outcome_kernel_qualified = False
    recovery_confirmed_cap_source = None
    if lifecycle_gate_mode == "recovery_probe_confirmed" and tier == "normal_buy":
        recovery_confirmed_cap_pct = _float(policy.get("recovery_probe_confirmed_cap_pct"), 0.0)
        recovery_positive_outcome = _has_positive_recovery_outcome(signal, policy)
        recovery_positive_outcome_kernel_qualified = raw_kernel_pct >= _float(
            policy.get("recovery_probe_confirmed_positive_outcome_min_kernel_pct"),
            35.0,
        )
        if recovery_positive_outcome and recovery_positive_outcome_kernel_qualified:
            recovery_confirmed_cap_pct = max(
                recovery_confirmed_cap_pct,
                _float(policy.get("recovery_probe_confirmed_positive_outcome_cap_pct"), recovery_confirmed_cap_pct),
            )
            recovery_confirmed_cap_source = "positive_outcome"
        else:
            recovery_quality_confirmed = _recovery_probe_quality_confirmed(signal, policy)
            if recovery_quality_confirmed:
                recovery_confirmed_cap_pct = max(
                    recovery_confirmed_cap_pct,
                    _float(policy.get("recovery_probe_confirmed_quality_cap_pct"), recovery_confirmed_cap_pct),
                )
                recovery_confirmed_cap_source = "quality_confirmed"
        if recovery_confirmed_cap_source is None:
            recovery_confirmed_cap_source = "base"
        risk_budget_pct = max(risk_budget_pct, _float(policy.get("recovery_probe_confirmed_risk_budget_pct"), 0.0))
    risk_budget_position_pct = (risk_budget_pct / stop_loss_pct) * 100.0
    buy_tier_cap = _float(policy["buy_tier_cap_pct"][tier])
    if recovery_confirmed_cap_pct > 0:
        buy_tier_cap = (
            max(buy_tier_cap, recovery_confirmed_cap_pct)
            if recovery_positive_outcome or recovery_quality_confirmed
            else min(buy_tier_cap, recovery_confirmed_cap_pct)
        )
    small_account_strong_recovery = lifecycle_gate_mode == "strong_recovery_confirmed" and float(total_equity or 0.0) < 300000
    lifecycle_cap_status = (
        "active"
        if lifecycle_gate_mode in {"trial_confirmed", "recovery_probe_confirmed"}
        or (lifecycle_gate_mode == "strong_recovery_confirmed" and not small_account_strong_recovery)
        or active_guarded_confirmed
        else status
    )
    lifecycle_cap_status = lifecycle_cap_status if lifecycle_cap_status in policy["lifecycle_cap_pct"] else "trial"
    portfolio_budget_status = "trial" if status == "trial" else status
    lifecycle_cap = _float(policy["lifecycle_cap_pct"].get(lifecycle_cap_status, policy["lifecycle_cap_pct"]["trial"])[tier])
    if trial_guarded_quality_confirmed and trial_guarded_confirmed_cap_pct > 0:
        lifecycle_cap = max(lifecycle_cap, trial_guarded_confirmed_cap_pct)
    if recovery_confirmed_cap_pct > 0:
        lifecycle_cap = (
            max(lifecycle_cap, recovery_confirmed_cap_pct)
            if recovery_positive_outcome or recovery_quality_confirmed
            else min(lifecycle_cap, recovery_confirmed_cap_pct)
        )
    lifecycle_gate_multiplier = _float(lifecycle_gate.get("size_multiplier"), 1.0)
    if lifecycle_gate_mode in {"recovery_probe_confirmed", "strong_recovery_confirmed", "trial_confirmed"}:
        lifecycle_gate_multiplier = 1.0
    lifecycle_gate_max_pct = lifecycle_gate.get("max_position_pct")
    lifecycle_buy_blocked = bool(lifecycle_gate.get("buy_blocked"))
    if active_guarded_confirmed:
        confirmed_cap = _float(policy.get("active_guarded_confirmed_cap_pct"), 0.0)
        if confirmed_cap > 0:
            lifecycle_gate_max_pct = max(_float(lifecycle_gate_max_pct), confirmed_cap)
    if trial_guarded_quality_confirmed and trial_guarded_confirmed_cap_pct > 0:
        lifecycle_gate_max_pct = max(_float(lifecycle_gate_max_pct), trial_guarded_confirmed_cap_pct)
    if (recovery_positive_outcome or recovery_quality_confirmed) and recovery_confirmed_cap_pct > 0:
        lifecycle_gate_max_pct = max(_float(lifecycle_gate_max_pct), recovery_confirmed_cap_pct)
    recovery_floor_pct = 0.0
    if lifecycle_gate_mode == "recovery_probe_confirmed" and tier == "normal_buy":
        recovery_floor_pct = min(_float(policy.get("recovery_probe_confirmed_floor_pct"), 0.0), buy_tier_cap)
        kernel_pct = max(kernel_pct, recovery_floor_pct)
    lifecycle_gate_adjusted_pct = kernel_pct * lifecycle_gate_multiplier
    account_tier = _account_tier(policy, float(total_equity))
    cap_values = {
        "kernel_quality_position_pct": kernel_pct,
        "buy_tier_cap_pct": buy_tier_cap,
        "lifecycle_cap_pct": lifecycle_cap,
        "risk_budget_position_pct": risk_budget_position_pct,
        "account_equity_tier_cap_pct": account_tier["cap_pct"],
    }
    if lifecycle_gate:
        cap_values["lifecycle_gate_adjusted_position_pct"] = lifecycle_gate_adjusted_pct
        if lifecycle_gate_max_pct not in (None, ""):
            cap_values["lifecycle_gate_max_position_pct"] = max(_float(lifecycle_gate_max_pct), 0.0)
        if lifecycle_buy_blocked:
            cap_values["lifecycle_gate_block_pct"] = 0.0
    base_effective_pct = min(cap_values.values())
    if stock_feedback_status == "downgraded" and stock_feedback_multiplier < 1.0:
        feedback_cap = max(base_effective_pct * stock_feedback_multiplier, 0.0)
        if trial_guarded_quality_confirmed and trial_guarded_confirmed_cap_pct > 0:
            feedback_cap = max(feedback_cap, min(base_effective_pct, trial_guarded_confirmed_cap_pct))
        cap_values["stock_execution_feedback_position_pct"] = feedback_cap
    if stock_feedback_blocked:
        cap_values["stock_execution_feedback_block_pct"] = 0.0
    effective_pct = min(cap_values.values())
    final_budget = min(
        float(total_equity) * effective_pct / 100.0,
        account_tier["max_cash"],
        float(available_cash),
        float(slot_available_cash),
    )
    batch_risk_pct = max(effective_pct * stop_loss_pct / 100.0, 0.0)
    one_lot_cost = max(_float(price), 0.0) * int(lot_size or 100)
    skip_reason = None
    if lifecycle_buy_blocked:
        skip_reason = str(lifecycle_gate.get("reason_code") or "exit_only_buy_blocked")
    if stock_feedback_blocked:
        skip_reason = str(stock_feedback_gate.get("reason_code") or "stock_execution_feedback_blocked")
    if tier == "weak_buy" and one_lot_cost > 0 and final_budget < one_lot_cost:
        skip_reason = "weak_buy_one_lot_exceeds_risk_budget"

    cap_reasons = [name for name, value in cap_values.items() if abs(value - effective_pct) < 1e-9]
    cap_reason_codes = _cap_reason_codes(cap_reasons, status=status, tier=tier)
    return {
        "buy_tier": tier,
        "raw_kernel_quality_position_pct": round(raw_kernel_pct, 6),
        "recovery_probe_confirmed_floor_pct": round(recovery_floor_pct, 6),
        "recovery_probe_confirmed_cap_pct": round(recovery_confirmed_cap_pct, 6),
        "recovery_probe_confirmed_positive_outcome": recovery_positive_outcome,
        "recovery_probe_confirmed_positive_outcome_kernel_qualified": recovery_positive_outcome_kernel_qualified,
        "recovery_probe_confirmed_quality": recovery_quality_confirmed,
        "recovery_probe_confirmed_cap_source": recovery_confirmed_cap_source,
        "trial_guarded_confirmed_quality": trial_guarded_quality_confirmed,
        "trial_guarded_confirmed_positive_outcome": trial_guarded_positive_outcome,
        "trial_guarded_confirmed_cap_source": trial_guarded_confirmed_cap_source,
        "trial_guarded_confirmed_cap_pct": round(trial_guarded_confirmed_cap_pct, 6),
        **{key: round(value, 6) for key, value in cap_values.items()},
        "risk_budget_pct": round(risk_budget_pct, 6),
        "expected_stop_loss_pct": round(stop_loss_pct, 6),
        "batch_risk_pct": round(batch_risk_pct, 6),
        "account_equity_tier_max_cash": round(account_tier["max_cash"], 4),
        "effective_position_pct": round(effective_pct, 6),
        "final_budget": round(final_budget, 4),
        "one_lot_cost": round(one_lot_cost, 4),
        "skip_reason": skip_reason,
        "cap_reasons": cap_reasons,
        "cap_reason_codes": cap_reason_codes,
        "lifecycle_gate_mode": lifecycle_gate_mode,
        "quant_status_for_portfolio_budget": portfolio_budget_status,
        "stock_execution_feedback_status": stock_feedback_status or None,
        "stock_execution_feedback_size_multiplier": round(stock_feedback_multiplier, 6)
        if stock_feedback_gate
        else None,
        "lifecycle_gate_size_multiplier": round(lifecycle_gate_multiplier, 6) if lifecycle_gate else None,
        "lifecycle_gate_adjusted_position_pct": round(lifecycle_gate_adjusted_pct, 6) if lifecycle_gate else None,
        "lifecycle_gate_max_position_pct": round(_float(lifecycle_gate_max_pct), 6)
        if lifecycle_gate and lifecycle_gate_max_pct not in (None, "")
        else None,
    }


def _cap_reason_codes(cap_reasons: list[str], *, status: str, tier: str) -> list[str]:
    codes: list[str] = []
    for reason in cap_reasons:
        if reason == "lifecycle_cap_pct":
            codes.append(f"{status}_{tier}_cap")
        else:
            codes.append(reason)
    return codes
