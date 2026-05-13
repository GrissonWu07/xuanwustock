from app.quant_sim.execution_sizing import (
    apply_batch_execution_caps,
    build_execution_sizing_plan,
    default_execution_position_cap_policy,
)
from app.quant_sim.db import QuantSimDB
from app.quant_sim.signal_center_service import SignalCenterService


def test_trial_weak_buy_uses_lifecycle_cap_and_final_budget():
    policy = default_execution_position_cap_policy("aggressive")
    plan = build_execution_sizing_plan(
        signal={
            "position_size_pct": 28.26,
            "stop_loss_pct": 5.0,
            "strategy_profile": {
                "portfolio_execution_guard": {"buy_tier": "weak_buy", "status": "downgraded"},
                "kernel_positioning": {"quality_position_pct": 28.26},
            },
        },
        total_equity=400000,
        available_cash=300000,
        slot_available_cash=300000,
        quant_status="trial",
        policy=policy,
    )

    assert plan["effective_position_pct"] == 3.0
    assert plan["final_budget"] == 12000.0
    assert "lifecycle_cap_pct" in plan["cap_reasons"]
    assert "trial_weak_buy_cap" in plan["cap_reason_codes"]


def test_execution_sizing_uses_resonance_quality_when_kernel_positioning_missing():
    policy = default_execution_position_cap_policy("aggressive")
    plan = build_execution_sizing_plan(
        signal={
            "position_size_pct": 50.0,
            "stop_loss_pct": 5.0,
            "strategy_profile": {
                "portfolio_execution_guard": {"buy_tier": "weak_buy", "status": "downgraded"},
                "explainability": {
                    "resonance": {
                        "rule_hit": "resonance_standard",
                        "quality_adjusted_position_ratio": 0.19508,
                    }
                },
            },
        },
        total_equity=400000,
        available_cash=300000,
        slot_available_cash=300000,
        quant_status="active",
        policy=policy,
    )

    assert plan["kernel_quality_position_pct"] == 19.508
    assert plan["effective_position_pct"] == 6.0


def test_aggressive_active_weak_buy_has_visible_upgrade_cap():
    policy = default_execution_position_cap_policy("aggressive")
    plan = build_execution_sizing_plan(
        signal={
            "position_size_pct": 20.0,
            "stop_loss_pct": 5.0,
            "strategy_profile": {
                "portfolio_execution_guard": {"buy_tier": "weak_buy"},
                "kernel_positioning": {"quality_position_pct": 20.0},
            },
        },
        total_equity=400000,
        available_cash=300000,
        slot_available_cash=300000,
        quant_status="active",
        policy=policy,
        price=10.0,
    )

    assert plan["buy_tier_cap_pct"] == 7.0
    assert plan["effective_position_pct"] == 6.0


def test_account_equity_tier_boundaries_are_mutually_exclusive():
    policy = default_execution_position_cap_policy("aggressive")
    signal = {
        "position_size_pct": 60,
        "stop_loss_pct": 5,
        "strategy_profile": {"portfolio_execution_guard": {"buy_tier": "strong_buy"}},
    }

    assert build_execution_sizing_plan(
        signal=signal,
        total_equity=99999.99,
        available_cash=99999,
        slot_available_cash=99999,
        quant_status="active",
        policy=policy,
    )["account_equity_tier_cap_pct"] == 18.0
    assert build_execution_sizing_plan(
        signal=signal,
        total_equity=100000,
        available_cash=100000,
        slot_available_cash=100000,
        quant_status="active",
        policy=policy,
    )["account_equity_tier_cap_pct"] == 15.0
    assert build_execution_sizing_plan(
        signal=signal,
        total_equity=300000,
        available_cash=300000,
        slot_available_cash=300000,
        quant_status="active",
        policy=policy,
    )["account_equity_tier_cap_pct"] == 12.5
    assert build_execution_sizing_plan(
        signal=signal,
        total_equity=800000,
        available_cash=800000,
        slot_available_cash=800000,
        quant_status="active",
        policy=policy,
    )["account_equity_tier_cap_pct"] == 8.0


