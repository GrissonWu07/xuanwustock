"""Execution sizing policy for quant BUY signals."""

from __future__ import annotations

from typing import Any


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
            "buy_tier_cap_pct": {"weak_buy": 5.0, "normal_buy": 9.0, "strong_buy": 15.0},
            "lifecycle_cap_pct": {
                "trial": {"weak_buy": 3.0, "normal_buy": 6.0, "strong_buy": 10.0},
                "active": {"weak_buy": 5.0, "normal_buy": 9.0, "strong_buy": 15.0},
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
    if status not in {"trial", "active", "exit_only"}:
        status = "trial"

    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    kernel_positioning = profile.get("kernel_positioning") if isinstance(profile.get("kernel_positioning"), dict) else {}
    kernel_pct = _float(kernel_positioning.get("quality_position_pct"), _float(signal.get("position_size_pct"), 0.0))
    stop_loss_pct = max(_float(signal.get("stop_loss_pct"), 5.0), 0.0001)
    risk_budget_pct = _float(policy["single_trade_risk_budget_pct"][tier])
    risk_budget_position_pct = (risk_budget_pct / stop_loss_pct) * 100.0
    buy_tier_cap = _float(policy["buy_tier_cap_pct"][tier])
    lifecycle_cap = _float(policy["lifecycle_cap_pct"].get(status, policy["lifecycle_cap_pct"]["trial"])[tier])
    account_tier = _account_tier(policy, float(total_equity))
    cap_values = {
        "kernel_quality_position_pct": kernel_pct,
        "buy_tier_cap_pct": buy_tier_cap,
        "lifecycle_cap_pct": lifecycle_cap,
        "risk_budget_position_pct": risk_budget_position_pct,
        "account_equity_tier_cap_pct": account_tier["cap_pct"],
    }
    effective_pct = min(cap_values.values())
    final_budget = min(
        float(total_equity) * effective_pct / 100.0,
        account_tier["max_cash"],
        float(available_cash),
        float(slot_available_cash),
    )
    one_lot_cost = max(_float(price), 0.0) * int(lot_size or 100)
    skip_reason = None
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
    }


def _cap_reason_codes(cap_reasons: list[str], *, status: str, tier: str) -> list[str]:
    codes: list[str] = []
    for reason in cap_reasons:
        if reason == "lifecycle_cap_pct":
            codes.append(f"{status}_{tier}_cap")
        else:
            codes.append(reason)
    return codes

