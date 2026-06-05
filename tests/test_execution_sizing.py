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


def test_aggressive_weak_buy_requires_meaningful_execution_strength():
    policy = default_execution_position_cap_policy("aggressive")

    assert policy["weak_buy_min_execution_strength"] == 0.45


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


def test_trial_guarded_normal_buy_keeps_guarded_sizing(tmp_path):
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
                "mode": "trial_guarded",
                "buy_threshold_delta": 0.08,
                "size_multiplier": 0.35,
                "max_position_pct": 4.0,
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
    assert profile["lifecycle_gate"]["mode"] == "trial_guarded"
    assert profile["execution_sizing_plan"]["lifecycle_gate_mode"] == "trial_guarded"
    assert profile["execution_sizing_plan"]["lifecycle_gate_max_position_pct"] == 4.0
    assert profile["execution_sizing_plan"]["effective_position_pct"] == 4.0
    assert signal["position_size_pct"] == 4.0


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
                            "above_ma20_checkpoints": 8,
                            "retest_confirmed": False,
                            "rsi": 62,
                            "recent_5d_return": 0.02,
                            "volume_confirmed": "strong",
                        },
                        "score_components": {
                            "edge_strength": 0.78,
                            "confirmation_score": 0.95,
                            "volume_score": 1.0,
                            "risk_penalty": 0.0,
                        },
                    },
                },
            },
        notify=False,
    )

    profile = signal["strategy_profile"]
    assert profile["lifecycle_gate"]["mode"] == "strong_recovery_confirmed"
    assert profile["execution_sizing_plan"]["lifecycle_gate_max_position_pct"] == 3.0
    assert profile["execution_sizing_plan"]["effective_position_pct"] == 3.0
    assert signal["position_size_pct"] == 3.0


def test_overextended_strong_recovery_probe_keeps_reduced_probe_cap(tmp_path):
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
            "reasoning": "overextended recovery probe",
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
                        "above_ma20_checkpoints": 8,
                        "retest_confirmed": False,
                        "recent_5d_return": 0.06,
                        "volume_ratio": 1.8,
                    },
                },
            },
        },
        notify=False,
    )

    profile = signal["strategy_profile"]
    assert profile["lifecycle_gate"]["mode"] == "recovery_probe_quality_limited"
    assert profile["lifecycle_gate"]["reason_code"] == "strong_recovery_overextended_without_retest"
    assert profile["execution_sizing_plan"]["lifecycle_gate_max_position_pct"] == 3.0
    assert profile["execution_sizing_plan"]["effective_position_pct"] == 3.0
    assert signal["position_size_pct"] == 3.0


def test_low_quality_strong_recovery_probe_keeps_reduced_probe_cap(tmp_path):
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
            "confidence": 88,
            "reasoning": "low quality strong recovery probe",
            "position_size_pct": 30,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "kernel_positioning": {"quality_position_pct": 30.0},
                "portfolio_execution_guard_policy": {"enabled": False},
                "portfolio_execution_guard": {
                    "buy_tier": "strong_buy",
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
    assert profile["lifecycle_gate"]["mode"] == "recovery_probe_quality_limited"
    assert profile["lifecycle_gate"]["reason_code"] == "strong_recovery_quality_not_confirmed"
    assert profile["execution_sizing_plan"]["effective_position_pct"] == 3.0


def test_small_account_strong_recovery_keeps_trial_strong_cap():
    policy = default_execution_position_cap_policy("aggressive")
    plan = build_execution_sizing_plan(
        signal={
            "position_size_pct": 30.0,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "kernel_positioning": {"quality_position_pct": 30.0},
                "portfolio_execution_guard": {"buy_tier": "strong_buy"},
                "lifecycle_gate": {
                    "mode": "strong_recovery_confirmed",
                    "size_multiplier": 1.0,
                    "max_position_pct": None,
                },
            },
        },
        total_equity=100000,
        available_cash=100000,
        slot_available_cash=100000,
        quant_status="trial",
        policy=policy,
        price=16.93,
    )

    assert plan["effective_position_pct"] == 10.0
    assert "trial_strong_buy_cap" in plan["cap_reason_codes"]


def test_recovery_probe_normal_confirmation_lifts_probe_cap(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=100000)
    db.upsert_quant_universe_state("301369", {"stock_name": "联动科技", "quant_status": "trial", "health_score": 60})
    service = SignalCenterService(db_file=db_path)

    signal = service.create_signal(
        {
            "stock_code": "301369",
            "stock_name": "联动科技",
            "latest_price": 136.52,
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
            "confidence": 82,
            "reasoning": "confirmed recovery probe normal buy",
            "position_size_pct": 30,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "kernel_positioning": {"quality_position_pct": 30.0},
                "portfolio_execution_guard_policy": {"enabled": False},
                "portfolio_execution_guard": {
                    "buy_tier": "normal_buy",
                    "buy_strength_score": 0.64,
                    "trend_confirmation": {
                        "ma_stack": True,
                        "ma20_rising": True,
                        "above_ma20_checkpoints": 4,
                        "retest_confirmed": False,
                    },
                    "score_components": {"confirmation_score": 0.55},
                },
            },
        },
        notify=False,
    )

    profile = signal["strategy_profile"]
    assert profile["lifecycle_gate"]["mode"] == "recovery_probe_confirmed"
    assert profile["execution_sizing_plan"]["lifecycle_gate_max_position_pct"] == 6.0
    assert profile["execution_sizing_plan"]["effective_position_pct"] == 6.0
    assert signal["position_size_pct"] == 6.0