def test_weak_buy_skips_when_one_lot_cost_exceeds_budget():
    policy = default_execution_position_cap_policy("stable")
    plan = build_execution_sizing_plan(
        signal={
            "position_size_pct": 20,
            "stop_loss_pct": 5,
            "strategy_profile": {"portfolio_execution_guard": {"buy_tier": "weak_buy"}},
        },
        total_equity=100000,
        available_cash=100000,
        slot_available_cash=100000,
        quant_status="trial",
        policy=policy,
        price=250.0,
        lot_size=100,
    )

    assert plan["final_budget"] < plan["one_lot_cost"]
    assert plan["skip_reason"] == "weak_buy_one_lot_exceeds_risk_budget"


def test_cooling_supplemental_lifecycle_gate_caps_position():
    policy = default_execution_position_cap_policy("aggressive")
    plan = build_execution_sizing_plan(
        signal={
            "position_size_pct": 50.0,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "portfolio_execution_guard": {"buy_tier": "strong_buy", "buy_strength_score": 0.8},
                "kernel_positioning": {"quality_position_pct": 50.0},
                "lifecycle_gate": {
                    "mode": "cooling_supplemental",
                    "size_multiplier": 0.2,
                    "max_position_pct": 3.0,
                    "buy_blocked": False,
                    "requires_strong_confirmation": True,
                },
            },
        },
        total_equity=400000,
        available_cash=300000,
        slot_available_cash=300000,
        quant_status="cooling",
        policy=policy,
        price=10.0,
    )

    assert plan["lifecycle_gate_mode"] == "cooling_supplemental"
    assert plan["lifecycle_gate_adjusted_position_pct"] == 10.0
    assert plan["lifecycle_gate_max_position_pct"] == 3.0
    assert plan["effective_position_pct"] == 3.0
    assert plan["final_budget"] == 12000.0
    assert "lifecycle_gate_max_position_pct" in plan["cap_reasons"]


def test_exit_only_lifecycle_gate_blocks_buy():
    policy = default_execution_position_cap_policy("aggressive")
    plan = build_execution_sizing_plan(
        signal={
            "position_size_pct": 20.0,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "portfolio_execution_guard": {"buy_tier": "strong_buy"},
                "kernel_positioning": {"quality_position_pct": 20.0},
                "lifecycle_gate": {"mode": "exit_only", "buy_blocked": True, "size_multiplier": 0.0, "max_position_pct": 0.0},
            },
        },
        total_equity=400000,
        available_cash=300000,
        slot_available_cash=300000,
        quant_status="exit_only",
        policy=policy,
        price=10.0,
    )

    assert plan["effective_position_pct"] == 0.0
    assert plan["final_budget"] == 0.0
    assert plan["skip_reason"] == "exit_only_buy_blocked"


def test_create_signal_attaches_execution_sizing_plan(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=400000)
    db.upsert_quant_universe_state("000001", {"stock_name": "平安银行", "quant_status": "trial", "health_score": 100})
    service = SignalCenterService(db_file=db_path)

    signal = service.create_signal(
        {"stock_code": "000001", "stock_name": "平安银行", "latest_price": 10.0},
        {
            "action": "BUY",
            "confidence": 80,
            "reasoning": "test",
            "position_size_pct": 28.26,
            "stop_loss_pct": 5,
            "decision_type": "dual_track_weighted_buy",
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "kernel_positioning": {"quality_position_pct": 28.26, "rule_hit": "resonance_standard"},
                "portfolio_execution_guard_policy": {"enabled": False},
                "portfolio_execution_guard": {"status": "downgraded", "buy_tier": "weak_buy", "buy_tier_label": "弱买"},
            },
        },
        notify=False,
    )

    profile = signal["strategy_profile"]
    assert profile["kernel_positioning"]["quality_position_pct"] == 28.26
    assert profile["execution_sizing_plan"]["buy_tier"] == "weak_buy"
    assert profile["execution_sizing_plan"]["effective_position_pct"] == 3.0
    assert signal["position_size_pct"] == profile["execution_sizing_plan"]["effective_position_pct"]


