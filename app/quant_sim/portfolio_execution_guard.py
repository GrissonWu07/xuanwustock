"""Portfolio-level BUY tier and defensive gate evaluation."""

from __future__ import annotations

from typing import Any


DEFAULT_PORTFOLIO_EXECUTION_GUARD_POLICY: dict[str, Any] = {
    "enabled": True,
    "weak_multiplier": 0.25,
    "normal_multiplier": 0.5,
    "strong_multiplier": 1.0,
    "weight_edge": 0.32,
    "weight_trend_structure": 0.30,
    "weight_confirmation": 0.18,
    "weight_volume": 0.10,
    "weight_track_alignment": 0.10,
    "weak_buy_max_score": 0.50,
    "strong_buy_min_score": 0.82,
    "full_edge": 0.20,
    "weak_edge_abs": 0.04,
    "normal_edge_abs": 0.10,
    "strong_edge_abs": 0.16,
    "confirm_checkpoints": 3,
    "min_ma20_slope": 0.0,
    "normal_volume_ratio": 1.2,
    "strong_volume_ratio": 1.6,
    "retest_lookback_checkpoints": 5,
    "retest_tolerance_pct": 1.5,
    "max_risk_penalty": 0.50,
    "late_rebound_penalty": 0.20,
    "t1_risk_penalty": 0.15,
    "hot_zone_penalty": 0.30,
    "hot_zone_rsi_threshold": 75.0,
    "hot_zone_extreme_rsi_threshold": 85.0,
    "hot_zone_recent_5d_return_threshold": 0.08,
    "hot_zone_extreme_recent_5d_return_threshold": 0.15,
    "hot_zone_volume_ratio_threshold": 2.0,
    "stock_failure_penalty": 0.20,
    "portfolio_cooldown_penalty": 0.25,
    "portfolio_drawdown_penalty": 0.18,
    "t1_confirm_checkpoints": 3,
    "lookback_checkpoints": 12,
    "lookback_days": 8,
    "cooldown_checkpoints": 4,
    "max_new_buys_per_checkpoint": 1,
    "max_new_buys_per_day": 3,
    "stop_loss_pnl_pct_threshold": -4.0,
    "stop_loss_circuit_threshold": 2,
    "consecutive_stop_loss_threshold": 2,
    "cooldown_days": 2,
    "loss_budget_pct": -2.0,
    "drawdown_guard_pct": 3.0,
    "stop_loss_density_threshold": 0.40,
    "cooldown_size_multiplier": 0.35,
    "cold_start_profit_sample_threshold": 1,
    "cold_start_weak_multiplier": 0.25,
    "cold_start_normal_multiplier": 0.5,
    "candidate_below_ma20_guard_ratio": 0.60,
    "position_below_ma20_guard_ratio": 0.60,
}


