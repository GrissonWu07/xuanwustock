"""Lifecycle rules for realtime quant universe management."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
import json
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
    max_auto_entries_per_batch: int
    max_auto_entries_per_day: int
    max_auto_entries_per_strategy_batch: int
    max_same_industry_auto_entries_per_day: int
    max_same_concept_auto_entries_per_day: int
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
    trial_cold_start_min_checkpoints: int
    trial_cold_start_health_floor: float
    cooling_min_dwell_days: int
    retired_min_dwell_days: int
    cooling_review_interval_minutes: int
    cooling_review_batch_size: int
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
            max_auto_entries_per_batch=6,
            max_auto_entries_per_day=20,
            max_auto_entries_per_strategy_batch=3,
            max_same_industry_auto_entries_per_day=3,
            max_same_concept_auto_entries_per_day=3,
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
            trial_min_dwell_checkpoints=16,
            trial_cold_start_min_checkpoints=8,
            trial_cold_start_health_floor=45,
            cooling_min_dwell_days=1,
            retired_min_dwell_days=7,
            cooling_review_interval_minutes=30,
            cooling_review_batch_size=20,
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
            active_upgrade_threshold=68,
            active_upgrade_confirm_checkpoints=3,
            max_auto_entries_per_batch=4,
            max_auto_entries_per_day=12,
            max_auto_entries_per_strategy_batch=2,
            max_same_industry_auto_entries_per_day=2,
            max_same_concept_auto_entries_per_day=2,
            exit_only_threshold=45,
            cooling_threshold=36,
            retire_threshold=28,
            exit_only_downtrend_streak=3,
            downtrend_cooling_streak=3,
            trial_no_buy_days_threshold=10,
            reentry_watch_hours=96,
            weak_warning_tech_threshold=0.15,
            warning_to_downtrend_threshold=3,
            health_score_lookback_checkpoints=10,
            candidate_support_lookback_days=7,
            trial_min_dwell_checkpoints=24,
            trial_cold_start_min_checkpoints=10,
            trial_cold_start_health_floor=50,
            cooling_min_dwell_days=2,
            retired_min_dwell_days=10,
            cooling_review_interval_minutes=60,
            cooling_review_batch_size=12,
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
            active_upgrade_threshold=75,
            active_upgrade_confirm_checkpoints=4,
            max_auto_entries_per_batch=2,
            max_auto_entries_per_day=6,
            max_auto_entries_per_strategy_batch=1,
            max_same_industry_auto_entries_per_day=1,
            max_same_concept_auto_entries_per_day=1,
            exit_only_threshold=52,
            cooling_threshold=42,
            retire_threshold=34,
            exit_only_downtrend_streak=2,
            downtrend_cooling_streak=2,
            trial_no_buy_days_threshold=8,
            reentry_watch_hours=120,
            weak_warning_tech_threshold=0.20,
            warning_to_downtrend_threshold=2,
            health_score_lookback_checkpoints=12,
            candidate_support_lookback_days=10,
            trial_min_dwell_checkpoints=40,
            trial_cold_start_min_checkpoints=12,
            trial_cold_start_health_floor=55,
            cooling_min_dwell_days=3,
            retired_min_dwell_days=14,
            cooling_review_interval_minutes=90,
            cooling_review_batch_size=8,
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

    def with_overrides(self, **overrides: Any) -> "QuantUniverseLifecyclePolicy":
        return replace(self, **overrides)


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
    reentry_watch_penalty_base = 12.0 if _is_future(inputs.reentry_watch_until, inputs.now) else 0.0
    reentry_watch_penalty = reentry_watch_penalty_base * policy.reentry_watch_penalty_multiplier
    health_score = _clamp(
        kernel_health_base
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
            "reentry_watch_penalty_base": round(reentry_watch_penalty_base, 4),
            "reentry_watch_penalty": round(reentry_watch_penalty, 4),
        },
    )


def detect_weakening_warning(signal: dict[str, Any], policy: QuantUniverseLifecyclePolicy) -> bool:
    action = _action(signal)
    tech_score = _float(signal.get("tech_score"), 0.0)
    fusion_score = _signal_fusion_score(signal, 1.0)
    buy_threshold = _float(signal.get("buy_threshold"), policy.trial_threshold)
    buy_strength_score = _signal_buy_strength_score(signal, 1.0)
    price = _float(signal.get("price"), 0.0)
    ma20 = _float(signal.get("ma20"), 0.0)
    portfolio_gate = _signal_portfolio_guard_status(signal)
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
    fusion_score = _signal_fusion_score(signal, 1.0)
    fusion_delta = _signal_fusion_delta(signal, 0.0)
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
    *,
    drill_mode: bool = False,
) -> dict[str, Any]:
    if not events:
        return {"candidate_score": 0.0, "breakdown": {}}
    source_component = max(_float(event.get("source_score"), 0.0) for event in events)
    confidence_component = sum(_float(event.get("confidence"), 0.0) for event in events) / len(events)
    trend_component = max(_trend_score(event.get("trend")) for event in events)
    source_count = len({str(event.get("source_type") or "") for event in events if event.get("source_type")})
    multi_source_bonus = 0.0 if drill_mode or source_count < 2 else 1.0
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
    cooling_min_dwell_active: bool = False,
    post_buy_grace_active: bool = False,
    requested_status: QuantStatus | str | None = None,
    manual_override: ManualOverride | str | None = None,
) -> TransitionResult:
    current = _status(current_status)
    requested = _status(requested_status) if requested_status else None
    override = _manual_override(manual_override)
    if override == ManualOverride.MANUAL_BAN and current == QuantStatus.EXIT_ONLY and not has_position:
        return _transition(current, QuantStatus.RETIRED, "manual_force_exit_flat_retired", "强制出池持仓已清空，退出量化")
    if override == ManualOverride.MANUAL_BAN:
        return _blocked(current, "manual_ban", "手工禁止自动纳入或恢复")
    if current == QuantStatus.MANUAL_PAUSED:
        return _blocked(current, "manual_paused_no_auto_restore", "手工暂停状态不允许系统自动恢复")
    if requested == QuantStatus.RETIRED and current in {QuantStatus.TRIAL, QuantStatus.ACTIVE}:
        return _blocked(current, "forbidden_direct_retire", "trial/active 禁止直接进入 retired")
    if current in {QuantStatus.ACTIVE, QuantStatus.TRIAL}:
        if (
            current == QuantStatus.TRIAL
            and health_score >= policy.active_upgrade_threshold
            and trend_confirmed
            and active_trend_confirm_checkpoints >= policy.active_upgrade_confirm_checkpoints
        ):
            return _transition(current, QuantStatus.ACTIVE, "trial_upgraded_to_active", "trial 趋势确认，升级 active")
        if (
            has_position
            and post_buy_grace_active
            and (health_score < policy.exit_only_threshold or downtrend_streak >= policy.exit_only_downtrend_streak)
        ):
            return _blocked(current, "post_buy_grace_active", "买入当日处于 T+1 保护期，暂不切入只出场管理")
        if has_position and health_score < policy.exit_only_threshold:
            if downtrend_streak < policy.exit_only_downtrend_streak:
                return _blocked(current, "holding_downtrend_not_confirmed", "持仓健康分偏弱，但连续下行确认不足")
            return _transition(current, QuantStatus.EXIT_ONLY, "holding_downtrend_exit_only", "持仓下行，进入只出场管理")
        if has_position and downtrend_streak >= policy.exit_only_downtrend_streak:
            return _transition(current, QuantStatus.EXIT_ONLY, "holding_downtrend_exit_only", "持仓下行，进入只出场管理")
        if (
            not has_position
            and health_score < policy.cooling_threshold
            and downtrend_streak < policy.trial_min_dwell_checkpoints
        ):
            return _blocked(current, "trial_min_dwell_not_met", "trial 最短观察检查点不足，暂不进入冷却")
        if (
            not has_position
            and health_score < policy.cooling_threshold
            and downtrend_streak >= max(policy.downtrend_cooling_streak, policy.trial_min_dwell_checkpoints)
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
    if current == QuantStatus.COOLING:
        if cooling_min_dwell_active:
            return _blocked(current, "cooling_min_dwell_active", "冷却最短停留期未结束")
        if health_score >= policy.cooling_threshold and trend_confirmed:
            return _transition(current, QuantStatus.TRIAL, "cooling_recovered_to_trial", "冷却复评趋势恢复，回到 trial")
        if health_score < policy.retire_threshold and downtrend_streak >= policy.downtrend_cooling_streak:
            return _transition(current, QuantStatus.RETIRED, "cooling_persisted_to_retired", "冷却后仍持续下行，退出自动量化")
        return _blocked(current, "cooling_recovery_not_confirmed", "冷却复评未满足趋势恢复")
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


class QuantUniverseDomainError(Exception):
    def __init__(self, error_code: str, error_message: str, *, payload: dict[str, Any] | None = None) -> None:
        super().__init__(error_message)
        self.error_code = error_code
        self.error_message = error_message
        self.payload = payload or {}

    def to_dict(self) -> dict[str, Any]:
        return {"error_code": self.error_code, "error_message": self.error_message, **self.payload}


class QuantUniverseManager:
    def __init__(
        self,
        *,
        db: Any,
        profile_id: str,
        policy: QuantUniverseLifecyclePolicy,
        drill_mode: bool = False,
    ) -> None:
        self.db = db
        self.profile_id = profile_id
        self.policy = policy
        self.drill_mode = bool(drill_mode)
        self._drill_auto_promotions_by_day: dict[str, int] = {}

    def ingest_candidate_event(self, payload: dict[str, Any], *, capacity_at: Any | None = None) -> dict[str, Any]:
        event = self.db.add_candidate_event({**payload, "status": payload.get("status") or "active"})
        evaluation = self.evaluate_candidate(event["stock_code"])
        settings = self.db.get_quant_universe_settings()
        stock = self._load_stock(event["stock_code"])
        state = self.db.get_quant_universe_state(event["stock_code"])
        current_status = _status(stock.get("quant_status") if stock else None)
        evaluation_time = capacity_at or event.get("occurred_at") or event.get("created_at")
        skip_reason = self._entry_skip_reason(stock, state, evaluation, evaluation_time=evaluation_time)
        if skip_reason and skip_reason not in {"basic_info_missing"}:
            return {**evaluation, "decision": "skipped", "skip_reason": skip_reason, "reason_code": skip_reason}
        if evaluation["candidate_score"] < self.policy.trial_threshold:
            return {**evaluation, "decision": "skipped", "skip_reason": "below_trial_threshold"}
        if current_status == QuantStatus.RETIRED and evaluation["candidate_score"] < self.policy.high_reentry_threshold:
            return {**evaluation, "decision": "skipped", "skip_reason": "retired_reentry_below_threshold"}
        self._mark_candidate_events(event["stock_code"], "eligible")
        if not settings["quant_universe_lifecycle_enabled"]:
            return {**evaluation, "decision": "eligible", "skip_reason": "lifecycle_disabled"}
        if settings["auto_entry_mode"] != AutoEntryMode.AUTO_TRIAL.value or skip_reason == "basic_info_missing":
            return {
                **evaluation,
                "decision": "eligible",
                "skip_reason": skip_reason or f"auto_entry_{settings['auto_entry_mode']}",
            }
        capacity_reason = self._auto_capacity_skip_reason(str(event.get("source_type") or ""), capacity_at=capacity_at)
        if capacity_reason:
            return {**evaluation, "decision": "eligible", "skip_reason": capacity_reason}
        promoted = self._promote_stock_to_trial(
            event["stock_code"],
            source_type=str(event.get("source_type") or "candidate_event"),
            source_key=event.get("source_key"),
            reason_code="auto_trial",
            reason_text=event.get("reason_text") or "候选事件自动纳入量化",
            candidate_score=evaluation["candidate_score"],
        )
        self._record_drill_auto_promotion(capacity_at)
        return {**evaluation, "decision": "promoted_to_trial", **promoted}

    def evaluate_candidate(self, stock_code: str) -> dict[str, Any]:
        code = str(stock_code or "").strip().upper()
        events = self.db.list_candidate_events(stock_code=code, status="active", limit=100)
        events.extend(self.db.list_candidate_events(stock_code=code, status="eligible", limit=100))
        stock = self._load_stock(code)
        state = self.db.get_quant_universe_state(code)
        snapshot = {
            "is_liquid": not bool((stock or {}).get("liquidity_blocked")),
            "in_cooldown": _is_future((state or {}).get("cooling_until"), None),
            "manual_priority": any(str(event.get("source_type")) == "manual" for event in events),
        }
        score = calculate_candidate_score(events, snapshot, self.policy, drill_mode=self.drill_mode)
        if state is not None:
            self.db.upsert_quant_universe_state(
                code,
                {
                    "quant_status": stock.get("quant_status") if stock else state.get("quant_status"),
                    "candidate_score": score["candidate_score"],
                    "candidate_confidence": max((_float(event.get("confidence"), 0.0) for event in events), default=0.0),
                    "health_score": state.get("health_score", 100),
                    "downtrend_streak": state.get("downtrend_streak", 0),
                    "weakening_warning_streak": state.get("weakening_warning_streak", 0),
                    "blocked_streak": state.get("blocked_streak", 0),
                    "no_buy_days": state.get("no_buy_days", 0),
                    "cooling_until": state.get("cooling_until"),
                    "retired_at": state.get("retired_at"),
                    "retire_reason": state.get("retire_reason"),
                    "reentry_watch_until": state.get("reentry_watch_until"),
                    "last_status_changed_at": state.get("last_status_changed_at"),
                    "last_health_evaluated_at": state.get("last_health_evaluated_at"),
                    "snapshot_json": {"candidate_score_breakdown": score["breakdown"]},
                },
            )
        return {
            "stock_code": code,
            "candidate_score": score["candidate_score"],
            "candidate_confidence": max((_float(event.get("confidence"), 0.0) for event in events), default=0.0),
            "breakdown": score["breakdown"],
        }

    def promote_to_trial(
        self,
        stock_codes: list[str],
        *,
        source_type: str,
        source_key: str | None,
    ) -> dict[str, Any]:
        evaluations = []
        for code in {str(stock_code or "").strip().upper() for stock_code in stock_codes if str(stock_code or "").strip()}:
            evaluation = self.evaluate_candidate(code)
            evaluations.append(evaluation)
        evaluations.sort(key=lambda item: item["candidate_score"], reverse=True)
        success: list[str] = []
        skipped: list[dict[str, str]] = []
        strategy_counts: dict[str, int] = {}
        industry_counts, concept_counts = self._theme_counts_today()
        promoted_today = self._promotions_today_count()
        for evaluation in evaluations:
            code = evaluation["stock_code"]
            stock = self._load_stock(code)
            state = self.db.get_quant_universe_state(code)
            skip_reason = self._entry_skip_reason(stock, state, evaluation)
            if skip_reason:
                skipped.append({"stock_code": code, "reason": skip_reason})
                continue
            if len(success) >= self.policy.max_auto_entries_per_batch:
                skipped.append({"stock_code": code, "reason": "batch_capacity_exceeded"})
                continue
            if promoted_today + len(success) >= self.policy.max_auto_entries_per_day:
                skipped.append({"stock_code": code, "reason": "daily_capacity_exceeded"})
                continue
            strategy_key = self._primary_candidate_source_key(code) or source_key or source_type
            if strategy_key and strategy_counts.get(strategy_key, 0) >= self.policy.max_auto_entries_per_strategy_batch:
                skipped.append({"stock_code": code, "reason": "strategy_batch_capacity_exceeded"})
                continue
            industry = str((stock or {}).get("industry") or "").strip()
            if industry and industry_counts.get(industry, 0) >= self.policy.max_same_industry_auto_entries_per_day:
                skipped.append({"stock_code": code, "reason": "industry_capacity_exceeded"})
                continue
            concept = self._stock_primary_theme(stock)
            if concept and concept_counts.get(concept, 0) >= self.policy.max_same_concept_auto_entries_per_day:
                skipped.append({"stock_code": code, "reason": "concept_capacity_exceeded"})
                continue
            self._promote_stock_to_trial(
                code,
                source_type=source_type,
                source_key=source_key,
                reason_code="manual_promote_to_trial",
                reason_text="用户批量纳入量化",
                candidate_score=evaluation["candidate_score"],
            )
            success.append(code)
            if strategy_key:
                strategy_counts[strategy_key] = strategy_counts.get(strategy_key, 0) + 1
            if industry:
                industry_counts[industry] = industry_counts.get(industry, 0) + 1
            if concept:
                concept_counts[concept] = concept_counts.get(concept, 0) + 1
        return {"success": success, "skipped": skipped}

    def ignore_auto_entry(self, stock_codes: list[str], source_type: str | None = None) -> dict[str, Any]:
        ignored: list[str] = []
        conn = self.db._connect()
        cursor = conn.cursor()
        for stock_code in stock_codes:
            code = str(stock_code or "").strip().upper()
            if not code:
                continue
            clauses = ["stock_code = ?", "status IN ('active', 'eligible')"]
            params: list[Any] = [code]
            if source_type:
                clauses.append("source_type = ?")
                params.append(source_type)
            cursor.execute(
                f"""
                UPDATE stock_universe_candidate_events
                SET status = 'ignored', updated_at = ?
                WHERE {' AND '.join(clauses)}
                """,
                (self.db._now(), *params),
            )
            ignored.append(code)
        conn.commit()
        conn.close()
        return {"ignored": ignored}

    def set_override(self, stock_code: str, override_type: str) -> dict[str, Any]:
        code = str(stock_code or "").strip().upper()
        override = _manual_override(override_type)
        conn = self.db._connect()
        cursor = conn.cursor()
        self.db._ensure_stock_universe_member(cursor, code)
        quant_status = "manual_paused" if override == ManualOverride.MANUAL_PAUSE else None
        quant_enabled = 0 if override in {ManualOverride.MANUAL_PAUSE, ManualOverride.MANUAL_BAN} else None
        updates = ["quant_manual_override = ?", "updated_at = ?"]
        params: list[Any] = [override.value, self.db._now()]
        if quant_status is not None:
            updates.append("quant_status = ?")
            params.append(quant_status)
        if quant_enabled is not None:
            updates.append("quant_enabled = ?")
            params.append(quant_enabled)
        params.append(code)
        cursor.execute(
            f"""
            UPDATE stock_universe
            SET {', '.join(updates)}
            WHERE stock_code = ?
            """,
            tuple(params),
        )
        conn.commit()
        conn.close()
        stock = self._load_stock(code)
        return {
            "stock_code": code,
            "quant_status": stock.get("quant_status") if stock else None,
            "quant_auto_managed": bool((stock or {}).get("quant_auto_managed", 1)),
            "quant_manual_override": override.value,
        }

    def force_exit(self, stock_codes: list[str], *, position_codes: set[str] | None = None) -> dict[str, Any]:
        position_codes = {str(item or "").strip().upper() for item in (position_codes or set()) if str(item or "").strip()}
        success: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for raw_code in stock_codes:
            code = str(raw_code or "").strip().upper()
            if not code:
                continue
            previous = self._load_stock(code) or {}
            previous_status = _status(previous.get("quant_status"))
            has_position = code in position_codes
            next_status = QuantStatus.EXIT_ONLY if has_position else QuantStatus.RETIRED
            state = self.db.get_quant_universe_state(code) or {}
            now_text = self.db._now()
            self.db.upsert_quant_universe_state(
                code,
                {
                    "quant_status": next_status.value,
                    "quant_entry_source": previous.get("quant_entry_source") or "manual_force_exit",
                    "health_score": state.get("health_score", 100),
                    "retired_at": now_text if next_status == QuantStatus.RETIRED else state.get("retired_at"),
                    "retire_reason": "用户强制出池" if next_status == QuantStatus.RETIRED else "用户强制出池，持仓进入只出场管理",
                    "last_status_changed_at": now_text,
                    "snapshot_json": {"manual_force_exit": True, "has_position": has_position},
                },
            )
            conn = self.db._connect()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE stock_universe
                SET quant_manual_override = ?,
                    quant_auto_managed = 0,
                    quant_enabled = ?,
                    updated_at = ?
                WHERE stock_code = ?
                """,
                (
                    ManualOverride.MANUAL_BAN.value,
                    1 if next_status == QuantStatus.EXIT_ONLY else 0,
                    now_text,
                    code,
                ),
            )
            conn.commit()
            conn.close()
            self.db.record_quant_universe_event(
                {
                    "stock_code": code,
                    "event_type": "manual_force_exit",
                    "from_status": previous_status.value,
                    "to_status": next_status.value,
                    "trigger_source": "manual_workbench",
                    "reason_code": "manual_force_exit_with_position" if has_position else "manual_force_exit",
                    "reason_text": "用户强制出池，持仓进入只出场管理" if has_position else "用户强制出池",
                    "health_score_before": state.get("health_score"),
                    "health_score_after": state.get("health_score"),
                    "evidence_json": {"has_position": has_position},
                }
            )
            success.append({"stock_code": code, "new_status": next_status.value, "has_position": has_position})
        return {"success": success, "skipped": skipped}

    def restore_to_trial(self, stock_code: str) -> dict[str, Any]:
        code = str(stock_code or "").strip().upper()
        stock = self._load_stock(code)
        current = _status((stock or {}).get("quant_status"))
        transition = resolve_restore_to_trial(current)
        if not transition.allowed:
            raise QuantUniverseDomainError(
                transition.error_code or transition.reason_code,
                transition.error_message or transition.reason,
                payload={"stock_code": code},
            )
        self._promote_stock_to_trial(
            code,
            source_type="manual",
            source_key=None,
            reason_code=transition.reason_code,
            reason_text=transition.reason,
            candidate_score=0.0,
        )
        return {"stock_code": code, "old_status": current.value, "new_status": QuantStatus.TRIAL.value}

    def update_after_signal(
        self,
        stock_code: str,
        latest_signal: dict[str, Any],
        recent_signals: list[dict[str, Any]],
        position: dict[str, Any] | None,
    ) -> dict[str, Any]:
        code = str(stock_code or "").strip().upper()
        stock = self._load_stock(code)
        current = _status((stock or {}).get("quant_status"))
        previous_state = self.db.get_quant_universe_state(code) or {}
        health = calculate_health_score(self._health_inputs_from_signals(recent_signals), self.policy)
        downtrend_hit = detect_downtrend_hit(latest_signal, previous_state, self.policy)
        warning_hit = detect_weakening_warning(latest_signal, self.policy)
        next_downtrend_streak = int(previous_state.get("downtrend_streak") or 0) + 1 if downtrend_hit else 0
        next_warning_streak = int(previous_state.get("weakening_warning_streak") or 0) + 1 if warning_hit else 0
        settings = self.db.get_quant_universe_settings()
        has_position = int((position or {}).get("quantity") or 0) > 0
        evaluation_time = _signal_datetime(latest_signal)
        cooling_min_dwell_active = current == QuantStatus.COOLING and _is_future(
            previous_state.get("cooling_until"),
            evaluation_time,
        )
        status_changed = False
        next_status = current
        cooling_until = previous_state.get("cooling_until")
        retired_at = previous_state.get("retired_at")
        retire_reason = previous_state.get("retire_reason")
        last_status_changed_at = previous_state.get("last_status_changed_at")
        if settings["quant_universe_lifecycle_enabled"] and settings["auto_exit_enabled"]:
            trend_confirmed = _signal_trend_confirmed(latest_signal, self.policy)
            trend_confirmed_streak = _trailing_trend_confirmed_count(recent_signals, self.policy)
            health = _apply_cold_start_health_floor(
                health,
                policy=self.policy,
                current_status=current,
                signal_count=len(recent_signals),
                has_position=has_position,
            )
            health = _apply_active_upgrade_health_floor(
                health,
                policy=self.policy,
                current_status=current,
                latest_signal=latest_signal,
                trend_confirmed=trend_confirmed,
                trend_confirmed_streak=trend_confirmed_streak,
                has_position=has_position,
            )
            transition = resolve_next_status(
                current_status=current,
                health_score=health.health_score,
                downtrend_streak=next_downtrend_streak,
                has_position=has_position,
                trend_confirmed=trend_confirmed,
                active_trend_confirm_checkpoints=trend_confirmed_streak,
                cooling_min_dwell_active=cooling_min_dwell_active,
                post_buy_grace_active=has_position and _has_same_day_buy_signal(recent_signals, evaluation_time),
                policy=self.policy,
            )
            if transition.allowed and transition.to_status != current:
                next_status = transition.to_status
                status_changed = True
                last_status_changed_at = _format_utc_iso_z(evaluation_time)
                if next_status == QuantStatus.COOLING:
                    cooling_until = _format_utc_iso_z(evaluation_time + timedelta(days=self.policy.cooling_min_dwell_days))
                elif current == QuantStatus.COOLING:
                    cooling_until = None
                if next_status == QuantStatus.RETIRED:
                    retired_at = _format_utc_iso_z(evaluation_time)
                    retire_reason = transition.reason_code
                elif current == QuantStatus.RETIRED:
                    retired_at = None
                    retire_reason = None
                self.db.record_quant_universe_event(
                    {
                        "stock_code": code,
                        "event_type": "state_changed",
                        "from_status": current.value,
                        "to_status": next_status.value,
                        "reason_code": transition.reason_code,
                        "reason_text": transition.reason,
                        "health_score_before": previous_state.get("health_score"),
                        "health_score_after": health.health_score,
                        "evidence_json": {"latest_signal": latest_signal, "health": health.breakdown},
                    }
                )
        self.db.upsert_quant_universe_state(
            code,
            {
                "quant_status": next_status.value,
                "health_score": health.health_score,
                "candidate_score": previous_state.get("candidate_score", 0),
                "candidate_confidence": previous_state.get("candidate_confidence", 0),
                "downtrend_streak": next_downtrend_streak,
                "weakening_warning_streak": next_warning_streak,
                "blocked_streak": previous_state.get("blocked_streak", 0),
                "no_buy_days": previous_state.get("no_buy_days", 0),
                "cooling_until": cooling_until,
                "retired_at": retired_at,
                "retire_reason": retire_reason,
                "last_status_changed_at": last_status_changed_at,
                "last_health_evaluated_at": _format_utc_iso_z(evaluation_time),
                "snapshot_json": {"latest_signal": latest_signal, "health": health.breakdown},
            },
        )
        return {
            "stock_code": code,
            "status_changed": status_changed,
            "old_status": current.value,
            "new_status": next_status.value,
            "health_score": health.health_score,
        }

    def overview(self) -> dict[str, Any]:
        return self.db.get_quant_universe_overview()

    def _health_inputs_from_signals(self, signals: list[dict[str, Any]]) -> HealthInputs:
        if not signals:
            return HealthInputs()
        count = len(signals)
        return HealthInputs(
            avg_tech_score=sum(_float(signal.get("tech_score"), 0.0) for signal in signals) / count,
            avg_context_score=sum(_float(signal.get("context_score"), 0.0) for signal in signals) / count,
            avg_fusion_score=sum(_signal_fusion_score(signal, 0.0) for signal in signals) / count,
            avg_buy_strength_score=sum(_signal_buy_strength_score(signal, 0.0) for signal in signals) / count,
            recent_stoploss_count=sum(1 for signal in signals if str(signal.get("decision_type") or "").lower() == "hard_stop_loss"),
            blocked_streak=sum(1 for signal in signals if _signal_stock_feedback_status(signal) == "blocked"),
        )

    def _entry_skip_reason(
        self,
        stock: dict[str, Any] | None,
        state: dict[str, Any] | None,
        evaluation: dict[str, Any],
        *,
        evaluation_time: Any | None = None,
    ) -> str:
        if not stock:
            return "stock_not_found"
        if str(stock.get("quant_manual_override") or "") == ManualOverride.MANUAL_BAN.value:
            return "manual_ban"
        if self._is_non_tradable(stock):
            return "non_tradable"
        if _is_future((state or {}).get("cooling_until"), None):
            return "cooling_blocked"
        state_status = _status((state or {}).get("quant_status"))
        current_status = state_status if state else _status(stock.get("quant_status"))
        if current_status == QuantStatus.COOLING:
            return "cooling_review_required"
        if current_status in {QuantStatus.TRIAL, QuantStatus.ACTIVE, QuantStatus.EXIT_ONLY}:
            return "already_quant_managed"
        if current_status == QuantStatus.MANUAL_PAUSED:
            return "manual_paused"
        if current_status == QuantStatus.RETIRED and not self.policy.retired_reactivation_check_enabled:
            return "retired_reactivation_disabled"
        if current_status == QuantStatus.RETIRED and _retired_min_dwell_active(state, self.policy, evaluation_time):
            return "retired_dwell_blocked"
        if current_status == QuantStatus.RETIRED and evaluation["candidate_score"] < self.policy.high_reentry_threshold:
            return "retired_reentry_below_threshold"
        if bool(stock.get("basic_info_missing")):
            return "basic_info_missing"
        return ""

    def _promote_stock_to_trial(
        self,
        stock_code: str,
        *,
        source_type: str,
        source_key: str | None,
        reason_code: str,
        reason_text: str,
        candidate_score: float,
    ) -> dict[str, Any]:
        code = str(stock_code or "").strip().upper()
        previous = self._load_stock(code) or {}
        previous_status = _status(previous.get("quant_status"))
        self.db.upsert_quant_universe_state(
            code,
            {
                "quant_status": QuantStatus.TRIAL.value,
                "quant_entry_source": source_type,
                "candidate_score": candidate_score,
                "candidate_confidence": 0,
                "health_score": (self.db.get_quant_universe_state(code) or {}).get("health_score", 100),
                "retired_at": None,
                "retire_reason": None,
                "snapshot_json": {"source_type": source_type, "source_key": source_key},
            },
        )
        self.db.record_quant_universe_event(
            {
                "stock_code": code,
                "event_type": "candidate_promoted_to_trial",
                "from_status": previous_status.value,
                "to_status": QuantStatus.TRIAL.value,
                "trigger_source": source_type,
                "reason_code": reason_code,
                "reason_text": reason_text,
                "candidate_score": candidate_score,
                "evidence_json": {"source_key": source_key},
            }
        )
        self._mark_candidate_events(code, "consumed")
        return {"stock_code": code, "old_status": previous_status.value, "new_status": QuantStatus.TRIAL.value}

    def _mark_candidate_events(self, stock_code: str, status: str) -> None:
        conn = self.db._connect()
        cursor = conn.cursor()
        now_text = self.db._now()
        cursor.execute(
            """
            UPDATE stock_universe_candidate_events
            SET status = ?,
                consumed_by_quant_manager_at = CASE WHEN ? = 'consumed' THEN ? ELSE consumed_by_quant_manager_at END,
                updated_at = ?
            WHERE stock_code = ? AND status IN ('active', 'eligible')
            """,
            (status, status, now_text, now_text, str(stock_code or "").strip().upper()),
        )
        conn.commit()
        conn.close()

    def _load_stock(self, stock_code: str) -> dict[str, Any] | None:
        conn = self.db._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM stock_universe WHERE stock_code = ?", (str(stock_code or "").strip().upper(),))
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        payload = {key: row[key] for key in row.keys()}
        payload["metadata"] = _loads_json_object(payload.get("metadata_json"))
        payload["basic_info_missing"] = bool(payload.get("basic_info_missing"))
        payload["quant_auto_managed"] = bool(payload.get("quant_auto_managed"))
        return payload

    def _auto_capacity_skip_reason(self, source_type: str, *, capacity_at: Any | None = None) -> str:
        if self._promotions_today_count(capacity_at=capacity_at) >= self.policy.max_auto_entries_per_day:
            return "daily_capacity_exceeded"
        return ""

    def _promotions_today_count(self, *, capacity_at: Any | None = None) -> int:
        if self.drill_mode and capacity_at is not None:
            day_key = self._capacity_day_key(capacity_at)
            return int(self._drill_auto_promotions_by_day.get(day_key, 0)) if day_key else 0
        today = datetime.now(timezone.utc).date().isoformat()
        conn = self.db._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM stock_universe_quant_events
            WHERE event_type = 'candidate_promoted_to_trial'
              AND created_at >= ?
            """,
            (f"{today}T00:00:00Z",),
        )
        row = cursor.fetchone()
        conn.close()
        return int(row["total"] or 0) if row else 0

    def _record_drill_auto_promotion(self, capacity_at: Any | None) -> None:
        if not self.drill_mode or capacity_at is None:
            return
        day_key = self._capacity_day_key(capacity_at)
        if day_key:
            self._drill_auto_promotions_by_day[day_key] = self._drill_auto_promotions_by_day.get(day_key, 0) + 1

    @staticmethod
    def _capacity_day_key(value: Any) -> str:
        if isinstance(value, datetime):
            return value.date().isoformat()
        text = str(value or "").strip()
        if len(text) >= 10:
            return text[:10]
        return ""

    def _theme_counts_today(self) -> tuple[dict[str, int], dict[str, int]]:
        today = datetime.now(timezone.utc).date().isoformat()
        conn = self.db._connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT su.industry AS industry, su.metadata_json AS metadata_json
            FROM stock_universe_quant_events qe
            JOIN stock_universe su ON su.stock_code = qe.stock_code
            WHERE qe.event_type = 'candidate_promoted_to_trial'
              AND qe.created_at >= ?
            """,
            (f"{today}T00:00:00Z",),
        )
        industry_counts: dict[str, int] = {}
        concept_counts: dict[str, int] = {}
        for row in cursor.fetchall():
            industry = str(row["industry"] or "").strip()
            if industry:
                industry_counts[industry] = industry_counts.get(industry, 0) + 1
            metadata = _loads_json_object(row["metadata_json"])
            concept = str(metadata.get("primary_theme") or metadata.get("concept_tag") or "").strip()
            if concept:
                concept_counts[concept] = concept_counts.get(concept, 0) + 1
        conn.close()
        return industry_counts, concept_counts

    def _primary_candidate_source_key(self, stock_code: str) -> str:
        events = self.db.list_candidate_events(stock_code=stock_code, status="eligible", limit=20)
        events.extend(self.db.list_candidate_events(stock_code=stock_code, status="active", limit=20))
        events.sort(key=lambda event: (_float(event.get("source_score"), 0.0), _float(event.get("confidence"), 0.0)), reverse=True)
        if not events:
            return ""
        event = events[0]
        return str(event.get("source_key") or event.get("source_type") or "").strip()

    def _is_non_tradable(self, stock: dict[str, Any]) -> bool:
        metadata = stock.get("metadata") if isinstance(stock.get("metadata"), dict) else {}
        limit_status = str(metadata.get("limit_status") or stock.get("limit_status") or "").strip().lower()
        return (
            metadata.get("tradable") is False
            or bool(metadata.get("is_suspended"))
            or limit_status in {"limit_up", "limit_down", "up_limit", "down_limit", "涨停", "跌停"}
        )

    def _stock_primary_theme(self, stock: dict[str, Any] | None) -> str:
        if not stock:
            return ""
        metadata = stock.get("metadata") if isinstance(stock.get("metadata"), dict) else {}
        return str(metadata.get("primary_theme") or metadata.get("concept_tag") or "").strip()


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


