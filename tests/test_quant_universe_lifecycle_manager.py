from datetime import datetime, timedelta, timezone

from app.quant_sim.quant_universe_lifecycle import (
    AutoEntryMode,
    HealthInputs,
    ManualOverride,
    QuantUniverseDomainError,
    QuantUniverseManager,
    QuantStatus,
    QuantUniverseLifecyclePolicy,
    build_lifecycle_gate,
    calculate_candidate_score,
    calculate_health_score,
    detect_downtrend_hit,
    detect_weakening_warning,
    resolve_next_status,
    resolve_restore_to_trial,
)
from app.quant_sim.db import QuantSimDB


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
    assert result.breakdown["kernel_health_base"] == 51.5
    assert "candidate_support_bonus" not in result.breakdown
    assert result.health_score == 34.5


def test_health_score_ignores_candidate_event_support():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()

    without_support = calculate_health_score(HealthInputs(avg_fusion_score=0.4), policy)
    with_support = calculate_health_score(
        HealthInputs(avg_fusion_score=0.4, candidate_support_bonus=15.0, valid_candidate_event_count=5),
        policy,
    )

    assert with_support.health_score == without_support.health_score


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


def test_profile_defaults_match_lifecycle_spec_19_9():
    expected = {
        "aggressive": {
            "active_upgrade_threshold": 60,
            "active_upgrade_confirm_checkpoints": 2,
            "exit_only_threshold": 38,
            "exit_only_downtrend_streak": 3,
            "cooling_threshold": 30,
            "retire_threshold": 22,
            "downtrend_cooling_streak": 3,
            "trial_no_buy_days_threshold": 12,
            "reentry_watch_hours": 72,
            "health_score_lookback_checkpoints": 8,
            "candidate_support_lookback_days": 5,
            "trial_min_dwell_checkpoints": 16,
            "trial_cold_start_min_checkpoints": 8,
            "trial_cold_start_health_floor": 45,
            "cooling_min_dwell_days": 3,
            "retired_min_dwell_days": 14,
            "cooling_review_interval_minutes": 30,
            "cooling_review_batch_size": 20,
            "min_scan_coverage": 6,
            "guarded_buy_threshold_delta": 0.08,
            "guarded_size_multiplier": 0.35,
            "guarded_max_position_pct": 4.0,
            "recovery_probe_hours": 24,
            "recovery_probe_buy_threshold_delta": 0.08,
            "recovery_probe_size_multiplier": 0.45,
            "recovery_probe_max_position_pct": 6.0,
            "recovery_probe_confirmed_max_position_pct": 10.0,
            "recovery_probe_failed_max_position_pct": 2.5,
            "recovery_probe_failure_threshold": 2,
            "recovery_probe_failure_lookback_days": 30,
            "recovery_probe_attempt_fatigue_threshold": 4,
            "recovery_probe_cooldown_days": 15,
            "cooling_supplemental_buy_threshold_delta": 0.12,
            "cooling_supplemental_size_multiplier": 0.20,
            "cooling_supplemental_max_position_pct": 3.0,
            "max_auto_entries_per_batch": 6,
            "max_auto_entries_per_day": 20,
            "max_auto_entries_per_strategy_batch": 3,
            "max_same_industry_auto_entries_per_day": 3,
            "max_same_concept_auto_entries_per_day": 3,
        },
        "stable": {
            "active_upgrade_threshold": 68,
            "active_upgrade_confirm_checkpoints": 3,
            "exit_only_threshold": 45,
            "exit_only_downtrend_streak": 3,
            "cooling_threshold": 36,
            "retire_threshold": 28,
            "downtrend_cooling_streak": 3,
            "trial_no_buy_days_threshold": 10,
            "reentry_watch_hours": 96,
            "health_score_lookback_checkpoints": 10,
            "candidate_support_lookback_days": 7,
            "trial_min_dwell_checkpoints": 24,
            "trial_cold_start_min_checkpoints": 10,
            "trial_cold_start_health_floor": 50,
            "cooling_min_dwell_days": 5,
            "retired_min_dwell_days": 21,
            "cooling_review_interval_minutes": 60,
            "cooling_review_batch_size": 12,
            "min_scan_coverage": 4,
            "guarded_buy_threshold_delta": 0.10,
            "guarded_size_multiplier": 0.30,
            "guarded_max_position_pct": 3.5,
            "recovery_probe_hours": 36,
            "recovery_probe_buy_threshold_delta": 0.10,
            "recovery_probe_size_multiplier": 0.35,
            "recovery_probe_max_position_pct": 4.0,
            "recovery_probe_confirmed_max_position_pct": 7.0,
            "recovery_probe_failed_max_position_pct": 2.0,
            "recovery_probe_failure_threshold": 2,
            "recovery_probe_failure_lookback_days": 30,
            "recovery_probe_attempt_fatigue_threshold": 3,
            "recovery_probe_cooldown_days": 20,
            "cooling_supplemental_buy_threshold_delta": 0.15,
            "cooling_supplemental_size_multiplier": 0.15,
            "cooling_supplemental_max_position_pct": 2.0,
            "max_auto_entries_per_batch": 4,
            "max_auto_entries_per_day": 12,
            "max_auto_entries_per_strategy_batch": 2,
            "max_same_industry_auto_entries_per_day": 2,
            "max_same_concept_auto_entries_per_day": 2,
        },
        "conservative": {
            "active_upgrade_threshold": 75,
            "active_upgrade_confirm_checkpoints": 4,
            "exit_only_threshold": 52,
            "exit_only_downtrend_streak": 2,
            "cooling_threshold": 42,
            "retire_threshold": 34,
            "downtrend_cooling_streak": 2,
            "trial_no_buy_days_threshold": 8,
            "reentry_watch_hours": 120,
            "health_score_lookback_checkpoints": 12,
            "candidate_support_lookback_days": 10,
            "trial_min_dwell_checkpoints": 40,
            "trial_cold_start_min_checkpoints": 12,
            "trial_cold_start_health_floor": 55,
            "cooling_min_dwell_days": 7,
            "retired_min_dwell_days": 30,
            "cooling_review_interval_minutes": 90,
            "cooling_review_batch_size": 8,
            "min_scan_coverage": 2,
            "guarded_buy_threshold_delta": 0.12,
            "guarded_size_multiplier": 0.25,
            "guarded_max_position_pct": 3.0,
            "recovery_probe_hours": 48,
            "recovery_probe_buy_threshold_delta": 0.12,
            "recovery_probe_size_multiplier": 0.25,
            "recovery_probe_max_position_pct": 2.5,
            "recovery_probe_confirmed_max_position_pct": 5.0,
            "recovery_probe_failed_max_position_pct": 1.5,
            "recovery_probe_failure_threshold": 2,
            "recovery_probe_failure_lookback_days": 30,
            "recovery_probe_attempt_fatigue_threshold": 2,
            "recovery_probe_cooldown_days": 30,
            "cooling_supplemental_buy_threshold_delta": 0.18,
            "cooling_supplemental_size_multiplier": 0.10,
            "cooling_supplemental_max_position_pct": 1.5,
            "max_auto_entries_per_batch": 2,
            "max_auto_entries_per_day": 6,
            "max_auto_entries_per_strategy_batch": 1,
            "max_same_industry_auto_entries_per_day": 1,
            "max_same_concept_auto_entries_per_day": 1,
        },
    }
    policies = {
        "aggressive": QuantUniverseLifecyclePolicy.aggressive_defaults(),
        "stable": QuantUniverseLifecyclePolicy.stable_defaults(),
        "conservative": QuantUniverseLifecyclePolicy.conservative_defaults(),
    }

    for profile_id, profile_expected in expected.items():
        policy = policies[profile_id]
        for field, value in profile_expected.items():
            assert getattr(policy, field) == value


def test_build_lifecycle_gate_defaults():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()

    trial_gate = build_lifecycle_gate("trial", policy)
    cooling_gate = build_lifecycle_gate("cooling", policy, supplemental=True)
    exit_gate = build_lifecycle_gate("exit_only", policy)

    assert trial_gate["mode"] == "trial_light"
    assert trial_gate["buy_threshold_delta"] == 0.03
    assert trial_gate["size_multiplier"] == policy.trial_position_multiplier
    assert trial_gate["max_position_pct"] == policy.trial_max_position_pct
    assert cooling_gate["mode"] == "cooling_supplemental"
    assert cooling_gate["buy_threshold_delta"] == policy.cooling_supplemental_buy_threshold_delta
    assert cooling_gate["size_multiplier"] == policy.cooling_supplemental_size_multiplier
    assert cooling_gate["max_position_pct"] == policy.cooling_supplemental_max_position_pct
    assert cooling_gate["requires_strong_confirmation"] is True
    assert exit_gate["mode"] == "exit_only"
    assert exit_gate["buy_blocked"] is True


def test_build_lifecycle_gate_uses_recovery_probe_caps_before_trial_confirmation():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()

    gate = build_lifecycle_gate("trial", policy, recovery_probe_active=True)

    assert gate["mode"] == "recovery_probe"
    assert gate["buy_threshold_delta"] == policy.recovery_probe_buy_threshold_delta
    assert gate["size_multiplier"] == policy.recovery_probe_size_multiplier
    assert gate["max_position_pct"] == policy.recovery_probe_max_position_pct
    assert gate["requires_strong_confirmation"] is True
    assert gate["buy_blocked"] is False


def test_build_lifecycle_gate_tightens_recovery_probe_after_recent_failure():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()

    gate = build_lifecycle_gate(
        "trial",
        policy,
        recovery_probe_active=True,
        recovery_probe_attempt_count=3,
        recent_probe_loss_count=1,
        probe_failure_reason="holding_downtrend_exit_only",
    )

    assert gate["mode"] == "recovery_probe_retry"
    assert gate["max_position_pct"] == policy.recovery_probe_failed_max_position_pct
    assert gate["probe_attempt_count"] == 3
    assert gate["recent_probe_loss_count"] == 1
    assert gate["probe_failure_reason"] == "holding_downtrend_exit_only"
    assert gate["requires_strong_confirmation"] is True
    assert gate["buy_blocked"] is False