def test_create_signal_copies_candidate_lifecycle_gate_into_profile(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=400000)
    db.upsert_quant_universe_state("000001", {"stock_name": "平安银行", "quant_status": "cooling", "health_score": 35})
    service = SignalCenterService(db_file=db_path)

    signal = service.create_signal(
        {
            "stock_code": "000001",
            "stock_name": "平安银行",
            "latest_price": 10.0,
            "lifecycle_gate": {
                "mode": "cooling_supplemental",
                "size_multiplier": 0.2,
                "max_position_pct": 3.0,
                "buy_blocked": False,
            },
        },
        {
            "action": "BUY",
            "confidence": 80,
            "reasoning": "test",
            "position_size_pct": 50,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "kernel_positioning": {"quality_position_pct": 50.0},
                "portfolio_execution_guard": {"buy_tier": "strong_buy", "buy_strength_score": 0.8},
            },
        },
        notify=False,
    )

    profile = signal["strategy_profile"]
    assert profile["lifecycle_gate"]["mode"] == "cooling_supplemental"
    assert profile["execution_sizing_plan"]["effective_position_pct"] == 3.0


def test_trial_normal_buy_with_confirmed_trend_uses_active_like_sizing(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=400000)
    db.upsert_quant_universe_state("000001", {"stock_name": "平安银行", "quant_status": "trial", "health_score": 42})
    service = SignalCenterService(db_file=db_path)

    signal = service.create_signal(
        {
            "stock_code": "000001",
            "stock_name": "平安银行",
            "latest_price": 10.0,
            "lifecycle_gate": {
                "mode": "trial_light",
                "buy_threshold_delta": 0.03,
                "size_multiplier": 0.5,
                "max_position_pct": 12.5,
                "buy_blocked": False,
            },
        },
        {
            "action": "BUY",
            "confidence": 80,
            "reasoning": "test",
            "position_size_pct": 30,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "kernel_positioning": {"quality_position_pct": 30.0},
                "portfolio_execution_guard_policy": {"enabled": False},
                "portfolio_execution_guard": {
                    "buy_tier": "normal_buy",
                    "buy_strength_score": 0.72,
                    "trend_confirmation": {
                        "ma_stack": False,
                        "ma20_rising": True,
                        "above_ma20_checkpoints": 3,
                        "retest_confirmed": False,
                    },
                },
            },
        },
        notify=False,
    )

    profile = signal["strategy_profile"]
    assert profile["lifecycle_gate"]["mode"] == "trial_confirmed"
    assert profile["execution_sizing_plan"]["lifecycle_cap_pct"] == 9.0
    assert profile["execution_sizing_plan"]["quant_status_for_portfolio_budget"] == "trial"
    assert profile["execution_sizing_plan"]["effective_position_pct"] == 9.0
    assert signal["position_size_pct"] == 9.0


def test_recovery_probe_strong_confirmation_lifts_probe_cap(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=400000)
    db.upsert_quant_universe_state("000001", {"stock_name": "平安银行", "quant_status": "trial", "health_score": 60})
    service = SignalCenterService(db_file=db_path)

    signal = service.create_signal(
        {
            "stock_code": "000001",
            "stock_name": "平安银行",
            "latest_price": 10.0,
                "lifecycle_gate": {
                    "mode": "recovery_probe",
                    "buy_threshold_delta": 0.08,
                    "size_multiplier": 0.45,
                    "max_position_pct": 6.0,
                    "confirmed_max_position_pct": 10.0,
                    "recent_probe_loss_count": 0,
                    "requires_strong_confirmation": True,
                    "buy_blocked": False,
                },
        },
        {
            "action": "BUY",
            "confidence": 90,
            "reasoning": "recovery probe",
            "position_size_pct": 30,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "kernel_positioning": {"quality_position_pct": 30.0},
                "portfolio_execution_guard_policy": {"enabled": False},
                "portfolio_execution_guard": {
                    "buy_tier": "strong_buy",
                    "buy_strength_score": 0.9,
                    "trend_confirmation": {
                        "ma_stack": True,
                        "ma20_rising": True,
                        "above_ma20_checkpoints": 3,
                        "retest_confirmed": False,
                    },
                },
            },
        },
        notify=False,
    )

    profile = signal["strategy_profile"]
    assert profile["lifecycle_gate"]["mode"] == "recovery_probe_confirmed"
    assert profile["execution_sizing_plan"]["lifecycle_gate_max_position_pct"] == 10.0
    assert profile["execution_sizing_plan"]["effective_position_pct"] == 10.0
    assert signal["position_size_pct"] == 10.0