PORTFOLIO_EXECUTION_GUARD_PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "aggressive": {
        **DEFAULT_PORTFOLIO_EXECUTION_GUARD_POLICY,
        "weight_edge": 0.40,
        "weight_trend_structure": 0.25,
        "weight_confirmation": 0.10,
        "weight_volume": 0.15,
        "weak_buy_max_score": 0.45,
        "strong_buy_min_score": 0.78,
        "full_edge": 0.10,
        "weak_edge_abs": 0.03,
        "normal_edge_abs": 0.08,
        "strong_edge_abs": 0.14,
        "confirm_checkpoints": 2,
        "normal_volume_ratio": 1.1,
        "strong_volume_ratio": 1.5,
        "max_risk_penalty": 0.45,
        "late_rebound_penalty": 0.18,
        "t1_risk_penalty": 0.12,
        "hot_zone_penalty": 0.28,
        "stock_failure_penalty": 0.18,
        "portfolio_cooldown_penalty": 0.20,
        "portfolio_drawdown_penalty": 0.15,
        "t1_confirm_checkpoints": 2,
        "lookback_checkpoints": 8,
        "lookback_days": 5,
        "cooldown_checkpoints": 2,
        "max_new_buys_per_checkpoint": 2,
        "max_new_buys_per_day": 4,
        "stop_loss_pnl_pct_threshold": -5.0,
        "stop_loss_circuit_threshold": 3,
        "cooldown_days": 1,
        "loss_budget_pct": -3.0,
        "drawdown_guard_pct": 4.0,
        "stop_loss_density_threshold": 0.50,
        "cooldown_size_multiplier": 0.5,
        "candidate_below_ma20_guard_ratio": 0.65,
        "position_below_ma20_guard_ratio": 0.65,
    },
    "stable": dict(DEFAULT_PORTFOLIO_EXECUTION_GUARD_POLICY),
    "conservative": {
        **DEFAULT_PORTFOLIO_EXECUTION_GUARD_POLICY,
        "weak_multiplier": 0.20,
        "normal_multiplier": 0.4,
        "strong_multiplier": 0.8,
        "weight_edge": 0.25,
        "weight_trend_structure": 0.35,
        "weight_confirmation": 0.22,
        "weight_volume": 0.08,
        "weak_buy_max_score": 0.55,
        "strong_buy_min_score": 0.86,
        "full_edge": 0.22,
        "weak_edge_abs": 0.05,
        "normal_edge_abs": 0.12,
        "strong_edge_abs": 0.18,
        "normal_volume_ratio": 1.3,
        "strong_volume_ratio": 1.8,
        "max_risk_penalty": 0.55,
        "late_rebound_penalty": 0.22,
        "t1_risk_penalty": 0.18,
        "hot_zone_penalty": 0.34,
        "stock_failure_penalty": 0.22,
        "portfolio_cooldown_penalty": 0.30,
        "portfolio_drawdown_penalty": 0.20,
        "lookback_checkpoints": 16,
        "lookback_days": 12,
        "cooldown_checkpoints": 6,
        "max_new_buys_per_day": 2,
        "stop_loss_pnl_pct_threshold": -3.0,
        "cooldown_days": 3,
        "loss_budget_pct": -1.5,
        "drawdown_guard_pct": 2.0,
        "stop_loss_density_threshold": 0.35,
        "cooldown_size_multiplier": 0.25,
        "cold_start_weak_multiplier": 0.20,
        "cold_start_normal_multiplier": 0.4,
        "candidate_below_ma20_guard_ratio": 0.55,
        "position_below_ma20_guard_ratio": 0.55,
    },
}

_WEIGHT_KEYS = (
    "weight_edge",
    "weight_trend_structure",
    "weight_confirmation",
    "weight_volume",
    "weight_track_alignment",
)


def default_portfolio_execution_guard_policy(profile_id: str | None = None) -> dict[str, Any]:
    key = str(profile_id or "").strip().lower()
    if "aggressive" in key:
        return dict(PORTFOLIO_EXECUTION_GUARD_PROFILE_DEFAULTS["aggressive"])
    if "conservative" in key:
        return dict(PORTFOLIO_EXECUTION_GUARD_PROFILE_DEFAULTS["conservative"])
    if "stable" in key or "neutral" in key:
        return dict(PORTFOLIO_EXECUTION_GUARD_PROFILE_DEFAULTS["stable"])
    return dict(DEFAULT_PORTFOLIO_EXECUTION_GUARD_POLICY)


