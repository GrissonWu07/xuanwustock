from app.quant_sim.portfolio_execution_guard import (
    default_portfolio_execution_guard_policy,
    evaluate_portfolio_execution_guard,
    normalize_portfolio_execution_guard_policy,
)
from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.db import QuantSimDB
from app.quant_sim.replay_service import QuantSimReplayService
from app.quant_sim.signal_center_service import SignalCenterService
from app.quant_kernel.models import Decision


def _signal(**overrides):
    payload = {
        "action": "BUY",
        "confidence": 85,
        "tech_score": 0.58,
        "context_score": 0.52,
        "strategy_profile": {
            "selected_strategy_profile": {"id": "stable"},
            "effective_thresholds": {
                "fusion_buy_threshold": 0.35,
            },
            "explainability": {
                "fusion_breakdown": {
                    "fusion_score": 0.52,
                    "buy_threshold_eff": 0.35,
                    "fusion_confidence": 0.86,
                    "tech_score": 0.58,
                    "context_score": 0.52,
                    "volume_ratio": 1.7,
                }
            },
            "market_snapshot": {
                "current_price": 12.0,
                "ma5": 12.2,
                "ma10": 11.8,
                "ma20": 11.3,
                "ma20_slope": 0.02,
                "volume_ratio": 1.7,
                "recent_checkpoints": [
                    {"close": 11.5, "ma20": 11.2, "ma20_slope": 0.01},
                    {"close": 11.8, "ma20": 11.25, "ma20_slope": 0.01},
                    {"close": 12.0, "ma20": 11.3, "ma20_slope": 0.02},
                ],
            },
        },
    }
    payload.update(overrides)
    return payload


def test_policy_defaults_are_profile_specific_and_weights_normalize():
    aggressive = normalize_portfolio_execution_guard_policy(
        {"weight_edge": 4, "weight_trend_structure": 3, "weight_confirmation": 2, "weight_volume": 1, "weight_track_alignment": 0},
        profile_id="aggressive",
    )
    stable = default_portfolio_execution_guard_policy("stable")
    conservative = default_portfolio_execution_guard_policy("conservative")

    assert aggressive["confirm_checkpoints"] == 2
    assert aggressive["full_edge"] == 0.10
    assert aggressive["weak_buy_max_score"] < stable["weak_buy_max_score"] < conservative["weak_buy_max_score"]
    assert aggressive["strong_buy_min_score"] == 0.78
    assert stable["confirm_checkpoints"] == 3
    assert conservative["weak_multiplier"] < stable["weak_multiplier"]
    assert aggressive["weight_edge"] > conservative["weight_edge"]
    assert round(
        aggressive["weight_edge"]
        + aggressive["weight_trend_structure"]
        + aggressive["weight_confirmation"]
        + aggressive["weight_volume"]
        + aggressive["weight_track_alignment"],
        6,
    ) == 1.0


def test_trend_structure_has_middle_score_for_sustained_ma20_confirmation():
    signal = _signal()
    signal["strategy_profile"]["market_snapshot"].update(
        {
            "current_price": 12.0,
            "ma5": 11.7,
            "ma10": 11.8,
            "ma20": 11.3,
            "ma20_slope": 0.0,
            "recent_checkpoints": [
                {"close": 11.5, "ma20": 11.2, "ma20_slope": 0.0},
                {"close": 11.8, "ma20": 11.25, "ma20_slope": 0.0},
                {"close": 12.0, "ma20": 11.3, "ma20_slope": 0.0},
            ],
        }
    )

    gate = evaluate_portfolio_execution_guard(
        signal=signal,
        policy=default_portfolio_execution_guard_policy("stable"),
        portfolio_summary={},
    )

    assert gate["trend_confirmation"]["ma_stack"] is False
    assert gate["trend_confirmation"]["above_ma20_checkpoints"] == 3
    assert gate["score_components"]["trend_structure_score"] == 0.5


def test_strong_buy_requires_score_ma_stack_and_volume_confirmation():
    gate = evaluate_portfolio_execution_guard(
        signal=_signal(),
        policy=default_portfolio_execution_guard_policy("stable"),
        portfolio_summary={},
    )

    assert gate["status"] == "passed"
    assert gate["buy_tier"] == "strong_buy"
    assert gate["buy_tier_label"] == "强买"
    assert gate["buy_strength_score"] > 0.82
    assert gate["trend_confirmation"]["ma_stack"] is True
    assert gate["trend_confirmation"]["volume_confirmed"] == "strong"