def test_recovery_probe_normal_confirmation_with_quality_uses_intermediate_cap(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=100000)
    db.upsert_quant_universe_state("301369", {"stock_name": "联动科技", "quant_status": "trial", "health_score": 60})
    service = SignalCenterService(db_file=db_path)

    signal = service.create_signal(
        {
            "stock_code": "301369",
            "stock_name": "联动科技",
            "latest_price": 136.52,
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
            "confidence": 82,
            "reasoning": "quality confirmed recovery probe normal buy",
            "position_size_pct": 30,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "kernel_positioning": {"quality_position_pct": 30.0},
                "portfolio_execution_guard_policy": {"enabled": False},
                "portfolio_execution_guard": {
                    "buy_tier": "normal_buy",
                    "buy_strength_score": 0.73,
                    "trend_confirmation": {
                        "ma_stack": True,
                        "ma20_rising": True,
                        "above_ma20_checkpoints": 4,
                        "retest_confirmed": False,
                        "recent_5d_return": 0.02,
                        "ma20_distance_pct": 1.2,
                    },
                    "score_components": {"confirmation_score": 0.72, "volume_score": 1.0},
                },
            },
        },
        notify=False,
    )

    profile = signal["strategy_profile"]
    plan = profile["execution_sizing_plan"]
    assert profile["lifecycle_gate"]["mode"] == "recovery_probe_confirmed"
    assert plan["recovery_probe_confirmed_cap_source"] == "quality_confirmed"
    assert plan["recovery_probe_confirmed_quality"] is True
    assert plan["lifecycle_gate_max_position_pct"] == 8.0
    assert plan["effective_position_pct"] == 8.0
    assert signal["position_size_pct"] == 8.0


def test_recovery_probe_normal_confirmation_requires_strong_volume_for_quality_cap(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=100000)
    db.upsert_quant_universe_state("301369", {"stock_name": "联动科技", "quant_status": "trial", "health_score": 60})
    service = SignalCenterService(db_file=db_path)

    signal = service.create_signal(
        {
            "stock_code": "301369",
            "stock_name": "联动科技",
            "latest_price": 136.52,
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
            "confidence": 82,
            "reasoning": "normal volume recovery probe normal buy",
            "position_size_pct": 30,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "kernel_positioning": {"quality_position_pct": 30.0},
                "portfolio_execution_guard_policy": {"enabled": False},
                "portfolio_execution_guard": {
                    "buy_tier": "normal_buy",
                    "buy_strength_score": 0.73,
                    "trend_confirmation": {
                        "ma_stack": True,
                        "ma20_rising": True,
                        "above_ma20_checkpoints": 8,
                        "retest_confirmed": False,
                        "recent_5d_return": 0.02,
                        "ma20_distance_pct": 1.2,
                    },
                    "score_components": {"confirmation_score": 0.72, "volume_score": 0.6},
                },
            },
        },
        notify=False,
    )

    plan = signal["strategy_profile"]["execution_sizing_plan"]
    assert plan["recovery_probe_confirmed_cap_source"] == "base"
    assert plan["recovery_probe_confirmed_quality"] is False
    assert plan["effective_position_pct"] == 6.0


def test_recovery_probe_normal_confirmation_overextended_keeps_base_cap(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=100000)
    db.upsert_quant_universe_state("301081", {"stock_name": "严牌股份", "quant_status": "trial", "health_score": 60})
    service = SignalCenterService(db_file=db_path)

    signal = service.create_signal(
        {
            "stock_code": "301081",
            "stock_name": "严牌股份",
            "latest_price": 15.76,
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
            "confidence": 82,
            "reasoning": "overextended recovery probe normal buy",
            "position_size_pct": 30,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "kernel_positioning": {"quality_position_pct": 30.0},
                "portfolio_execution_guard_policy": {"enabled": False},
                "portfolio_execution_guard": {
                    "buy_tier": "normal_buy",
                    "buy_strength_score": 0.73,
                    "trend_confirmation": {
                        "ma_stack": True,
                        "ma20_rising": True,
                        "above_ma20_checkpoints": 4,
                        "retest_confirmed": True,
                        "recent_5d_return": 0.048,
                    },
                    "score_components": {"confirmation_score": 0.72},
                },
            },
        },
        notify=False,
    )

    plan = signal["strategy_profile"]["execution_sizing_plan"]
    assert plan["recovery_probe_confirmed_cap_source"] == "base"
    assert plan["recovery_probe_confirmed_quality"] is False
    assert plan["effective_position_pct"] == 6.0
    assert signal["position_size_pct"] == 6.0


def test_recovery_probe_normal_confirmation_with_good_outcome_lifts_full_cap(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=100000)
    db.upsert_quant_universe_state("301369", {"stock_name": "联动科技", "quant_status": "trial", "health_score": 60})
    service = SignalCenterService(db_file=db_path)

    signal = service.create_signal(
        {
            "stock_code": "301369",
            "stock_name": "联动科技",
            "latest_price": 136.52,
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
            "confidence": 82,
            "reasoning": "confirmed recovery probe normal buy with positive outcome",
            "position_size_pct": 36,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "kernel_positioning": {"quality_position_pct": 36.0},
                "portfolio_execution_guard_policy": {"enabled": False},
                "portfolio_execution_guard": {
                    "buy_tier": "normal_buy",
                    "buy_strength_score": 0.73,
                    "trend_confirmation": {
                        "ma_stack": True,
                        "ma20_rising": True,
                        "above_ma20_checkpoints": 4,
                        "retest_confirmed": False,
                    },
                    "score_components": {"confirmation_score": 0.72},
                },
                "outcome_feedback": {
                    "summary": {
                        "actionable": True,
                        "sample_count": 3,
                        "outcome_feedback_score": 68.0,
                    }
                },
            },
        },
        notify=False,
    )

    profile = signal["strategy_profile"]
    assert profile["lifecycle_gate"]["mode"] == "recovery_probe_confirmed"
    assert profile["execution_sizing_plan"]["lifecycle_gate_max_position_pct"] == 12.5
    assert profile["execution_sizing_plan"]["effective_position_pct"] == 12.5
    assert signal["position_size_pct"] == 12.5


