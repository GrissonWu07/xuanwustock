"""Execution sizing policy for quant BUY signals."""

from __future__ import annotations

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
    return str(profile.get("quant_status") or signal.get("quant_status") or "active").strip().lower()


def _priority(signal: dict[str, Any]) -> tuple[int, float, float, int]:
    plan = _signal_plan(signal)
    tier = str(plan.get("buy_tier") or _buy_tier(signal)).strip().lower()
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    gate = profile.get("portfolio_execution_guard") if isinstance(profile.get("portfolio_execution_guard"), dict) else {}
    strength = _float(gate.get("buy_strength_score"), 0.0)
    confidence = _float(signal.get("confidence"), 0.0)
    signal_id = int(_float(signal.get("id"), 0.0))
    return (BUY_TIER_ORDER.get(tier, 9), -strength, -confidence, signal_id)


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
    rows: list[dict[str, Any]] = []
    for signal in sorted(signals, key=_priority):
        plan = _signal_plan(signal)
        tier = str(plan.get("buy_tier") or _buy_tier(signal)).strip().lower()
        status = _signal_quant_status(signal)
        final_budget = _float(plan.get("final_budget"), 0.0)
        risk_budget_pct = _float(plan.get("risk_budget_pct"), 0.0)
        reason_code = ""
        if status == "trial":
            if checkpoint_trial_risk + risk_budget_pct > float(policy["checkpoint_trial_risk_budget_pct"]) + 1e-9:
                reason_code = "portfolio_trial_risk_budget_exhausted"
            elif day_trial_risk + risk_budget_pct > float(policy["daily_trial_risk_budget_pct"]) + 1e-9:
                reason_code = "daily_trial_risk_budget_exhausted"
            elif trial_exposure + final_budget > trial_exposure_cap + 1e-9:
                reason_code = "trial_exposure_cap_hit"
        if not reason_code and tier == "weak_buy" and weak_exposure + final_budget > weak_exposure_cap + 1e-9:
            reason_code = "weak_buy_exposure_cap_hit"
        allowed = not reason_code
        if allowed:
            if status == "trial":
                checkpoint_trial_risk += risk_budget_pct
                day_trial_risk += risk_budget_pct
                trial_exposure += final_budget
            if tier == "weak_buy":
                weak_exposure += final_budget
        rows.append({"signal_id": signal.get("id"), "allowed": allowed, "reason_code": reason_code, "signal": signal})
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
    kernel_positioning = profile.get("kernel_positioning") if isinstance(profile.get("kernel_positioning"), dict) else {}
    if not kernel_positioning:
        explainability = profile.get("explainability") if isinstance(profile.get("explainability"), dict) else {}
        resonance = explainability.get("resonance") if isinstance(explainability.get("resonance"), dict) else {}
        quality_ratio = resonance.get("quality_adjusted_position_ratio")
        if quality_ratio is not None:
            kernel_positioning = {"quality_position_pct": _float(quality_ratio, 0.0) * 100.0}
    kernel_pct = _float(kernel_positioning.get("quality_position_pct"), _float(signal.get("position_size_pct"), 0.0))
    stop_loss_pct = max(_float(signal.get("stop_loss_pct"), 5.0), 0.0001)
    risk_budget_pct = _float(policy["single_trade_risk_budget_pct"][tier])
    risk_budget_position_pct = (risk_budget_pct / stop_loss_pct) * 100.0
    buy_tier_cap = _float(policy["buy_tier_cap_pct"][tier])
    lifecycle_gate_mode = str(lifecycle_gate.get("mode") or "").strip()
    lifecycle_cap_status = "active" if lifecycle_gate_mode == "trial_confirmed" else status
    lifecycle_cap_status = lifecycle_cap_status if lifecycle_cap_status in policy["lifecycle_cap_pct"] else "trial"
    lifecycle_cap = _float(policy["lifecycle_cap_pct"].get(lifecycle_cap_status, policy["lifecycle_cap_pct"]["trial"])[tier])
    lifecycle_gate_multiplier = _float(lifecycle_gate.get("size_multiplier"), 1.0)
    lifecycle_gate_max_pct = lifecycle_gate.get("max_position_pct")
    lifecycle_gate_adjusted_pct = kernel_pct * lifecycle_gate_multiplier
    lifecycle_buy_blocked = bool(lifecycle_gate.get("buy_blocked"))
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
    effective_pct = min(cap_values.values())
    final_budget = min(
        float(total_equity) * effective_pct / 100.0,
        account_tier["max_cash"],
        float(available_cash),
        float(slot_available_cash),
    )
    one_lot_cost = max(_float(price), 0.0) * int(lot_size or 100)
    skip_reason = None
    if lifecycle_buy_blocked:
        skip_reason = str(lifecycle_gate.get("reason_code") or "exit_only_buy_blocked")
    if tier == "weak_buy" and one_lot_cost > 0 and final_budget < one_lot_cost:
        skip_reason = "weak_buy_one_lot_exceeds_risk_budget"

    cap_reasons = [name for name, value in cap_values.items() if abs(value - effective_pct) < 1e-9]
    cap_reason_codes = _cap_reason_codes(cap_reasons, status=status, tier=tier)
    return {
        "buy_tier": tier,
        **{key: round(value, 6) for key, value in cap_values.items()},
        "risk_budget_pct": round(risk_budget_pct, 6),
        "expected_stop_loss_pct": round(stop_loss_pct, 6),
        "account_equity_tier_max_cash": round(account_tier["max_cash"], 4),
        "effective_position_pct": round(effective_pct, 6),
        "final_budget": round(final_budget, 4),
        "one_lot_cost": round(one_lot_cost, 4),
        "skip_reason": skip_reason,
        "cap_reasons": cap_reasons,
        "cap_reason_codes": cap_reason_codes,
        "lifecycle_gate_mode": lifecycle_gate_mode,
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