def test_build_lifecycle_gate_blocks_recovery_probe_when_failure_cooldown_active():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()

    gate = build_lifecycle_gate(
        "trial",
        policy,
        recovery_probe_active=True,
        recovery_probe_attempt_count=4,
        recent_probe_loss_count=2,
        recovery_probe_cooldown_active=True,
        probe_failure_reason="probe_loss_threshold",
    )

    assert gate["mode"] == "recovery_probe_cooldown"
    assert gate["buy_blocked"] is True
    assert gate["max_position_pct"] == 0.0
    assert gate["reason_code"] == "recovery_probe_cooldown"
    assert gate["recent_probe_loss_count"] == 2


def test_build_lifecycle_gate_uses_probe_fatigue_when_attempts_repeat_without_success():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults().with_overrides(
        recovery_probe_attempt_fatigue_threshold=4,
    )

    gate = build_lifecycle_gate(
        "trial",
        policy,
        recovery_probe_active=True,
        recovery_probe_attempt_count=4,
        recent_probe_loss_count=0,
    )

    assert gate["mode"] == "recovery_probe_fatigue"
    assert gate["requires_strong_confirmation"] is True
    assert gate["max_position_pct"] == policy.recovery_probe_failed_max_position_pct
    assert gate["reason_code"] == "recovery_probe_attempt_fatigue"


def test_build_lifecycle_gate_softens_active_after_downtrend_warning():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()

    normal_gate = build_lifecycle_gate("active", policy, downtrend_streak=0)
    guarded_gate = build_lifecycle_gate(
        "active",
        policy,
        downtrend_streak=policy.active_guarded_downtrend_streak,
    )

    assert normal_gate["mode"] == "normal_scan"
    assert guarded_gate["mode"] == "active_guarded"
    assert guarded_gate["buy_threshold_delta"] == policy.guarded_buy_threshold_delta
    assert guarded_gate["size_multiplier"] == policy.guarded_size_multiplier
    assert guarded_gate["max_position_pct"] == policy.guarded_max_position_pct
    assert guarded_gate["buy_blocked"] is False


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


def test_downtrend_warning_streak_does_not_self_perpetuate_after_recovery():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    recovered_signal = {
        "final_action": "HOLD",
        "tech_score": 0.32,
        "fusion_score": 0.62,
        "buy_threshold": policy.trial_threshold,
        "buy_strength_score": 0.62,
        "price": 10.8,
        "ma20": 10.0,
        "ma20_slope": 0.02,
    }

    assert detect_weakening_warning(recovered_signal, policy) is False
    assert detect_downtrend_hit(
        recovered_signal,
        {"weakening_warning_streak": policy.warning_to_downtrend_threshold},
        policy,
    ) is False


def test_candidate_score_uses_explicit_recommendation_not_source_identity():
    policy = QuantUniverseLifecyclePolicy.stable_defaults()
    events = [
        {"source_type": "discover", "source_score": 0.8, "confidence": 0.7, "trend": "up"},
        {"source_type": "research", "source_score": 0.6, "confidence": 0.6, "trend": "up"},
    ]
    same_quality_different_sources = [
        {"source_type": "low_price", "source_score": 0.8, "confidence": 0.7, "trend": "up"},
        {"source_type": "main_force", "source_score": 0.6, "confidence": 0.6, "trend": "up"},
    ]

    result = calculate_candidate_score(events, {"is_liquid": True}, policy)
    same_quality_result = calculate_candidate_score(same_quality_different_sources, {"is_liquid": True}, policy)

    assert 0 <= result["candidate_score"] <= 1
    assert result["candidate_score"] == same_quality_result["candidate_score"]
    assert result["candidate_score"] == 0.6986
    assert result["breakdown"]["recommendation_score_component"] == 0.8
    assert "source_score_component" not in result["breakdown"]
    assert result["breakdown"]["multi_source_bonus"] == 0.0


def test_candidate_score_does_not_use_source_count_bonus():
    policy = QuantUniverseLifecyclePolicy.stable_defaults()
    single_source = [
        {"source_type": "discover", "source_score": 0.8, "confidence": 0.7, "trend": "up"},
    ]
    multi_source = [
        {"source_type": "discover", "source_score": 0.8, "confidence": 0.7, "trend": "up"},
        {"source_type": "research", "source_score": 0.8, "confidence": 0.7, "trend": "up"},
    ]

    single_result = calculate_candidate_score(single_source, {"is_liquid": True}, policy)
    multi_result = calculate_candidate_score(multi_source, {"is_liquid": True}, policy)
    drill_result = calculate_candidate_score(multi_source, {"is_liquid": True}, policy, drill_mode=True)

    assert single_result["candidate_score"] == multi_result["candidate_score"]
    assert multi_result["candidate_score"] == drill_result["candidate_score"]
    assert single_result["breakdown"]["multi_source_bonus"] == 0.0
    assert multi_result["breakdown"]["multi_source_bonus"] == 0.0
    assert drill_result["breakdown"]["multi_source_bonus"] == 0.0


def test_resolve_active_to_exit_only_requires_holding_health_break_and_downtrend_confirmation():
    policy = QuantUniverseLifecyclePolicy.stable_defaults()

    post_buy_blocked = resolve_next_status(
        current_status=QuantStatus.ACTIVE,
        health_score=policy.exit_only_threshold - 1,
        downtrend_streak=policy.exit_only_downtrend_streak,
        has_position=True,
        post_buy_grace_active=True,
        policy=policy,
    )
    blocked = resolve_next_status(
        current_status=QuantStatus.ACTIVE,
        health_score=policy.exit_only_threshold - 1,
        downtrend_streak=0,
        has_position=True,
        policy=policy,
    )
    result = resolve_next_status(
        current_status=QuantStatus.ACTIVE,
        health_score=policy.exit_only_threshold - 1,
        downtrend_streak=policy.active_exit_only_downtrend_streak,
        has_position=True,
        active_dwell_checkpoints=policy.active_min_dwell_checkpoints,
        policy=policy,
    )

    assert post_buy_blocked.allowed is False
    assert post_buy_blocked.reason_code == "post_buy_grace_active"
    assert blocked.allowed is False
    assert blocked.reason_code == "no_transition"
    assert result.allowed is True
    assert result.from_status == QuantStatus.ACTIVE
    assert result.to_status == QuantStatus.EXIT_ONLY
    assert result.reason_code == "active_holding_downtrend_exit_only"


def test_low_health_without_downtrend_does_not_force_cooling_or_exit_only():
    policy = QuantUniverseLifecyclePolicy.stable_defaults()

    flat = resolve_next_status(
        current_status="active",
        health_score=0,
        downtrend_streak=0,
        has_position=False,
        policy=policy,
    )
    holding = resolve_next_status(
        current_status="active",
        health_score=0,
        downtrend_streak=0,
        has_position=True,
        policy=policy,
    )

    assert flat.allowed is False
    assert flat.reason_code == "no_transition"
    assert holding.allowed is False
    assert holding.reason_code == "no_transition"


def test_resolve_active_to_cooling_when_flat_and_downtrend_persists():
    policy = QuantUniverseLifecyclePolicy.stable_defaults()

    result = resolve_next_status(
        current_status="active",
        health_score=policy.cooling_threshold,
        downtrend_streak=policy.active_cooling_downtrend_streak,
        has_position=False,
        active_dwell_checkpoints=policy.active_min_dwell_checkpoints,
        policy=policy,
    )

    assert result.allowed is True
    assert result.to_status == QuantStatus.COOLING
    assert result.reason_code == "active_flat_downtrend_cooling"


def test_resolve_trial_to_active_when_trend_confirmed_and_health_strong():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()

    result = resolve_next_status(
        current_status=QuantStatus.TRIAL,
        health_score=policy.active_upgrade_threshold,
        downtrend_streak=0,
        has_position=False,
        trend_confirmed=True,
        active_trend_confirm_checkpoints=policy.active_upgrade_confirm_checkpoints,
        policy=policy,
    )

    assert result.allowed is True
    assert result.from_status == QuantStatus.TRIAL
    assert result.to_status == QuantStatus.ACTIVE
    assert result.reason_code == "trial_upgraded_to_active"


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


def test_resolve_cooling_to_trial_requires_checkpoint_health_and_trend_confirmation():
    policy = QuantUniverseLifecyclePolicy.stable_defaults()

    dwell_blocked = resolve_next_status(
        current_status=QuantStatus.COOLING,
        health_score=policy.cooling_threshold + 10,
        trend_confirmed=True,
        cooling_min_dwell_active=True,
        policy=policy,
    )
    blocked = resolve_next_status(
        current_status=QuantStatus.COOLING,
        health_score=policy.cooling_threshold + 10,
        trend_confirmed=False,
        policy=policy,
    )
    weak_recovery = resolve_next_status(
        current_status=QuantStatus.COOLING,
        health_score=policy.cooling_threshold + 10,
        trend_confirmed=True,
        policy=policy,
    )
    restored = resolve_next_status(
        current_status=QuantStatus.COOLING,
        health_score=policy.active_upgrade_threshold,
        trend_confirmed=True,
        active_trend_confirm_checkpoints=policy.active_upgrade_confirm_checkpoints,
        policy=policy,
    )

    assert dwell_blocked.allowed is False
    assert dwell_blocked.reason_code == "cooling_min_dwell_active"
    assert blocked.allowed is False
    assert blocked.reason_code == "cooling_recovery_not_confirmed"
    assert weak_recovery.allowed is False
    assert weak_recovery.reason_code == "cooling_recovery_not_confirmed"
    assert restored.allowed is True
    assert restored.to_status == QuantStatus.TRIAL
    assert restored.reason_code == "cooling_recovered_to_trial"


def test_resolve_cooling_to_trial_allows_executable_normal_or_strong_buy():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()

    result = resolve_next_status(
        current_status=QuantStatus.COOLING,
        health_score=policy.cooling_threshold - 5,
        downtrend_streak=0,
        trend_confirmed=False,
        active_trend_confirm_checkpoints=0,
        cooling_min_dwell_active=False,
        cooling_recovery_buy=True,
        policy=policy,
    )

    assert result.allowed is True
    assert result.to_status == QuantStatus.TRIAL
    assert result.reason_code == "cooling_recovered_by_executable_buy"


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