def _signal_profile(signal: dict[str, Any]) -> dict[str, Any]:
    profile = signal.get("strategy_profile")
    if isinstance(profile, dict):
        return profile
    return _loads_json_object(profile)


def _signal_fusion_breakdown(signal: dict[str, Any]) -> dict[str, Any]:
    profile = _signal_profile(signal)
    explainability = profile.get("explainability") if isinstance(profile.get("explainability"), dict) else {}
    breakdown = explainability.get("fusion_breakdown") if isinstance(explainability.get("fusion_breakdown"), dict) else {}
    return breakdown if isinstance(breakdown, dict) else {}


def _signal_fusion_score(signal: dict[str, Any], default: float) -> float:
    if signal.get("fusion_score") not in (None, ""):
        return _clamp(_float(signal.get("fusion_score"), default), 0.0, 1.0)
    breakdown = _signal_fusion_breakdown(signal)
    return _clamp(_float(breakdown.get("fusion_score"), default), 0.0, 1.0)


def _signal_fusion_delta(signal: dict[str, Any], default: float) -> float:
    if signal.get("fusion_score_delta") not in (None, ""):
        return _float(signal.get("fusion_score_delta"), default)
    breakdown = _signal_fusion_breakdown(signal)
    return _float(breakdown.get("fusion_score_delta"), default)


