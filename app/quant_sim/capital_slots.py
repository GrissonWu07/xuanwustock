"""Capital-slot sizing and BUY prioritization for quant simulation."""

from __future__ import annotations

from math import ceil
from typing import Any


DEFAULT_CAPITAL_SLOT_CONFIG: dict[str, Any] = {
    "capital_slot_enabled": True,
    "capital_pool_min_cash": 20000.0,
    "capital_pool_max_cash": 1000000000000.0,
    "capital_slot_min_cash": 20000.0,
    "capital_max_slots": 25,
    "capital_min_buy_slot_fraction": 0.25,
    "capital_full_buy_edge": 0.25,
    "capital_confidence_weight": 0.35,
    "capital_high_price_threshold": 100.0,
    "capital_high_price_max_slot_units": 2.0,
    "capital_sell_cash_reuse_policy": "next_batch",
}
MIN_CAPITAL_SLOT_CASH = 20000.0
SUPPORTED_SELL_CASH_REUSE_POLICIES = {"next_batch", "same_batch"}


def clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    return normalized in {"1", "true", "yes", "on", "enabled", "开启"}


def normalize_capital_slot_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {**DEFAULT_CAPITAL_SLOT_CONFIG, **(config or {})}
    sell_cash_reuse_policy = str(payload.get("capital_sell_cash_reuse_policy") or "next_batch").strip().lower()
    if sell_cash_reuse_policy not in SUPPORTED_SELL_CASH_REUSE_POLICIES:
        sell_cash_reuse_policy = "next_batch"

    return {
        "capital_slot_enabled": truthy(payload.get("capital_slot_enabled")),
        "capital_pool_min_cash": max(float(payload.get("capital_pool_min_cash") or 0), 0.0),
        "capital_pool_max_cash": max(float(payload.get("capital_pool_max_cash") or 0), 0.0),
        "capital_slot_min_cash": max(float(payload.get("capital_slot_min_cash") or MIN_CAPITAL_SLOT_CASH), MIN_CAPITAL_SLOT_CASH),
        "capital_max_slots": max(int(float(payload.get("capital_max_slots") or 1)), 1),
        "capital_min_buy_slot_fraction": clamp(float(payload.get("capital_min_buy_slot_fraction") or 0.25), 0.0, 1.0),
        "capital_full_buy_edge": max(float(payload.get("capital_full_buy_edge") or 0.25), 0.0001),
        "capital_confidence_weight": clamp(float(payload.get("capital_confidence_weight") or 0.35), 0.0, 1.0),
        "capital_high_price_threshold": max(float(payload.get("capital_high_price_threshold") or 0), 0.0),
        "capital_high_price_max_slot_units": max(float(payload.get("capital_high_price_max_slot_units") or 1), 1.0),
        "capital_sell_cash_reuse_policy": sell_cash_reuse_policy,
    }