def test_recovery_probe_confirmed_ignores_old_probe_multiplier():
    policy = default_execution_position_cap_policy("aggressive")
    plan = build_execution_sizing_plan(
        signal={
            "position_size_pct": 30.0,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "kernel_positioning": {"quality_position_pct": 30.0},
                "portfolio_execution_guard": {"buy_tier": "strong_buy"},
                "lifecycle_gate": {
                    "mode": "recovery_probe_confirmed",
                    "size_multiplier": 0.25,
                    "max_position_pct": 10.0,
                },
            },
        },
        total_equity=400000,
        available_cash=300000,
        slot_available_cash=300000,
        quant_status="trial",
        policy=policy,
        price=10.0,
    )

    assert plan["lifecycle_gate_size_multiplier"] == 1.0
    assert plan["lifecycle_gate_adjusted_position_pct"] == 30.0
    assert plan["lifecycle_gate_max_position_pct"] == 10.0
    assert plan["effective_position_pct"] == 10.0
    assert plan["quant_status_for_portfolio_budget"] == "trial"


def test_recovery_probe_recent_failure_keeps_retry_cap(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=400000)
    db.upsert_quant_universe_state("000001", {"stock_name": "平安银行", "quant_status": "trial", "health_score": 60})
    service = SignalCenterService(db_file=db_path)

    signal = service.create_signal(
        {
            "stock_code": "000001",
            "stock_name": "平安银行",
            "latest_price": 10.0,
            "lifecycle_gate": {
                "mode": "recovery_probe_retry",
                "buy_threshold_delta": 0.12,
                "size_multiplier": 0.20,
                "max_position_pct": 2.5,
                "confirmed_max_position_pct": 10.0,
                "recent_probe_loss_count": 1,
                "probe_failure_reason": "holding_downtrend_exit_only",
                "requires_strong_confirmation": True,
                "buy_blocked": False,
            },
        },
        {
            "action": "BUY",
            "confidence": 90,
            "reasoning": "recovery probe retry",
            "position_size_pct": 30,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "kernel_positioning": {"quality_position_pct": 30.0},
                "portfolio_execution_guard_policy": {"enabled": False},
                "portfolio_execution_guard": {
                    "buy_tier": "strong_buy",
                    "buy_strength_score": 0.9,
                    "trend_confirmation": {
                        "ma_stack": True,
                        "ma20_rising": True,
                        "above_ma20_checkpoints": 3,
                        "retest_confirmed": False,
                    },
                },
            },
        },
        notify=False,
    )

    profile = signal["strategy_profile"]
    assert profile["lifecycle_gate"]["mode"] == "recovery_probe_retry"
    assert profile["execution_sizing_plan"]["lifecycle_gate_max_position_pct"] == 2.5
    assert profile["execution_sizing_plan"]["effective_position_pct"] == 2.5
    assert signal["position_size_pct"] == 2.5