def normalize_portfolio_execution_guard_policy(
    raw: dict[str, Any] | None,
    *,
    profile_id: str | None = None,
) -> dict[str, Any]:
    policy = default_portfolio_execution_guard_policy(profile_id)
    if isinstance(raw, dict):
        policy.update(raw)

    policy["enabled"] = _truthy(policy.get("enabled"), True)
    for key in _WEIGHT_KEYS:
        policy[key] = max(_float(policy.get(key), default_portfolio_execution_guard_policy(profile_id).get(key, 0.0)), 0.0)
    weight_sum = sum(float(policy[key]) for key in _WEIGHT_KEYS)
    if weight_sum <= 0:
        defaults = default_portfolio_execution_guard_policy(profile_id)
        for key in _WEIGHT_KEYS:
            policy[key] = float(defaults[key])
    else:
        for key in _WEIGHT_KEYS:
            policy[key] = float(policy[key]) / weight_sum

    for key in (
        "weak_multiplier",
        "normal_multiplier",
        "strong_multiplier",
        "weak_buy_max_score",
        "strong_buy_min_score",
        "max_risk_penalty",
        "late_rebound_penalty",
        "t1_risk_penalty",
        "hot_zone_penalty",
        "stock_failure_penalty",
        "portfolio_cooldown_penalty",
        "portfolio_drawdown_penalty",
        "cooldown_size_multiplier",
        "cold_start_weak_multiplier",
        "cold_start_normal_multiplier",
    ):
        policy[key] = _clamp(_float(policy.get(key), DEFAULT_PORTFOLIO_EXECUTION_GUARD_POLICY.get(key, 0.0)), 0.0, 1.0)
    for key in (
        "full_edge",
        "weak_edge_abs",
        "normal_edge_abs",
        "strong_edge_abs",
        "normal_volume_ratio",
        "strong_volume_ratio",
        "retest_tolerance_pct",
        "hot_zone_rsi_threshold",
        "hot_zone_extreme_rsi_threshold",
        "hot_zone_recent_5d_return_threshold",
        "hot_zone_extreme_recent_5d_return_threshold",
        "hot_zone_volume_ratio_threshold",
        "candidate_below_ma20_guard_ratio",
        "position_below_ma20_guard_ratio",
    ):
        policy[key] = max(_float(policy.get(key), DEFAULT_PORTFOLIO_EXECUTION_GUARD_POLICY.get(key, 0.0)), 0.0)
    for key in (
        "confirm_checkpoints",
        "retest_lookback_checkpoints",
        "t1_confirm_checkpoints",
        "lookback_checkpoints",
        "lookback_days",
        "cooldown_checkpoints",
        "max_new_buys_per_checkpoint",
        "max_new_buys_per_day",
        "stop_loss_circuit_threshold",
        "consecutive_stop_loss_threshold",
        "cooldown_days",
        "cold_start_profit_sample_threshold",
    ):
        policy[key] = max(int(_float(policy.get(key), DEFAULT_PORTFOLIO_EXECUTION_GUARD_POLICY.get(key, 1))), 1)
    policy["min_ma20_slope"] = _float(policy.get("min_ma20_slope"), 0.0)
    policy["stop_loss_pnl_pct_threshold"] = min(_float(policy.get("stop_loss_pnl_pct_threshold"), -4.0), 0.0)
    policy["loss_budget_pct"] = min(_float(policy.get("loss_budget_pct"), -2.0), 0.0)
    policy["drawdown_guard_pct"] = max(_float(policy.get("drawdown_guard_pct"), 3.0), 0.0)
    policy["stop_loss_density_threshold"] = _clamp(_float(policy.get("stop_loss_density_threshold"), 0.4), 0.0, 1.0)
    return policy


