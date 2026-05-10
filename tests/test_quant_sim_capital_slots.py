import json
from datetime import datetime

from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.capital_slots import (
    DEFAULT_CAPITAL_SLOT_CONFIG,
    normalize_capital_slot_config,
    calculate_slot_plan,
    calculate_slot_units,
    calculate_buy_priority,
    gate_size_multiplier,
)
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.scheduler import QuantSimScheduler
from app.quant_sim.signal_center_service import SignalCenterService


def _fusion_signal(
    stock_code: str,
    *,
    fusion_score: float,
    buy_threshold: float = 0.5,
    fusion_confidence: float = 0.8,
    price: float = 10.0,
    confidence: int = 80,
) -> dict:
    return {
        "id": 0,
        "stock_code": stock_code,
        "stock_name": stock_code,
        "action": "BUY",
        "confidence": confidence,
        "position_size_pct": 50,
        "price": price,
        "strategy_profile": {
            "effective_thresholds": {"min_fusion_confidence": 0.4},
            "selected_strategy_profile": {"id": "aggressive"},
            "market_snapshot": {
                "current_price": price,
                "ma5": price * 1.02,
                "ma10": price * 1.01,
                "ma20": price * 0.98,
                "ma20_slope": 0.02,
                "volume_ratio": 1.8,
                "recent_checkpoints": [
                    {"close": price * 0.99, "ma20": price * 0.97, "ma20_slope": 0.01},
                    {"close": price, "ma20": price * 0.975, "ma20_slope": 0.02},
                ],
            },
            "explainability": {
                "fusion_breakdown": {
                    "fusion_score": fusion_score,
                    "buy_threshold_eff": buy_threshold,
                    "fusion_confidence": fusion_confidence,
                    "tech_score": 0.55,
                    "context_score": 0.45,
                }
            },
        },
    }


def test_slot_plan_uses_dynamic_equity_tiers():
    plan = calculate_slot_plan(
        total_equity=80000,
        config={**DEFAULT_CAPITAL_SLOT_CONFIG, "capital_max_slots": 25},
    )

    assert plan["enabled"] is True
    assert plan["slot_count"] == 2
    assert plan["slot_budget"] == 40000

    mid_plan = calculate_slot_plan(
        total_equity=452000,
        config={**DEFAULT_CAPITAL_SLOT_CONFIG, "capital_max_slots": 25},
    )
    assert mid_plan["slot_count"] == 5
    assert mid_plan["slot_budget"] == 90400

    large_plan = calculate_slot_plan(
        total_equity=1200000,
        config={**DEFAULT_CAPITAL_SLOT_CONFIG, "capital_max_slots": 25},
    )
    assert large_plan["slot_count"] == 6
    assert large_plan["slot_budget"] == 200000


def test_slot_config_enforces_minimum_slot_cash_and_known_sell_reuse_policy():
    config = normalize_capital_slot_config(
        {
            **DEFAULT_CAPITAL_SLOT_CONFIG,
            "capital_slot_min_cash": 1000,
            "capital_sell_cash_reuse_policy": "invalid",
        }
    )

    assert config["capital_slot_min_cash"] == 20000
    assert config["capital_sell_cash_reuse_policy"] == "next_batch"


def test_slot_plan_blocks_pool_below_one_minimum_slot_even_if_pool_min_is_lower():
    plan = calculate_slot_plan(
        total_equity=10000,
        config={**DEFAULT_CAPITAL_SLOT_CONFIG, "capital_pool_min_cash": 0, "capital_slot_min_cash": 20000},
    )

    assert plan["pool_ready"] is False
    assert plan["slot_count"] == 0
    assert plan["required_pool_cash"] == 20000


def test_high_price_strong_buy_can_use_two_slots_to_buy_one_lot():
    signal = _fusion_signal("688001", fusion_score=0.72, buy_threshold=0.5, fusion_confidence=0.88, price=260)
    plan = calculate_slot_plan(total_equity=50000, config=DEFAULT_CAPITAL_SLOT_CONFIG)
    priority = calculate_buy_priority(signal)

    assert plan["slot_count"] == 2
    assert priority > 0.5


def test_buy_slot_units_floor_to_one_lot_when_full_slot_can_afford_it():
    signal = _fusion_signal("301662", fusion_score=0.351, buy_threshold=0.35, fusion_confidence=0.45, price=800.0)

    sizing = calculate_slot_units(
        signal,
        price=800.0,
        slot_budget=100000,
        commission_rate=0.00025,
        config=DEFAULT_CAPITAL_SLOT_CONFIG,
    )

    assert sizing["slot_units"] >= sizing["one_lot_cost"] / 100000
    assert sizing["slot_units"] > sizing["base_slot_units"]