def test_active_downtrend_uses_active_specific_slow_degrade_rules():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()

    held_early = resolve_next_status(
        current_status=QuantStatus.ACTIVE,
        health_score=25,
        has_position=True,
        downtrend_streak=policy.exit_only_downtrend_streak,
        active_dwell_checkpoints=1,
        policy=policy,
    )
    held_later = resolve_next_status(
        current_status=QuantStatus.ACTIVE,
        health_score=25,
        has_position=True,
        downtrend_streak=policy.active_exit_only_downtrend_streak - 1,
        active_dwell_checkpoints=policy.active_min_dwell_checkpoints,
        policy=policy,
    )
    exits = resolve_next_status(
        current_status=QuantStatus.ACTIVE,
        health_score=25,
        has_position=True,
        downtrend_streak=policy.active_exit_only_downtrend_streak,
        active_dwell_checkpoints=policy.active_min_dwell_checkpoints,
        policy=policy,
    )

    assert held_early.allowed is False
    assert held_early.reason_code == "active_min_dwell_guarded"
    assert held_later.allowed is False
    assert held_later.reason_code == "active_downtrend_guarded"
    assert exits.allowed is True
    assert exits.to_status == QuantStatus.EXIT_ONLY
    assert exits.reason_code == "active_holding_downtrend_exit_only"


def test_active_immediate_sell_still_enters_exit_only():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()

    result = resolve_next_status(
        current_status=QuantStatus.ACTIVE,
        health_score=80,
        has_position=True,
        downtrend_streak=1,
        active_dwell_checkpoints=0,
        immediate_exit_signal=True,
        policy=policy,
    )

    assert result.allowed is True
    assert result.to_status == QuantStatus.EXIT_ONLY
    assert result.reason_code == "active_immediate_exit_signal"


def test_manager_active_weak_sell_observes_instead_of_immediate_exit(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state(
        "600000",
        {
            "quant_status": "active",
            "health_score": 78.0,
            "active_since": "2026-01-05T10:00:00Z",
            "active_checkpoints": policy.active_min_dwell_checkpoints + 4,
        },
    )
    signal = {
        "stock_code": "600000",
        "stock_name": "浦发银行",
        "action": "SELL",
        "decision_type": "dual_track_weighted_sell",
        "decision_time": "2026-01-06T10:30:00Z",
        "tech_score": 0.35,
        "context_score": 0.04,
        "fusion_score": 0.30,
        "price": 12.8,
        "ma20": 12.0,
        "ma20_slope": 0.02,
        "unrealized_pnl_pct": -1.8,
    }

    result = manager.update_after_signal(
        "600000",
        latest_signal=signal,
        recent_signals=[signal],
        position={"stock_code": "600000", "quantity": 100, "unrealized_pnl_pct": -1.8},
    )
    state = manager.db.get_quant_universe_state("600000")

    assert result["status_changed"] is False
    assert result["new_status"] == "active"
    assert result["reason_code"] == "active_downtrend_guarded"
    assert state["quant_status"] == "active"


def test_manager_active_hard_stop_sell_still_immediately_exits(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state(
        "600000",
        {
            "quant_status": "active",
            "health_score": 78.0,
            "active_since": "2026-01-05T10:00:00Z",
            "active_checkpoints": policy.active_min_dwell_checkpoints + 4,
        },
    )
    signal = {
        "stock_code": "600000",
        "stock_name": "浦发银行",
        "action": "SELL",
        "decision_type": "hard_stop_loss",
        "decision_time": "2026-01-06T10:30:00Z",
        "tech_score": -0.8,
        "context_score": -0.3,
        "fusion_score": 0.05,
        "quick_stoploss_failure": False,
        "strategy_profile": {
            "explainability": {
                "fusion_breakdown": {
                    "veto_id": "hard_stop_loss",
                    "veto_trigger_type": "hard_stop_loss",
                }
            }
        },
    }

    result = manager.update_after_signal(
        "600000",
        latest_signal=signal,
        recent_signals=[signal],
        position={"stock_code": "600000", "quantity": 100, "unrealized_pnl_pct": -6.0},
    )

    assert result["status_changed"] is True
    assert result["new_status"] == "exit_only"
    assert result["reason_code"] == "active_immediate_exit_signal"


def test_active_flat_downtrend_uses_active_specific_cooling_threshold():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()

    held = resolve_next_status(
        current_status=QuantStatus.ACTIVE,
        health_score=30,
        has_position=False,
        downtrend_streak=policy.downtrend_cooling_streak,
        active_dwell_checkpoints=policy.active_min_dwell_checkpoints,
        policy=policy,
    )
    cooled = resolve_next_status(
        current_status=QuantStatus.ACTIVE,
        health_score=30,
        has_position=False,
        downtrend_streak=policy.active_cooling_downtrend_streak,
        active_dwell_checkpoints=policy.active_min_dwell_checkpoints,
        policy=policy,
    )

    assert held.allowed is False
    assert held.reason_code == "active_downtrend_guarded"
    assert cooled.allowed is True
    assert cooled.to_status == QuantStatus.COOLING
    assert cooled.reason_code == "active_flat_downtrend_cooling"


def test_active_downtrend_keeps_high_health_position_in_guarded_instead_of_exiting():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()

    holding = resolve_next_status(
        current_status=QuantStatus.ACTIVE,
        health_score=policy.exit_only_threshold + 20,
        has_position=True,
        downtrend_streak=policy.active_exit_only_downtrend_streak,
        active_dwell_checkpoints=policy.active_min_dwell_checkpoints,
        policy=policy,
    )
    flat = resolve_next_status(
        current_status=QuantStatus.ACTIVE,
        health_score=policy.cooling_threshold + 20,
        has_position=False,
        downtrend_streak=policy.active_cooling_downtrend_streak,
        active_dwell_checkpoints=policy.active_min_dwell_checkpoints,
        policy=policy,
    )

    assert holding.allowed is False
    assert holding.reason_code == "active_downtrend_guarded"
    assert flat.allowed is False
    assert flat.reason_code == "active_downtrend_guarded"


def _manager(
    tmp_path,
    policy: QuantUniverseLifecyclePolicy | None = None,
    *,
    drill_mode: bool = False,
) -> QuantUniverseManager:
    db = QuantSimDB(tmp_path / "quant_sim.db")
    return QuantUniverseManager(
        db=db,
        profile_id="stable",
        policy=policy or QuantUniverseLifecyclePolicy.stable_defaults(),
        drill_mode=drill_mode,
    )


def test_manager_confirm_first_marks_eligible_without_promoting(tmp_path):
    manager = _manager(tmp_path)
    manager.db.update_quant_universe_settings({"auto_entry_mode": "confirm_first"})
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="discover")

    result = manager.ingest_candidate_event(
        {
            "stock_code": "600000",
            "source_type": "discover",
            "source_key": "main_force",
            "source_score": 0.9,
            "confidence": 0.8,
            "trend": "up",
            "reason_text": "主力与趋势共振",
        }
    )

    state = manager.db.get_quant_universe_state("600000")
    events = manager.db.list_candidate_events(stock_code="600000", status="eligible")
    assert result["decision"] == "eligible"
    assert result["candidate_score"] >= manager.policy.trial_threshold
    assert state is None or state["quant_status"] == "inactive"
    assert events[0]["status"] == "eligible"


def test_manager_auto_trial_promotes_eligible_candidate(tmp_path):
    manager = _manager(tmp_path)
    manager.db.update_quant_universe_settings({"auto_entry_mode": "auto_trial"})
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="discover")

    result = manager.ingest_candidate_event(
        {
            "stock_code": "600000",
            "source_type": "discover",
            "source_key": "main_force",
            "source_score": 0.9,
            "confidence": 0.8,
            "trend": "up",
            "reason_text": "自动纳入",
        }
    )

    state = manager.db.get_quant_universe_state("600000")
    assert result["decision"] == "promoted_to_trial"
    assert state["quant_status"] == "trial"
    assert state["quant_enabled"] is True


def test_low_price_event_requires_trend_repair_before_auto_entry(tmp_path):
    manager = _manager(tmp_path, policy=QuantUniverseLifecyclePolicy.aggressive_defaults())
    manager.db.update_quant_universe_settings({"auto_entry_mode": "auto_trial"})
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="low_price")

    result = manager.ingest_candidate_event(
        {
            "stock_code": "600000",
            "source_type": "low_price",
            "source_key": "low_price:test",
            "source_score": 0.95,
            "confidence": 0.9,
            "trend": "up",
            "payload_json": {
                "price": 8.8,
                "ma5": 8.7,
                "ma10": 8.9,
                "ma20": 9.4,
                "ma20_slope": -0.02,
                "amount": 60_000_000,
                "volume_ratio": 1.6,
                "rsi": 58,
                "macd": 0.05,
            },
        }
    )

    assert result["decision"] == "skipped"
    assert result["reason_code"] == "low_price_below_falling_ma20"
    assert manager.db.get_quant_universe_state("600000")["quant_status"] == "inactive"
    blocked_events = manager.db.list_candidate_events(stock_code="600000", status="blocked")
    assert blocked_events[0]["payload_json"]["entry_gate"]["result"] == "eligible_blocked"


def test_research_event_requires_technical_confirmation_for_auto_entry(tmp_path):
    manager = _manager(tmp_path, policy=QuantUniverseLifecyclePolicy.aggressive_defaults())
    manager.db.update_quant_universe_settings({"auto_entry_mode": "auto_trial"})
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="research")

    result = manager.ingest_candidate_event(
        {
            "stock_code": "600000",
            "source_type": "research",
            "source_key": "research:test",
            "source_score": 0.98,
            "confidence": 0.95,
            "trend": "up",
            "payload_json": {
                "price": 9.8,
                "ma5": 9.6,
                "ma10": 9.7,
                "ma20": 10.1,
                "ma20_slope": -0.01,
                "amount": 100_000_000,
                "volume_ratio": 1.4,
                "rsi": 62,
                "macd": 0.08,
            },
        }
    )

    assert result["decision"] == "skipped"
    assert result["reason_code"] == "ai_requires_technical_confirmation"
    assert manager.db.get_quant_universe_state("600000")["quant_status"] == "inactive"
    recommended_events = manager.db.list_candidate_events(stock_code="600000", status="recommended_only")
    assert recommended_events[0]["payload_json"]["entry_gate"]["result"] == "recommended_only"


def test_quant_universe_state_persists_recovery_probe_diagnostics(tmp_path):
    manager = _manager(tmp_path)

    manager.db.upsert_quant_universe_state(
        "600000",
        {
            "stock_name": "浦发银行",
            "quant_status": "trial",
            "recovery_probe_attempt_count": 3,
            "recent_probe_loss_count": 2,
            "last_recovery_probe_failure_at": "2026-05-08T10:00:00Z",
            "recovery_probe_cooldown_until": "2026-05-28T10:00:00Z",
            "probe_failure_reason": "holding_downtrend_exit_only",
        },
    )

    state = manager.db.get_quant_universe_state("600000")

    assert state["recovery_probe_attempt_count"] == 3
    assert state["recent_probe_loss_count"] == 2
    assert state["last_recovery_probe_failure_at"] == "2026-05-08T10:00:00Z"
    assert state["recovery_probe_cooldown_until"] == "2026-05-28T10:00:00Z"
    assert state["probe_failure_reason"] == "holding_downtrend_exit_only"