def evaluate_portfolio_execution_guard(
    *,
    signal: dict[str, Any],
    policy: dict[str, Any] | None,
    portfolio_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = normalize_portfolio_execution_guard_policy(policy, profile_id=_profile_id(signal))
    if str(signal.get("action") or "").upper() != "BUY" or not resolved["enabled"]:
        return _gate("passed", "none", "无BUY分层", 1.0, resolved, [], {}, {}, {}, False, [])

    profile = _dict(signal.get("strategy_profile"))
    market = _dict(profile.get("market_snapshot"))
    fusion = _dict(_dict(_dict(profile.get("explainability")).get("fusion_breakdown")))
    thresholds = _dict(profile.get("effective_thresholds"))
    metrics = _metrics(signal, market)
    trend = _trend_confirmation(metrics, market, resolved)
    buy_edge, edge_source = _buy_edge(signal, fusion, thresholds)
    has_signal_context = bool(market) or bool(fusion) or any(
        _maybe_float(thresholds.get(key)) is not None
        for key in ("fusion_buy_threshold", "tech_buy_threshold", "candidate_buy_threshold")
    )
    edge_strength = _clamp(buy_edge / max(float(resolved["full_edge"]), 0.0001), 0.0, 1.0)
    volume_score, volume_confirmed = _volume_score(metrics.get("volume_ratio"), resolved)
    track_alignment = _track_alignment(signal, fusion)
    is_late_rebound, late_reasons = _late_rebound(metrics, trend, resolved)
    t1_active = _t1_risk(signal, trend, resolved)
    hot_zone_penalty, hot_zone_reasons = _hot_zone_risk(metrics, resolved)
    portfolio = _portfolio_state(portfolio_summary or {}, resolved)
    if not has_signal_context:
        status = "passed"
        tier = "none"
        multiplier = 1.0
        if portfolio["loss_budget_triggered"] or portfolio["blocked"]:
            status = "blocked"
            multiplier = 0.0
        elif portfolio["drawdown_guard_triggered"] or portfolio["cooldown_active"]:
            status = "downgraded"
            multiplier = float(resolved["cooldown_size_multiplier"])
        return _gate(
            status,
            "none",
            tier,
            multiplier,
            resolved,
            list(portfolio["reasons"]),
            {
                "buy_edge": 0.0,
                "edge_strength": 0.0,
                "trend_structure_score": 0.0,
                "confirmation_score": 0.0,
                "volume_score": 0.0,
                "track_alignment_score": 0.0,
                "risk_penalty": 0.0,
                "risk_penalties": {},
            },
            {**trend, "volume_confirmed": False},
            portfolio,
            False,
            [],
            cold_start={"active": False},
            t1_active=False,
            score=0.0,
        )
    penalties = {
        "late_rebound": float(resolved["late_rebound_penalty"]) if is_late_rebound else 0.0,
        "t1": float(resolved["t1_risk_penalty"]) if t1_active else 0.0,
        "hot_zone": hot_zone_penalty,
        "stock_failure": _stock_failure_penalty(profile, resolved),
        "portfolio_cooldown": float(resolved["portfolio_cooldown_penalty"]) if portfolio["cooldown_active"] else 0.0,
        "portfolio_drawdown": float(resolved["portfolio_drawdown_penalty"]) if portfolio["drawdown_guard_triggered"] else 0.0,
    }
    risk_penalty = min(sum(penalties.values()), float(resolved["max_risk_penalty"]))
    trend_score = _trend_structure_score(trend, metrics)
    confirmation_score = _confirmation_score(trend, resolved)
    raw_score = (
        float(resolved["weight_edge"]) * edge_strength
        + float(resolved["weight_trend_structure"]) * trend_score
        + float(resolved["weight_confirmation"]) * confirmation_score
        + float(resolved["weight_volume"]) * volume_score
        + float(resolved["weight_track_alignment"]) * track_alignment
        - risk_penalty
    )
    score = _clamp(raw_score, 0.0, 1.0)
    tier = _initial_tier(score, resolved)
    tier = _apply_hard_tier_requirements(
        tier=tier,
        score=score,
        buy_edge=buy_edge,
        trend=trend,
        is_late_rebound=is_late_rebound,
        t1_active=t1_active,
        hot_zone_active=bool(hot_zone_reasons),
        policy=resolved,
    )
    initial_tier = tier
    reasons: list[str] = []
    if edge_source == "missing":
        reasons.append("missing_buy_edge")
    reasons.extend(late_reasons)
    if t1_active:
        reasons.append("t1_new_buy_unconfirmed")
    reasons.extend(hot_zone_reasons)

    status = "passed"
    multiplier = float(resolved[f"{tier.split('_')[0]}_multiplier"])
    cold_start = _cold_start_state(profile, resolved)
    if cold_start["active"]:
        if tier == "weak_buy":
            multiplier = min(multiplier, float(resolved["cold_start_weak_multiplier"]))
            reasons.append("冷启动无盈利样本，先轻仓试错")
        elif tier == "normal_buy":
            multiplier = min(multiplier, float(resolved["cold_start_normal_multiplier"]))
            reasons.append("冷启动无盈利样本，先轻仓试错")
    if tier != "strong_buy":
        status = "downgraded"
    if portfolio["loss_budget_triggered"] or portfolio["blocked"]:
        status = "blocked"
        tier = "weak_buy"
        multiplier = 0.0
    elif portfolio["drawdown_guard_triggered"]:
        status = "downgraded"
        if tier == "weak_buy":
            status = "blocked"
            multiplier = 0.0
        elif tier == "normal_buy":
            tier = "weak_buy"
            multiplier = min(multiplier, float(resolved["weak_multiplier"]))
        else:
            multiplier = min(multiplier, float(resolved["cooldown_size_multiplier"]))
    elif portfolio["cooldown_active"]:
        status = "downgraded"
        if tier != "strong_buy":
            status = "blocked"
            multiplier = 0.0
        else:
            multiplier = min(multiplier, float(resolved["cooldown_size_multiplier"]))

    stock_gate = _dict(profile.get("stock_execution_feedback_gate"))
    weak_buy_loss_reentry_active = (
        bool(stock_gate.get("last_buy_was_weak"))
        and int(_float(stock_gate.get("loss_after_last_buy_count"), 0.0)) > 0
    )
    if weak_buy_loss_reentry_active and tier == "weak_buy" and not bool(stock_gate.get("trend_confirmed")):
        status = "blocked"
        multiplier = 0.0
        reasons.append("弱买亏损后再买需要强趋势确认")

    if status == "blocked":
        reasons.extend(portfolio["reasons"])

    return _gate(
        status,
        initial_tier,
        tier,
        multiplier,
        resolved,
        reasons,
        {
            "buy_edge": round(buy_edge, 6),
            "edge_strength": round(edge_strength, 6),
            "trend_structure_score": round(trend_score, 6),
            "confirmation_score": round(confirmation_score, 6),
            "volume_score": round(volume_score, 6),
            "track_alignment_score": round(track_alignment, 6),
            "risk_penalty": round(risk_penalty, 6),
            "risk_penalties": {key: round(value, 6) for key, value in penalties.items()},
        },
        {**trend, "volume_confirmed": volume_confirmed},
        portfolio,
        is_late_rebound,
        late_reasons,
        cold_start=cold_start,
        t1_active=t1_active,
        score=score,
    )


def _gate(
    status: str,
    initial_tier: str,
    tier: str,
    multiplier: float,
    policy: dict[str, Any],
    reasons: list[str],
    score_components: dict[str, Any],
    trend: dict[str, Any],
    portfolio: dict[str, Any],
    is_late_rebound: bool,
    late_reasons: list[str],
    *,
    cold_start: dict[str, Any] | None = None,
    t1_active: bool = False,
    score: float = 0.0,
) -> dict[str, Any]:
    label = {"weak_buy": "弱买", "normal_buy": "普通买", "strong_buy": "强买"}.get(tier, "无")
    return {
        "intent": "portfolio_execution_guard",
        "status": status,
        "initial_buy_tier": initial_tier,
        "buy_tier": tier,
        "buy_tier_label": label,
        "buy_strength_score": round(score, 6),
        "size_multiplier": round(_clamp(multiplier, 0.0, 1.0), 6),
        "is_late_rebound": bool(is_late_rebound),
        "late_rebound_reasons": late_reasons,
        "score_components": score_components,
        "trend_confirmation": trend,
        "cold_start": cold_start or {"active": False},
        "t1_risk": {"active": bool(t1_active), "confirm_checkpoints": int(policy.get("t1_confirm_checkpoints") or 1)},
        "portfolio_guard": portfolio,
        "ui_badges": [item for item in (label, "疑似反弹尾段" if is_late_rebound else None) if item],
        "policy": policy,
        "reasons": reasons,
    }


def _metrics(signal: dict[str, Any], market: dict[str, Any]) -> dict[str, Any]:
    return {
        "price": _float(market.get("current_price") or market.get("latest_price") or signal.get("price"), 0.0),
        "ma5": _maybe_float(market.get("ma5")),
        "ma10": _maybe_float(market.get("ma10")),
        "ma20": _maybe_float(market.get("ma20")),
        "ma20_slope": _float(market.get("ma20_slope"), 0.0),
        "volume_ratio": _maybe_float(market.get("volume_ratio")),
        "rsi": _first_maybe_float(market.get("rsi12"), market.get("rsi14"), market.get("rsi")),
        "recent_5d_return": _return_ratio(
            _first_maybe_float(
                market.get("recent_5d_return"),
                market.get("recent5d_return"),
                market.get("recent_5d_change"),
                market.get("recent_5d_pct"),
                market.get("recent_return_5d"),
                market.get("five_day_return"),
            )
        ),
    }


def _trend_confirmation(metrics: dict[str, Any], market: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    price = metrics.get("price")
    ma5 = metrics.get("ma5")
    ma10 = metrics.get("ma10")
    ma20 = metrics.get("ma20")
    ma20_rising = metrics.get("ma20_slope", 0.0) > float(policy["min_ma20_slope"])
    ma_stack = bool(price and ma5 and ma10 and ma20 and price > ma20 and ma5 > ma10 > ma20)
    recent = market.get("recent_checkpoints") if isinstance(market.get("recent_checkpoints"), list) else []
    above = 0
    for item in reversed(recent):
        close = _maybe_float(_dict(item).get("close"))
        item_ma20 = _maybe_float(_dict(item).get("ma20"))
        if close is None or item_ma20 is None or close <= item_ma20:
            break
        above += 1
    retest = _retest_confirmed(recent, metrics, policy)
    return {
        "ma_stack": ma_stack,
        "ma20_rising": ma20_rising,
        "above_ma20_checkpoints": above,
        "retest_confirmed": retest,
    }


def _retest_confirmed(recent: list[Any], metrics: dict[str, Any], policy: dict[str, Any]) -> bool:
    price = metrics.get("price")
    ma10 = metrics.get("ma10")
    ma20 = metrics.get("ma20")
    if not recent or price is None or ma10 is None or ma20 is None or price <= ma20 or price <= ma10:
        return False
    lookback = int(policy.get("retest_lookback_checkpoints") or 1)
    window = [_dict(item) for item in recent[-lookback:]]
    tolerance = 1.0 - float(policy.get("retest_tolerance_pct") or 0.0) / 100.0
    broke_above = any((_maybe_float(item.get("close")) or 0.0) > (_maybe_float(item.get("ma20")) or float("inf")) for item in window)
    retested = any(
        (_maybe_float(item.get("low")) is not None)
        and (_maybe_float(item.get("ma20")) is not None)
        and (_maybe_float(item.get("low")) or 0.0) >= (_maybe_float(item.get("ma20")) or 0.0) * tolerance
        for item in window
    )
    return bool(broke_above and retested)


def _buy_edge(signal: dict[str, Any], fusion: dict[str, Any], thresholds: dict[str, Any]) -> tuple[float, str]:
    fusion_score = _maybe_float(fusion.get("fusion_score"))
    buy_threshold = _maybe_float(fusion.get("buy_threshold_eff") or fusion.get("buy_threshold") or thresholds.get("fusion_buy_threshold"))
    if fusion_score is not None and buy_threshold is not None:
        return fusion_score - buy_threshold, "fusion"
    tech_score = _maybe_float(signal.get("tech_score"))
    tech_threshold = _maybe_float(thresholds.get("tech_buy_threshold") or thresholds.get("candidate_buy_threshold"))
    if tech_score is not None and tech_threshold is not None:
        return tech_score - tech_threshold, "tech"
    return 0.0, "missing"


def _volume_score(volume_ratio: float | None, policy: dict[str, Any]) -> tuple[float, str]:
    if volume_ratio is None:
        return 0.3, "missing"
    if volume_ratio >= float(policy["strong_volume_ratio"]):
        return 1.0, "strong"
    if volume_ratio >= float(policy["normal_volume_ratio"]):
        return 0.6, "normal"
    return 0.3, "weak"


def _track_alignment(signal: dict[str, Any], fusion: dict[str, Any]) -> float:
    tech = _maybe_float(fusion.get("tech_score") if fusion.get("tech_score") is not None else signal.get("tech_score"))
    context = _maybe_float(fusion.get("context_score") if fusion.get("context_score") is not None else signal.get("context_score"))
    if tech is None or context is None:
        return 0.5
    return _clamp(1.0 - abs(tech - context) / 2.0, 0.0, 1.0)


def _late_rebound(metrics: dict[str, Any], trend: dict[str, Any], policy: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not trend.get("ma20_rising") and metrics.get("price", 0.0) > (metrics.get("ma20") or float("inf")):
        reasons.append("MA20 still falling")
    if int(trend.get("above_ma20_checkpoints") or 0) < int(policy["confirm_checkpoints"]) and not trend.get("retest_confirmed"):
        reasons.append("insufficient checkpoints above MA20")
    if not trend.get("ma_stack") and not trend.get("retest_confirmed"):
        reasons.append("MA stack not confirmed")
    return bool(reasons), reasons


def _hot_zone_risk(metrics: dict[str, Any], policy: dict[str, Any]) -> tuple[float, list[str]]:
    rsi = metrics.get("rsi")
    recent_5d_return = metrics.get("recent_5d_return")
    volume_ratio = metrics.get("volume_ratio")
    rsi_hot = rsi is not None and rsi >= float(policy["hot_zone_rsi_threshold"])
    rsi_extreme = rsi is not None and rsi >= float(policy["hot_zone_extreme_rsi_threshold"])
    return_hot = (
        recent_5d_return is not None
        and recent_5d_return >= float(policy["hot_zone_recent_5d_return_threshold"])
    )
    return_extreme = (
        recent_5d_return is not None
        and recent_5d_return >= float(policy["hot_zone_extreme_recent_5d_return_threshold"])
    )
    volume_hot = volume_ratio is not None and volume_ratio >= float(policy["hot_zone_volume_ratio_threshold"])

    active = bool(rsi_extreme or return_extreme or ((rsi_hot or return_hot) and volume_hot) or (rsi_hot and return_hot))
    if not active:
        return 0.0, []

    reasons = ["hot_zone_extended"]
    if rsi_extreme:
        reasons.append("hot_zone_rsi_extreme")
    elif rsi_hot:
        reasons.append("hot_zone_rsi_overbought")
    if return_extreme:
        reasons.append("hot_zone_recent_return_extreme")
    elif return_hot:
        reasons.append("hot_zone_recent_return_elevated")
    if volume_hot:
        reasons.append("hot_zone_volume_amplified")
    return float(policy["hot_zone_penalty"]), reasons


def _t1_risk(signal: dict[str, Any], trend: dict[str, Any], policy: dict[str, Any]) -> bool:
    market = str(signal.get("market") or "A").strip().upper()
    timeframe = str(signal.get("timeframe") or signal.get("analysis_timeframe") or "30m").strip().lower()
    if market not in {"A", "ASHARE", "CN", "CHINA"} or timeframe not in {"30m", "15m", "5m", "1m"}:
        return False
    if _strong_t1_confirmation(trend, policy):
        return False
    return True


def _strong_t1_confirmation(trend: dict[str, Any], policy: dict[str, Any]) -> bool:
    required = int(policy["t1_confirm_checkpoints"])
    above_ma20 = int(trend.get("above_ma20_checkpoints") or 0)
    has_structure = bool(trend.get("ma_stack") or trend.get("retest_confirmed"))
    return bool(trend.get("ma20_rising")) and above_ma20 >= required and has_structure


def _stock_failure_penalty(profile: dict[str, Any], policy: dict[str, Any]) -> float:
    gate = _dict(profile.get("stock_execution_feedback_gate"))
    return float(policy["stock_failure_penalty"]) if str(gate.get("status") or "").lower() == "downgraded" else 0.0


def _cold_start_state(profile: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    gate = _dict(profile.get("stock_execution_feedback_gate"))
    sample_count = int(_float(gate.get("sample_count"), 0.0))
    realized_pnl = _float(gate.get("recent_realized_pnl"), 0.0)
    threshold = int(policy.get("cold_start_profit_sample_threshold") or 1)
    active = sample_count < threshold and realized_pnl <= 0
    return {
        "active": bool(active),
        "sample_count": sample_count,
        "recent_realized_pnl": round(realized_pnl, 4),
        "profit_sample_threshold": threshold,
    }


def _trend_structure_score(trend: dict[str, Any], metrics: dict[str, Any]) -> float:
    above_ma20 = int(trend.get("above_ma20_checkpoints") or 0)
    if trend.get("ma_stack") and trend.get("ma20_rising"):
        return 1.0
    if trend.get("retest_confirmed"):
        return 0.65
    if trend.get("ma20_rising") and above_ma20 >= 2:
        return 0.75
    if above_ma20 >= 3 and float(metrics.get("ma20_slope") or 0.0) >= 0:
        return 0.5
    if metrics.get("price") and metrics.get("ma20") and metrics["price"] > metrics["ma20"]:
        return 0.25
    return 0.0


def _confirmation_score(trend: dict[str, Any], policy: dict[str, Any]) -> float:
    score = _clamp(int(trend.get("above_ma20_checkpoints") or 0) / max(int(policy["confirm_checkpoints"]), 1), 0.0, 1.0)
    return max(score, 0.75) if trend.get("retest_confirmed") else score


def _initial_tier(score: float, policy: dict[str, Any]) -> str:
    if score < float(policy["weak_buy_max_score"]):
        return "weak_buy"
    if score < float(policy["strong_buy_min_score"]):
        return "normal_buy"
    return "strong_buy"


def _apply_hard_tier_requirements(
    *,
    tier: str,
    score: float,
    buy_edge: float,
    trend: dict[str, Any],
    is_late_rebound: bool,
    t1_active: bool,
    hot_zone_active: bool,
    policy: dict[str, Any],
) -> str:
    if t1_active:
        return "weak_buy"
    trend_confirmed = (
        (trend.get("ma20_rising") and int(trend.get("above_ma20_checkpoints") or 0) >= int(policy["confirm_checkpoints"]))
        or trend.get("ma_stack")
        or trend.get("retest_confirmed")
    )
    if tier == "normal_buy" and hot_zone_active:
        return "weak_buy"
    if tier == "normal_buy" and (not trend_confirmed or is_late_rebound):
        return "weak_buy"
    strong_ok = (
        score >= float(policy["strong_buy_min_score"])
        and trend.get("ma_stack")
        and trend.get("ma20_rising")
        and (not is_late_rebound or buy_edge >= float(policy["strong_edge_abs"]))
    )
    if tier == "strong_buy" and hot_zone_active and buy_edge < float(policy["strong_edge_abs"]):
        return "normal_buy" if trend_confirmed else "weak_buy"
    if tier == "strong_buy" and not strong_ok:
        return "normal_buy" if trend_confirmed else "weak_buy"
    if buy_edge < float(policy["weak_edge_abs"]):
        return "weak_buy"
    return tier


def _portfolio_state(summary: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    recent_sell_count = int(_float(summary.get("recent_sell_count"), 0.0))
    recent_stop_count = int(_float(summary.get("recent_stop_loss_count"), 0.0))
    stop_density = recent_stop_count / max(recent_sell_count, 1)
    recent_pnl_pct = _float(summary.get("recent_realized_pnl_pct"), 0.0)
    recent_pnl = _float(summary.get("recent_realized_pnl"), 0.0)
    reference_equity = _float(summary.get("reference_equity"), 0.0)
    checkpoint_buy_count = int(_float(summary.get("current_checkpoint_buy_count"), 0.0))
    day_buy_count = int(_float(summary.get("current_day_buy_count"), 0.0))
    loss_budget_amount = -abs(reference_equity * float(policy["loss_budget_pct"]) / 100.0) if reference_equity > 0 else None
    cooldown = recent_stop_count >= int(policy["stop_loss_circuit_threshold"]) and stop_density >= float(policy["stop_loss_density_threshold"])
    loss_budget = recent_pnl_pct <= float(policy["loss_budget_pct"]) or (
        loss_budget_amount is not None and recent_pnl <= loss_budget_amount
    )
    drawdown = _float(summary.get("portfolio_drawdown_pct"), 0.0) >= float(policy["drawdown_guard_pct"])
    consecutive = int(_float(summary.get("consecutive_stop_loss_count"), 0.0)) >= int(policy["consecutive_stop_loss_threshold"])
    checkpoint_limit = checkpoint_buy_count >= int(policy["max_new_buys_per_checkpoint"])
    day_limit = day_buy_count >= int(policy["max_new_buys_per_day"])
    buy_limit = checkpoint_limit or day_limit
    reasons: list[str] = []
    if cooldown:
        reasons.append("组合止损密度达到冷却阈值")
    if loss_budget:
        reasons.append("组合近期亏损达到预算阈值")
    if drawdown:
        reasons.append("组合回撤达到防守阈值")
    if consecutive:
        reasons.append("组合连续止损达到暂停阈值")
    if checkpoint_limit:
        reasons.append("组合防守：超过本 checkpoint BUY 上限")
    if day_limit:
        reasons.append("组合防守：超过本日 BUY 上限")
    return {
        "cooldown_active": cooldown,
        "current_checkpoint_buy_count": checkpoint_buy_count,
        "current_day_buy_count": day_buy_count,
        "recent_stop_loss_count": recent_stop_count,
        "consecutive_stop_loss_count": int(_float(summary.get("consecutive_stop_loss_count"), 0.0)),
        "recent_realized_pnl": round(recent_pnl, 4),
        "recent_realized_pnl_pct": round(recent_pnl_pct, 4),
        "stop_loss_density": round(stop_density, 6),
        "portfolio_drawdown_pct": round(_float(summary.get("portfolio_drawdown_pct"), 0.0), 4),
        "loss_budget_triggered": loss_budget,
        "drawdown_guard_triggered": drawdown,
        "buy_limit_triggered": buy_limit,
        "blocked": bool(loss_budget or consecutive or buy_limit),
        "reasons": reasons,
    }


def _profile_id(signal: dict[str, Any]) -> str | None:
    selected = _dict(_dict(signal.get("strategy_profile")).get("selected_strategy_profile"))
    return selected.get("id")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled", "开启"}


def _maybe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_maybe_float(*values: Any) -> float | None:
    for value in values:
        maybe = _maybe_float(value)
        if maybe is not None:
            return maybe
    return None


def _return_ratio(value: Any) -> float | None:
    maybe = _maybe_float(value)
    if maybe is None:
        return None
    if abs(maybe) > 2.0:
        return maybe / 100.0
    return maybe


def _float(value: Any, default: float) -> float:
    maybe = _maybe_float(value)
    return default if maybe is None else maybe


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(max(float(value), lower), upper)