def test_late_rebound_is_weak_buy_with_reason_and_clamped_score():
    signal = _signal()
    signal["strategy_profile"]["explainability"]["fusion_breakdown"]["fusion_score"] = 0.39
    signal["strategy_profile"]["market_snapshot"].update(
        {
            "current_price": 12.0,
            "ma5": 11.9,
            "ma10": 12.1,
            "ma20": 11.95,
            "ma20_slope": -0.01,
            "volume_ratio": 0.9,
            "recent_checkpoints": [
                {"close": 11.8, "ma20": 11.9, "ma20_slope": -0.01},
                {"close": 12.0, "ma20": 11.95, "ma20_slope": -0.01},
            ],
        }
    )

    gate = evaluate_portfolio_execution_guard(
        signal=signal,
        policy=default_portfolio_execution_guard_policy("stable"),
        portfolio_summary={},
    )

    assert gate["status"] == "downgraded"
    assert gate["buy_tier"] == "weak_buy"
    assert gate["size_multiplier"] == 0.25
    assert gate["is_late_rebound"] is True
    assert gate["late_rebound_reasons"]
    assert 0.0 <= gate["buy_strength_score"] <= 1.0


def test_cold_start_caps_normal_buy_size_without_blocking_later_adds():
    signal = _signal()
    signal["strategy_profile"]["stock_execution_feedback_gate"] = {
        "sample_count": 0,
        "recent_realized_pnl": 0,
    }
    policy = default_portfolio_execution_guard_policy("stable")
    policy["strong_buy_min_score"] = 0.99
    policy["normal_multiplier"] = 0.8
    policy["cold_start_normal_multiplier"] = 0.35

    gate = evaluate_portfolio_execution_guard(
        signal=signal,
        policy=policy,
        portfolio_summary={},
    )

    assert gate["status"] == "downgraded"
    assert gate["buy_tier"] == "normal_buy"
    assert gate["size_multiplier"] == 0.35
    assert gate["cold_start"]["active"] is True
    assert "冷启动无盈利样本，先轻仓试错" in gate["reasons"]


def test_t1_unconfirmed_a_share_buy_downgrades_to_weak_buy():
    signal = _signal()
    signal["market"] = "A"
    signal["timeframe"] = "30m"
    signal["strategy_profile"]["market_snapshot"]["recent_checkpoints"] = [
        {"close": 12.0, "ma20": 11.9, "ma20_slope": 0.02}
    ]

    gate = evaluate_portfolio_execution_guard(
        signal=signal,
        policy=default_portfolio_execution_guard_policy("stable"),
        portfolio_summary={},
    )

    assert gate["buy_tier"] == "weak_buy"
    assert gate["t1_risk"]["active"] is True
    assert "t1_new_buy_unconfirmed" in gate["reasons"]


def test_retest_confirmation_can_remain_normal_buy_without_full_checkpoint_count():
    signal = _signal()
    signal["market"] = "A"
    signal["timeframe"] = "30m"
    signal["strategy_profile"]["market_snapshot"].update(
        {
            "current_price": 12.0,
            "ma5": 11.4,
            "ma10": 11.5,
            "ma20": 11.2,
            "ma20_slope": 0.02,
            "volume_ratio": 1.7,
            "recent_checkpoints": [
                {"close": 10.9, "low": 10.8, "ma20": 11.0, "ma20_slope": 0.01},
                {"close": 11.4, "low": 11.05, "ma20": 11.1, "ma20_slope": 0.01},
                {"close": 12.0, "low": 11.15, "ma20": 11.2, "ma20_slope": 0.02},
            ],
        }
    )
    policy = default_portfolio_execution_guard_policy("stable")
    policy["strong_buy_min_score"] = 0.99

    gate = evaluate_portfolio_execution_guard(signal=signal, policy=policy, portfolio_summary={})

    assert gate["trend_confirmation"]["retest_confirmed"] is True
    assert gate["trend_confirmation"]["above_ma20_checkpoints"] == 2
    assert gate["score_components"]["confirmation_score"] == 0.75
    assert gate["t1_risk"]["active"] is False
    assert gate["is_late_rebound"] is False
    assert gate["buy_tier"] == "normal_buy"