def test_trial_weak_buy_keeps_trial_light_sizing(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=400000)
    db.upsert_quant_universe_state("000001", {"stock_name": "平安银行", "quant_status": "trial", "health_score": 42})
    service = SignalCenterService(db_file=db_path)

    signal = service.create_signal(
        {
            "stock_code": "000001",
            "stock_name": "平安银行",
            "latest_price": 10.0,
            "lifecycle_gate": {
                "mode": "trial_light",
                "buy_threshold_delta": 0.03,
                "size_multiplier": 0.5,
                "max_position_pct": 12.5,
                "buy_blocked": False,
            },
        },
        {
            "action": "BUY",
            "confidence": 80,
            "reasoning": "test",
            "position_size_pct": 30,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "kernel_positioning": {"quality_position_pct": 30.0},
                "portfolio_execution_guard_policy": {"enabled": False},
                "portfolio_execution_guard": {
                    "buy_tier": "weak_buy",
                    "buy_strength_score": 0.62,
                    "trend_confirmation": {
                        "ma_stack": True,
                        "ma20_rising": True,
                        "above_ma20_checkpoints": 3,
                        "retest_confirmed": False,
                    },
                },
            },
        },
        notify=False,
    )

    profile = signal["strategy_profile"]
    assert profile["lifecycle_gate"]["mode"] == "trial_light"
    assert profile["execution_sizing_plan"]["effective_position_pct"] == 3.0


def test_create_signal_blocks_cooling_buy_without_strong_lifecycle_confirmation(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=400000)
    db.upsert_quant_universe_state("000001", {"stock_name": "平安银行", "quant_status": "cooling", "health_score": 35})
    service = SignalCenterService(db_file=db_path)

    signal = service.create_signal(
        {
            "stock_code": "000001",
            "stock_name": "平安银行",
            "latest_price": 10.0,
            "lifecycle_gate": {
                "mode": "cooling_supplemental",
                "size_multiplier": 0.2,
                "max_position_pct": 3.0,
                "buy_threshold_delta": 0.12,
                "requires_strong_confirmation": True,
                "buy_blocked": False,
            },
        },
        {
            "action": "BUY",
            "confidence": 80,
            "reasoning": "test",
            "position_size_pct": 50,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "kernel_positioning": {"quality_position_pct": 50.0},
                "portfolio_execution_guard": {
                    "buy_tier": "normal_buy",
                    "buy_strength_score": 0.50,
                    "trend_confirmation": {"ma_stack": False, "retest_confirmed": False, "ma20_rising": True, "above_ma20_checkpoints": 1},
                    "score_components": {"confirmation_score": 0.3},
                },
            },
        },
        notify=False,
    )

    assert signal["action"] == "HOLD"
    assert signal["decision_type"] == "lifecycle_gate_blocked"


def test_create_signal_blocks_cooling_weak_buy_even_with_trend_confirmation(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=400000)
    db.upsert_quant_universe_state("600000", {"stock_name": "浦发银行", "quant_status": "cooling", "health_score": 35})
    service = SignalCenterService(db_file=db_path)

    signal = service.create_signal(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "latest_price": 10.0,
            "lifecycle_gate": {
                "mode": "cooling_supplemental",
                "requires_strong_confirmation": True,
                "buy_threshold_delta": 0.12,
                "size_multiplier": 0.2,
                "max_position_pct": 3.0,
            },
        },
        {
            "action": "BUY",
            "confidence": 80,
            "reasoning": "test",
            "position_size_pct": 50.0,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "kernel_positioning": {"quality_position_pct": 50.0},
                "portfolio_execution_guard": {
                    "buy_tier": "weak_buy",
                    "buy_strength_score": 0.7,
                    "trend_confirmation": {"ma_stack": True},
                },
            },
        },
        notify=False,
    )

    assert signal["action"] == "HOLD"
    assert signal["decision_type"] == "lifecycle_gate_blocked"


def test_cooling_supplemental_strong_confirmation_rejects_weak_tier():
    assert SignalCenterService._lifecycle_gate_has_strong_confirmation(
        {
            "portfolio_execution_guard": {
                "buy_tier": "weak_buy",
                "buy_strength_score": 0.9,
                "trend_confirmation": {"ma_stack": True},
            }
        },
        {"mode": "cooling_supplemental", "buy_threshold_delta": 0.12},
    ) is False


def test_cooling_supplemental_strong_confirmation_accepts_normal_tier():
    assert SignalCenterService._lifecycle_gate_has_strong_confirmation(
        {
            "portfolio_execution_guard": {
                "buy_tier": "normal_buy",
                "buy_strength_score": 0.71,
                "trend_confirmation": {"ma_stack": True},
            }
        },
        {"mode": "cooling_supplemental", "buy_threshold_delta": 0.12},
    ) is True