def _signal_portfolio_guard(signal: dict[str, Any]) -> dict[str, Any]:
    profile = _signal_profile(signal)
    gate = profile.get("portfolio_execution_guard") if isinstance(profile.get("portfolio_execution_guard"), dict) else {}
    return gate if isinstance(gate, dict) else {}


def _signal_buy_strength_score(signal: dict[str, Any], default: float) -> float:
    if signal.get("buy_strength_score") not in (None, ""):
        return _clamp(_float(signal.get("buy_strength_score"), default), 0.0, 1.0)
    gate = _signal_portfolio_guard(signal)
    return _clamp(_float(gate.get("buy_strength_score"), default), 0.0, 1.0)


def _signal_portfolio_guard_status(signal: dict[str, Any]) -> str:
    top_level = str(signal.get("portfolio_execution_guard_status") or "").strip()
    if top_level:
        return top_level
    return str(_signal_portfolio_guard(signal).get("status") or "").strip()


def _signal_stock_feedback_status(signal: dict[str, Any]) -> str:
    top_level = str(signal.get("stock_execution_feedback_status") or "").strip()
    if top_level:
        return top_level
    profile = _signal_profile(signal)
    gate = profile.get("stock_execution_feedback_gate") if isinstance(profile.get("stock_execution_feedback_gate"), dict) else {}
    return str((gate or {}).get("status") or "").strip()