def test_aggressive_cash_pressure_increases_slot_units_when_cash_ratio_is_high():
    signal = _fusion_signal("301662", fusion_score=0.385865, buy_threshold=0.35, fusion_confidence=0.890861, price=182.07)

    base = calculate_slot_units(
        signal,
        price=182.07,
        slot_budget=100000,
        commission_rate=0.00025,
        config=DEFAULT_CAPITAL_SLOT_CONFIG,
        strategy_profile_id="stable",
        cash_ratio=0.82,
    )
    pressured = calculate_slot_units(
        signal,
        price=182.07,
        slot_budget=100000,
        commission_rate=0.00025,
        config=DEFAULT_CAPITAL_SLOT_CONFIG,
        strategy_profile_id="aggressive",
        cash_ratio=0.82,
    )

    assert pressured["cash_pressure_units"] > 0
    assert pressured["slot_units"] > base["slot_units"]


def test_reentry_gate_size_multiplier_reduces_slot_units():
    signal = _fusion_signal("300857", fusion_score=0.60, buy_threshold=0.35, fusion_confidence=0.90, price=180.59)
    downgraded = {
        **signal,
        "strategy_profile": {
            **signal["strategy_profile"],
            "reentry_gate": {
                "status": "downgraded",
                "size_multiplier": 0.5,
            },
        },
    }

    base = calculate_slot_units(
        signal,
        price=180.59,
        slot_budget=100000,
        commission_rate=0.00025,
        config=DEFAULT_CAPITAL_SLOT_CONFIG,
    )
    reduced = calculate_slot_units(
        downgraded,
        price=180.59,
        slot_budget=100000,
        commission_rate=0.00025,
        config=DEFAULT_CAPITAL_SLOT_CONFIG,
    )

    assert reduced["reentry_size_multiplier"] == 0.5
    assert reduced["slot_units"] == max(round(base["slot_units"] * 0.5, 6), reduced["one_lot_floor_units"])


def test_stock_execution_feedback_gate_size_multiplier_reduces_slot_units_once():
    signal = _fusion_signal("300857", fusion_score=0.60, buy_threshold=0.35, fusion_confidence=0.90, price=180.59)
    downgraded = {
        **signal,
        "position_size_pct": signal.get("position_size_pct", 0),
        "strategy_profile": {
            **signal["strategy_profile"],
            "stock_execution_feedback_gate": {
                "status": "downgraded",
                "size_multiplier": 0.5,
            },
        },
    }

    base = calculate_slot_units(
        signal,
        price=180.59,
        slot_budget=100000,
        commission_rate=0.00025,
        config=DEFAULT_CAPITAL_SLOT_CONFIG,
    )
    reduced = calculate_slot_units(
        downgraded,
        price=180.59,
        slot_budget=100000,
        commission_rate=0.00025,
        config=DEFAULT_CAPITAL_SLOT_CONFIG,
    )

    assert reduced["reentry_size_multiplier"] == 0.5
    assert reduced["slot_units"] == max(round(base["slot_units"] * 0.5, 6), reduced["one_lot_floor_units"])


def test_portfolio_execution_guard_size_multiplier_reduces_slot_units_once():
    signal = _fusion_signal("300857", fusion_score=0.60, buy_threshold=0.35, fusion_confidence=0.90, price=180.59)
    downgraded = {
        **signal,
        "strategy_profile": {
            **signal["strategy_profile"],
            "portfolio_execution_guard": {
                "status": "downgraded",
                "size_multiplier": 0.35,
            },
        },
    }

    base = calculate_slot_units(
        signal,
        price=180.59,
        slot_budget=100000,
        commission_rate=0.00025,
        config=DEFAULT_CAPITAL_SLOT_CONFIG,
    )
    reduced = calculate_slot_units(
        downgraded,
        price=180.59,
        slot_budget=100000,
        commission_rate=0.00025,
        config=DEFAULT_CAPITAL_SLOT_CONFIG,
    )

    assert reduced["reentry_size_multiplier"] == 0.35
    assert abs(reduced["slot_units"] - max(round(base["slot_units"] * 0.35, 6), reduced["one_lot_floor_units"])) <= 0.000002


def test_portfolio_execution_guard_zero_multiplier_is_preserved():
    signal = _fusion_signal("300857", fusion_score=0.60, buy_threshold=0.35, fusion_confidence=0.90, price=180.59)
    signal["strategy_profile"]["portfolio_execution_guard"] = {
        "status": "downgraded",
        "size_multiplier": 0.0,
    }

    assert gate_size_multiplier(signal) == 0.0


def test_gate_size_multiplier_preserves_zero_multiplier():
    signal = _fusion_signal("300857", fusion_score=0.60, buy_threshold=0.35, fusion_confidence=0.90, price=180.59)
    signal["strategy_profile"]["stock_execution_feedback_gate"] = {
        "status": "downgraded",
        "size_multiplier": 0.0,
    }

    assert gate_size_multiplier(signal) == 0.0


