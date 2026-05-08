"""Lifecycle rules for realtime quant universe management."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class QuantStatus(str, Enum):
    INACTIVE = "inactive"
    TRIAL = "trial"
    ACTIVE = "active"
    EXIT_ONLY = "exit_only"
    COOLING = "cooling"
    RETIRED = "retired"
    MANUAL_PAUSED = "manual_paused"


class ManualOverride(str, Enum):
    NONE = "none"
    MANUAL_PIN = "manual_pin"
    MANUAL_PAUSE = "manual_pause"
    MANUAL_BAN = "manual_ban"


class AutoEntryMode(str, Enum):
    MANUAL_ONLY = "manual_only"
    CONFIRM_FIRST = "confirm_first"
    AUTO_TRIAL = "auto_trial"


@dataclass(frozen=True)
class QuantUniverseLifecyclePolicy:
    profile_id: str
    trial_threshold: float
    strong_candidate_threshold: float
    high_reentry_threshold: float
    active_upgrade_threshold: float
    active_upgrade_confirm_checkpoints: int
    exit_only_threshold: float
    cooling_threshold: float
    retire_threshold: float
    exit_only_downtrend_streak: int
    downtrend_cooling_streak: int
    trial_no_buy_days_threshold: int
    reentry_watch_hours: int
    weak_warning_tech_threshold: float
    warning_to_downtrend_threshold: int
    health_score_lookback_checkpoints: int
    candidate_support_lookback_days: int
    trial_min_dwell_checkpoints: int
    cooling_min_dwell_days: int
    retired_min_dwell_days: int
    cooling_review_interval_minutes: int
    retired_reactivation_check_enabled: bool
    trial_position_multiplier: float
    trial_max_position_pct: float
    source_score_weight: float
    confidence_weight: float
    trend_weight: float
    multi_source_weight: float
    liquidity_penalty_multiplier: float
    cooldown_penalty_multiplier: float
    manual_priority_bonus_multiplier: float
    fusion_health_weight: float
    buy_strength_health_weight: float
    tech_health_weight: float
    context_health_weight: float
    candidate_support_bonus_multiplier: float
    execution_penalty_multiplier: float
    inactivity_penalty_multiplier: float
    reentry_watch_penalty_multiplier: float

    @classmethod
    def aggressive_defaults(cls) -> "QuantUniverseLifecyclePolicy":
        return cls(
            profile_id="aggressive",
            trial_threshold=0.50,
            strong_candidate_threshold=0.70,
            high_reentry_threshold=0.85,
            active_upgrade_threshold=60,
            active_upgrade_confirm_checkpoints=2,
            exit_only_threshold=38,
            cooling_threshold=30,
            retire_threshold=22,
            exit_only_downtrend_streak=3,
            downtrend_cooling_streak=3,
            trial_no_buy_days_threshold=12,
            reentry_watch_hours=72,
            weak_warning_tech_threshold=0.10,
            warning_to_downtrend_threshold=4,
            health_score_lookback_checkpoints=8,
            candidate_support_lookback_days=5,
            trial_min_dwell_checkpoints=3,
            cooling_min_dwell_days=2,
            retired_min_dwell_days=7,
            cooling_review_interval_minutes=30,
            retired_reactivation_check_enabled=True,
            trial_position_multiplier=0.50,
            trial_max_position_pct=12.5,
            source_score_weight=0.40,
            confidence_weight=0.20,
            trend_weight=0.15,
            multi_source_weight=0.25,
            liquidity_penalty_multiplier=0.80,
            cooldown_penalty_multiplier=0.80,
            manual_priority_bonus_multiplier=1.10,
            fusion_health_weight=0.35,
            buy_strength_health_weight=0.30,
            tech_health_weight=0.20,
            context_health_weight=0.15,
            candidate_support_bonus_multiplier=1.10,
            execution_penalty_multiplier=0.90,
            inactivity_penalty_multiplier=0.80,
            reentry_watch_penalty_multiplier=1.00,
        )

    @classmethod
    def stable_defaults(cls) -> "QuantUniverseLifecyclePolicy":
        return cls(
            profile_id="stable",
            trial_threshold=0.55,
            strong_candidate_threshold=0.75,
            high_reentry_threshold=0.88,
            active_upgrade_threshold=65,
            active_upgrade_confirm_checkpoints=3,
            exit_only_threshold=35,
            cooling_threshold=28,
            retire_threshold=20,
            exit_only_downtrend_streak=2,
            downtrend_cooling_streak=3,
            trial_no_buy_days_threshold=10,
            reentry_watch_hours=72,
            weak_warning_tech_threshold=0.15,
            warning_to_downtrend_threshold=3,
            health_score_lookback_checkpoints=10,
            candidate_support_lookback_days=5,
            trial_min_dwell_checkpoints=4,
            cooling_min_dwell_days=3,
            retired_min_dwell_days=10,
            cooling_review_interval_minutes=60,
            retired_reactivation_check_enabled=True,
            trial_position_multiplier=0.35,
            trial_max_position_pct=10.0,
            source_score_weight=0.35,
            confidence_weight=0.20,
            trend_weight=0.25,
            multi_source_weight=0.20,
            liquidity_penalty_multiplier=1.00,
            cooldown_penalty_multiplier=1.00,
            manual_priority_bonus_multiplier=1.00,
            fusion_health_weight=0.30,
            buy_strength_health_weight=0.25,
            tech_health_weight=0.25,
            context_health_weight=0.20,
            candidate_support_bonus_multiplier=1.00,
            execution_penalty_multiplier=1.00,
            inactivity_penalty_multiplier=1.00,
            reentry_watch_penalty_multiplier=1.10,
        )

    @classmethod
    def conservative_defaults(cls) -> "QuantUniverseLifecyclePolicy":
        return cls(
            profile_id="conservative",
            trial_threshold=0.65,
            strong_candidate_threshold=0.82,
            high_reentry_threshold=0.92,
            active_upgrade_threshold=70,
            active_upgrade_confirm_checkpoints=4,
            exit_only_threshold=42,
            cooling_threshold=34,
            retire_threshold=26,
            exit_only_downtrend_streak=2,
            downtrend_cooling_streak=2,
            trial_no_buy_days_threshold=8,
            reentry_watch_hours=72,
            weak_warning_tech_threshold=0.20,
            warning_to_downtrend_threshold=2,
            health_score_lookback_checkpoints=12,
            candidate_support_lookback_days=7,
            trial_min_dwell_checkpoints=5,
            cooling_min_dwell_days=4,
            retired_min_dwell_days=14,
            cooling_review_interval_minutes=90,
            retired_reactivation_check_enabled=True,
            trial_position_multiplier=0.25,
            trial_max_position_pct=7.5,
            source_score_weight=0.30,
            confidence_weight=0.20,
            trend_weight=0.35,
            multi_source_weight=0.15,
            liquidity_penalty_multiplier=1.20,
            cooldown_penalty_multiplier=1.20,
            manual_priority_bonus_multiplier=0.90,
            fusion_health_weight=0.25,
            buy_strength_health_weight=0.15,
            tech_health_weight=0.30,
            context_health_weight=0.30,
            candidate_support_bonus_multiplier=0.90,
            execution_penalty_multiplier=1.20,
            inactivity_penalty_multiplier=1.20,
            reentry_watch_penalty_multiplier=1.25,
        )


@dataclass(frozen=True)
class HealthInputs:
    avg_tech_score: float = 0.0
    avg_context_score: float = 0.0
    avg_fusion_score: float = 0.0
    avg_buy_strength_score: float = 0.0
    no_buy_days: int = 0
    recent_stoploss_count: int = 0
    blocked_streak: int = 0
    candidate_support_bonus: float = 0.0
    valid_candidate_event_count: int = 0
    reentry_watch_until: datetime | str | None = None
    now: datetime | str | None = None


@dataclass(frozen=True)
class HealthResult:
    health_score: float
    breakdown: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class TransitionResult:
    allowed: bool
    from_status: QuantStatus
    to_status: QuantStatus
    reason_code: str
    reason: str = ""
    error_code: str | None = None
    error_message: str | None = None


def calculate_health_score(inputs: HealthInputs, policy: QuantUniverseLifecyclePolicy) -> HealthResult:
    normalized_tech = _clamp(((float(inputs.avg_tech_score) + 1.0) / 2.0) * 100.0, 0.0, 100.0)
    normalized_context = _clamp(((float(inputs.avg_context_score) + 1.0) / 2.0) * 100.0, 0.0, 100.0)
    normalized_fusion = _clamp(float(inputs.avg_fusion_score) * 100.0, 0.0, 100.0)
    normalized_buy_strength = _clamp(float(inputs.avg_buy_strength_score) * 100.0, 0.0, 100.0)
    kernel_health_base = (
        normalized_fusion * policy.fusion_health_weight
        + normalized_buy_strength * policy.buy_strength_health_weight
        + normalized_tech * policy.tech_health_weight
        + normalized_context * policy.context_health_weight
    )
    execution_penalty_base = float(inputs.recent_stoploss_count) * 5.0 + float(inputs.blocked_streak) * 3.0
    execution_penalty = execution_penalty_base * policy.execution_penalty_multiplier
    inactivity_penalty_base = min(max(int(inputs.no_buy_days), 0), policy.trial_no_buy_days_threshold) * 2.0
    inactivity_penalty = inactivity_penalty_base * policy.inactivity_penalty_multiplier
    if inputs.valid_candidate_event_count > 0:
        candidate_support_bonus_base = min(float(inputs.valid_candidate_event_count) * 3.0, 15.0)
    else:
        candidate_support_bonus_base = float(inputs.candidate_support_bonus)
    candidate_support_bonus = candidate_support_bonus_base * policy.candidate_support_bonus_multiplier
    reentry_watch_penalty_base = 12.0 if _is_future(inputs.reentry_watch_until, inputs.now) else 0.0
    reentry_watch_penalty = reentry_watch_penalty_base * policy.reentry_watch_penalty_multiplier
    health_score = _clamp(
        kernel_health_base
        + candidate_support_bonus
        - execution_penalty
        - inactivity_penalty
        - reentry_watch_penalty,
        0.0,
        100.0,
    )
    return HealthResult(
        health_score=round(health_score, 4),
        breakdown={
            "normalized_tech_health": round(normalized_tech, 4),
            "normalized_context_health": round(normalized_context, 4),
            "normalized_fusion_health": round(normalized_fusion, 4),
            "normalized_buy_strength_health": round(normalized_buy_strength, 4),
            "kernel_health_base": round(kernel_health_base, 4),
            "execution_penalty_base": round(execution_penalty_base, 4),
            "execution_penalty": round(execution_penalty, 4),
            "inactivity_penalty_base": round(inactivity_penalty_base, 4),
            "inactivity_penalty": round(inactivity_penalty, 4),
            "candidate_support_bonus_base": round(candidate_support_bonus_base, 4),
            "candidate_support_bonus": round(candidate_support_bonus, 4),
            "reentry_watch_penalty_base": round(reentry_watch_penalty_base, 4),
            "reentry_watch_penalty": round(reentry_watch_penalty, 4),
        },
    )


def detect_weakening_warning(signal: dict[str, Any], policy: QuantUniverseLifecyclePolicy) -> bool:
    action = _action(signal)
    tech_score = _float(signal.get("tech_score"), 0.0)
    fusion_score = _float(signal.get("fusion_score"), 1.0)
    buy_threshold = _float(signal.get("buy_threshold"), policy.trial_threshold)
    buy_strength_score = _float(signal.get("buy_strength_score"), 1.0)
    price = _float(signal.get("price"), 0.0)
    ma20 = _float(signal.get("ma20"), 0.0)
    portfolio_gate = str(signal.get("portfolio_execution_guard_status") or "")
    return (
        (action == "HOLD" and tech_score < policy.weak_warning_tech_threshold)
        or (fusion_score < buy_threshold and fusion_score > 0)
        or (ma20 > 0 and price > 0 and abs(price - ma20) / ma20 <= 0.015 and buy_strength_score < 0.45)
        or portfolio_gate == "weak_buy"
    )


def detect_downtrend_hit(
    signal: dict[str, Any],
    state: dict[str, Any],
    policy: QuantUniverseLifecyclePolicy,
) -> bool:
    action = _action(signal)
    if action == "SELL":
        return True
    tech_score = _float(signal.get("tech_score"), 0.0)
    fusion_score = _float(signal.get("fusion_score"), 1.0)
    fusion_delta = _float(signal.get("fusion_score_delta"), 0.0)
    price = _float(signal.get("price"), 0.0)
    ma20 = _float(signal.get("ma20"), 0.0)
    ma20_slope = _float(signal.get("ma20_slope"), 0.0)
    warning_streak = int(state.get("weakening_warning_streak") or 0)
    return (
        (action == "HOLD" and tech_score <= 0 and (fusion_score < policy.trial_threshold or fusion_delta < 0))
        or (ma20 > 0 and price > 0 and price < ma20 and ma20_slope <= 0)
        or warning_streak >= policy.warning_to_downtrend_threshold
        or bool(signal.get("quick_stoploss_failure"))
        or (int(state.get("blocked_streak") or 0) >= policy.warning_to_downtrend_threshold)
    )


def calculate_candidate_score(
    events: list[dict[str, Any]],
    stock_snapshot: dict[str, Any],
    policy: QuantUniverseLifecyclePolicy,
) -> dict[str, Any]:
    if not events:
        return {"candidate_score": 0.0, "breakdown": {}}
    source_component = max(_float(event.get("source_score"), 0.0) for event in events)
    confidence_component = sum(_float(event.get("confidence"), 0.0) for event in events) / len(events)
    trend_component = max(_trend_score(event.get("trend")) for event in events)
    source_count = len({str(event.get("source_type") or "") for event in events if event.get("source_type")})
    multi_source_bonus = _clamp((source_count - 1) / 3.0, 0.0, 1.0)
    liquidity_penalty = 0.0 if stock_snapshot.get("is_liquid", True) else 0.10 * policy.liquidity_penalty_multiplier
    cooldown_penalty = 0.15 * policy.cooldown_penalty_multiplier if stock_snapshot.get("in_cooldown") else 0.0
    manual_priority_bonus = 0.08 * policy.manual_priority_bonus_multiplier if stock_snapshot.get("manual_priority") else 0.0
    weighted_sum = (
        source_component * policy.source_score_weight
        + confidence_component * policy.confidence_weight
        + trend_component * policy.trend_weight
        + multi_source_bonus * policy.multi_source_weight
    )
    candidate_score = _clamp(weighted_sum + manual_priority_bonus - liquidity_penalty - cooldown_penalty, 0.0, 1.0)
    return {
        "candidate_score": round(candidate_score, 4),
        "breakdown": {
            "source_score_component": round(source_component, 4),
            "confidence_component": round(confidence_component, 4),
            "trend_component": round(trend_component, 4),
            "multi_source_bonus": round(multi_source_bonus, 4),
            "liquidity_penalty": round(liquidity_penalty, 4),
            "cooldown_penalty": round(cooldown_penalty, 4),
            "manual_priority_bonus": round(manual_priority_bonus, 4),
        },
    }


def resolve_next_status(
    *,
    current_status: QuantStatus | str,
    health_score: float,
    policy: QuantUniverseLifecyclePolicy,
    downtrend_streak: int = 0,
    has_position: bool = False,
    candidate_support: bool = False,
    trend_confirmed: bool = False,
    active_trend_confirm_checkpoints: int = 0,
    requested_status: QuantStatus | str | None = None,
    manual_override: ManualOverride | str | None = None,
) -> TransitionResult:
    current = _status(current_status)
    requested = _status(requested_status) if requested_status else None
    override = _manual_override(manual_override)
    if override == ManualOverride.MANUAL_BAN:
        return _blocked(current, "manual_ban", "手工禁止自动纳入或恢复")
    if current == QuantStatus.MANUAL_PAUSED:
        return _blocked(current, "manual_paused_no_auto_restore", "手工暂停状态不允许系统自动恢复")
    if requested == QuantStatus.RETIRED and current in {QuantStatus.TRIAL, QuantStatus.ACTIVE}:
        return _blocked(current, "forbidden_direct_retire", "trial/active 禁止直接进入 retired")
    if current in {QuantStatus.ACTIVE, QuantStatus.TRIAL}:
        if has_position and (health_score < policy.exit_only_threshold or downtrend_streak >= policy.exit_only_downtrend_streak):
            return _transition(current, QuantStatus.EXIT_ONLY, "holding_downtrend_exit_only", "持仓下行，进入只出场管理")
        if (
            not has_position
            and health_score < policy.cooling_threshold
            and downtrend_streak >= policy.downtrend_cooling_streak
        ):
            return _transition(current, QuantStatus.COOLING, "flat_downtrend_cooling", "空仓且持续下行，进入冷却")
    if current == QuantStatus.EXIT_ONLY:
        if has_position:
            return _blocked(current, "exit_only_position_not_flat", "exit_only 持仓未清空，不能恢复")
        if (
            health_score >= policy.active_upgrade_threshold
            and trend_confirmed
            and active_trend_confirm_checkpoints >= policy.active_upgrade_confirm_checkpoints
        ):
            return _transition(current, QuantStatus.ACTIVE, "exit_only_recovered_to_active", "清仓后趋势强确认，恢复 active")
        if health_score >= policy.cooling_threshold and candidate_support:
            return _transition(current, QuantStatus.TRIAL, "exit_only_recovered_to_trial", "清仓后有新候选支持，恢复 trial")
        return _transition(current, QuantStatus.COOLING, "exit_only_flat_to_cooling", "清仓但恢复条件不足，进入冷却")
    return _blocked(current, "no_transition", "未满足状态流转条件")


def resolve_restore_to_trial(current_status: QuantStatus | str) -> TransitionResult:
    current = _status(current_status)
    if current in {QuantStatus.TRIAL, QuantStatus.ACTIVE, QuantStatus.EXIT_ONLY}:
        message = f"股票当前处于 {current.value}，无需恢复"
        if current == QuantStatus.ACTIVE:
            message = "股票当前处于 active，无需恢复"
        return TransitionResult(
            allowed=False,
            from_status=current,
            to_status=current,
            reason_code="invalid_restore_state",
            error_code="invalid_restore_state",
            error_message=message,
        )
    if current in {QuantStatus.COOLING, QuantStatus.MANUAL_PAUSED, QuantStatus.RETIRED}:
        return _transition(current, QuantStatus.TRIAL, "manual_restore_to_trial", "用户手工恢复到 trial")
    return _blocked(current, "invalid_restore_state", "当前状态不能恢复到 trial", error_code="invalid_restore_state")


def _transition(from_status: QuantStatus, to_status: QuantStatus, reason_code: str, reason: str) -> TransitionResult:
    return TransitionResult(
        allowed=True,
        from_status=from_status,
        to_status=to_status,
        reason_code=reason_code,
        reason=reason,
    )


def _blocked(
    status: QuantStatus,
    reason_code: str,
    reason: str,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
) -> TransitionResult:
    return TransitionResult(
        allowed=False,
        from_status=status,
        to_status=status,
        reason_code=reason_code,
        reason=reason,
        error_code=error_code,
        error_message=error_message,
    )


def _status(value: QuantStatus | str | None) -> QuantStatus:
    if isinstance(value, QuantStatus):
        return value
    text = str(value or "").strip()
    try:
        return QuantStatus(text)
    except ValueError:
        return QuantStatus.INACTIVE


def _manual_override(value: ManualOverride | str | None) -> ManualOverride:
    if isinstance(value, ManualOverride):
        return value
    text = str(value or "none").strip() or "none"
    try:
        return ManualOverride(text)
    except ValueError:
        return ManualOverride.NONE


def _action(signal: dict[str, Any]) -> str:
    return str(signal.get("final_action") or signal.get("action") or "").strip().upper()


def _trend_score(value: Any) -> float:
    text = str(value or "").strip().lower()
    if text in {"up", "bullish", "strong_up"}:
        return 1.0
    if text in {"flat", "neutral"}:
        return 0.5
    return 0.0


def _is_future(value: datetime | str | None, now: datetime | str | None) -> bool:
    if value is None:
        return False
    target = _to_datetime(value)
    current = _to_datetime(now) if now is not None else datetime.now(timezone.utc)
    return target > current


def _to_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _float(value: Any, default: float) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