def _signal_trend_confirmed(signal: dict[str, Any], policy: QuantUniverseLifecyclePolicy) -> bool:
    if _action(signal) != "BUY":
        return False
    guard_confirmation = _guard_trend_confirmed(signal, policy)
    if guard_confirmation is not None:
        return guard_confirmation
    tech_score = _float(signal.get("tech_score"), 0.0)
    fusion_score = _signal_fusion_score(signal, 0.0)
    buy_strength = _signal_buy_strength_score(signal, 0.0)
    price = _float(signal.get("price"), 0.0)
    ma20 = _float(signal.get("ma20"), 0.0)
    ma20_slope = _float(signal.get("ma20_slope"), 0.0)
    return (
        fusion_score >= policy.trial_threshold
        and buy_strength >= 0.45
        and tech_score >= policy.weak_warning_tech_threshold
        and (ma20 <= 0 or price <= 0 or price >= ma20)
        and ma20_slope >= 0
    )


def _guard_trend_confirmed(signal: dict[str, Any], policy: QuantUniverseLifecyclePolicy) -> bool | None:
    gate = _signal_portfolio_guard(signal)
    trend = gate.get("trend_confirmation") if isinstance(gate.get("trend_confirmation"), dict) else {}
    if not trend:
        return None
    components = gate.get("score_components") if isinstance(gate.get("score_components"), dict) else {}
    buy_strength = _signal_buy_strength_score(signal, 0.0)
    confirmation_score = _clamp(_float(components.get("confirmation_score"), 0.0), 0.0, 1.0)
    above_ma20 = int(_float(trend.get("above_ma20_checkpoints"), 0.0))
    return bool(
        buy_strength >= 0.45
        and (
            bool(trend.get("ma_stack"))
            or bool(trend.get("retest_confirmed"))
            or (bool(trend.get("ma20_rising")) and above_ma20 >= policy.active_upgrade_confirm_checkpoints)
            or confirmation_score >= 0.75
        )
    )