def test_aggressive_recovery_probe_positive_outcome_threshold_accepts_mid_positive_score():
    policy = default_execution_position_cap_policy("aggressive")
    plan = build_execution_sizing_plan(
        signal={
            "position_size_pct": 36.0,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "kernel_positioning": {"quality_position_pct": 36.0},
                "portfolio_execution_guard": {"buy_tier": "normal_buy"},
                "lifecycle_gate": {
                    "mode": "recovery_probe_confirmed",
                    "size_multiplier": 1.0,
                    "max_position_pct": 10.0,
                },
                "outcome_feedback": {
                    "summary": {
                        "actionable": True,
                        "sample_count": 3,
                        "outcome_feedback_score": 56.0,
                    }
                },
            },
        },
        total_equity=400000,
        available_cash=400000,
        slot_available_cash=400000,
        quant_status="trial",
        policy=policy,
        price=30.0,
    )

    assert plan["recovery_probe_confirmed_positive_outcome"] is True
    assert plan["recovery_probe_confirmed_positive_outcome_kernel_qualified"] is True
    assert plan["recovery_probe_confirmed_cap_source"] == "positive_outcome"
    assert plan["effective_position_pct"] == 12.5


def test_aggressive_recovery_probe_positive_outcome_below_kernel_threshold_keeps_base_cap():
    policy = default_execution_position_cap_policy("aggressive")
    plan = build_execution_sizing_plan(
        signal={
            "position_size_pct": 31.0,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "kernel_positioning": {"quality_position_pct": 31.0},
                "portfolio_execution_guard": {"buy_tier": "normal_buy"},
                "lifecycle_gate": {
                    "mode": "recovery_probe_confirmed",
                    "size_multiplier": 1.0,
                    "max_position_pct": 6.0,
                },
                "outcome_feedback": {
                    "summary": {
                        "actionable": True,
                        "sample_count": 3,
                        "outcome_feedback_score": 56.0,
                    }
                },
            },
        },
        total_equity=400000,
        available_cash=400000,
        slot_available_cash=400000,
        quant_status="trial",
        policy=policy,
        price=30.0,
    )

    assert plan["recovery_probe_confirmed_positive_outcome"] is True
    assert plan["recovery_probe_confirmed_positive_outcome_kernel_qualified"] is False
    assert plan["recovery_probe_confirmed_cap_source"] == "base"
    assert plan["effective_position_pct"] == 6.0


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


def test_recovery_probe_confirmed_normal_buy_uses_profile_floor():
    policy = default_execution_position_cap_policy("aggressive")
    plan = build_execution_sizing_plan(
        signal={
            "position_size_pct": 3.0,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "kernel_positioning": {"quality_position_pct": 3.0},
                "portfolio_execution_guard": {"buy_tier": "normal_buy"},
                "lifecycle_gate": {
                    "mode": "recovery_probe_confirmed",
                    "size_multiplier": 1.0,
                    "max_position_pct": 10.0,
                },
            },
        },
        total_equity=400000,
        available_cash=400000,
        slot_available_cash=400000,
        quant_status="trial",
        policy=policy,
        price=10.0,
    )

    assert plan["raw_kernel_quality_position_pct"] == 3.0
    assert plan["recovery_probe_confirmed_floor_pct"] == 6.0
    assert plan["effective_position_pct"] == 6.0
    assert plan["final_budget"] == 24000.0


def test_stock_execution_feedback_caps_confirmed_recovery_sizing():
    policy = default_execution_position_cap_policy("aggressive")
    plan = build_execution_sizing_plan(
        signal={
            "position_size_pct": 30.0,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "kernel_positioning": {"quality_position_pct": 30.0},
                "portfolio_execution_guard": {"buy_tier": "normal_buy"},
                "lifecycle_gate": {
                    "mode": "recovery_probe_confirmed",
                    "size_multiplier": 1.0,
                    "max_position_pct": 10.0,
                },
                "stock_execution_feedback_gate": {
                    "status": "downgraded",
                    "size_multiplier": 0.5,
                    "reason_code": "recent_loss_reentry",
                },
            },
        },
        total_equity=400000,
        available_cash=400000,
        slot_available_cash=400000,
        quant_status="trial",
        policy=policy,
        price=10.0,
    )

    assert plan["effective_position_pct"] == 3.0
    assert plan["final_budget"] == 12000.0
    assert "stock_execution_feedback_position_pct" in plan["cap_reasons"]
    assert plan["stock_execution_feedback_status"] == "downgraded"
    assert plan["stock_execution_feedback_size_multiplier"] == 0.5


def test_stock_execution_feedback_blocked_blocks_sizing():
    policy = default_execution_position_cap_policy("aggressive")
    plan = build_execution_sizing_plan(
        signal={
            "position_size_pct": 30.0,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "kernel_positioning": {"quality_position_pct": 30.0},
                "portfolio_execution_guard": {"buy_tier": "normal_buy"},
                "stock_execution_feedback_gate": {
                    "status": "blocked",
                    "size_multiplier": 0.0,
                    "reason_code": "stock_loss_reentry_blocked",
                },
            },
        },
        total_equity=400000,
        available_cash=400000,
        slot_available_cash=400000,
        quant_status="trial",
        policy=policy,
        price=10.0,
    )

    assert plan["effective_position_pct"] == 0.0
    assert plan["final_budget"] == 0.0
    assert plan["skip_reason"] == "stock_loss_reentry_blocked"
    assert "stock_execution_feedback_block_pct" in plan["cap_reasons"]