def test_manager_records_recovery_probe_failure_and_cooldown_after_repeated_failures(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults().with_overrides(
        recovery_probe_failure_threshold=2,
        recovery_probe_cooldown_days=20,
    )
    manager = _manager(tmp_path, policy)
    manager.db.update_quant_universe_settings({"auto_exit_enabled": True})
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="discover")
    manager.db.upsert_quant_universe_state(
        "600000",
        {
            "stock_name": "浦发银行",
            "quant_status": "trial",
            "recovery_probe_until": "2026-05-10T10:00:00Z",
            "recent_probe_loss_count": 1,
            "last_recovery_probe_failure_at": "2026-05-01T10:00:00Z",
            "downtrend_streak": policy.exit_only_downtrend_streak - 1,
        },
    )

    result = manager.update_after_signal(
        "600000",
        {
            "action": "HOLD",
            "tech_score": -0.2,
            "fusion_score": 0.1,
            "fusion_score_delta": -0.1,
            "decision_time": "2026-05-08T10:00:00Z",
            "status": "observed",
        },
        recent_signals=[],
        position={"stock_code": "600000", "quantity": 100, "unrealized_pnl_pct": -2.0},
    )

    state = manager.db.get_quant_universe_state("600000")

    assert result["new_status"] == "exit_only"
    assert state["recent_probe_loss_count"] == 2
    assert state["last_recovery_probe_failure_at"] == "2026-05-08T10:00:00Z"
    assert state["probe_failure_reason"] == "holding_downtrend_exit_only"
    assert state["recovery_probe_cooldown_until"] == "2026-05-28T10:00:00Z"


def test_manager_records_probe_attempt_fatigue_cooldown(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults().with_overrides(
        recovery_probe_attempt_fatigue_threshold=3,
        recovery_probe_cooldown_days=20,
    )
    manager = _manager(tmp_path, policy)
    manager.db.update_quant_universe_settings({"auto_exit_enabled": True})
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="discover")
    manager.db.upsert_quant_universe_state(
        "600000",
        {
            "stock_name": "浦发银行",
            "quant_status": "cooling",
            "health_score": policy.cooling_threshold - 5,
            "recovery_probe_attempt_count": 2,
            "last_recovery_probe_attempt_at": "2026-05-01T10:00:00Z",
            "cooling_until": "2026-05-01T00:00:00Z",
        },
    )
    signal = {
        "action": "BUY",
        "decision_time": "2026-05-08T10:00:00Z",
        "tech_score": 0.3,
        "context_score": 0.1,
        "price": 12.8,
        "ma20": 12.0,
        "ma20_slope": 0.02,
        "status": "observed",
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.39, "fusion_score_delta": 0.04}},
            "portfolio_execution_guard": {
                "status": "normal_buy",
                "buy_tier": "normal_buy",
                "buy_strength_score": 0.71,
            },
            "execution_sizing_plan": {
                "effective_position_pct": 6.0,
                "final_budget": 24000.0,
                "skip_reason": None,
            },
        },
    }

    result = manager.update_after_signal("600000", signal, recent_signals=[signal], position=None)
    state = manager.db.get_quant_universe_state("600000")

    assert result["new_status"] == "trial"
    assert state["recovery_probe_attempt_count"] == 3
    assert state["last_recovery_probe_attempt_at"] == "2026-05-08T10:00:00Z"
    assert state["probe_failure_reason"] == "recovery_probe_attempt_fatigue"
    assert state["recovery_probe_cooldown_until"] == "2026-05-28T10:00:00Z"


def test_manager_drill_mode_does_not_promote_by_source_count_bonus(tmp_path):
    manager = _manager(tmp_path, drill_mode=True)
    manager.db.update_quant_universe_settings({"auto_entry_mode": "auto_trial"})
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="discover")

    first = manager.ingest_candidate_event(
        {
            "stock_code": "600000",
            "source_type": "discover",
            "source_key": "main_force",
            "source_score": 0.6,
            "confidence": 0.4,
            "trend": "up",
            "reason_text": "first historical candidate",
        }
    )
    second = manager.ingest_candidate_event(
        {
            "stock_code": "600000",
            "source_type": "research",
            "source_key": "low_price",
            "source_score": 0.6,
            "confidence": 0.4,
            "trend": "up",
            "reason_text": "second historical candidate",
        }
    )

    state = manager.db.get_quant_universe_state("600000")
    assert first["decision"] == "skipped"
    assert second["decision"] == "skipped"
    assert second["candidate_score"] < manager.policy.trial_threshold
    assert second["breakdown"]["multi_source_bonus"] == 0.0
    assert state is None or state["quant_status"] == "inactive"


def test_manager_lifecycle_disabled_records_event_without_auto_promoting(tmp_path):
    manager = _manager(tmp_path)
    manager.db.update_quant_universe_settings(
        {"auto_entry_mode": "auto_trial", "quant_universe_lifecycle_enabled": False}
    )
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="discover")

    result = manager.ingest_candidate_event(
        {"stock_code": "600000", "source_type": "discover", "source_score": 0.95, "confidence": 0.9, "trend": "up"}
    )

    assert result["decision"] == "eligible"
    assert result["skip_reason"] == "lifecycle_disabled"
    assert manager.db.get_quant_universe_state("600000")["quant_status"] == "inactive"


def test_manager_ignore_auto_entry_marks_events_ignored(tmp_path):
    manager = _manager(tmp_path)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="discover")
    manager.db.add_candidate_event(
        {
            "stock_code": "600000",
            "source_type": "discover",
            "source_score": 0.9,
            "confidence": 0.8,
            "trend": "up",
            "status": "eligible",
        }
    )

    result = manager.ignore_auto_entry(["600000"], source_type="discover")

    assert result["ignored"] == ["600000"]
    assert manager.db.list_candidate_events(stock_code="600000", status="ignored")[0]["status"] == "ignored"


def test_manager_set_override_manual_pause_sets_manual_paused_and_disables_quant(tmp_path):
    manager = _manager(tmp_path)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="discover")
    manager.db.upsert_quant_universe_state("600000", {"quant_status": "active"})

    result = manager.set_override("600000", "manual_pause")
    state = manager.db.get_quant_universe_state("600000")

    assert result["quant_status"] == "manual_paused"
    assert result["quant_manual_override"] == "manual_pause"
    assert state["quant_status"] == "manual_paused"
    assert state["quant_enabled"] is False


def test_manager_basic_info_missing_blocks_auto_trial_but_keeps_eligible(tmp_path):
    manager = _manager(tmp_path)
    manager.db.update_quant_universe_settings({"auto_entry_mode": "auto_trial"})
    manager.db.add_watch(
        stock_code="600000",
        stock_name="浦发银行",
        source="discover",
        metadata={"basic_info_missing": True},
    )

    result = manager.ingest_candidate_event(
        {
            "stock_code": "600000",
            "source_type": "discover",
            "source_score": 0.95,
            "confidence": 0.9,
            "trend": "up",
        }
    )

    assert result["decision"] == "eligible"
    assert result["skip_reason"] == "basic_info_missing"
    assert manager.db.get_quant_universe_state("600000")["quant_status"] == "inactive"


def test_manager_manual_ban_and_cooling_window_block_entry(tmp_path):
    manager = _manager(tmp_path)
    manager.db.update_quant_universe_settings({"auto_entry_mode": "auto_trial"})
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="discover")
    manager.db.add_watch(stock_code="000001", stock_name="平安银行", source="discover")
    manager.set_override("600000", "manual_ban")
    manager.db.upsert_quant_universe_state(
        "000001",
        {"quant_status": "cooling", "cooling_until": "2099-01-01T00:00:00Z"},
    )

    banned = manager.ingest_candidate_event(
        {"stock_code": "600000", "source_type": "discover", "source_score": 0.95, "confidence": 0.9, "trend": "up"}
    )
    cooling = manager.ingest_candidate_event(
        {"stock_code": "000001", "source_type": "discover", "source_score": 0.95, "confidence": 0.9, "trend": "up"}
    )

    assert banned["decision"] == "skipped"
    assert banned["skip_reason"] == "manual_ban"
    assert cooling["decision"] == "cooling_review_queued"
    assert cooling["skip_reason"] == "cooling_review_required"


def test_manager_candidate_event_does_not_restore_expired_cooling_stock(tmp_path):
    manager = _manager(tmp_path)
    manager.db.update_quant_universe_settings({"auto_entry_mode": "auto_trial"})
    manager.db.add_watch(stock_code="000001", stock_name="平安银行", source="discover")
    manager.db.upsert_quant_universe_state(
        "000001",
        {"quant_status": "cooling", "cooling_until": "2026-01-04T02:00:00Z", "health_score": 26},
    )

    result = manager.ingest_candidate_event(
        {
            "stock_code": "000001",
            "source_type": "low_price",
            "source_score": 0.95,
            "confidence": 0.9,
            "trend": "up",
            "payload_json": {
                "price": 8.8,
                "ma5": 9.2,
                "ma10": 9.0,
                "ma20": 8.6,
                "ma20_slope": 0.02,
                "amount": 80_000_000,
                "volume_ratio": 1.5,
                "rsi": 62,
                "macd": 0.05,
            },
        },
        capacity_at=datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc),
    )

    assert result["decision"] == "cooling_review_queued"
    assert result["skip_reason"] == "cooling_review_required"
    assert manager.db.get_quant_universe_state("000001")["quant_status"] == "cooling"


def test_manager_non_tradable_blocks_auto_entry(tmp_path):
    manager = _manager(tmp_path)
    manager.db.update_quant_universe_settings({"auto_entry_mode": "auto_trial"})
    manager.db.add_watch(
        stock_code="600000",
        stock_name="浦发银行",
        source="discover",
        metadata={"tradable": False},
    )

    result = manager.ingest_candidate_event(
        {"stock_code": "600000", "source_type": "discover", "source_score": 0.95, "confidence": 0.9, "trend": "up"}
    )

    assert result["decision"] == "skipped"
    assert result["skip_reason"] == "non_tradable"