def _trailing_trend_confirmed_count(signals: list[dict[str, Any]], policy: QuantUniverseLifecyclePolicy) -> int:
    count = 0
    for signal in signals:
        if not _signal_trend_confirmed(signal, policy):
            break
        count += 1
    return count


def _apply_cold_start_health_floor(
    health: HealthResult,
    *,
    policy: QuantUniverseLifecyclePolicy,
    current_status: QuantStatus,
    signal_count: int,
    has_position: bool,
) -> HealthResult:
    min_samples = max(0, int(policy.trial_cold_start_min_checkpoints or 0))
    if current_status != QuantStatus.TRIAL or has_position or min_samples <= 0 or signal_count >= min_samples:
        return health
    floor = float(policy.trial_cold_start_health_floor or 0)
    if health.health_score >= floor:
        return health
    breakdown = dict(health.breakdown)
    breakdown["cold_start_signal_count"] = int(signal_count)
    breakdown["cold_start_min_checkpoints"] = min_samples
    breakdown["cold_start_health_floor"] = round(floor, 4)
    return HealthResult(health_score=round(floor, 4), breakdown=breakdown)


def _apply_active_upgrade_health_floor(
    health: HealthResult,
    *,
    policy: QuantUniverseLifecyclePolicy,
    current_status: QuantStatus,
    latest_signal: dict[str, Any],
    trend_confirmed: bool,
    trend_confirmed_streak: int,
    has_position: bool,
) -> HealthResult:
    if current_status != QuantStatus.TRIAL or has_position:
        return health
    if not trend_confirmed or trend_confirmed_streak < policy.active_upgrade_confirm_checkpoints:
        return health
    strength_threshold = min(0.80, float(policy.trial_threshold) + 0.15)
    if _signal_buy_strength_score(latest_signal, 0.0) < strength_threshold:
        return health
    floor = float(policy.active_upgrade_threshold)
    if health.health_score >= floor:
        return health
    breakdown = dict(health.breakdown)
    breakdown["active_upgrade_floor"] = round(floor, 4)
    breakdown["active_upgrade_strength_threshold"] = round(strength_threshold, 4)
    breakdown["active_upgrade_confirmed_streak"] = int(trend_confirmed_streak)
    return HealthResult(health_score=round(floor, 4), breakdown=breakdown)


