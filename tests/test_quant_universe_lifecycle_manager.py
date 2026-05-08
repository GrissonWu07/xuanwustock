from datetime import datetime, timedelta, timezone

from app.quant_sim.quant_universe_lifecycle import (
    AutoEntryMode,
    HealthInputs,
    ManualOverride,
    QuantStatus,
    QuantUniverseLifecyclePolicy,
    calculate_candidate_score,
    calculate_health_score,
    detect_downtrend_hit,
    detect_weakening_warning,
    resolve_next_status,
    resolve_restore_to_trial,
)


def test_health_score_uses_kernel_score_normalization():
    inputs = HealthInputs(
        avg_tech_score=0.0,
        avg_context_score=-1.0,
        avg_fusion_score=0.8,
        avg_buy_strength_score=0.6,
        no_buy_days=3,
        recent_stoploss_count=1,
        blocked_streak=2,
        candidate_support_bonus=4.0,
    )
    policy = QuantUniverseLifecyclePolicy.stable_defaults()

    result = calculate_health_score(inputs, policy)

    assert 0 <= result.health_score <= 100
    assert result.breakdown["normalized_tech_health"] == 50.0
    assert result.breakdown["normalized_context_health"] == 0.0
    assert result.breakdown["normalized_fusion_health"] == 80.0
    assert result.breakdown["normalized_buy_strength_health"] == 60.0
    assert result.breakdown["execution_penalty_base"] == 11.0
    assert result.breakdown["inactivity_penalty_base"] == 6.0
    assert result.breakdown["candidate_support_bonus_base"] == 4.0
    assert result.breakdown["kernel_health_base"] == 51.5
    assert result.health_score == 38.5


def test_health_score_applies_reentry_watch_penalty_until_window_expires():
    now = datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc)
    policy = QuantUniverseLifecyclePolicy.stable_defaults()

    active_watch = calculate_health_score(
        HealthInputs(reentry_watch_until=now + timedelta(hours=1), now=now),
        policy,
    )
    expired_watch = calculate_health_score(
        HealthInputs(reentry_watch_until=now - timedelta(seconds=1), now=now),
        policy,
    )

    assert active_watch.breakdown["reentry_watch_penalty_base"] == 12.0
    assert active_watch.breakdown["reentry_watch_penalty"] == 13.2
    assert expired_watch.breakdown["reentry_watch_penalty"] == 0.0


def test_profile_defaults_keep_system_enums_distinct_from_profile_weights():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()

    assert QuantStatus.ACTIVE.value == "active"
    assert ManualOverride.MANUAL_BAN.value == "manual_ban"
    assert AutoEntryMode.CONFIRM_FIRST.value == "confirm_first"
    assert policy.profile_id == "aggressive"
    assert round(
        policy.fusion_health_weight
        + policy.buy_strength_health_weight
        + policy.tech_health_weight
        + policy.context_health_weight,
        5,
    ) == 1.0


def test_detect_weakening_warning_and_downtrend_hit():
    policy = QuantUniverseLifecyclePolicy.stable_defaults()

    warning_signal = {
        "final_action": "HOLD",
        "tech_score": 0.12,
        "fusion_score": 0.42,
        "buy_threshold": 0.55,
    }
    downtrend_signal = {
        "final_action": "HOLD",
        "tech_score": -0.1,
        "fusion_score": 0.2,
        "fusion_score_delta": -0.08,
    }

    assert detect_weakening_warning(warning_signal, policy) is True
    assert detect_downtrend_hit(downtrend_signal, {"weakening_warning_streak": 1}, policy) is True
    assert detect_downtrend_hit({"final_action": "SELL"}, {}, policy) is True


def test_candidate_score_uses_profile_weights_and_clamps_result():
    policy = QuantUniverseLifecyclePolicy.stable_defaults()
    events = [
        {"source_type": "discover", "source_score": 0.8, "confidence": 0.7, "trend": "up"},
        {"source_type": "research", "source_score": 0.6, "confidence": 0.6, "trend": "up"},
    ]

    result = calculate_candidate_score(events, {"is_liquid": True}, policy)

    assert 0 <= result["candidate_score"] <= 1
    assert result["candidate_score"] == 0.7267
    assert result["breakdown"]["multi_source_bonus"] > 0