def calculate_slot_plan(total_equity: float, config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = normalize_capital_slot_config(config)
    effective_pool_cash = min(max(float(total_equity or 0), 0.0), cfg["capital_pool_max_cash"])
    enabled = bool(cfg["capital_slot_enabled"])
    required_pool_cash = max(cfg["capital_pool_min_cash"], cfg["capital_slot_min_cash"])
    if effective_pool_cash < required_pool_cash:
        return {
            "enabled": enabled,
            "pool_ready": False,
            "effective_pool_cash": round(effective_pool_cash, 4),
            "slot_count": 0,
            "slot_budget": 0.0,
            "reason": "capital_pool_below_min_cash",
            "required_pool_cash": round(required_pool_cash, 4),
        }

    if effective_pool_cash <= 100000:
        raw_slot_count = 2
    else:
        tier_slot_cash = 200000.0 if effective_pool_cash > 1000000 else 100000.0
        raw_slot_count = ceil(effective_pool_cash / tier_slot_cash)
    slot_count = min(max(raw_slot_count, 1), cfg["capital_max_slots"])
    slot_budget = effective_pool_cash / slot_count if slot_count > 0 else 0.0
    return {
        "enabled": enabled,
        "pool_ready": True,
        "effective_pool_cash": round(effective_pool_cash, 4),
        "slot_count": int(slot_count),
        "slot_budget": round(slot_budget, 4),
        "reason": "ok",
    }


def _nested_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _fusion_payload(signal: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = _nested_dict(signal.get("strategy_profile"))
    explainability = _nested_dict(profile.get("explainability"))
    fusion = _nested_dict(explainability.get("fusion_breakdown"))
    thresholds = _nested_dict(profile.get("effective_thresholds"))
    return fusion, thresholds


def _float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def calculate_buy_strength(signal: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, float | bool]:
    cfg = normalize_capital_slot_config(config)
    fusion, thresholds = _fusion_payload(signal)
    confidence = (_float_or_none(signal.get("confidence")) or 0.0) / 100.0
    fusion_confidence = _float_or_none(fusion.get("fusion_confidence"))
    if fusion_confidence is None:
        fusion_confidence = clamp(confidence, 0.0, 1.0)

    fusion_score = _float_or_none(fusion.get("fusion_score"))
    buy_threshold = (
        _float_or_none(fusion.get("buy_threshold_eff"))
        or _float_or_none(fusion.get("buy_threshold"))
        or _float_or_none(thresholds.get("fusion_buy_threshold"))
    )
    min_confidence = (
        _float_or_none(thresholds.get("min_fusion_confidence"))
        or _float_or_none(fusion.get("min_fusion_confidence"))
        or 0.0
    )

    if fusion_score is None or buy_threshold is None:
        edge_strength = 0.0
        confidence_strength = clamp(fusion_confidence, 0.0, 1.0)
        fallback = True
    else:
        edge_strength = clamp((fusion_score - buy_threshold) / cfg["capital_full_buy_edge"], 0.0, 1.0)
        denominator = max(1.0 - min_confidence, 0.0001)
        confidence_strength = clamp((fusion_confidence - min_confidence) / denominator, 0.0, 1.0)
        fallback = False

    confidence_weight = cfg["capital_confidence_weight"]
    size_strength = (1.0 - confidence_weight) * edge_strength + confidence_weight * confidence_strength
    track_alignment = _track_alignment(signal, fusion)
    liquidity_score = _liquidity_score(signal, fusion)
    risk_penalty = _risk_penalty(fusion)
    priority = clamp(
        0.50 * edge_strength + 0.25 * fusion_confidence + 0.15 * track_alignment + 0.10 * liquidity_score - risk_penalty,
        0.0,
        1.0,
    )
    if fallback:
        priority = clamp(fusion_confidence, 0.0, 1.0)

    return {
        "fallback": fallback,
        "fusion_score": float(fusion_score or 0.0),
        "buy_threshold": float(buy_threshold or 0.0),
        "fusion_confidence": round(float(fusion_confidence), 6),
        "min_fusion_confidence": round(float(min_confidence), 6),
        "edge_strength": round(edge_strength, 6),
        "confidence_strength": round(confidence_strength, 6),
        "size_strength": round(size_strength, 6),
        "track_alignment": round(track_alignment, 6),
        "liquidity_score": round(liquidity_score, 6),
        "risk_penalty": round(risk_penalty, 6),
        "priority": round(priority, 6),
        "strong_buy": bool(edge_strength >= 0.6 and fusion_confidence >= min_confidence),
    }


def _track_alignment(signal: dict[str, Any], fusion: dict[str, Any]) -> float:
    tech_score = _float_or_none(fusion.get("tech_score")) or _float_or_none(signal.get("tech_score"))
    context_score = _float_or_none(fusion.get("context_score")) or _float_or_none(signal.get("context_score"))
    if tech_score is None or context_score is None:
        return 0.5
    return clamp(1.0 - abs(tech_score - context_score) / 2.0, 0.0, 1.0)


def _liquidity_score(signal: dict[str, Any], fusion: dict[str, Any]) -> float:
    value = (
        _float_or_none(signal.get("volume_ratio"))
        or _float_or_none(fusion.get("volume_ratio"))
        or _float_or_none(fusion.get("liquidity_value"))
    )
    if value is None:
        return 0.5
    return clamp(value / 2.0, 0.0, 1.0)


def _risk_penalty(fusion: dict[str, Any]) -> float:
    risk_score = _float_or_none(fusion.get("risk_score"))
    if risk_score is None:
        return 0.0
    return clamp(max(-risk_score, 0.0), 0.0, 0.4)


def calculate_buy_priority(signal: dict[str, Any], config: dict[str, Any] | None = None) -> float:
    return float(calculate_buy_strength(signal, config).get("priority") or 0.0)


def calculate_slot_units(
    signal: dict[str, Any],
    *,
    price: float,
    slot_budget: float,
    commission_rate: float = 0.0,
    config: dict[str, Any] | None = None,
    strategy_profile_id: str | None = None,
    cash_ratio: float | None = None,
) -> dict[str, Any]:
    cfg = normalize_capital_slot_config(config)
    strength = calculate_buy_strength(signal, cfg)
    base_units = cfg["capital_min_buy_slot_fraction"] + (1.0 - cfg["capital_min_buy_slot_fraction"]) * float(
        strength["size_strength"]
    )
    base_units = clamp(base_units, cfg["capital_min_buy_slot_fraction"], 1.0)
    one_lot_cost = max(float(price or 0), 0.0) * 100.0 * (1.0 + max(float(commission_rate or 0.0), 0.0))
    high_price = float(price or 0) > cfg["capital_high_price_threshold"]
    requires_extra_slot = high_price and slot_budget > 0 and one_lot_cost > slot_budget
    if requires_extra_slot and bool(strength["strong_buy"]):
        slot_units = min(cfg["capital_high_price_max_slot_units"], max(base_units, one_lot_cost / slot_budget))
    else:
        slot_units = min(base_units, 1.0)
    one_lot_floor_units = 0.0
    if slot_budget > 0 and one_lot_cost > 0 and one_lot_cost <= slot_budget:
        one_lot_floor_units = one_lot_cost / slot_budget
        slot_units = max(slot_units, one_lot_floor_units)
    cash_pressure_units = _cash_pressure_slot_units(strategy_profile_id=strategy_profile_id, cash_ratio=cash_ratio)
    if cash_pressure_units > 0:
        slot_units = min(slot_units + cash_pressure_units, cfg["capital_high_price_max_slot_units"])
    reentry_size_multiplier = gate_size_multiplier(signal)
    if reentry_size_multiplier < 1.0:
        slot_units = slot_units * reentry_size_multiplier
        if one_lot_floor_units > 0:
            slot_units = max(slot_units, one_lot_floor_units)
    return {
        **strength,
        "base_slot_units": round(base_units, 6),
        "slot_units": round(slot_units, 6),
        "one_lot_cost": round(one_lot_cost, 4),
        "one_lot_floor_units": round(one_lot_floor_units, 6),
        "cash_pressure_units": round(cash_pressure_units, 6),
        "reentry_size_multiplier": round(reentry_size_multiplier, 6),
        "high_price": high_price,
        "requires_extra_slot": requires_extra_slot,
    }


def gate_size_multiplier(signal: dict[str, Any]) -> float:
    profile = _nested_dict(signal.get("strategy_profile"))
    multipliers: list[float] = []
    for key in ("reentry_gate", "stock_execution_feedback_gate", "portfolio_execution_guard"):
        gate = _nested_dict(profile.get(key))
        if str(gate.get("status") or "").strip().lower() != "downgraded":
            continue
        try:
            raw_multiplier = gate.get("size_multiplier")
            multiplier = 1.0 if raw_multiplier in (None, "") else float(raw_multiplier)
            multipliers.append(clamp(multiplier, 0.0, 1.0))
        except (TypeError, ValueError):
            continue
    return min(multipliers) if multipliers else 1.0


def _cash_pressure_slot_units(*, strategy_profile_id: str | None, cash_ratio: float | None) -> float:
    profile_key = str(strategy_profile_id or "").strip().lower()
    if "aggressive" not in profile_key:
        return 0.0
    try:
        ratio = float(cash_ratio if cash_ratio is not None else 0.0)
    except (TypeError, ValueError):
        return 0.0
    if ratio >= 0.75:
        return 0.50
    if ratio >= 0.60:
        return 0.25
    return 0.0


def build_sizing_explainability(
    *,
    config: dict[str, Any],
    slot_plan: dict[str, Any],
    sizing: dict[str, Any],
    available_cash: float,
    slot_available_cash: float,
    buy_budget: float,
    quantity: int,
    skip_reason: str | None = None,
    target_position_pct: float | None = None,
    target_position_budget: float | None = None,
    slot_capacity_capped: bool | None = None,
) -> dict[str, Any]:
    payload = {
        "config": normalize_capital_slot_config(config),
        "slot_plan": slot_plan,
        "sizing": sizing,
        "available_cash": round(float(available_cash or 0), 4),
        "slot_available_cash": round(float(slot_available_cash or 0), 4),
        "buy_budget": round(float(buy_budget or 0), 4),
        "quantity": int(quantity or 0),
        "skip_reason": skip_reason,
    }
    if target_position_pct is not None:
        payload["target_position_pct"] = round(float(target_position_pct or 0), 6)
    if target_position_budget is not None:
        payload["target_position_budget"] = round(float(target_position_budget or 0), 4)
    if slot_capacity_capped is not None:
        payload["slot_capacity_capped"] = bool(slot_capacity_capped)
    return payload