def test_portfolio_loss_budget_blocks_new_buy_and_exposes_portfolio_reasons():
    gate = evaluate_portfolio_execution_guard(
        signal=_signal(),
        policy=default_portfolio_execution_guard_policy("stable"),
        portfolio_summary={
            "recent_realized_pnl_pct": -3.1,
            "recent_realized_pnl": -3100.0,
            "reference_equity": 100000.0,
            "recent_stop_loss_count": 0,
            "recent_sell_count": 1,
        },
    )

    assert gate["status"] == "blocked"
    assert gate["size_multiplier"] == 0.0
    assert gate["portfolio_guard"]["loss_budget_triggered"] is True
    assert gate["portfolio_guard"]["reasons"]


def test_portfolio_buy_limit_blocks_after_checkpoint_limit():
    gate = evaluate_portfolio_execution_guard(
        signal=_signal(),
        policy=default_portfolio_execution_guard_policy("stable"),
        portfolio_summary={
            "current_checkpoint_buy_count": 1,
            "current_day_buy_count": 1,
            "recent_sell_count": 0,
            "recent_stop_loss_count": 0,
            "reference_equity": 100000.0,
        },
    )

    assert gate["status"] == "blocked"
    assert gate["size_multiplier"] == 0.0
    assert gate["portfolio_guard"]["buy_limit_triggered"] is True
    assert "组合防守：超过本 checkpoint BUY 上限" in gate["portfolio_guard"]["reasons"]