def test_resolve_active_to_exit_only_when_holding_and_health_breaks_threshold():
    policy = QuantUniverseLifecyclePolicy.stable_defaults()

    result = resolve_next_status(
        current_status=QuantStatus.ACTIVE,
        health_score=policy.exit_only_threshold - 1,
        downtrend_streak=0,
        has_position=True,
        policy=policy,
    )

    assert result.allowed is True
    assert result.from_status == QuantStatus.ACTIVE
    assert result.to_status == QuantStatus.EXIT_ONLY
    assert result.reason_code == "holding_downtrend_exit_only"


def test_resolve_active_to_cooling_when_flat_and_downtrend_persists():
    policy = QuantUniverseLifecyclePolicy.stable_defaults()

    result = resolve_next_status(
        current_status="active",
        health_score=policy.cooling_threshold - 1,
        downtrend_streak=policy.downtrend_cooling_streak,
        has_position=False,
        policy=policy,
    )

    assert result.allowed is True
    assert result.to_status == QuantStatus.COOLING
    assert result.reason_code == "flat_downtrend_cooling"


def test_resolve_exit_only_to_trial_requires_flat_health_recovery_and_support():
    policy = QuantUniverseLifecyclePolicy.stable_defaults()

    blocked = resolve_next_status(
        current_status=QuantStatus.EXIT_ONLY,
        health_score=policy.cooling_threshold + 5,
        has_position=True,
        candidate_support=True,
        policy=policy,
    )
    restored = resolve_next_status(
        current_status=QuantStatus.EXIT_ONLY,
        health_score=policy.cooling_threshold + 5,
        has_position=False,
        candidate_support=True,
        policy=policy,
    )

    assert blocked.allowed is False
    assert blocked.reason_code == "exit_only_position_not_flat"
    assert restored.allowed is True
    assert restored.to_status == QuantStatus.TRIAL
    assert restored.reason_code == "exit_only_recovered_to_trial"


def test_resolve_exit_only_to_active_requires_flat_health_and_trend_confirmation():
    policy = QuantUniverseLifecyclePolicy.stable_defaults()

    result = resolve_next_status(
        current_status=QuantStatus.EXIT_ONLY,
        health_score=policy.active_upgrade_threshold,
        has_position=False,
        trend_confirmed=True,
        active_trend_confirm_checkpoints=policy.active_upgrade_confirm_checkpoints,
        policy=policy,
    )

    assert result.allowed is True
    assert result.to_status == QuantStatus.ACTIVE
    assert result.reason_code == "exit_only_recovered_to_active"


def test_restore_to_trial_rejects_active_with_invalid_restore_state():
    result = resolve_restore_to_trial(QuantStatus.ACTIVE)

    assert result.allowed is False
    assert result.from_status == QuantStatus.ACTIVE
    assert result.to_status == QuantStatus.ACTIVE
    assert result.error_code == "invalid_restore_state"
    assert result.error_message == "股票当前处于 active，无需恢复"


def test_manual_paused_is_not_auto_restored_and_active_to_retired_is_forbidden():
    policy = QuantUniverseLifecyclePolicy.stable_defaults()

    manual = resolve_next_status(
        current_status=QuantStatus.MANUAL_PAUSED,
        health_score=100,
        has_position=False,
        candidate_support=True,
        trend_confirmed=True,
        active_trend_confirm_checkpoints=10,
        policy=policy,
    )
    forbidden = resolve_next_status(
        current_status=QuantStatus.ACTIVE,
        requested_status=QuantStatus.RETIRED,
        health_score=0,
        has_position=False,
        downtrend_streak=100,
        policy=policy,
    )

    assert manual.allowed is False
    assert manual.reason_code == "manual_paused_no_auto_restore"
    assert forbidden.allowed is False
    assert forbidden.reason_code == "forbidden_direct_retire"