def test_active_guarded_confirmed_buy_uses_active_like_cap_without_stock_feedback():
    policy = default_execution_position_cap_policy("aggressive")
    plan = build_execution_sizing_plan(
        signal={
            "action": "BUY",
            "confidence": 80,
            "position_size_pct": 50,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "kernel_positioning": {"quality_position_pct": 30.0},
                "portfolio_execution_guard": {"buy_tier": "normal_buy", "buy_strength_score": 0.7},
                "lifecycle_gate": {"mode": "active_guarded", "max_position_pct": 4.0},
            },
        },
        total_equity=400000,
        available_cash=400000,
        slot_available_cash=400000,
        quant_status="active",
        policy=policy,
        price=30.0,
    )

    assert plan["effective_position_pct"] == 9.0
    assert plan["final_budget"] == 36000.0
    assert plan["lifecycle_gate_max_position_pct"] == 9.0
    assert plan["cap_reason_codes"] == [
        "buy_tier_cap_pct",
        "active_normal_buy_cap",
        "risk_budget_position_pct",
        "lifecycle_gate_max_position_pct",
    ]


def test_active_guarded_confirmed_buy_keeps_stock_feedback_downgrade():
    policy = default_execution_position_cap_policy("aggressive")
    plan = build_execution_sizing_plan(
        signal={
            "action": "BUY",
            "confidence": 80,
            "position_size_pct": 50,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "kernel_positioning": {"quality_position_pct": 30.0},
                "portfolio_execution_guard": {"buy_tier": "normal_buy", "buy_strength_score": 0.7},
                "lifecycle_gate": {"mode": "active_guarded", "max_position_pct": 4.0},
                "stock_execution_feedback_gate": {
                    "status": "downgraded",
                    "size_multiplier": 0.5,
                },
            },
        },
        total_equity=400000,
        available_cash=400000,
        slot_available_cash=400000,
        quant_status="active",
        policy=policy,
        price=30.0,
    )

    assert plan["lifecycle_gate_max_position_pct"] == 4.0
    assert plan["stock_execution_feedback_position_pct"] == 2.0
    assert plan["effective_position_pct"] == 2.0
    assert plan["final_budget"] == 8000.0


def test_trial_guarded_quality_confirmed_normal_buy_uses_confirmed_cap_with_feedback_downgrade():
    policy = default_execution_position_cap_policy("aggressive")
    plan = build_execution_sizing_plan(
        signal={
            "action": "BUY",
            "confidence": 80,
            "position_size_pct": 50,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "kernel_positioning": {"quality_position_pct": 34.0},
                "portfolio_execution_guard": {
                    "buy_tier": "normal_buy",
                    "buy_strength_score": 0.67,
                    "score_components": {
                        "confirmation_score": 1.0,
                        "edge_strength": 0.69,
                        "volume_score": 1.0,
                        "risk_penalty": 0.18,
                    },
                    "trend_confirmation": {
                        "ma_stack": True,
                        "ma20_rising": True,
                        "above_ma20_checkpoints": 20,
                        "recent_5d_return": 0.035,
                        "ma20_distance_pct": 1.1,
                    },
                },
                "lifecycle_gate": {"mode": "trial_guarded", "size_multiplier": 0.35, "max_position_pct": 4.0},
                "stock_execution_feedback_gate": {
                    "status": "downgraded",
                    "size_multiplier": 0.75,
                },
            },
        },
        total_equity=400000,
        available_cash=400000,
        slot_available_cash=400000,
        quant_status="trial",
        policy=policy,
        price=85.12,
    )

    assert plan["trial_guarded_confirmed_quality"] is True
    assert plan["trial_guarded_confirmed_cap_pct"] == 6.0
    assert plan["lifecycle_gate_max_position_pct"] == 6.0
    assert plan["stock_execution_feedback_position_pct"] == 6.0
    assert plan["effective_position_pct"] == 6.0
    assert plan["final_budget"] == 24000.0


def test_trial_guarded_positive_outcome_lifts_confirmed_normal_cap():
    policy = default_execution_position_cap_policy("aggressive")
    plan = build_execution_sizing_plan(
        signal={
            "action": "BUY",
            "confidence": 80,
            "position_size_pct": 50,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "kernel_positioning": {"quality_position_pct": 34.0},
                "portfolio_execution_guard": {
                    "buy_tier": "normal_buy",
                    "buy_strength_score": 0.67,
                    "score_components": {
                        "confirmation_score": 1.0,
                        "edge_strength": 0.69,
                        "volume_score": 1.0,
                        "risk_penalty": 0.18,
                    },
                    "trend_confirmation": {
                        "ma_stack": True,
                        "ma20_rising": True,
                        "above_ma20_checkpoints": 20,
                        "recent_5d_return": 0.035,
                        "ma20_distance_pct": 1.1,
                    },
                },
                "lifecycle_gate": {"mode": "trial_guarded", "size_multiplier": 0.35, "max_position_pct": 4.0},
                "stock_execution_feedback_gate": {
                    "status": "downgraded",
                    "size_multiplier": 0.75,
                },
                "outcome_feedback": {
                    "summary": {
                        "actionable": True,
                        "sample_count": 4,
                        "outcome_feedback_score": 58.0,
                    }
                },
            },
        },
        total_equity=400000,
        available_cash=400000,
        slot_available_cash=400000,
        quant_status="trial",
        policy=policy,
        price=85.12,
    )

    assert plan["trial_guarded_confirmed_quality"] is True
    assert plan["trial_guarded_confirmed_positive_outcome"] is True
    assert plan["trial_guarded_confirmed_cap_source"] == "positive_outcome"
    assert plan["trial_guarded_confirmed_cap_pct"] == 8.0
    assert plan["stock_execution_feedback_position_pct"] == 8.0
    assert plan["effective_position_pct"] == 8.0
    assert plan["final_budget"] == 32000.0