def test_create_signal_backfills_kernel_positioning_from_resonance(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=400000)
    db.upsert_quant_universe_state("000001", {"stock_name": "平安银行", "quant_status": "active", "health_score": 100})
    service = SignalCenterService(db_file=db_path)

    signal = service.create_signal(
        {"stock_code": "000001", "stock_name": "平安银行", "latest_price": 10.0},
        {
            "action": "BUY",
            "confidence": 80,
            "reasoning": "test",
            "position_size_pct": 50.0,
            "stop_loss_pct": 5,
            "decision_type": "dual_track_weighted_buy",
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "explainability": {
                    "resonance": {
                        "rule_hit": "resonance_standard",
                        "signal_quality_score": 0.227515,
                        "quality_adjusted_position_ratio": 0.19508,
                    }
                },
                "portfolio_execution_guard_policy": {"enabled": False},
                "portfolio_execution_guard": {"status": "downgraded", "buy_tier": "weak_buy", "buy_tier_label": "弱买"},
            },
        },
        notify=False,
    )

    profile = signal["strategy_profile"]
    assert profile["kernel_positioning"]["quality_position_pct"] == 19.508
    assert profile["execution_sizing_plan"]["kernel_quality_position_pct"] == 19.508
    assert signal["position_size_pct"] == 6.0


def test_create_signal_backfills_non_resonance_positioning_from_buy_strength(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=400000)
    db.upsert_quant_universe_state("000001", {"stock_name": "平安银行", "quant_status": "active", "health_score": 100})
    service = SignalCenterService(db_file=db_path)

    signal = service.create_signal(
        {"stock_code": "000001", "stock_name": "平安银行", "latest_price": 10.0},
        {
            "action": "BUY",
            "confidence": 80,
            "reasoning": "test",
            "position_size_pct": 50.0,
            "stop_loss_pct": 5,
            "decision_type": "dual_track_weighted_buy",
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "portfolio_execution_guard_policy": {"enabled": False},
                "portfolio_execution_guard": {
                    "status": "downgraded",
                    "buy_tier": "weak_buy",
                    "buy_tier_label": "弱买",
                    "buy_strength_score": 0.236748,
                },
            },
        },
        notify=False,
    )

    profile = signal["strategy_profile"]
    assert profile["kernel_positioning"]["rule_hit"] == "non_resonance_guard_quality"
    assert profile["kernel_positioning"]["quality_position_pct"] == 11.8374
    assert profile["execution_sizing_plan"]["kernel_quality_position_pct"] == 11.8374
    assert signal["position_size_pct"] == 6.0


def test_create_signal_keeps_fallback_position_when_guard_has_no_buy_tier(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=400000)
    db.upsert_quant_universe_state("000001", {"stock_name": "平安银行", "quant_status": "active", "health_score": 100})
    service = SignalCenterService(db_file=db_path)

    signal = service.create_signal(
        {"stock_code": "000001", "stock_name": "平安银行", "latest_price": 10.0},
        {
            "action": "BUY",
            "confidence": 80,
            "reasoning": "test",
            "position_size_pct": 60.0,
            "stop_loss_pct": 5,
            "decision_type": "test",
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "portfolio_execution_guard_policy": {"enabled": False},
                "portfolio_execution_guard": {"status": "passed", "buy_tier": "none", "buy_strength_score": 0.0},
            },
        },
        notify=False,
    )

    profile = signal["strategy_profile"]
    assert "kernel_positioning" not in profile
    assert profile["execution_sizing_plan"]["kernel_quality_position_pct"] == 60.0
    assert signal["position_size_pct"] > 0


