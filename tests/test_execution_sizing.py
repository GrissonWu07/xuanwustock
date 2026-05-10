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


def _buy_signal(signal_id: int, tier: str, final_budget: float, risk_pct: float = 0.30, status: str = "trial") -> dict:
    return {
        "id": signal_id,
        "stock_code": f"000{signal_id:03d}",
        "stock_name": f"股票{signal_id}",
        "action": "BUY",
        "confidence": 80 - signal_id,
        "position_size_pct": 3.0,
        "strategy_profile": {
            "portfolio_execution_guard": {
                "buy_tier": tier,
                "buy_strength_score": 0.6 - signal_id * 0.01,
            },
            "execution_sizing_plan": {
                "buy_tier": tier,
                "final_budget": final_budget,
                "risk_budget_pct": risk_pct,
                "effective_position_pct": 3.0,
            },
            "quant_status": status,
        },
    }


def test_batch_caps_skip_trial_buys_after_checkpoint_risk_budget():
    policy = default_execution_position_cap_policy("aggressive")
    signals = [
        _buy_signal(1, "weak_buy", 6000, 0.30),
        _buy_signal(2, "weak_buy", 6000, 0.30),
        _buy_signal(3, "weak_buy", 6000, 0.30),
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