def test_manager_daily_capacity_keeps_candidate_eligible_without_auto_promoting(tmp_path):
    policy = QuantUniverseLifecyclePolicy.stable_defaults().with_overrides(max_auto_entries_per_day=0)
    manager = _manager(tmp_path, policy)
    manager.db.update_quant_universe_settings({"auto_entry_mode": "auto_trial"})
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="discover")

    result = manager.ingest_candidate_event(
        {"stock_code": "600000", "source_type": "discover", "source_score": 0.95, "confidence": 0.9, "trend": "up"}
    )

    assert result["decision"] == "eligible"
    assert result["skip_reason"] == "daily_capacity_exceeded"
    assert manager.db.get_quant_universe_state("600000")["quant_status"] == "inactive"


def test_manager_drill_capacity_uses_checkpoint_day_without_changing_live_default(tmp_path):
    policy = QuantUniverseLifecyclePolicy.stable_defaults().with_overrides(max_auto_entries_per_day=1)
    live_manager = _manager(tmp_path / "live", policy)
    live_manager.db.update_quant_universe_settings({"auto_entry_mode": "auto_trial"})
    for code in ("600000", "000001"):
        live_manager.db.add_watch(stock_code=code, stock_name=code, source="discover")

    first_live = live_manager.ingest_candidate_event(
        {"stock_code": "600000", "source_type": "discover", "source_score": 0.95, "confidence": 0.9, "trend": "up"}
    )
    second_live = live_manager.ingest_candidate_event(
        {"stock_code": "000001", "source_type": "discover", "source_score": 0.95, "confidence": 0.9, "trend": "up"}
    )

    drill_manager = _manager(tmp_path / "drill", policy, drill_mode=True)
    drill_manager.db.update_quant_universe_settings({"auto_entry_mode": "auto_trial"})
    for code in ("600000", "000001"):
        drill_manager.db.add_watch(stock_code=code, stock_name=code, source="discover")

    first_drill = drill_manager.ingest_candidate_event(
        {"stock_code": "600000", "source_type": "discover", "source_score": 0.95, "confidence": 0.9, "trend": "up"},
        capacity_at=datetime(2026, 1, 5, 10, 0),
    )
    second_drill = drill_manager.ingest_candidate_event(
        {"stock_code": "000001", "source_type": "discover", "source_score": 0.95, "confidence": 0.9, "trend": "up"},
        capacity_at=datetime(2026, 1, 6, 10, 0),
    )

    assert first_live["decision"] == "promoted_to_trial"
    assert second_live["decision"] == "eligible"
    assert second_live["skip_reason"] == "daily_capacity_exceeded"
    assert first_drill["decision"] == "promoted_to_trial"
    assert second_drill["decision"] == "promoted_to_trial"


def test_manager_promote_to_trial_respects_batch_capacity(tmp_path):
    policy = QuantUniverseLifecyclePolicy.stable_defaults()
    policy = policy.with_overrides(max_auto_entries_per_batch=1)
    manager = _manager(tmp_path, policy)
    for code, score in (("600000", 0.95), ("000001", 0.75)):
        manager.db.add_watch(stock_code=code, stock_name=code, source="discover")
        manager.db.add_candidate_event(
            {
                "stock_code": code,
                "source_type": "discover",
                "source_score": score,
                "confidence": 0.9,
                "trend": "up",
                "status": "eligible",
            }
        )

    result = manager.promote_to_trial(["000001", "600000"], source_type="manual", source_key=None)

    assert result["success"] == ["600000"]
    assert result["skipped"][0]["stock_code"] == "000001"
    assert result["skipped"][0]["reason"] == "batch_capacity_exceeded"


def test_manager_promote_to_trial_respects_strategy_and_industry_capacity(tmp_path):
    policy = QuantUniverseLifecyclePolicy.stable_defaults().with_overrides(
        max_auto_entries_per_batch=10,
        max_auto_entries_per_strategy_batch=1,
        max_same_industry_auto_entries_per_day=1,
    )
    manager = _manager(tmp_path, policy)
    for code, score, source_key in (
        ("600000", 0.95, "main_force"),
        ("000001", 0.90, "main_force"),
        ("600036", 0.88, "value"),
    ):
        manager.db.add_watch(stock_code=code, stock_name=code, source="discover")
        with manager.db._connect() as conn:  # noqa: SLF001 - test setup for stock universe metadata
            conn.execute("UPDATE stock_universe SET industry = ? WHERE stock_code = ?", ("银行", code))
            conn.commit()
        manager.db.add_candidate_event(
            {
                "stock_code": code,
                "source_type": "discover",
                "source_key": source_key,
                "source_score": score,
                "confidence": 0.9,
                "trend": "up",
                "status": "eligible",
            }
        )

    result = manager.promote_to_trial(["600000", "000001", "600036"], source_type="discover", source_key="main_force")

    assert result["success"] == ["600000"]
    assert {item["reason"] for item in result["skipped"]} == {
        "strategy_batch_capacity_exceeded",
        "industry_capacity_exceeded",
    }


def test_manager_promote_to_trial_respects_same_concept_capacity(tmp_path):
    policy = QuantUniverseLifecyclePolicy.stable_defaults().with_overrides(
        max_auto_entries_per_batch=10,
        max_same_concept_auto_entries_per_day=1,
    )
    manager = _manager(tmp_path, policy)
    for code, score in (("600000", 0.95), ("000001", 0.90)):
        manager.db.add_watch(
            stock_code=code,
            stock_name=code,
            source="discover",
            metadata={"primary_theme": "AI金融"},
        )
        manager.db.add_candidate_event(
            {
                "stock_code": code,
                "source_type": "discover",
                "source_score": score,
                "confidence": 0.9,
                "trend": "up",
                "status": "eligible",
            }
        )

    result = manager.promote_to_trial(["600000", "000001"], source_type="manual", source_key=None)

    assert result["success"] == ["600000"]
    assert result["skipped"] == [{"stock_code": "000001", "reason": "concept_capacity_exceeded"}]


def test_manager_retired_reactivation_requires_high_threshold(tmp_path):
    manager = _manager(tmp_path)
    manager.db.update_quant_universe_settings({"auto_entry_mode": "auto_trial"})
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="discover")
    manager.db.upsert_quant_universe_state("600000", {"quant_status": "retired", "health_score": 20})

    weak = manager.ingest_candidate_event(
        {"stock_code": "600000", "source_type": "discover", "source_score": 0.7, "confidence": 0.6, "trend": "up"}
    )
    strong = manager.ingest_candidate_event(
        {
            "stock_code": "600000",
            "source_type": "research",
            "source_score": 0.98,
            "confidence": 0.95,
            "trend": "up",
            "payload_json": {
                "price": 10.8,
                "ma5": 10.9,
                "ma10": 10.6,
                "ma20": 10.1,
                "ma20_slope": 0.02,
                "amount": 120_000_000,
                "volume_ratio": 1.4,
                "rsi": 61,
                "macd": 0.06,
            },
        }
    )

    assert weak["decision"] == "skipped"
    assert weak["skip_reason"] == "retired_reentry_below_threshold"
    assert strong["decision"] == "promoted_to_trial"


def test_manager_retired_min_dwell_blocks_high_score_reactivation(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults().with_overrides(retired_min_dwell_days=14)
    manager = _manager(tmp_path, policy)
    manager.db.update_quant_universe_settings({"auto_entry_mode": "auto_trial"})
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="discover")
    manager.db.upsert_quant_universe_state(
        "600000",
        {
            "quant_status": "retired",
            "health_score": 20,
            "retired_at": "2026-01-10T00:00:00Z",
        },
    )
    manager.db.add_candidate_event(
        {
            "stock_code": "600000",
            "source_type": "research",
            "source_score": 0.98,
            "confidence": 0.95,
            "trend": "up",
            "status": "active",
        }
    )

    result = manager.ingest_candidate_event(
        {"stock_code": "600000", "source_type": "discover", "source_score": 1.0, "confidence": 1.0, "trend": "up"},
        capacity_at=datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
    )

    assert result["decision"] == "skipped"
    assert result["skip_reason"] == "retired_dwell_blocked"
    assert result["reason_code"] == "retired_dwell_blocked"
    assert manager.db.get_quant_universe_state("600000")["quant_status"] == "retired"


def test_manager_retired_reactivation_allowed_after_min_dwell(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults().with_overrides(retired_min_dwell_days=14)
    manager = _manager(tmp_path, policy)
    manager.db.update_quant_universe_settings({"auto_entry_mode": "auto_trial"})
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="discover")
    manager.db.upsert_quant_universe_state(
        "600000",
        {
            "quant_status": "retired",
            "health_score": 20,
            "retired_at": "2026-01-10T00:00:00Z",
        },
    )
    manager.db.add_candidate_event(
        {
            "stock_code": "600000",
            "source_type": "research",
            "source_score": 0.98,
            "confidence": 0.95,
            "trend": "up",
            "status": "active",
        }
    )

    result = manager.ingest_candidate_event(
        {"stock_code": "600000", "source_type": "discover", "source_score": 1.0, "confidence": 1.0, "trend": "up"},
        capacity_at=datetime(2026, 1, 25, 10, 0, tzinfo=timezone.utc),
    )

    assert result["decision"] == "promoted_to_trial"
    assert manager.db.get_quant_universe_state("600000")["quant_status"] == "trial"


def test_manager_retired_reactivation_can_be_disabled(tmp_path):
    policy = QuantUniverseLifecyclePolicy.stable_defaults().with_overrides(retired_reactivation_check_enabled=False)
    manager = _manager(tmp_path, policy)
    manager.db.update_quant_universe_settings({"auto_entry_mode": "auto_trial"})
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="discover")
    manager.db.upsert_quant_universe_state("600000", {"quant_status": "retired", "health_score": 20})

    result = manager.ingest_candidate_event(
        {"stock_code": "600000", "source_type": "discover", "source_score": 1.0, "confidence": 1.0, "trend": "up"}
    )

    assert result["decision"] == "skipped"
    assert result["skip_reason"] == "retired_reactivation_disabled"