def test_signal_center_stores_portfolio_execution_guard_for_buy(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    candidates = CandidatePoolService(db_file=db_file)
    candidates.add_manual_candidate("300857", "协创数据", "manual", latest_price=12.0)
    candidate = candidates.list_candidates()[0]
    service = SignalCenterService(db_file=db_file)

    signal = service.create_signal(candidate, _signal(), notify=False)

    gate = signal["strategy_profile"]["portfolio_execution_guard"]
    assert signal["action"] == "BUY"
    assert gate["buy_tier"] == "strong_buy"
    assert gate["buy_strength_score"] > 0
    assert gate["portfolio_guard"]["reasons"] == []


def test_signal_center_blocks_buy_when_portfolio_guard_blocks(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    candidates = CandidatePoolService(db_file=db_file)
    candidates.add_manual_candidate("300857", "协创数据", "manual", latest_price=12.0)
    candidate = candidates.list_candidates()[0]
    service = SignalCenterService(db_file=db_file)

    def blocked_summary(*args, **kwargs):
        return {
            "recent_realized_pnl_pct": -3.1,
            "recent_realized_pnl": -3100.0,
            "reference_equity": 100000.0,
            "recent_sell_count": 1,
        }

    service.db.get_portfolio_execution_guard_summary = blocked_summary
    signal = service.create_signal(candidate, _signal(), notify=False)

    gate = signal["strategy_profile"]["portfolio_execution_guard"]
    assert signal["action"] == "HOLD"
    assert gate["status"] == "blocked"
    assert gate["size_multiplier"] == 0.0
    assert gate["portfolio_guard"]["loss_budget_triggered"] is True


def test_signal_center_applies_portfolio_guard_for_position_add(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    service = SignalCenterService(db_file=db_file)
    payload = _signal(decision_type="position_add")
    payload["strategy_profile"]["execution_intent"] = "position_add"

    def blocked_summary(*args, **kwargs):
        return {
            "recent_realized_pnl_pct": -10.0,
            "recent_realized_pnl": -10000.0,
            "reference_equity": 100000.0,
            "recent_sell_count": 2,
        }

    service.db.get_portfolio_execution_guard_summary = blocked_summary
    result = service._apply_portfolio_execution_guard({"stock_code": "300857", "market": "A"}, payload)

    gate = result["strategy_profile"]["portfolio_execution_guard"]

    assert result["action"] == "HOLD"
    assert result["decision_type"] == "portfolio_execution_guard_blocked"
    assert gate["status"] == "blocked"
    assert gate["portfolio_guard"]["loss_budget_triggered"] is True


def test_signal_center_buy_limit_counts_pending_buys_before_execution(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    candidates = CandidatePoolService(db_file=db_file)
    candidates.add_manual_candidate("300857", "协创数据", "manual", latest_price=12.0)
    candidates.add_manual_candidate("300858", "科拓生物", "manual", latest_price=12.0)
    first, second = candidates.list_candidates()[:2]
    service = SignalCenterService(db_file=db_file)
    decision = _signal()

    first_signal = service.create_signal(first, decision, notify=False)
    second_signal = service.create_signal(second, decision, notify=False)

    assert first_signal["action"] == "BUY"
    assert second_signal["action"] == "HOLD"
    assert second_signal["strategy_profile"]["portfolio_execution_guard"]["portfolio_guard"]["buy_limit_triggered"] is True


def test_replay_service_stamps_decision_time_with_checkpoint(tmp_path):
    service = QuantSimReplayService(db_file=tmp_path / "quant_sim.db", replay_db_file=tmp_path / "quant_sim_replay.db")
    decision = Decision(
        code="300857",
        action="BUY",
        confidence=90,
        price=10.0,
        timestamp="real-time-now",
        reason="buy",
    )
    checkpoint = __import__("datetime").datetime(2026, 3, 25, 10, 0, 0)

    stamped = service._with_replay_decision_time(decision, checkpoint)

    assert stamped.timestamp == checkpoint


def test_db_portfolio_execution_guard_summary_uses_recent_live_tables(tmp_path):
    db = QuantSimDB(tmp_path / "quant_sim.db")
    db.configure_account(100000)
    conn = db._connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO sim_trades (
            signal_id, stock_code, stock_name, action, price, quantity,
            amount, gross_amount, commission_fee, sell_tax_fee, net_amount, fee_total,
            trade_metadata_json, realized_pnl, note, executed_at, created_at
        ) VALUES
        (1, '300001', 'A', 'SELL', 10, 100, 1000, 1000, 0, 0, 1000, 0, NULL, -600, 'hard stop loss 止损', '2026-04-03T10:00:00Z', '2026-04-03T10:00:00Z'),
        (2, '300002', 'B', 'SELL', 10, 100, 1000, 1000, 0, 0, 1000, 0, NULL, -500, '止损', '2026-04-04T10:00:00Z', '2026-04-04T10:00:00Z'),
        (3, '300003', 'C', 'SELL', 10, 100, 1000, 1000, 0, 0, 1000, 0, NULL, 300, 'take profit', '2026-04-05T10:00:00Z', '2026-04-05T10:00:00Z')
        """
    )
    cursor.execute(
        """
        INSERT INTO sim_account_snapshots (
            run_reason, initial_cash, available_cash, market_value, total_equity,
            realized_pnl, unrealized_pnl, created_at
        ) VALUES
        ('test', 100000, 100000, 10000, 110000, 0, 0, '2026-04-03T10:00:00Z'),
        ('test', 100000, 90000, 10000, 100000, -800, 0, '2026-04-05T10:00:00Z')
        """
    )
    cursor.execute(
        """
        INSERT INTO sim_trades (
            signal_id, stock_code, stock_name, action, price, quantity,
            amount, gross_amount, commission_fee, sell_tax_fee, net_amount, fee_total,
            trade_metadata_json, realized_pnl, note, executed_at, created_at
        ) VALUES
        (4, '300004', 'D', 'BUY', 10, 100, 1000, 1000, 0, 0, 1000, 0, NULL, 0, '建仓', '2026-04-05T10:00:00Z', '2026-04-05T10:00:00Z'),
        (5, '300005', 'E', 'BUY', 10, 100, 1000, 1000, 0, 0, 1000, 0, NULL, 0, '建仓', '2026-04-05T11:00:00Z', '2026-04-05T11:00:00Z')
        """
    )
    conn.commit()
    conn.close()

    summary = db.get_portfolio_execution_guard_summary(
        as_of="2026-04-05T10:00:00Z",
        lookback_checkpoints=10,
        lookback_days=5,
    )

    assert summary["recent_sell_count"] == 3
    assert summary["recent_stop_loss_count"] == 2
    assert summary["consecutive_stop_loss_count"] == 0
    assert summary["recent_realized_pnl"] == -800
    assert summary["recent_realized_pnl_pct"] < 0
    assert summary["portfolio_drawdown_pct"] == 9.0909
    assert summary["reference_equity"] == 100000
    assert summary["current_checkpoint_buy_count"] == 1
    assert summary["current_day_buy_count"] == 1
    assert summary["pending_buy_count"] == 0