def test_auto_execute_uses_position_budget_before_slot_allocation(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)
    portfolio = PortfolioService(db_file=db_file)
    portfolio.configure_account(177003.52)

    candidate_service.add_manual_candidate("603669", "灵康药业", "main_force", latest_price=4.56)
    candidate = candidate_service.list_candidates()[0]
    decision = _fusion_signal("603669", fusion_score=0.35454, buy_threshold=0.35, fusion_confidence=0.853971, price=4.56)
    decision["strategy_profile"]["portfolio_execution_guard"] = {
        "status": "downgraded",
        "size_multiplier": 0.25,
    }
    signal = signal_service.create_signal(candidate, decision)

    executed = portfolio.auto_execute_signal(signal, note="position first", executed_at="2026-03-30 10:00:00")

    assert executed is True
    position = portfolio.list_positions()[0]
    assert position["quantity"] == 1900
    metadata = json.loads(portfolio.db.get_trade_history(limit=1)[0]["trade_metadata_json"])
    sizing = metadata["position_sizing"]
    assert sizing["target_position_budget"] == 8850.176
    assert sizing["buy_budget"] == 8850.176
    assert sizing["sizing"]["effective_position_pct"] == 5.0
    assert sizing["sizing"]["slot_units_source"] == "execution_sizing_plan"


def test_auto_execute_high_price_strong_buy_uses_two_slots_and_records_slot_lot_allocation(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)
    portfolio = PortfolioService(db_file=db_file)
    portfolio.configure_account(50000)

    candidate_service.add_manual_candidate("688001", "高价强势股", "main_force", latest_price=260.0)
    candidate = candidate_service.list_candidates()[0]
    signal = signal_service.create_signal(candidate, _fusion_signal("688001", fusion_score=0.72, price=260.0))

    executed = portfolio.auto_execute_signal(signal, note="slot sizing test", executed_at="2026-04-24 10:00:00")

    slots = portfolio.db.get_capital_slots()
    allocations = portfolio.db.get_lot_slot_allocations("688001")
    positions = portfolio.list_positions()

    assert executed is False
    assert positions == []
    assert len(slots) == 2
    assert allocations == []


def test_batch_execution_prioritizes_stronger_buy_signal_when_cash_has_one_slot(tmp_path, monkeypatch):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_manual_candidate("000001", "弱信号", "main_force", latest_price=10.0)
    candidate_service.add_manual_candidate("000002", "强信号", "main_force", latest_price=10.0)

    scheduler = QuantSimScheduler(db_file=db_file)
    scheduler.update_config(enabled=True, auto_execute=True)
    scheduler.portfolio.configure_account(20000)
    monkeypatch.setattr(scheduler, "_is_trading_time", lambda market: True)

    def fake_analyze(candidate, market_snapshot=None, analysis_timeframe="30m", strategy_mode="auto"):
        code = candidate["stock_code"]
        if code == "000001":
            return _fusion_signal(code, fusion_score=0.51, buy_threshold=0.5, fusion_confidence=0.45, price=10.0)
        return _fusion_signal(code, fusion_score=0.75, buy_threshold=0.5, fusion_confidence=0.9, price=10.0)

    monkeypatch.setattr(scheduler.engine.adapter, "analyze_candidate", fake_analyze)

    summary = scheduler.run_once(run_reason="slot_priority_test")
    positions = scheduler.portfolio.list_positions()
    signals = SignalCenterService(db_file=db_file).list_signals(limit=10)

    assert summary["auto_executed"] == 1
    assert positions[0]["stock_code"] == "000002"
    assert any(item["stock_code"] == "000001" and "自动执行跳过" in str(item.get("execution_note") or "") for item in signals)


def test_sell_proceeds_are_settling_and_not_reused_in_same_batch(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)
    portfolio = PortfolioService(db_file=db_file)
    portfolio.configure_account(20000)

    candidate_service.add_manual_candidate("000001", "已有持仓", "main_force", latest_price=10.0)
    candidate_service.add_manual_candidate("000002", "新信号", "main_force", latest_price=10.0)
    old_candidate = candidate_service.db.get_candidate("000001")
    new_candidate = candidate_service.db.get_candidate("000002")
    assert old_candidate and new_candidate

    seed = signal_service.create_signal(old_candidate, _fusion_signal("000001", fusion_score=0.75, price=10.0))
    portfolio.confirm_buy(seed["id"], price=10.0, quantity=1900, note="seed", executed_at="2026-04-23 10:00:00")

    sell_signal = signal_service.create_signal(
        old_candidate,
        {"action": "SELL", "confidence": 90, "reasoning": "卖出释放资金", "position_size_pct": 0, "price": 10.0},
    )
    buy_signal = signal_service.create_signal(new_candidate, _fusion_signal("000002", fusion_score=0.75, price=10.0))

    executed = portfolio.auto_execute_pending_signals([buy_signal, sell_signal], note="same batch", executed_at=datetime(2026, 4, 24, 10, 0))

    slots = portfolio.db.get_capital_slots()
    signals = signal_service.list_signals(limit=10)

    assert executed == 1
    assert portfolio.db.has_open_position("000002") is False
    assert sum(float(item["settling_cash"]) for item in slots) > 0
    assert any(item["stock_code"] == "000002" and "自动执行跳过" in str(item.get("execution_note") or "") for item in signals)