def test_manager_update_after_signal_respects_auto_exit_switch(tmp_path):
    manager = _manager(tmp_path)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state("600000", {"quant_status": "active", "health_score": 80})
    manager.db.update_quant_universe_settings({"auto_exit_enabled": False})

    result = manager.update_after_signal(
        "600000",
        latest_signal={"action": "HOLD", "tech_score": -0.5, "fusion_score": 0.1, "fusion_score_delta": -0.1},
        recent_signals=[
            {"action": "HOLD", "tech_score": -0.5, "context_score": -0.5, "fusion_score": 0.1, "buy_strength_score": 0.1}
        ],
        position={"quantity": 100},
    )

    state = manager.db.get_quant_universe_state("600000")
    assert result["status_changed"] is False
    assert state["quant_status"] == "active"
    assert state["health_score"] < 80


def test_manager_health_inputs_read_nested_checkpoint_signal_scores(tmp_path):
    manager = _manager(tmp_path, QuantUniverseLifecyclePolicy.aggressive_defaults())

    inputs = manager._health_inputs_from_signals(  # noqa: SLF001 - validates lifecycle signal contract
        [
            {
                "action": "BUY",
                "tech_score": 0.6,
                "context_score": 0.0,
                "strategy_profile": {
                    "explainability": {
                        "fusion_breakdown": {
                            "fusion_score": 0.4,
                            "fusion_score_delta": 0.06,
                        }
                    },
                    "portfolio_execution_guard": {
                        "status": "normal_buy",
                        "buy_strength_score": 0.3,
                    },
                    "stock_execution_feedback_gate": {
                        "status": "blocked",
                    },
                },
            }
        ]
    )

    assert inputs.avg_fusion_score == 0.4
    assert inputs.avg_buy_strength_score == 0.3
    assert inputs.blocked_streak == 1


def test_manager_update_after_signal_restores_cooling_from_checkpoint_trend(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state("600000", {"quant_status": "cooling", "health_score": policy.active_upgrade_threshold})

    signal = {
        "action": "BUY",
        "tech_score": 0.65,
        "context_score": 0.1,
        "price": 12.8,
        "ma20": 12.0,
        "ma20_slope": 0.02,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.72, "fusion_score_delta": 0.2}},
            "portfolio_execution_guard": {"status": "strong_buy", "buy_strength_score": 0.68},
        },
    }

    result = manager.update_after_signal(
        "600000",
        latest_signal=signal,
        recent_signals=[signal] * policy.active_upgrade_confirm_checkpoints,
        position=None,
    )

    assert result["status_changed"] is True
    assert result["old_status"] == "cooling"
    assert result["new_status"] == "trial"
    assert result["health_score"] >= policy.cooling_threshold


def test_manager_update_after_signal_restores_cooling_from_executable_normal_buy(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state(
        "600000",
        {
            "quant_status": "cooling",
            "health_score": policy.cooling_threshold - 5,
            "cooling_until": "2026-01-01T00:00:00Z",
        },
    )

    signal = {
        "action": "BUY",
        "decision_time": "2026-01-05T10:00:00Z",
        "tech_score": 0.3,
        "context_score": 0.1,
        "price": 12.8,
        "ma20": 12.0,
        "ma20_slope": 0.02,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.39, "fusion_score_delta": 0.04}},
            "portfolio_execution_guard": {
                "status": "normal_buy",
                "buy_tier": "normal_buy",
                "buy_strength_score": 0.71,
            },
            "execution_sizing_plan": {
                "effective_position_pct": 6.0,
                "final_budget": 24000.0,
                "skip_reason": None,
            },
        },
    }

    result = manager.update_after_signal("600000", latest_signal=signal, recent_signals=[signal], position=None)

    assert result["status_changed"] is True
    assert result["old_status"] == "cooling"
    assert result["new_status"] == "trial"
    assert manager.db.get_latest_quant_universe_event("600000")["reason_code"] == "cooling_recovered_by_executable_buy"
    state = manager.db.get_quant_universe_state("600000")
    assert state["recovery_probe_until"] == "2026-01-06T10:00:00Z"


def test_manager_blocks_cooling_normal_buy_after_two_recent_probe_losses(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state(
        "600000",
        {
            "quant_status": "cooling",
            "health_score": policy.cooling_threshold - 5,
            "cooling_until": "2026-01-01T00:00:00Z",
            "recent_probe_loss_count": 2,
            "last_recovery_probe_failure_at": "2026-01-02T10:00:00Z",
        },
    )

    signal = {
        "action": "BUY",
        "decision_time": "2026-01-20T10:00:00Z",
        "tech_score": 0.3,
        "context_score": 0.1,
        "price": 12.8,
        "ma20": 12.0,
        "ma20_slope": 0.02,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.39, "fusion_score_delta": 0.04}},
            "portfolio_execution_guard": {
                "status": "normal_buy",
                "buy_tier": "normal_buy",
                "buy_strength_score": 0.71,
            },
            "execution_sizing_plan": {
                "effective_position_pct": 6.0,
                "final_budget": 24000.0,
                "skip_reason": None,
            },
        },
    }

    result = manager.update_after_signal("600000", latest_signal=signal, recent_signals=[signal], position=None)
    state = manager.db.get_quant_universe_state("600000")

    assert result["status_changed"] is False
    assert result["new_status"] == "cooling"
    assert result["reason_code"] == "recovery_probe_recent_loss_requires_strong_confirmation"
    assert state["quant_status"] == "cooling"
    assert state["recovery_probe_until"] is None


def test_manager_update_after_signal_resets_streaks_when_cooling_buy_recovers(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state(
        "600000",
        {
            "quant_status": "cooling",
            "health_score": policy.cooling_threshold - 5,
            "cooling_until": "2026-01-01T00:00:00Z",
            "downtrend_streak": 100,
            "weakening_warning_streak": 100,
        },
    )

    recovery_signal = {
        "action": "BUY",
        "decision_time": "2026-01-05T10:00:00Z",
        "tech_score": 0.3,
        "context_score": 0.1,
        "price": 12.8,
        "ma20": 12.0,
        "ma20_slope": 0.02,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.39, "fusion_score_delta": 0.04}},
            "portfolio_execution_guard": {
                "status": "normal_buy",
                "buy_tier": "normal_buy",
                "buy_strength_score": 0.71,
            },
            "execution_sizing_plan": {
                "effective_position_pct": 6.0,
                "final_budget": 24000.0,
                "skip_reason": None,
            },
        },
    }

    result = manager.update_after_signal("600000", latest_signal=recovery_signal, recent_signals=[recovery_signal], position=None)

    state = manager.db.get_quant_universe_state("600000")
    assert result["new_status"] == "trial"
    assert state["downtrend_streak"] == 0
    assert state["weakening_warning_streak"] == 0


def test_manager_recovery_probe_strong_confirmation_upgrades_to_active(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state(
        "600000",
        {
            "quant_status": "trial",
            "health_score": policy.active_upgrade_threshold,
            "recovery_probe_until": "2026-01-06T10:00:00Z",
        },
    )
    signal = {
        "action": "BUY",
        "decision_time": "2026-01-05T10:00:00Z",
        "tech_score": 0.7,
        "context_score": 0.2,
        "price": 12.8,
        "ma20": 12.0,
        "ma20_slope": 0.02,
        "strategy_profile": {
            "portfolio_execution_guard": {
                "status": "strong_buy",
                "buy_tier": "strong_buy",
                "buy_strength_score": 0.9,
                "trend_confirmation": {
                    "ma_stack": True,
                    "ma20_rising": True,
                    "above_ma20_checkpoints": policy.active_upgrade_confirm_checkpoints,
                },
            }
        },
    }

    result = manager.update_after_signal(
        "600000",
        latest_signal=signal,
        recent_signals=[signal] * policy.active_upgrade_confirm_checkpoints,
        position={"quantity": 100},
    )

    assert result["status_changed"] is True
    assert result["new_status"] == "active"
    assert result["reason_code"] == "trial_recovery_probe_strong_upgraded_to_active"


def test_resolve_trial_recovery_probe_grace_blocks_fast_exit_only():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()

    result = resolve_next_status(
        current_status=QuantStatus.TRIAL,
        health_score=policy.exit_only_threshold - 5,
        has_position=True,
        downtrend_streak=policy.exit_only_downtrend_streak,
        recovery_probe_exit_grace_active=True,
        policy=policy,
    )

    assert result.allowed is False
    assert result.reason_code == "recovery_probe_grace_active"


def test_manager_cooling_strong_trend_recovery_upgrades_directly_to_active(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state(
        "600000",
        {
            "quant_status": "cooling",
            "health_score": policy.cooling_threshold - 5,
            "cooling_until": "2026-01-01T00:00:00Z",
            "recent_probe_loss_count": 2,
            "last_recovery_probe_failure_at": "2026-01-02T10:00:00Z",
        },
    )
    signal = {
        "action": "BUY",
        "decision_time": "2026-01-05T10:00:00Z",
        "tech_score": 0.7,
        "context_score": 0.2,
        "price": 12.8,
        "ma20": 12.0,
        "ma20_slope": 0.02,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.8, "fusion_score_delta": 0.1}},
            "portfolio_execution_guard": {
                "status": "strong_buy",
                "buy_tier": "strong_buy",
                "buy_strength_score": 0.9,
                "score_components": {"confirmation_score": 1.0},
                "trend_confirmation": {
                    "ma_stack": True,
                    "ma20_rising": True,
                    "above_ma20_checkpoints": policy.active_upgrade_confirm_checkpoints,
                    "retest_confirmed": False,
                },
            },
            "execution_sizing_plan": {
                "effective_position_pct": 10.0,
                "final_budget": 40000.0,
                "skip_reason": None,
            },
        },
    }

    result = manager.update_after_signal("600000", latest_signal=signal, recent_signals=[signal], position=None)
    state = manager.db.get_quant_universe_state("600000")

    assert result["status_changed"] is True
    assert result["new_status"] == "active"
    assert result["reason_code"] == "cooling_strong_recovered_to_active"
    assert state["quant_status"] == "active"
    assert state["recovery_probe_until"] is None