def test_trial_guarded_positive_outcome_requires_prior_samples():
    policy = default_execution_position_cap_policy("aggressive")
    plan = build_execution_sizing_plan(
        signal={
            "action": "BUY",
            "confidence": 80,
            "position_size_pct": 50,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "kernel_positioning": {"quality_position_pct": 34.0},
                "portfolio_execution_guard": {
                    "buy_tier": "normal_buy",
                    "buy_strength_score": 0.67,
                    "score_components": {
                        "confirmation_score": 1.0,
                        "edge_strength": 0.69,
                        "volume_score": 1.0,
                        "risk_penalty": 0.18,
                    },
                    "trend_confirmation": {
                        "ma_stack": True,
                        "ma20_rising": True,
                        "above_ma20_checkpoints": 20,
                        "recent_5d_return": 0.035,
                        "ma20_distance_pct": 1.1,
                    },
                },
                "lifecycle_gate": {"mode": "trial_guarded", "size_multiplier": 0.35, "max_position_pct": 4.0},
                "outcome_feedback": {
                    "summary": {
                        "actionable": True,
                        "sample_count": 0,
                        "outcome_feedback_score": 80.0,
                    }
                },
            },
        },
        total_equity=400000,
        available_cash=400000,
        slot_available_cash=400000,
        quant_status="trial",
        policy=policy,
        price=85.12,
    )

    assert plan["trial_guarded_confirmed_quality"] is True
    assert plan["trial_guarded_confirmed_positive_outcome"] is False
    assert plan["trial_guarded_confirmed_cap_source"] == "quality_confirmed"
    assert plan["trial_guarded_confirmed_cap_pct"] == 6.0
    assert plan["effective_position_pct"] == 6.0


def test_trial_guarded_overextended_strong_buy_keeps_guarded_cap():
    policy = default_execution_position_cap_policy("aggressive")
    plan = build_execution_sizing_plan(
        signal={
            "action": "BUY",
            "confidence": 90,
            "position_size_pct": 50,
            "stop_loss_pct": 5,
            "strategy_profile": {
                "kernel_positioning": {"quality_position_pct": 45.0},
                "portfolio_execution_guard": {
                    "buy_tier": "strong_buy",
                    "buy_strength_score": 0.91,
                    "score_components": {
                        "confirmation_score": 1.0,
                        "edge_strength": 1.0,
                        "volume_score": 0.6,
                        "risk_penalty": 0.0,
                    },
                    "trend_confirmation": {
                        "ma_stack": True,
                        "ma20_rising": True,
                        "above_ma20_checkpoints": 20,
                        "recent_5d_return": 0.097,
                        "ma20_distance_pct": 3.4,
                    },
                },
                "lifecycle_gate": {"mode": "trial_guarded", "size_multiplier": 0.35, "max_position_pct": 4.0},
            },
        },
        total_equity=400000,
        available_cash=400000,
        slot_available_cash=400000,
        quant_status="trial",
        policy=policy,
        price=308.8,
    )

    assert plan["trial_guarded_confirmed_quality"] is False
    assert plan["lifecycle_gate_max_position_pct"] == 4.0
    assert plan["effective_position_pct"] == 4.0
    assert plan["final_budget"] == 16000.0


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
    lifecycle_gate_mode: str | None = None,
) -> dict:
    plan = {
        "buy_tier": tier,
        "final_budget": final_budget,
        "risk_budget_pct": risk_pct,
        "effective_position_pct": effective_position_pct,
        "expected_stop_loss_pct": stop_loss_pct,
    }
    if lifecycle_gate_mode:
        plan["lifecycle_gate_mode"] = lifecycle_gate_mode
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
            "execution_sizing_plan": plan,
            "quant_status": status,
        },
    }


def test_batch_caps_skip_trial_buys_after_checkpoint_risk_budget():
    policy = default_execution_position_cap_policy("aggressive")
    policy["max_new_buys_per_checkpoint"] = 99
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