def _buy_signal(
    signal_id: int,
    tier: str,
    final_budget: float,
    risk_pct: float = 0.30,
    status: str = "trial",
    effective_position_pct: float = 3.0,
    stop_loss_pct: float = 5.0,
) -> dict:
    return {
        "id": signal_id,
        "stock_code": f"000{signal_id:03d}",
        "stock_name": f"股票{signal_id}",
        "action": "BUY",
        "confidence": 80 - signal_id,
        "position_size_pct": effective_position_pct,
        "stop_loss_pct": stop_loss_pct,
        "strategy_profile": {
            "portfolio_execution_guard": {
                "buy_tier": tier,
                "buy_strength_score": 0.6 - signal_id * 0.01,
            },
            "execution_sizing_plan": {
                "buy_tier": tier,
                "final_budget": final_budget,
                "risk_budget_pct": risk_pct,
                "effective_position_pct": effective_position_pct,
                "expected_stop_loss_pct": stop_loss_pct,
            },
            "quant_status": status,
        },
    }


def test_batch_caps_skip_trial_buys_after_checkpoint_risk_budget():
    policy = default_execution_position_cap_policy("aggressive")
    signals = [
        _buy_signal(1, "weak_buy", 6000, 0.30, effective_position_pct=6.0),
        _buy_signal(2, "weak_buy", 6000, 0.30, effective_position_pct=6.0),
        _buy_signal(3, "weak_buy", 6000, 0.30, effective_position_pct=6.0),
    ]

    result = apply_batch_execution_caps(
        signals=signals,
        total_equity=100000,
        existing_trial_market_value=0,
        existing_weak_buy_market_value=0,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    allowed = [item for item in result if item["allowed"]]
    skipped = [item for item in result if not item["allowed"]]
    assert len(allowed) == 2
    assert skipped[0]["reason_code"] == "portfolio_trial_risk_budget_exhausted"


def test_batch_caps_use_actual_execution_risk_not_nominal_tier_budget():
    policy = default_execution_position_cap_policy("aggressive")
    signals = [
        _buy_signal(1, "strong_buy", 3000, 0.65, effective_position_pct=3.0, stop_loss_pct=5.0),
        _buy_signal(2, "weak_buy", 3000, 0.30, effective_position_pct=3.0, stop_loss_pct=5.0),
    ]

    result = apply_batch_execution_caps(
        signals=signals,
        total_equity=100000,
        existing_trial_market_value=0,
        existing_weak_buy_market_value=0,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    assert [item["allowed"] for item in result] == [True, True]
    assert [item["batch_risk_pct"] for item in result] == [0.15, 0.15]


def test_batch_caps_skip_when_weak_buy_exposure_already_full():
    policy = default_execution_position_cap_policy("stable")
    signals = [_buy_signal(1, "weak_buy", 8000, 0.20)]

    result = apply_batch_execution_caps(
        signals=signals,
        total_equity=200000,
        existing_trial_market_value=0,
        existing_weak_buy_market_value=200000 * 0.08,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    assert result[0]["allowed"] is False
    assert result[0]["reason_code"] == "weak_buy_exposure_cap_hit"


def test_batch_caps_clip_strong_buy_to_remaining_trial_exposure_before_weaker_signal():
    policy = default_execution_position_cap_policy("aggressive")
    signals = [
        _buy_signal(1, "weak_buy", 8000, 0.30, effective_position_pct=2.0),
        _buy_signal(2, "strong_buy", 30000, 0.65, effective_position_pct=7.5),
    ]

    result = apply_batch_execution_caps(
        signals=signals,
        total_equity=400000,
        existing_trial_market_value=70000,
        existing_weak_buy_market_value=0,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    strong = next(item for item in result if item["signal"]["id"] == 2)
    weak = next(item for item in result if item["signal"]["id"] == 1)
    strong_plan = strong["signal"]["strategy_profile"]["execution_sizing_plan"]

    assert strong["allowed"] is True
    assert strong["reason_code"] == ""
    assert strong_plan["final_budget"] == 10000
    assert strong_plan["batch_cap_adjustment"]["reason_code"] == "trial_exposure_cap_applied"
    assert strong_plan["effective_position_pct"] == 2.5
    assert strong["batch_risk_pct"] == 0.125
    assert weak["allowed"] is False
    assert weak["reason_code"] == "trial_exposure_cap_hit"