def test_manager_recovery_probe_expires_before_active_upgrade(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state(
        "600000",
        {
            "quant_status": "trial",
            "health_score": policy.active_upgrade_threshold,
            "recovery_probe_until": "2026-01-05T09:59:59Z",
        },
    )
    signal = {
        "action": "BUY",
        "decision_time": "2026-01-05T10:00:00Z",
        "tech_score": 0.7,
        "context_score": 0.2,
        "price": 12.8,
        "ma20": 12.0,
        "ma20_slope": 0.02,
        "strategy_profile": {
            "portfolio_execution_guard": {
                "status": "strong_buy",
                "buy_tier": "strong_buy",
                "buy_strength_score": 0.9,
                "trend_confirmation": {
                    "ma_stack": True,
                    "ma20_rising": True,
                    "above_ma20_checkpoints": policy.active_upgrade_confirm_checkpoints,
                },
            }
        },
    }

    result = manager.update_after_signal(
        "600000",
        latest_signal=signal,
        recent_signals=[signal] * policy.active_upgrade_confirm_checkpoints,
        position={"quantity": 100},
    )

    assert result["status_changed"] is True
    assert result["new_status"] == "active"


def test_manager_update_after_signal_keeps_cooling_for_executable_weak_buy(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state(
        "600000",
        {
            "quant_status": "cooling",
            "health_score": policy.cooling_threshold - 5,
            "cooling_until": "2026-01-01T00:00:00Z",
        },
    )

    signal = {
        "action": "BUY",
        "decision_time": "2026-01-05T10:00:00Z",
        "tech_score": 0.3,
        "context_score": 0.1,
        "price": 12.8,
        "ma20": 12.0,
        "ma20_slope": 0.02,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.36, "fusion_score_delta": 0.02}},
            "portfolio_execution_guard": {
                "status": "weak_buy",
                "buy_tier": "weak_buy",
                "buy_strength_score": 0.57,
            },
            "execution_sizing_plan": {
                "effective_position_pct": 3.0,
                "final_budget": 12000.0,
                "skip_reason": None,
            },
        },
    }

    result = manager.update_after_signal("600000", latest_signal=signal, recent_signals=[signal], position=None)

    assert result["status_changed"] is False
    assert result["new_status"] == "cooling"


def test_manager_trial_cold_start_health_floor_prevents_early_cooling(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state("600000", {"quant_status": "trial", "health_score": 100.0})
    signal = {
        "stock_code": "600000",
        "stock_name": "浦发银行",
        "action": "HOLD",
        "decision_time": "2026-01-05T10:00:00Z",
        "tech_score": -0.9,
        "context_score": -0.9,
        "price": 9.0,
        "ma20": 10.0,
        "ma20_slope": -0.1,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.05, "fusion_score_delta": -0.2}},
            "portfolio_execution_guard": {"status": "weak_buy", "buy_strength_score": 0.05},
        },
    }

    result = manager.update_after_signal("600000", signal, [signal], None)
    state = manager.db.get_quant_universe_state("600000")

    assert result["new_status"] == "trial"
    assert state["quant_status"] == "trial"
    assert state["health_score"] == policy.trial_cold_start_health_floor
    assert state["snapshot_json"]["health"]["cold_start_min_checkpoints"] == policy.trial_cold_start_min_checkpoints


def test_manager_trial_upgrades_to_active_after_confirmed_trend_window(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state("600000", {"quant_status": "trial", "health_score": 100.0})
    signals = [
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "action": "BUY",
            "decision_time": f"2026-01-05T10:0{idx}:00Z",
            "tech_score": 0.7,
            "context_score": 0.2,
            "price": 12.0,
            "ma20": 11.0,
            "ma20_slope": 0.05,
            "strategy_profile": {
                "explainability": {"fusion_breakdown": {"fusion_score": 0.8, "fusion_score_delta": 0.1}},
                "portfolio_execution_guard": {
                    "status": "strong_buy",
                    "buy_strength_score": 0.75,
                    "score_components": {"confirmation_score": 1.0},
                    "trend_confirmation": {
                        "ma_stack": True,
                        "ma20_rising": True,
                        "above_ma20_checkpoints": policy.active_upgrade_confirm_checkpoints,
                        "retest_confirmed": False,
                    },
                },
            },
        }
        for idx in range(policy.active_upgrade_confirm_checkpoints)
    ]

    result = manager.update_after_signal("600000", signals[0], signals, None)

    assert result["status_changed"] is True
    assert result["old_status"] == "trial"
    assert result["new_status"] == "active"
    assert manager.db.get_quant_universe_state("600000")["quant_status"] == "active"


def test_manager_trial_active_upgrade_clears_stale_downtrend_memory(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state(
        "600000",
        {
            "quant_status": "trial",
            "health_score": 100.0,
            "downtrend_streak": 9,
            "weakening_warning_streak": 7,
        },
    )
    signal = {
        "stock_code": "600000",
        "stock_name": "浦发银行",
        "action": "BUY",
        "decision_time": "2026-01-05T10:00:00Z",
        "tech_score": 0.7,
        "context_score": 0.2,
        "price": 12.0,
        "ma20": 11.0,
        "ma20_slope": 0.05,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.8, "fusion_score_delta": 0.1}},
            "portfolio_execution_guard": {
                "status": "strong_buy",
                "buy_strength_score": 0.75,
                "score_components": {"confirmation_score": 1.0},
                "trend_confirmation": {
                    "ma_stack": True,
                    "ma20_rising": True,
                    "above_ma20_checkpoints": policy.active_upgrade_confirm_checkpoints,
                    "retest_confirmed": False,
                },
            },
        },
    }

    result = manager.update_after_signal("600000", signal, [signal], None)
    state = manager.db.get_quant_universe_state("600000")

    assert result["new_status"] == "active"
    assert state["downtrend_streak"] == 0
    assert state["weakening_warning_streak"] == 0


def test_manager_trial_does_not_upgrade_when_buy_lacks_trend_confirmation(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state("600000", {"quant_status": "trial", "health_score": 100.0})
    signals = [
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "action": "BUY",
            "decision_time": f"2026-01-05T10:0{idx}:00Z",
            "tech_score": 0.7,
            "context_score": 0.2,
            "price": 12.0,
            "ma20": 11.0,
            "ma20_slope": 0.05,
            "strategy_profile": {
                "explainability": {"fusion_breakdown": {"fusion_score": 0.8, "fusion_score_delta": 0.1}},
                "portfolio_execution_guard": {
                    "status": "weak_buy",
                    "buy_strength_score": 0.35,
                    "score_components": {"confirmation_score": 0.0},
                    "trend_confirmation": {
                        "ma_stack": False,
                        "ma20_rising": False,
                        "above_ma20_checkpoints": 0,
                        "retest_confirmed": False,
                    },
                },
            },
        }
        for idx in range(policy.active_upgrade_confirm_checkpoints)
    ]

    result = manager.update_after_signal("600000", signals[0], signals, None)

    assert result["status_changed"] is False
    assert result["new_status"] == "trial"
    assert manager.db.get_quant_universe_state("600000")["quant_status"] == "trial"


def test_manager_trial_upgrades_when_recent_strong_signals_overcome_weak_history(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state("600000", {"quant_status": "trial", "health_score": 20.0})

    strong_signal = {
        "stock_code": "600000",
        "stock_name": "浦发银行",
        "action": "BUY",
        "decision_time": "2026-01-05T10:00:00Z",
        "tech_score": 0.8,
        "context_score": 0.2,
        "price": 12.0,
        "ma20": 11.0,
        "ma20_slope": 0.05,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.8, "fusion_score_delta": 0.1}},
            "portfolio_execution_guard": {
                "status": "strong_buy",
                "buy_strength_score": 0.75,
                "score_components": {"confirmation_score": 1.0},
                "trend_confirmation": {
                    "ma_stack": True,
                    "ma20_rising": True,
                    "above_ma20_checkpoints": policy.active_upgrade_confirm_checkpoints,
                    "retest_confirmed": False,
                },
            },
        },
    }
    weak_signal = {
        **strong_signal,
        "action": "HOLD",
        "tech_score": -0.5,
        "context_score": -0.2,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.1, "fusion_score_delta": -0.1}},
            "portfolio_execution_guard": {
                "status": "weak_buy",
                "buy_strength_score": 0.05,
                "score_components": {"confirmation_score": 0.0},
                "trend_confirmation": {
                    "ma_stack": False,
                    "ma20_rising": False,
                    "above_ma20_checkpoints": 0,
                    "retest_confirmed": False,
                },
            },
        },
    }
    recent_signals = [strong_signal, dict(strong_signal, decision_time="2026-01-05T09:30:00Z")] + [weak_signal] * 8

    result = manager.update_after_signal("600000", strong_signal, recent_signals, None)
    state = manager.db.get_quant_universe_state("600000")

    assert result["status_changed"] is True
    assert result["new_status"] == "active"
    assert state["quant_status"] == "active"
    assert state["snapshot_json"]["health"]["active_upgrade_floor"] == policy.active_upgrade_threshold


def test_manager_trial_upgrades_after_executed_strong_buy_even_with_position(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state("600000", {"quant_status": "trial", "health_score": 20.0})

    strong_signal = {
        "stock_code": "600000",
        "stock_name": "浦发银行",
        "action": "BUY",
        "status": "executed",
        "decision_time": "2026-01-05T10:00:00Z",
        "tech_score": 0.8,
        "context_score": 0.2,
        "price": 12.0,
        "ma20": 11.0,
        "ma20_slope": 0.05,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.8, "fusion_score_delta": 0.1}},
            "portfolio_execution_guard": {
                "status": "strong_buy",
                "buy_strength_score": 0.82,
                "score_components": {"confirmation_score": 1.0},
                "trend_confirmation": {
                    "ma_stack": True,
                    "ma20_rising": True,
                    "above_ma20_checkpoints": policy.active_upgrade_confirm_checkpoints,
                    "retest_confirmed": True,
                },
            },
            "execution_sizing_plan": {
                "buy_tier": "strong_buy",
                "effective_position_pct": 12.5,
                "final_budget": 50000,
            },
        },
    }
    weak_signal = {
        **strong_signal,
        "action": "HOLD",
        "tech_score": -0.5,
        "context_score": -0.2,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.1, "fusion_score_delta": -0.1}},
            "portfolio_execution_guard": {
                "status": "weak_buy",
                "buy_strength_score": 0.05,
                "score_components": {"confirmation_score": 0.0},
                "trend_confirmation": {
                    "ma_stack": False,
                    "ma20_rising": False,
                    "above_ma20_checkpoints": 0,
                    "retest_confirmed": False,
                },
            },
        },
    }
    recent_signals = [
        strong_signal,
        *[weak_signal] * 8,
    ]

    result = manager.update_after_signal(
        "600000",
        strong_signal,
        recent_signals,
        {"stock_code": "600000", "quantity": 100},
    )
    state = manager.db.get_quant_universe_state("600000")

    assert result["status_changed"] is True
    assert result["new_status"] == "active"
    assert state["quant_status"] == "active"
    assert state["snapshot_json"]["health"]["active_upgrade_floor"] == policy.active_upgrade_threshold


