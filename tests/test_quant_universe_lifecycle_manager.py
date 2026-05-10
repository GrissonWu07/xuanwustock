from datetime import datetime, timedelta, timezone

from app.quant_sim.quant_universe_lifecycle import (
    AutoEntryMode,
    HealthInputs,
    ManualOverride,
    QuantUniverseDomainError,
    QuantUniverseManager,
    QuantStatus,
    QuantUniverseLifecyclePolicy,
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
            "trial_min_dwell_checkpoints": 3,
            "cooling_min_dwell_days": 2,
            "retired_min_dwell_days": 7,
            "cooling_review_interval_minutes": 30,
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
            "trial_min_dwell_checkpoints": 4,
            "cooling_min_dwell_days": 3,
            "retired_min_dwell_days": 10,
            "cooling_review_interval_minutes": 60,
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
            "trial_min_dwell_checkpoints": 5,
            "cooling_min_dwell_days": 4,
            "retired_min_dwell_days": 14,
            "cooling_review_interval_minutes": 90,
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
    assert result["candidate_score"] == 0.86
    assert result["breakdown"]["multi_source_bonus"] == 1.0


def test_live_quant_drill_candidate_score_does_not_use_source_count_bonus():
    policy = QuantUniverseLifecyclePolicy.stable_defaults()
    single_source = [
        {"source_type": "discover", "source_score": 0.8, "confidence": 0.7, "trend": "up"},
    ]
    multi_source = [
        {"source_type": "discover", "source_score": 0.8, "confidence": 0.7, "trend": "up"},
        {"source_type": "research", "source_score": 0.8, "confidence": 0.7, "trend": "up"},
    ]

    single_result = calculate_candidate_score(single_source, {"is_liquid": True}, policy, drill_mode=True)
    multi_result = calculate_candidate_score(multi_source, {"is_liquid": True}, policy, drill_mode=True)

    assert single_result["candidate_score"] == multi_result["candidate_score"]
    assert single_result["breakdown"]["multi_source_bonus"] == 0.0
    assert multi_result["breakdown"]["multi_source_bonus"] == 0.0


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
    assert cooling["decision"] == "skipped"
    assert cooling["skip_reason"] == "cooling_blocked"


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
        {"stock_code": "600000", "source_type": "research", "source_score": 0.98, "confidence": 0.95, "trend": "up"}
    )

    assert weak["decision"] == "skipped"
    assert weak["skip_reason"] == "retired_reentry_below_threshold"
    assert strong["decision"] == "promoted_to_trial"


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
