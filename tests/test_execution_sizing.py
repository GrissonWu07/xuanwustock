from app.quant_sim.execution_sizing import build_execution_sizing_plan, default_execution_position_cap_policy


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