def test_batch_caps_use_stock_code_not_signal_id_as_final_tiebreaker():
    policy = default_execution_position_cap_policy("aggressive")
    lower_code_later_signal = _buy_signal(20, "normal_buy", 36000, 0.45, effective_position_pct=9.0)
    lower_code_later_signal["stock_code"] = "000001"
    higher_code_earlier_signal = _buy_signal(1, "normal_buy", 36000, 0.45, effective_position_pct=9.0)
    higher_code_earlier_signal["stock_code"] = "000002"
    for signal in (lower_code_later_signal, higher_code_earlier_signal):
        signal["confidence"] = 80
        signal["strategy_profile"]["portfolio_execution_guard"]["buy_strength_score"] = 0.60

    result = apply_batch_execution_caps(
        signals=[higher_code_earlier_signal, lower_code_later_signal],
        total_equity=400000,
        existing_trial_market_value=0,
        existing_weak_buy_market_value=0,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    allowed_codes = [item["signal"]["stock_code"] for item in result if item["allowed"]]
    skipped_codes = [item["signal"]["stock_code"] for item in result if not item["allowed"]]

    assert allowed_codes == ["000001"]
    assert skipped_codes == ["000002"]


def test_batch_caps_apply_checkpoint_buy_count_after_quality_sorting():
    policy = default_execution_position_cap_policy("aggressive")
    strongest = _buy_signal(10, "normal_buy", 3000, 0.0375, effective_position_pct=0.75)
    strongest["stock_code"] = "000003"
    strongest["strategy_profile"]["portfolio_execution_guard"]["buy_strength_score"] = 0.90
    middle = _buy_signal(20, "normal_buy", 3000, 0.0375, effective_position_pct=0.75)
    middle["stock_code"] = "000002"
    middle["strategy_profile"]["portfolio_execution_guard"]["buy_strength_score"] = 0.80
    weakest = _buy_signal(30, "normal_buy", 3000, 0.0375, effective_position_pct=0.75)
    weakest["stock_code"] = "000001"
    weakest["strategy_profile"]["portfolio_execution_guard"]["buy_strength_score"] = 0.70

    result = apply_batch_execution_caps(
        signals=[weakest, middle, strongest],
        total_equity=400000,
        existing_trial_market_value=0,
        existing_weak_buy_market_value=0,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    allowed_codes = [item["signal"]["stock_code"] for item in result if item["allowed"]]
    skipped = [item for item in result if not item["allowed"]]

    assert allowed_codes == ["000003", "000002"]
    assert [item["signal"]["stock_code"] for item in skipped] == ["000001"]
    assert skipped[0]["reason_code"] == "checkpoint_buy_count_limit_hit"


def test_batch_caps_prioritize_stock_feedback_outcome_score_before_stock_code_tiebreaker():
    policy = default_execution_position_cap_policy("aggressive")
    policy["max_new_buys_per_checkpoint"] = 1
    low_feedback_low_code = _buy_signal(1, "normal_buy", 3000, 0.0375, effective_position_pct=0.75)
    low_feedback_low_code["stock_code"] = "000001"
    low_feedback_low_code["strategy_profile"]["portfolio_execution_guard"]["buy_strength_score"] = 0.70
    low_feedback_low_code["strategy_profile"]["stock_execution_feedback_gate"] = {
        "outcome_feedback": {"outcome_feedback_score": 40}
    }
    high_feedback_high_code = _buy_signal(2, "normal_buy", 3000, 0.0375, effective_position_pct=0.75)
    high_feedback_high_code["stock_code"] = "000002"
    high_feedback_high_code["strategy_profile"]["portfolio_execution_guard"]["buy_strength_score"] = 0.70
    high_feedback_high_code["strategy_profile"]["stock_execution_feedback_gate"] = {
        "outcome_feedback": {"outcome_feedback_score": 80}
    }

    result = apply_batch_execution_caps(
        signals=[low_feedback_low_code, high_feedback_high_code],
        total_equity=400000,
        existing_trial_market_value=0,
        existing_weak_buy_market_value=0,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    assert [item["signal"]["stock_code"] for item in result if item["allowed"]] == ["000002"]
    assert [item["signal"]["stock_code"] for item in result if not item["allowed"]] == ["000001"]


def test_batch_caps_use_buy_outcome_score_for_buy_priority():
    policy = default_execution_position_cap_policy("aggressive")
    policy["max_new_buys_per_checkpoint"] = 1
    sell_dragged_good_buy = _buy_signal(1, "normal_buy", 3000, 0.0375, effective_position_pct=0.75)
    sell_dragged_good_buy["stock_code"] = "000002"
    sell_dragged_good_buy["strategy_profile"]["portfolio_execution_guard"]["buy_strength_score"] = 0.70
    sell_dragged_good_buy["strategy_profile"]["outcome_feedback"] = {
        "summary": {
            "outcome_feedback_score": 15,
            "buy_avg_score": 70,
            "buy_sample_count": 4,
            "sell_avg_score": 10,
            "sell_sample_count": 4,
        }
    }
    neutral_buy = _buy_signal(2, "normal_buy", 3000, 0.0375, effective_position_pct=0.75)
    neutral_buy["stock_code"] = "000001"
    neutral_buy["strategy_profile"]["portfolio_execution_guard"]["buy_strength_score"] = 0.70
    neutral_buy["strategy_profile"]["outcome_feedback"] = {
        "summary": {
            "outcome_feedback_score": 50,
            "buy_avg_score": 50,
            "buy_sample_count": 4,
        }
    }

    result = apply_batch_execution_caps(
        signals=[neutral_buy, sell_dragged_good_buy],
        total_equity=400000,
        existing_trial_market_value=0,
        existing_weak_buy_market_value=0,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    assert [item["signal"]["stock_code"] for item in result if item["allowed"]] == ["000002"]
    assert [item["signal"]["stock_code"] for item in result if not item["allowed"]] == ["000001"]


def test_batch_caps_keep_buy_priority_neutral_when_only_sell_outcomes_exist():
    policy = default_execution_position_cap_policy("aggressive")
    policy["max_new_buys_per_checkpoint"] = 1
    sell_only_outcome = _buy_signal(1, "normal_buy", 3000, 0.0375, effective_position_pct=0.75)
    sell_only_outcome["stock_code"] = "000002"
    sell_only_outcome["strategy_profile"]["portfolio_execution_guard"]["buy_strength_score"] = 0.70
    sell_only_outcome["strategy_profile"]["outcome_feedback"] = {
        "summary": {
            "outcome_feedback_score": 15,
            "buy_avg_score": 50,
            "buy_sample_count": 0,
            "sell_avg_score": 10,
            "sell_sample_count": 4,
        }
    }
    poor_buy_outcome = _buy_signal(2, "normal_buy", 3000, 0.0375, effective_position_pct=0.75)
    poor_buy_outcome["stock_code"] = "000001"
    poor_buy_outcome["strategy_profile"]["portfolio_execution_guard"]["buy_strength_score"] = 0.70
    poor_buy_outcome["strategy_profile"]["outcome_feedback"] = {
        "summary": {
            "outcome_feedback_score": 43,
            "buy_avg_score": 43,
            "buy_sample_count": 4,
        }
    }

    result = apply_batch_execution_caps(
        signals=[poor_buy_outcome, sell_only_outcome],
        total_equity=400000,
        existing_trial_market_value=0,
        existing_weak_buy_market_value=0,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    assert [item["signal"]["stock_code"] for item in result if item["allowed"]] == ["000002"]
    assert [item["signal"]["stock_code"] for item in result if not item["allowed"]] == ["000001"]


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


def test_batch_caps_prioritize_normal_scan_before_recovery_probe_when_risk_is_tight():
    policy = default_execution_position_cap_policy("aggressive")
    signals = [
        _buy_signal(1, "strong_buy", 40000, 0.65, effective_position_pct=10.0, lifecycle_gate_mode="strong_recovery_confirmed"),
        _buy_signal(2, "normal_buy", 40000, 0.45, effective_position_pct=10.0, lifecycle_gate_mode="normal_scan"),
    ]

    result = apply_batch_execution_caps(
        signals=signals,
        total_equity=400000,
        existing_trial_market_value=0,
        existing_weak_buy_market_value=0,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    recovery = next(item for item in result if item["signal"]["id"] == 1)
    normal = next(item for item in result if item["signal"]["id"] == 2)

    assert normal["allowed"] is True
    assert recovery["allowed"] is False
    assert recovery["reason_code"] == "portfolio_trial_risk_budget_exhausted"


def test_batch_caps_prioritize_confirmed_normal_recovery_before_strong_recovery_probe():
    policy = default_execution_position_cap_policy("aggressive")
    policy["max_new_buys_per_checkpoint"] = 99
    signals = [
        _buy_signal(1, "strong_buy", 24000, 0.30, effective_position_pct=6.0, lifecycle_gate_mode="strong_recovery_confirmed"),
        _buy_signal(2, "normal_buy", 36000, 0.45, effective_position_pct=9.0, lifecycle_gate_mode="recovery_probe_confirmed"),
        _buy_signal(3, "weak_buy", 12000, 0.15, effective_position_pct=3.0, lifecycle_gate_mode="trial_light"),
    ]

    result = apply_batch_execution_caps(
        signals=signals,
        total_equity=400000,
        existing_trial_market_value=0,
        existing_weak_buy_market_value=0,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    strong_recovery = next(item for item in result if item["signal"]["id"] == 1)
    normal_recovery = next(item for item in result if item["signal"]["id"] == 2)
    weak = next(item for item in result if item["signal"]["id"] == 3)

    assert normal_recovery["allowed"] is True
    assert weak["allowed"] is True
    assert strong_recovery["allowed"] is False
    assert strong_recovery["reason_code"] == "portfolio_trial_risk_budget_exhausted"


def test_batch_caps_preserve_one_lot_for_high_quality_expensive_recovery():
    policy = default_execution_position_cap_policy("aggressive")
    expensive = _buy_signal(
        1,
        "strong_buy",
        12000,
        0.15,
        effective_position_pct=3.0,
        lifecycle_gate_mode="recovery_probe_quality_limited",
    )
    expensive["strategy_profile"]["execution_sizing_plan"]["one_lot_cost"] = 26000.0
    expensive["strategy_profile"]["portfolio_execution_guard"].update(
        {
            "buy_strength_score": 0.94,
            "score_components": {
                "edge_strength": 0.95,
                "confirmation_score": 0.92,
                "trend_structure_score": 0.95,
                "volume_score": 0.7,
                "risk_penalty": 0.05,
            },
            "trend_confirmation": {"recent_5d_return": 0.04},
        }
    )
    expensive["strategy_profile"]["market_snapshot"] = {"rsi": 72.0}
    flexible = _buy_signal(
        2,
        "strong_buy",
        24000,
        0.30,
        effective_position_pct=6.0,
        lifecycle_gate_mode="strong_recovery_confirmed",
    )
    flexible["strategy_profile"]["execution_sizing_plan"]["one_lot_cost"] = 6000.0

    result = apply_batch_execution_caps(
        signals=[flexible, expensive],
        total_equity=400000,
        existing_trial_market_value=52000,
        existing_weak_buy_market_value=0,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    expensive_row = next(item for item in result if item["signal"]["id"] == 1)
    flexible_row = next(item for item in result if item["signal"]["id"] == 2)

    assert expensive_row["allowed"] is True
    assert expensive_row["reason_code"] == ""
    assert flexible_row["allowed"] is False
    assert flexible_row["reason_code"] == "trial_exposure_one_lot_insufficient"


def test_batch_caps_do_not_spend_weak_exposure_on_clipped_budget_below_one_lot():
    policy = default_execution_position_cap_policy("aggressive")
    expensive = _buy_signal(1, "weak_buy", 12000, 0.15, effective_position_pct=3.0)
    expensive["strategy_profile"]["execution_sizing_plan"]["one_lot_cost"] = 15000.0
    cheap = _buy_signal(2, "weak_buy", 6000, 0.075, effective_position_pct=1.5)
    cheap["strategy_profile"]["execution_sizing_plan"]["one_lot_cost"] = 5000.0

    result = apply_batch_execution_caps(
        signals=[expensive, cheap],
        total_equity=400000,
        existing_trial_market_value=0,
        existing_weak_buy_market_value=42000,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    expensive_row = next(item for item in result if item["signal"]["id"] == 1)
    cheap_row = next(item for item in result if item["signal"]["id"] == 2)

    assert expensive_row["allowed"] is False
    assert expensive_row["reason_code"] == "weak_buy_exposure_one_lot_insufficient"
    assert cheap_row["allowed"] is True


def test_batch_caps_prioritize_weak_buy_with_better_outcome_feedback():
    policy = default_execution_position_cap_policy("aggressive")
    stale_bad = _buy_signal(1, "weak_buy", 6000, 0.075, effective_position_pct=1.5)
    stale_bad["strategy_profile"]["portfolio_execution_guard"]["buy_strength_score"] = 0.8
    stale_bad["strategy_profile"]["outcome_feedback"] = {
        "summary": {"actionable": True, "outcome_feedback_score": 30}
    }
    recent_good = _buy_signal(2, "weak_buy", 6000, 0.075, effective_position_pct=1.5)
    recent_good["strategy_profile"]["portfolio_execution_guard"]["buy_strength_score"] = 0.55
    recent_good["strategy_profile"]["outcome_feedback"] = {
        "summary": {"actionable": True, "outcome_feedback_score": 80}
    }

    result = apply_batch_execution_caps(
        signals=[stale_bad, recent_good],
        total_equity=400000,
        existing_trial_market_value=0,
        existing_weak_buy_market_value=42000,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    stale_bad_row = next(item for item in result if item["signal"]["id"] == 1)
    recent_good_row = next(item for item in result if item["signal"]["id"] == 2)

    assert recent_good_row["allowed"] is True
    assert stale_bad_row["allowed"] is False
    assert stale_bad_row["reason_code"] == "weak_buy_exposure_cap_hit"


def test_batch_caps_allow_confirmed_weak_buy_one_lot_from_persistent_quality_reserve():
    policy = default_execution_position_cap_policy("aggressive")
    signal = _buy_signal(1, "weak_buy", 12000, 0.15, effective_position_pct=3.0)
    signal["strategy_profile"]["execution_sizing_plan"]["one_lot_cost"] = 3000.0
    signal["strategy_profile"]["portfolio_execution_guard"].update(
        {
            "buy_strength_score": 0.53,
            "score_components": {
                "edge_strength": 0.03,
                "trend_structure_score": 1.0,
                "confirmation_score": 1.0,
                "volume_score": 0.6,
                "risk_penalty": 0.0,
            },
            "trend_confirmation": {
                "retest_confirmed": True,
                "ma_stack": True,
                "ma20_rising": True,
                "above_ma20_checkpoints": 20,
                "recent_5d_return": 0.01,
            },
        }
    )

    result = apply_batch_execution_caps(
        signals=[signal],
        total_equity=400000,
        existing_trial_market_value=0,
        existing_weak_buy_market_value=47000,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    row = result[0]
    plan = row["signal"]["strategy_profile"]["execution_sizing_plan"]
    assert row["allowed"] is True
    assert row["reason_code"] == ""
    assert plan["final_budget"] > plan["one_lot_cost"]


def test_batch_caps_use_quality_reserve_to_avoid_residual_weak_buy_probe():
    policy = default_execution_position_cap_policy("aggressive")
    signal = _buy_signal(1, "weak_buy", 12000, 0.15, effective_position_pct=3.0)
    signal["strategy_profile"]["execution_sizing_plan"]["one_lot_cost"] = 1600.0
    signal["strategy_profile"]["portfolio_execution_guard"].update(
        {
            "buy_strength_score": 0.63,
            "score_components": {
                "edge_strength": 0.28,
                "trend_structure_score": 1.0,
                "confirmation_score": 1.0,
                "volume_score": 0.6,
                "risk_penalty": 0.0,
            },
            "trend_confirmation": {
                "retest_confirmed": False,
                "ma_stack": True,
                "ma20_rising": True,
                "above_ma20_checkpoints": 10,
                "recent_5d_return": 0.02,
                "rsi": 62.0,
            },
        }
    )

    result = apply_batch_execution_caps(
        signals=[signal],
        total_equity=400000,
        existing_trial_market_value=0,
        existing_weak_buy_market_value=44700,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    row = result[0]
    plan = row["signal"]["strategy_profile"]["execution_sizing_plan"]
    assert row["allowed"] is True
    assert row["reason_code"] == ""
    assert plan["final_budget"] == 12000
    assert "batch_cap_adjustment" not in plan


def test_batch_caps_block_unconfirmed_weak_buy_when_only_quality_reserve_remains():
    policy = default_execution_position_cap_policy("aggressive")
    signal = _buy_signal(1, "weak_buy", 12000, 0.15, effective_position_pct=3.0)
    signal["strategy_profile"]["execution_sizing_plan"]["one_lot_cost"] = 3000.0
    signal["strategy_profile"]["portfolio_execution_guard"].update(
        {
            "buy_strength_score": 0.68,
            "score_components": {
                "edge_strength": 0.3,
                "trend_structure_score": 1.0,
                "confirmation_score": 1.0,
                "volume_score": 1.0,
                "risk_penalty": 0.0,
            },
            "trend_confirmation": {
                "retest_confirmed": False,
                "ma_stack": True,
                "ma20_rising": True,
                "above_ma20_checkpoints": 12,
                "recent_5d_return": 0.01,
            },
        }
    )

    result = apply_batch_execution_caps(
        signals=[signal],
        total_equity=400000,
        existing_trial_market_value=0,
        existing_weak_buy_market_value=47000,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    assert result[0]["allowed"] is False
    assert result[0]["reason_code"] == "weak_buy_exposure_one_lot_insufficient"


def test_batch_caps_block_low_strength_weak_buy_even_when_budget_fits():
    policy = default_execution_position_cap_policy("aggressive")
    signal = _buy_signal(1, "weak_buy", 12000, 0.15, effective_position_pct=3.0)
    signal["strategy_profile"]["execution_sizing_plan"]["one_lot_cost"] = 10000.0
    signal["strategy_profile"]["portfolio_execution_guard"]["buy_strength_score"] = 0.12

    result = apply_batch_execution_caps(
        signals=[signal],
        total_equity=400000,
        existing_trial_market_value=0,
        existing_weak_buy_market_value=0,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    assert result[0]["allowed"] is False
    assert result[0]["reason_code"] == "weak_buy_strength_floor_not_met"
