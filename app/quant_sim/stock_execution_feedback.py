"""Stock-level execution feedback gates shared by live sim and replay."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


DEFAULT_STOCK_EXECUTION_FEEDBACK_POLICY: dict[str, Any] = {
    "enabled": True,
    "lookback_days": 20,
    "stop_loss_count_threshold": 2,
    "stop_loss_cooldown_days": 12,
    "loss_pnl_pct_threshold": -5.0,
    "loss_amount_threshold": -1000.0,
    "loss_reentry_size_multiplier": 0.35,
    "repeated_stop_size_multiplier": 0.25,
    "require_trend_confirmation": True,
    "trend_confirm_checkpoints": 3,
    "require_ma20_slope": True,
    "allow_ma_stack_confirmation": True,
    "allow_ma20_retest_confirmation": True,
    "strict_reentry_trend_confirmation": True,
    "execution_feedback_score_cap": 0.25,
}


STOCK_EXECUTION_FEEDBACK_PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "aggressive": {
        **DEFAULT_STOCK_EXECUTION_FEEDBACK_POLICY,
        "lookback_days": 15,
        "stop_loss_cooldown_days": 8,
        "loss_pnl_pct_threshold": -8.0,
        "loss_amount_threshold": -2000.0,
        "loss_reentry_size_multiplier": 0.5,
        "repeated_stop_size_multiplier": 0.25,
        "trend_confirm_checkpoints": 2,
    },
    "stable": {
        **DEFAULT_STOCK_EXECUTION_FEEDBACK_POLICY,
        "lookback_days": 20,
        "stop_loss_cooldown_days": 12,
        "loss_pnl_pct_threshold": -5.0,
        "loss_amount_threshold": -1000.0,
        "loss_reentry_size_multiplier": 0.35,
        "repeated_stop_size_multiplier": 0.25,
        "trend_confirm_checkpoints": 3,
    },
    "conservative": {
        **DEFAULT_STOCK_EXECUTION_FEEDBACK_POLICY,
        "lookback_days": 30,
        "stop_loss_cooldown_days": 20,
        "loss_pnl_pct_threshold": -3.0,
        "loss_amount_threshold": -500.0,
        "loss_reentry_size_multiplier": 0.25,
        "repeated_stop_size_multiplier": 0.15,
        "trend_confirm_checkpoints": 3,
    },
}


@dataclass(frozen=True)
class StockExecutionFeedbackSummary:
    stock_code: str
    lookback_days: int
    recent_stop_loss_count: int = 0
    recent_loss_trade_count: int = 0
    recent_realized_pnl: float = 0.0
    recent_realized_pnl_pct: float = 0.0
    sample_count: int = 0
    last_stop_loss_at: str | None = None
    last_loss_sell_at: str | None = None
    recent_checkpoints: list[dict[str, Any]] = field(default_factory=list)


def default_stock_execution_feedback_policy(profile_id: str | None = None) -> dict[str, Any]:
    key = str(profile_id or "").strip().lower()
    if "aggressive" in key:
        return dict(STOCK_EXECUTION_FEEDBACK_PROFILE_DEFAULTS["aggressive"])
    if "conservative" in key:
        return dict(STOCK_EXECUTION_FEEDBACK_PROFILE_DEFAULTS["conservative"])
    if "stable" in key or "neutral" in key:
        return dict(STOCK_EXECUTION_FEEDBACK_PROFILE_DEFAULTS["stable"])
    return dict(DEFAULT_STOCK_EXECUTION_FEEDBACK_POLICY)


def normalize_stock_execution_feedback_policy(
    raw: dict[str, Any] | None,
    *,
    profile_id: str | None = None,
) -> dict[str, Any]:
    policy = default_stock_execution_feedback_policy(profile_id)
    if isinstance(raw, dict):
        policy.update(raw)
    policy["enabled"] = _bool(policy.get("enabled"), True)
    policy["lookback_days"] = max(1, int(_float(policy.get("lookback_days"), 20)))
    policy["stop_loss_count_threshold"] = max(1, int(_float(policy.get("stop_loss_count_threshold"), 2)))
    policy["stop_loss_cooldown_days"] = max(0, int(_float(policy.get("stop_loss_cooldown_days"), 12)))
    policy["loss_pnl_pct_threshold"] = min(0.0, _float(policy.get("loss_pnl_pct_threshold"), -5.0))
    policy["loss_amount_threshold"] = min(0.0, _float(policy.get("loss_amount_threshold"), -1000.0))
    policy["loss_reentry_size_multiplier"] = _clamp(_float(policy.get("loss_reentry_size_multiplier"), 0.35), 0.0, 1.0)
    policy["repeated_stop_size_multiplier"] = _clamp(_float(policy.get("repeated_stop_size_multiplier"), 0.25), 0.0, 1.0)
    policy["require_trend_confirmation"] = _bool(policy.get("require_trend_confirmation"), True)
    policy["trend_confirm_checkpoints"] = max(1, int(_float(policy.get("trend_confirm_checkpoints"), 3)))
    policy["require_ma20_slope"] = _bool(policy.get("require_ma20_slope"), True)
    policy["allow_ma_stack_confirmation"] = _bool(policy.get("allow_ma_stack_confirmation"), True)
    policy["allow_ma20_retest_confirmation"] = _bool(policy.get("allow_ma20_retest_confirmation"), True)
    policy["strict_reentry_trend_confirmation"] = _bool(policy.get("strict_reentry_trend_confirmation"), True)
    policy["execution_feedback_score_cap"] = max(0.0, _float(policy.get("execution_feedback_score_cap"), 0.25))
    return policy


def evaluate_stock_execution_feedback_gate(
    *,
    action: str,
    stock_code: str,
    policy: dict[str, Any] | None,
    summary: StockExecutionFeedbackSummary | dict[str, Any] | None,
    market_snapshot: dict[str, Any] | None,
    current_time: datetime | str | None = None,
) -> dict[str, Any]:
    resolved_policy = normalize_stock_execution_feedback_policy(policy)
    summary_obj = _summary_from_any(stock_code, summary, resolved_policy)
    metrics = _extract_metrics(market_snapshot)
    checkpoints = summary_obj.recent_checkpoints
    if not checkpoints and isinstance(market_snapshot, dict) and isinstance(market_snapshot.get("recent_checkpoints"), list):
        checkpoints = market_snapshot["recent_checkpoints"]
    trend = _trend_confirmation(metrics, checkpoints, resolved_policy)
    cap = max(0.0, _float(resolved_policy.get("execution_feedback_score_cap"), 0.25))
    status = "passed"
    multiplier = 1.0
    reasons: list[str] = []

    if str(action or "").upper() != "BUY" or not str(stock_code or "").strip() or not resolved_policy["enabled"]:
        return _gate(
            status="passed",
            multiplier=1.0,
            policy=resolved_policy,
            summary=summary_obj,
            trend=trend,
            feedback_score=0.0,
            reasons=[],
            current_time=current_time,
        )

    stop_threshold = int(resolved_policy["stop_loss_count_threshold"])
    stop_cooldown_active = _within_cooldown(
        summary_obj.last_stop_loss_at,
        current_time,
        int(resolved_policy.get("stop_loss_cooldown_days") or 0),
    )
    loss_reentry_cooldown_active = _within_cooldown(
        summary_obj.last_loss_sell_at,
        current_time,
        int(resolved_policy.get("stop_loss_cooldown_days") or 0),
    )
    repeated_stop = summary_obj.recent_stop_loss_count >= stop_threshold and stop_cooldown_active
    recent_loss_reentry = summary_obj.recent_loss_trade_count > 0
    repeated_loss = summary_obj.recent_loss_trade_count >= stop_threshold
    loss_trigger = (
        summary_obj.recent_realized_pnl <= float(resolved_policy["loss_amount_threshold"])
        or summary_obj.recent_realized_pnl_pct <= float(resolved_policy["loss_pnl_pct_threshold"])
    )

    if repeated_stop or repeated_loss:
        if repeated_stop:
            reasons.append(f"最近{summary_obj.lookback_days}天止损{summary_obj.recent_stop_loss_count}次")
        if repeated_loss:
            reasons.append(f"最近{summary_obj.lookback_days}天亏损卖出{summary_obj.recent_loss_trade_count}次")
        if resolved_policy["require_trend_confirmation"] and not trend["confirmed"]:
            status = "blocked"
            multiplier = 0.0
            reasons.append("缺少强趋势确认")
        else:
            status = "downgraded"
            multiplier = min(multiplier, float(resolved_policy["repeated_stop_size_multiplier"]))
            reasons.append("连续亏损后仅允许轻仓试错")
    elif recent_loss_reentry:
        reasons.append(f"最近{summary_obj.lookback_days}天存在亏损卖出")
        if resolved_policy["require_trend_confirmation"] and not trend["confirmed"]:
            status = "blocked"
            multiplier = 0.0
            reasons.append("缺少强趋势确认")
        else:
            status = "downgraded"
            multiplier = min(multiplier, float(resolved_policy["loss_reentry_size_multiplier"]))
            reasons.append("亏损后仅允许降仓试错")

    if loss_trigger and status != "blocked":
        status = "downgraded"
        multiplier = min(multiplier, float(resolved_policy["loss_reentry_size_multiplier"]))
        reasons.append(
            f"近期累计已实现盈亏{summary_obj.recent_realized_pnl:.2f} / {summary_obj.recent_realized_pnl_pct:.2f}%"
        )

    if status == "passed":
        feedback_score = 0.0
    else:
        severity = 0.0
        if repeated_stop:
            severity += 0.7
        if repeated_loss:
            severity += 0.7
        elif recent_loss_reentry:
            severity += 0.4
        if loss_trigger:
            severity += 0.5
        feedback_score = -min(cap, cap * min(1.0, severity))

    return _gate(
        status=status,
        multiplier=multiplier,
        policy=resolved_policy,
        summary=summary_obj,
        trend=trend,
        feedback_score=feedback_score,
        reasons=reasons,
        current_time=current_time,
    )


def _gate(
    *,
    status: str,
    multiplier: float,
    policy: dict[str, Any],
    summary: StockExecutionFeedbackSummary,
    trend: dict[str, Any],
    feedback_score: float,
    reasons: list[str],
    current_time: datetime | str | None,
) -> dict[str, Any]:
    return {
        "intent": "stock_execution_feedback",
        "status": status,
        "size_multiplier": round(_clamp(multiplier, 0.0, 1.0), 6),
        "execution_feedback_score": round(feedback_score, 6),
        "recent_stop_loss_count": int(summary.recent_stop_loss_count),
        "recent_loss_trade_count": int(summary.recent_loss_trade_count),
        "recent_realized_pnl": round(float(summary.recent_realized_pnl), 4),
        "recent_realized_pnl_pct": round(float(summary.recent_realized_pnl_pct), 4),
        "sample_count": int(summary.sample_count),
        "lookback_days": int(summary.lookback_days),
        "last_stop_loss_at": summary.last_stop_loss_at,
        "last_loss_sell_at": summary.last_loss_sell_at,
        "stop_loss_cooldown_days": int(policy.get("stop_loss_cooldown_days") or 0),
        "stop_loss_cooldown_active": _within_cooldown(
            summary.last_stop_loss_at,
            current_time,
            int(policy.get("stop_loss_cooldown_days") or 0),
        ),
        "loss_reentry_cooldown_active": _within_cooldown(
            summary.last_loss_sell_at,
            current_time,
            int(policy.get("stop_loss_cooldown_days") or 0),
        ),
        "recent_loss_reentry_active": summary.recent_loss_trade_count > 0,
        "trend_confirmed": bool(trend.get("confirmed")),
        "trend_confirmation": trend,
        "policy": policy,
        "evaluated_at": _time_text(current_time),
        "reasons": reasons,
    }


def _trend_confirmation(
    metrics: dict[str, float | None],
    checkpoints: list[dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    price = metrics.get("price")
    ma5 = metrics.get("ma5")
    ma10 = metrics.get("ma10")
    ma20 = metrics.get("ma20")
    ma20_slope = metrics.get("ma20_slope")
    if price is None or ma20 is None or price <= 0 or ma20 <= 0:
        return {"confirmed": False, "mode": "missing_market_snapshot"}

    require_slope = bool(policy.get("require_ma20_slope", True))
    ma_stack = (
        bool(policy.get("allow_ma_stack_confirmation", True))
        and ma5 is not None
        and ma10 is not None
        and ma5 > ma10 > ma20
        and price > ma20
        and (not require_slope or (ma20_slope is not None and ma20_slope > 0.0))
    )

    needed = int(policy.get("trend_confirm_checkpoints") or 1)
    recent = checkpoints[-needed:] if needed > 0 else []
    checkpoints_confirmed = False
    slopes_ok = False
    if len(recent) >= needed:
        above = all(_price_above_ma20(item) for item in recent)
        slopes_ok = all((_float(item.get("ma20_slope"), 0.0) > 0.0) for item in recent) if require_slope else True
        checkpoints_confirmed = above and slopes_ok

    retest_confirmed = False
    if bool(policy.get("allow_ma20_retest_confirmation", True)) and len(checkpoints) >= 3:
        previous = checkpoints[-3:]
        broke_above = _price_above_ma20(previous[0])
        retest_ok = _low_not_below_ma20(previous[1])
        recovered = _price_above_ma20(previous[2])
        retest_confirmed = broke_above and retest_ok and recovered

    if bool(policy.get("strict_reentry_trend_confirmation", True)):
        required = {
            "ma_stack": ma_stack,
            "above_ma20_checkpoints": checkpoints_confirmed,
            "ma20_retest": retest_confirmed if bool(policy.get("allow_ma20_retest_confirmation", True)) else True,
        }
        confirmed = all(required.values())
        if confirmed:
            return {
                "confirmed": True,
                "mode": "strict_reentry_trend",
                "ma_stack": ma_stack,
                "above_ma20_checkpoints": needed,
                "ma20_retest": retest_confirmed,
                "reason": "MA多头排列、连续checkpoint站上MA20、MA20回踩确认均满足",
            }
        missing = [label for label, ok in required.items() if not ok]
        return {
            "confirmed": False,
            "mode": "weak_or_unconfirmed",
            "ma_stack": ma_stack,
            "above_ma20_checkpoints": len(recent) if checkpoints_confirmed else 0,
            "ma20_retest": retest_confirmed,
            "missing": missing,
            "reason": "亏损后再买需要同时满足MA多头、连续checkpoint、MA20回踩确认",
        }

    if ma_stack:
        return {"confirmed": True, "mode": "ma_stack", "reason": "MA5 > MA10 > MA20 且价格站上 MA20"}

    if checkpoints_confirmed:
        return {
            "confirmed": True,
            "mode": "above_ma20_checkpoints",
            "checkpoint_count": needed,
            "reason": f"价格连续{needed}个checkpoint站上MA20" + ("且MA20上行" if require_slope else ""),
        }

    if retest_confirmed:
        return {"confirmed": True, "mode": "ma20_retest", "reason": "突破后回踩不破MA20并重新站上"}

    return {"confirmed": False, "mode": "weak_or_unconfirmed", "reason": "仅站上MA20不足以通过亏损反馈例外"}


def _summary_from_any(
    stock_code: str,
    value: StockExecutionFeedbackSummary | dict[str, Any] | None,
    policy: dict[str, Any],
) -> StockExecutionFeedbackSummary:
    if isinstance(value, StockExecutionFeedbackSummary):
        return value
    payload = value if isinstance(value, dict) else {}
    return StockExecutionFeedbackSummary(
        stock_code=str(payload.get("stock_code") or stock_code or ""),
        lookback_days=int(payload.get("lookback_days") or policy.get("lookback_days") or 20),
        recent_stop_loss_count=int(payload.get("recent_stop_loss_count") or 0),
        recent_loss_trade_count=int(payload.get("recent_loss_trade_count") or 0),
        recent_realized_pnl=float(payload.get("recent_realized_pnl") or 0.0),
        recent_realized_pnl_pct=float(payload.get("recent_realized_pnl_pct") or 0.0),
        sample_count=int(payload.get("sample_count") or 0),
        last_stop_loss_at=payload.get("last_stop_loss_at"),
        last_loss_sell_at=payload.get("last_loss_sell_at"),
        recent_checkpoints=payload.get("recent_checkpoints") if isinstance(payload.get("recent_checkpoints"), list) else [],
    )


def _extract_metrics(snapshot: dict[str, Any] | None) -> dict[str, float | None]:
    payload = snapshot if isinstance(snapshot, dict) else {}
    return {
        "price": _optional_float(payload.get("current_price") or payload.get("latest_price") or payload.get("close")),
        "ma5": _optional_float(payload.get("ma5")),
        "ma10": _optional_float(payload.get("ma10")),
        "ma20": _optional_float(payload.get("ma20")),
        "ma20_slope": _optional_float(payload.get("ma20_slope")),
    }


def _price_above_ma20(item: dict[str, Any]) -> bool:
    price = _optional_float(item.get("current_price") or item.get("latest_price") or item.get("close"))
    ma20 = _optional_float(item.get("ma20"))
    return price is not None and ma20 is not None and price > ma20 > 0


def _low_not_below_ma20(item: dict[str, Any]) -> bool:
    low = _optional_float(item.get("low") or item.get("lowest_price") or item.get("current_price") or item.get("close"))
    ma20 = _optional_float(item.get("ma20"))
    return low is not None and ma20 is not None and low >= ma20 > 0


def _optional_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any, default: float) -> float:
    parsed = _optional_float(value)
    return default if parsed is None else parsed


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "on", "enabled"}:
        return True
    if text in {"false", "0", "no", "off", "disabled"}:
        return False
    return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _time_text(value: datetime | str | None) -> str | None:
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat(sep=" ")
    if value in (None, ""):
        return None
    return str(value)


def _within_cooldown(last_at: str | None, current_time: datetime | str | None, cooldown_days: int) -> bool:
    if cooldown_days <= 0:
        return True
    last_dt = _parse_time(last_at)
    current_dt = _parse_time(current_time)
    if last_dt is None or current_dt is None:
        return True
    return 0 <= (current_dt.date() - last_dt.date()).days <= cooldown_days


def _parse_time(value: datetime | str | None) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if value in (None, ""):
        return None
    text = str(value).strip().replace("T", " ").replace("Z", "")
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        try:
            return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