def test_manager_trial_position_upgrades_on_confirmed_hold_trend(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state("600000", {"quant_status": "trial", "health_score": 20.0})

    hold_signal = {
        "stock_code": "600000",
        "stock_name": "浦发银行",
        "action": "HOLD",
        "status": "observed",
        "decision_time": "2026-01-06T10:00:00Z",
        "tech_score": 0.65,
        "context_score": 0.15,
        "price": 12.0,
        "ma20": 11.0,
        "ma20_slope": 0.03,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.72, "fusion_score_delta": 0.05}},
            "portfolio_execution_guard": {
                "status": "hold",
                "buy_strength_score": 0.62,
                "score_components": {"confirmation_score": 1.0},
                "trend_confirmation": {
                    "ma_stack": True,
                    "ma20_rising": True,
                    "above_ma20_checkpoints": policy.active_upgrade_confirm_checkpoints,
                    "retest_confirmed": False,
                },
            },
        },
    }

    result = manager.update_after_signal(
        "600000",
        latest_signal=hold_signal,
        recent_signals=[hold_signal] * policy.active_upgrade_confirm_checkpoints,
        position={"stock_code": "600000", "quantity": 100},
    )
    state = manager.db.get_quant_universe_state("600000")

    assert result["status_changed"] is True
    assert result["new_status"] == "active"
    assert state["quant_status"] == "active"


def test_manager_does_not_downgrade_profitable_active_hold_as_downtrend(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="301666", stock_name="大普微-UW", source="manual")
    manager.db.upsert_quant_universe_state(
        "301666",
        {
            "quant_status": "active",
            "health_score": 28.0,
            "downtrend_streak": policy.active_exit_only_downtrend_streak - 1,
            "weakening_warning_streak": policy.warning_to_downtrend_threshold,
            "active_checkpoints": policy.active_min_dwell_checkpoints,
            "active_since": "2026-04-29T02:00:00Z",
        },
    )
    hold_signal = {
        "stock_code": "301666",
        "stock_name": "大普微-UW",
        "action": "HOLD",
        "status": "observed",
        "decision_time": "2026-05-06T02:30:00Z",
        "tech_score": 0.05,
        "context_score": 0.05,
        "price": 381.6,
        "ma20": 301.78,
        "ma20_slope": 6.48,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.62, "fusion_score_delta": -0.02}},
            "portfolio_execution_guard": {
                "status": "hold",
                "buy_strength_score": 0.30,
                "score_components": {"confirmation_score": 0.4},
                "trend_confirmation": {
                    "ma_stack": True,
                    "ma20_rising": True,
                    "above_ma20_checkpoints": 16,
                    "retest_confirmed": False,
                },
            },
        },
    }

    result = manager.update_after_signal(
        "301666",
        latest_signal=hold_signal,
        recent_signals=[hold_signal] * policy.health_score_lookback_checkpoints,
        position={"stock_code": "301666", "quantity": 100, "unrealized_pnl_pct": 44.14},
    )
    state = manager.db.get_quant_universe_state("301666")

    assert result["status_changed"] is False
    assert result["new_status"] == "active"
    assert state["downtrend_streak"] == 0
    assert state["health_score"] >= policy.active_upgrade_threshold


def test_manager_does_not_upgrade_trial_to_active_when_buy_was_not_executed(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="603669", stock_name="灵康药业", source="manual")
    manager.db.upsert_quant_universe_state("603669", {"quant_status": "trial", "health_score": 100.0})
    ignored_buy = {
        "stock_code": "603669",
        "stock_name": "灵康药业",
        "action": "BUY",
        "status": "ignored",
        "decision_time": "2026-01-06T07:00:00Z",
        "tech_score": 0.9,
        "context_score": 0.3,
        "price": 4.73,
        "ma20": 4.67,
        "ma20_slope": 0.01,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.82, "fusion_score_delta": 0.08}},
            "portfolio_execution_guard": {
                "status": "strong_buy",
                "buy_strength_score": 0.86,
                "score_components": {"confirmation_score": 1.0},
                "trend_confirmation": {
                    "ma_stack": True,
                    "ma20_rising": True,
                    "above_ma20_checkpoints": policy.active_upgrade_confirm_checkpoints,
                    "retest_confirmed": True,
                },
            },
        },
    }

    result = manager.update_after_signal(
        "603669",
        latest_signal=ignored_buy,
        recent_signals=[ignored_buy] * policy.active_upgrade_confirm_checkpoints,
        position=None,
    )

    assert result["status_changed"] is False
    assert result["new_status"] == "trial"


def test_manager_update_after_signal_blocks_cooling_restore_until_min_dwell_expires(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state(
        "600000",
        {
            "quant_status": "cooling",
            "health_score": 20,
            "cooling_until": "2026-01-07T02:00:00Z",
        },
    )

    signal = {
        "action": "BUY",
        "decision_time": "2026-01-06T02:00:00Z",
        "tech_score": 0.65,
        "context_score": 0.1,
        "price": 12.8,
        "ma20": 12.0,
        "ma20_slope": 0.02,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.72, "fusion_score_delta": 0.2}},
            "portfolio_execution_guard": {"status": "strong_buy", "buy_strength_score": 0.68},
        },
    }

    result = manager.update_after_signal("600000", latest_signal=signal, recent_signals=[signal], position=None)

    assert result["status_changed"] is False
    assert result["new_status"] == "cooling"
    assert manager.db.get_quant_universe_state("600000")["quant_status"] == "cooling"


def test_manager_update_after_signal_sets_cooling_until_when_entering_cooling(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state(
        "600000",
        {
            "quant_status": "trial",
            "health_score": 100,
            "downtrend_streak": policy.trial_min_dwell_checkpoints - 1,
        },
    )

    signal = {
        "action": "HOLD",
        "decision_time": "2026-01-05T02:00:00Z",
        "tech_score": -0.6,
        "context_score": -0.4,
        "price": 9.5,
        "ma20": 10.0,
        "ma20_slope": -0.03,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.1, "fusion_score_delta": -0.2}},
            "portfolio_execution_guard": {"status": "weak_buy", "buy_strength_score": 0.1},
        },
    }

    result = manager.update_after_signal(
        "600000",
        latest_signal=signal,
        recent_signals=[signal] * policy.trial_min_dwell_checkpoints,
        position=None,
    )

    state = manager.db.get_quant_universe_state("600000")
    assert result["status_changed"] is True
    assert result["new_status"] == "cooling"
    assert state["cooling_until"] == "2026-01-08T02:00:00Z"


def test_manager_update_after_signal_keeps_cooling_soft_gated_on_persistent_downtrend(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state(
        "600000",
        {
            "quant_status": "cooling",
            "health_score": policy.retire_threshold + 5,
            "downtrend_streak": policy.downtrend_cooling_streak - 1,
            "cooling_until": "2026-01-04T00:00:00Z",
        },
    )
    signal = {
        "action": "HOLD",
        "decision_time": "2026-01-05T02:00:00Z",
        "tech_score": -0.9,
        "context_score": -0.9,
        "price": 9.0,
        "ma20": 10.0,
        "ma20_slope": -0.1,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.05, "fusion_score_delta": -0.2}},
            "portfolio_execution_guard": {"status": "weak_buy", "buy_strength_score": 0.05},
        },
    }

    result = manager.update_after_signal("600000", latest_signal=signal, recent_signals=[signal], position=None)
    state = manager.db.get_quant_universe_state("600000")

    assert result["status_changed"] is False
    assert result["new_status"] == "cooling"
    assert state["retired_at"] is None
    assert state["retire_reason"] is None
    assert state["quant_status"] == "cooling"


def test_manager_update_after_signal_blocks_exit_only_on_same_day_as_buy(tmp_path):
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    manager = _manager(tmp_path, policy)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state(
        "600000",
        {
            "quant_status": "trial",
            "health_score": 100,
            "downtrend_streak": policy.exit_only_downtrend_streak - 1,
        },
    )
    buy_signal = {
        "action": "BUY",
        "updated_at": "2026-01-05T02:00:00Z",
        "created_at": "2026-05-10T10:33:31Z",
        "tech_score": 0.7,
        "context_score": 0.0,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.7}},
            "portfolio_execution_guard": {"status": "strong_buy", "buy_strength_score": 0.7},
        },
    }
    weak_signal = {
        "action": "HOLD",
        "decision_time": "2026-01-05T06:30:00Z",
        "tech_score": -0.6,
        "context_score": -0.2,
        "price": 9.5,
        "ma20": 10.0,
        "ma20_slope": -0.04,
        "strategy_profile": {
            "explainability": {"fusion_breakdown": {"fusion_score": 0.1, "fusion_score_delta": -0.2}},
            "portfolio_execution_guard": {"status": "weak_buy", "buy_strength_score": 0.1},
        },
    }

    result = manager.update_after_signal(
        "600000",
        latest_signal=weak_signal,
        recent_signals=[weak_signal, buy_signal],
        position={"quantity": 100},
    )

    assert result["status_changed"] is False
    assert result["new_status"] == "trial"


def test_manager_update_after_signal_freezes_status_when_lifecycle_disabled(tmp_path):
    manager = _manager(tmp_path)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state("600000", {"quant_status": "active", "health_score": 80})
    manager.db.update_quant_universe_settings({"quant_universe_lifecycle_enabled": False})

    result = manager.update_after_signal(
        "600000",
        latest_signal={"action": "SELL", "tech_score": -0.8, "fusion_score": 0.1},
        recent_signals=[{"action": "SELL", "tech_score": -0.8, "context_score": -0.5, "fusion_score": 0.1}],
        position={"quantity": 100},
    )

    assert result["status_changed"] is False
    assert manager.db.get_quant_universe_state("600000")["quant_status"] == "active"


def test_manager_restore_to_trial_raises_structured_error_for_active(tmp_path):
    manager = _manager(tmp_path)
    manager.db.add_watch(stock_code="600000", stock_name="浦发银行", source="manual")
    manager.db.upsert_quant_universe_state("600000", {"quant_status": "active"})

    try:
        manager.restore_to_trial("600000")
    except QuantUniverseDomainError as exc:
        payload = exc.to_dict()
    else:
        raise AssertionError("expected QuantUniverseDomainError")

    assert payload["error_code"] == "invalid_restore_state"
    assert payload["error_message"] == "股票当前处于 active，无需恢复"