def _signal_datetime(signal: dict[str, Any]) -> datetime:
    for key in ("decision_time", "signal_time", "checkpoint_at", "updated_at", "created_at", "timestamp"):
        value = signal.get(key)
        if value not in (None, ""):
            return _to_datetime(value)
    return datetime.now(timezone.utc)


def _has_same_day_buy_signal(signals: list[dict[str, Any]], evaluation_time: datetime) -> bool:
    evaluation_day = evaluation_time.astimezone(timezone.utc).date()
    for signal in signals:
        if _action(signal) != "BUY":
            continue
        try:
            signal_day = _signal_datetime(signal).astimezone(timezone.utc).date()
        except (TypeError, ValueError):
            continue
        if signal_day == evaluation_day:
            return True
    return False


def _format_utc_iso_z(value: datetime) -> str:
    dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _retired_min_dwell_active(
    state: dict[str, Any] | None,
    policy: QuantUniverseLifecyclePolicy,
    now: datetime | str | None,
) -> bool:
    days = int(policy.retired_min_dwell_days or 0)
    retired_at = (state or {}).get("retired_at")
    if days <= 0 or not retired_at:
        return False
    try:
        target = _to_datetime(retired_at) + timedelta(days=days)
        current = _to_datetime(now) if now is not None else datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return False
    return current < target


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


def _loads_json_object(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))

