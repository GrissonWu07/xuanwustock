from __future__ import annotations

from app.quant_sim.db import QuantSimDB
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.signal_center_service import SignalCenterService
from app.quant_sim.stock_execution_feedback import evaluate_stock_execution_feedback_gate


def _policy(**overrides):
    return {
        "enabled": True,
        "lookback_days": 20,
        "stop_loss_count_threshold": 2,
        "stop_loss_cooldown_days": 12,
        "loss_pnl_pct_threshold": -5.0,
        "loss_amount_threshold": -1000.0,
        "loss_reentry_size_multiplier": 0.35,
        "repeated_stop_size_multiplier": 0.25,
        "require_trend_confirmation": True,
        "trend_confirm_checkpoints": 2,
        "require_ma20_slope": True,
        "allow_ma_stack_confirmation": True,
        "allow_ma20_retest_confirmation": True,
        "execution_feedback_score_cap": 0.25,
        **overrides,
    }


def _snapshot(**overrides):
    return {
        "current_price": 10.0,
        "ma5": 9.8,
        "ma10": 9.9,
        "ma20": 10.1,
        "ma20_slope": -0.01,
        **overrides,
    }


def _strict_trend_snapshot(**overrides):
    return _snapshot(
        current_price=12.0,
        ma5=11.8,
        ma10=11.5,
        ma20=11.0,
        ma20_slope=0.03,
        volume_ratio=1.8,
        recent_checkpoints=[
            {"close": 11.3, "low": 11.05, "ma20": 11.0, "ma20_slope": 0.01},
            {"close": 11.4, "low": 11.1, "ma20": 11.05, "ma20_slope": 0.02},
            {"close": 12.0, "low": 11.2, "ma20": 11.1, "ma20_slope": 0.03},
        ],
        **overrides,
    )


def test_feedback_gate_blocks_repeated_stop_without_trend_confirmation():
    gate = evaluate_stock_execution_feedback_gate(
        action="BUY",
        stock_code="300857",
        policy=_policy(),
        summary={
            "stock_code": "300857",
            "lookback_days": 20,
            "recent_stop_loss_count": 2,
            "recent_realized_pnl": -2500,
            "recent_realized_pnl_pct": -12,
        },
        market_snapshot=_snapshot(),
        current_time="2026-01-10 10:00:00",
    )

    assert gate["status"] == "blocked"
    assert gate["size_multiplier"] == 0
    assert gate["trend_confirmed"] is False
    assert gate["execution_feedback_score"] < 0


def test_feedback_gate_downgrades_repeated_stop_when_trend_is_confirmed():
    snapshot = _strict_trend_snapshot()
    gate = evaluate_stock_execution_feedback_gate(
        action="BUY",
        stock_code="300857",
        policy=_policy(),
        summary={
            "stock_code": "300857",
            "lookback_days": 20,
            "recent_stop_loss_count": 2,
            "recent_realized_pnl": -300,
            "recent_realized_pnl_pct": -1.5,
        },
        market_snapshot=snapshot,
        current_time="2026-01-10 10:00:00",
    )

    assert gate["status"] == "downgraded"
    assert gate["size_multiplier"] == 0.25
    assert gate["trend_confirmed"] is True


def test_feedback_gate_blocks_loss_reentry_when_only_ma_stack_is_confirmed():
    gate = evaluate_stock_execution_feedback_gate(
        action="BUY",
        stock_code="300857",
        policy=_policy(),
        summary={
            "stock_code": "300857",
            "lookback_days": 20,
            "recent_loss_trade_count": 1,
            "recent_realized_pnl": -300,
            "recent_realized_pnl_pct": -2.5,
        },
        market_snapshot=_snapshot(current_price=12.0, ma5=11.5, ma10=11.0, ma20=10.5, ma20_slope=0.02),
        current_time="2026-01-10 10:00:00",
    )

    assert gate["status"] == "blocked"
    assert gate["trend_confirmed"] is False
    assert "缺少强趋势确认" in gate["reasons"]


def test_feedback_gate_downgrades_recent_realized_loss():
    gate = evaluate_stock_execution_feedback_gate(
        action="BUY",
        stock_code="300857",
        policy=_policy(loss_reentry_size_multiplier=0.4),
        summary={
            "stock_code": "300857",
            "lookback_days": 20,
            "recent_stop_loss_count": 0,
            "recent_realized_pnl": -1200,
            "recent_realized_pnl_pct": -6,
        },
        market_snapshot=_snapshot(current_price=12.0, ma5=11.5, ma10=11.0, ma20=10.5, ma20_slope=0.02),
        current_time="2026-01-10 10:00:00",
    )

    assert gate["status"] == "downgraded"
    assert gate["size_multiplier"] == 0.4
    assert gate["recent_loss_trade_count"] == 0


def test_feedback_gate_blocks_recent_loss_reentry_without_trend_confirmation():
    gate = evaluate_stock_execution_feedback_gate(
        action="BUY",
        stock_code="300857",
        policy=_policy(stop_loss_cooldown_days=8),
        summary={
            "stock_code": "300857",
            "lookback_days": 20,
            "recent_loss_trade_count": 1,
            "recent_realized_pnl": -300,
            "recent_realized_pnl_pct": -2.5,
            "last_loss_sell_at": "2026-01-05 10:00:00",
        },
        market_snapshot=_snapshot(),
        current_time="2026-01-08 10:00:00",
    )

    assert gate["status"] == "blocked"
    assert gate["size_multiplier"] == 0
    assert gate["loss_reentry_cooldown_active"] is True
    assert "缺少强趋势确认" in gate["reasons"]


def test_feedback_gate_does_not_block_weak_buy_history_without_loss():
    gate = evaluate_stock_execution_feedback_gate(
        action="BUY",
        stock_code="300857",
        policy=_policy(),
        summary={
            "stock_code": "300857",
            "recent_weak_buy_count": 1,
            "last_weak_buy_at": "2026-01-05 10:00:00",
        },
        market_snapshot=_snapshot(),
        current_time="2026-01-08 10:00:00",
    )

    assert gate["status"] == "passed"
    assert gate["recent_loss_trade_count"] == 0
    assert gate["recent_weak_buy_count"] == 1
    assert gate["weak_buy_reentry_active"] is False


def test_feedback_gate_uses_stop_loss_cooldown_days():
    gate = evaluate_stock_execution_feedback_gate(
        action="BUY",
        stock_code="300857",
        policy=_policy(stop_loss_cooldown_days=3),
        summary={
            "stock_code": "300857",
            "lookback_days": 20,
            "recent_stop_loss_count": 2,
            "recent_realized_pnl": -300,
            "recent_realized_pnl_pct": -1.5,
            "last_stop_loss_at": "2026-01-01 10:00:00",
        },
        market_snapshot=_snapshot(),
        current_time="2026-01-10 10:00:00",
    )

    assert gate["status"] == "passed"
    assert gate["stop_loss_cooldown_active"] is False


def _seed_stop_loss_round(portfolio: PortfolioService, signals: SignalCenterService, code: str, buy_time: str, sell_time: str) -> None:
    candidate = {"stock_code": code, "stock_name": "协创数据", "source": "main_force"}
    buy = signals.create_signal(candidate, {"action": "BUY", "confidence": 90, "position_size_pct": 50, "reasoning": "buy"}, notify=False)
    portfolio.confirm_buy(buy["id"], price=100.0, quantity=100, note="seed", executed_at=buy_time)
    sell = signals.create_signal(
        candidate,
        {
            "action": "SELL",
            "confidence": 90,
            "position_size_pct": 100,
            "reasoning": "stop",
            "decision_type": "hard_stop_loss",
            "strategy_profile": {
                "explainability": {
                    "fusion_breakdown": {
                        "veto_id": "hard_stop_loss",
                        "veto_trigger_type": "hard_stop_loss",
                    }
                }
            },
        },
        notify=False,
    )
    portfolio.confirm_sell(sell["id"], price=90.0, quantity=100, note="止损", executed_at=sell_time)


def test_signal_center_applies_live_stock_feedback_gate(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    portfolio = PortfolioService(db_file=db_file)
    signals = SignalCenterService(db_file=db_file)
    portfolio.configure_account(100000)
    _seed_stop_loss_round(portfolio, signals, "300857", "2026-01-01 10:00:00", "2026-01-05 10:00:00")
    _seed_stop_loss_round(portfolio, signals, "300857", "2026-01-06 10:00:00", "2026-01-07 10:00:00")

    blocked = signals.create_signal(
        {"stock_code": "300857", "stock_name": "协创数据", "source": "main_force"},
        {
            "action": "BUY",
            "confidence": 88,
            "position_size_pct": 50,
            "reasoning": "retry",
            "decision_time": "2026-01-08 10:00:00",
            "strategy_profile": {
                "stock_execution_feedback_policy": _policy(),
                "market_snapshot": _snapshot(),
            },
        },
        notify=False,
    )

    assert blocked["action"] == "HOLD"
    assert blocked["position_size_pct"] == 0
    assert blocked["strategy_profile"]["stock_execution_feedback_gate"]["status"] == "blocked"


def test_signal_center_allows_loss_reentry_with_strong_trend_when_previous_buy_was_not_weak(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    portfolio = PortfolioService(db_file=db_file)
    signals = SignalCenterService(db_file=db_file)
    portfolio.configure_account(100000)
    _seed_stop_loss_round(portfolio, signals, "300857", "2026-01-01 10:00:00", "2026-01-05 10:00:00")
    signals.db.get_portfolio_execution_guard_summary = lambda *args, **kwargs: {
        "recent_realized_pnl_pct": 0.0,
        "recent_realized_pnl": 0.0,
        "reference_equity": 100000.0,
        "recent_stop_loss_count": 0,
        "recent_sell_count": 0,
        "current_checkpoint_buy_count": 0,
        "current_day_buy_count": 0,
    }

    weak_retry = signals.create_signal(
        {"stock_code": "300857", "stock_name": "协创数据", "source": "main_force", "market": "A"},
        {
            "action": "BUY",
            "confidence": 88,
            "position_size_pct": 50,
            "reasoning": "weak retry",
            "decision_time": "2026-01-08 10:00:00",
            "market": "A",
            "timeframe": "30m",
            "strategy_profile": {
                "stock_execution_feedback_policy": _policy(loss_amount_threshold=-1000, loss_reentry_size_multiplier=0.5),
                "portfolio_execution_guard_policy": {
                    "enabled": True,
                    "max_new_buys_per_checkpoint": 10,
                    "max_new_buys_per_day": 10,
                },
                "effective_thresholds": {"fusion_buy_threshold": 0.35},
                "explainability": {
                    "fusion_breakdown": {
                        "fusion_score": 0.37,
                        "buy_threshold_eff": 0.35,
                        "tech_score": 0.58,
                        "context_score": 0.56,
                    }
                },
                "market_snapshot": _strict_trend_snapshot(),
            },
        },
        notify=False,
    )

    assert weak_retry["action"] == "BUY"
    stock_gate = weak_retry["strategy_profile"]["stock_execution_feedback_gate"]
    portfolio_gate = weak_retry["strategy_profile"]["portfolio_execution_guard"]
    assert stock_gate["status"] == "downgraded"
    assert stock_gate["trend_confirmed"] is True
    assert portfolio_gate["buy_tier"] == "weak_buy"
    assert portfolio_gate["status"] == "downgraded"
    assert "弱买亏损后再买需要强趋势确认" not in portfolio_gate["reasons"]


def test_signal_center_allows_profitable_weak_buy_reentry_without_loss(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    portfolio = PortfolioService(db_file=db_file)
    signals = SignalCenterService(db_file=db_file)
    portfolio.configure_account(100000)
    candidate = {"stock_code": "300857", "stock_name": "协创数据", "source": "main_force"}
    weak_buy = signals.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 80,
            "position_size_pct": 25,
            "reasoning": "weak seed",
            "decision_time": "2026-01-05 10:00:00",
            "strategy_profile": {
                "portfolio_execution_guard_policy": {"enabled": False},
                "portfolio_execution_guard": {
                    "buy_tier": "weak_buy",
                    "buy_tier_label": "弱买",
                    "buy_strength_score": 0.42,
                },
            },
        },
        notify=False,
    )
    portfolio.confirm_buy(weak_buy["id"], price=100.0, quantity=100, note="weak buy seed", executed_at="2026-01-05 10:00:00")
    sell = signals.create_signal(
        candidate,
        {"action": "SELL", "confidence": 80, "position_size_pct": 100, "reasoning": "profit sell"},
        notify=False,
    )
    portfolio.confirm_sell(sell["id"], price=105.0, quantity=100, note="止盈", executed_at="2026-01-06 10:00:00")

    retry = signals.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 88,
            "position_size_pct": 50,
            "reasoning": "retry after weak buy",
            "decision_time": "2026-02-10 10:00:00",
            "strategy_profile": {
                "stock_execution_feedback_policy": _policy(),
                "market_snapshot": _snapshot(),
            },
        },
        notify=False,
    )

    assert retry["action"] == "BUY"
    gate = retry["strategy_profile"].get("stock_execution_feedback_gate")
    assert gate is None or gate["status"] != "blocked"


def test_portfolio_guard_blocks_current_weak_buy_after_previous_weak_buy_loss():
    signal = {
        "action": "BUY",
        "confidence": 88,
        "tech_score": 0.58,
        "context_score": 0.52,
        "market": "A",
        "timeframe": "30m",
        "strategy_profile": {
            "selected_strategy_profile": {"id": "stable"},
            "effective_thresholds": {"fusion_buy_threshold": 0.35},
            "stock_execution_feedback_gate": {
                "status": "passed",
                "last_buy_was_weak": True,
                "loss_after_last_buy_count": 1,
                "trend_confirmed": False,
                "trend_confirmation": {"confirmed": False, "mode": "weak_or_unconfirmed"},
            },
            "explainability": {
                "fusion_breakdown": {
                    "fusion_score": 0.37,
                    "buy_threshold_eff": 0.35,
                    "tech_score": 0.58,
                    "context_score": 0.52,
                }
            },
            "market_snapshot": _snapshot(volume_ratio=1.0),
        },
    }

    from app.quant_sim.portfolio_execution_guard import default_portfolio_execution_guard_policy, evaluate_portfolio_execution_guard

    gate = evaluate_portfolio_execution_guard(
        signal=signal,
        policy=default_portfolio_execution_guard_policy("stable"),
        portfolio_summary={
            "recent_realized_pnl_pct": 0.0,
            "recent_realized_pnl": 0.0,
            "reference_equity": 100000.0,
            "recent_stop_loss_count": 0,
            "recent_sell_count": 0,
        },
    )

    assert gate["buy_tier"] == "weak_buy"
    assert gate["status"] == "blocked"
    assert "弱买亏损后再买需要强趋势确认" in gate["reasons"]


def test_signal_center_records_previous_weak_buy_loss_context(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    portfolio = PortfolioService(db_file=db_file)
    signals = SignalCenterService(db_file=db_file)
    portfolio.configure_account(100000)
    candidate = {"stock_code": "300857", "stock_name": "协创数据", "source": "main_force"}
    weak_buy = signals.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 80,
            "position_size_pct": 25,
            "reasoning": "weak seed",
            "decision_time": "2026-01-05 10:00:00",
            "strategy_profile": {
                "portfolio_execution_guard_policy": {"enabled": False},
                "portfolio_execution_guard": {
                    "buy_tier": "weak_buy",
                    "buy_tier_label": "弱买",
                    "buy_strength_score": 0.42,
                },
            },
        },
        notify=False,
    )
    portfolio.confirm_buy(weak_buy["id"], price=100.0, quantity=100, note="weak buy seed", executed_at="2026-01-05 10:00:00")
    sell = signals.create_signal(
        candidate,
        {"action": "SELL", "confidence": 80, "position_size_pct": 100, "reasoning": "loss sell"},
        notify=False,
    )
    portfolio.confirm_sell(sell["id"], price=95.0, quantity=100, note="亏损卖出", executed_at="2026-01-06 10:00:00")

    summary = signals.db.get_stock_execution_feedback_summary(
        "300857",
        as_of="2026-02-10 10:00:00",
        lookback_days=20,
    )

    assert summary["last_buy_was_weak"] is True
    assert summary["loss_after_last_buy_count"] == 1
    assert summary["recent_loss_trade_count"] == 0


def test_signal_center_blocks_generic_loss_reentry_without_trend_confirmation(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    portfolio = PortfolioService(db_file=db_file)
    signals = SignalCenterService(db_file=db_file)
    portfolio.configure_account(100000)
    candidate = {"stock_code": "300857", "stock_name": "协创数据", "source": "main_force"}
    buy = signals.create_signal(candidate, {"action": "BUY", "confidence": 90, "position_size_pct": 50, "reasoning": "buy"}, notify=False)
    portfolio.confirm_buy(buy["id"], price=100.0, quantity=100, note="seed", executed_at="2026-01-05 10:00:00")
    sell = signals.create_signal(
        candidate,
        {"action": "SELL", "confidence": 90, "position_size_pct": 100, "reasoning": "ordinary sell"},
        notify=False,
    )
    portfolio.confirm_sell(sell["id"], price=96.0, quantity=100, note="普通卖出亏损", executed_at="2026-01-06 10:00:00")

    blocked = signals.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 88,
            "position_size_pct": 50,
            "reasoning": "retry",
            "decision_time": "2026-01-08 10:00:00",
            "strategy_profile": {
                "stock_execution_feedback_policy": _policy(stop_loss_cooldown_days=8),
                "market_snapshot": _snapshot(),
            },
        },
        notify=False,
    )

    assert blocked["action"] == "HOLD"
    gate = blocked["strategy_profile"]["stock_execution_feedback_gate"]
    assert gate["status"] == "blocked"
    assert gate["recent_loss_trade_count"] == 1
    assert gate["recent_stop_loss_count"] == 0


def test_signal_center_records_downgrade_without_pre_scaling_position_size(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    portfolio = PortfolioService(db_file=db_file)
    signals = SignalCenterService(db_file=db_file)
    portfolio.configure_account(100000)
    _seed_stop_loss_round(portfolio, signals, "300857", "2026-01-01 10:00:00", "2026-01-05 10:00:00")

    downgraded = signals.create_signal(
        {"stock_code": "300857", "stock_name": "协创数据", "source": "main_force"},
        {
            "action": "BUY",
            "confidence": 88,
            "position_size_pct": 50,
            "reasoning": "retry",
            "decision_time": "2026-01-08 10:00:00",
                "strategy_profile": {
                    "stock_execution_feedback_policy": _policy(loss_amount_threshold=-1000, loss_reentry_size_multiplier=0.5),
                    "portfolio_execution_guard_policy": {"enabled": False},
                    "market_snapshot": _strict_trend_snapshot(),
                },
            },
        notify=False,
    )

    assert downgraded["action"] == "BUY"
    assert downgraded["position_size_pct"] == 50
    gate = downgraded["strategy_profile"]["stock_execution_feedback_gate"]
    assert gate["status"] == "downgraded"
    assert gate["size_multiplier"] == 0.5


def test_signal_center_feedback_uses_market_snapshot_time_before_runtime_decision_time(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    portfolio = PortfolioService(db_file=db_file)
    signals = SignalCenterService(db_file=db_file)
    portfolio.configure_account(100000)
    _seed_stop_loss_round(portfolio, signals, "300857", "2026-03-18 10:00:00", "2026-03-20 10:00:00")

    downgraded = signals.create_signal(
        {"stock_code": "300857", "stock_name": "Xiechuang Data", "source": "main_force"},
        {
            "action": "BUY",
            "confidence": 88,
            "position_size_pct": 50,
            "reasoning": "replay retry",
            "decision_time": "2026-05-04 15:55:00",
            "strategy_profile": {
                "stock_execution_feedback_policy": _policy(
                    lookback_days=15,
                    loss_amount_threshold=-1000,
                    loss_reentry_size_multiplier=0.5,
                ),
                "market_snapshot": _strict_trend_snapshot(update_time="2026-03-25 10:00:00"),
            },
        },
        notify=False,
    )

    gate = downgraded["strategy_profile"]["stock_execution_feedback_gate"]
    assert gate["status"] == "downgraded"
    assert gate["size_multiplier"] == 0.5
    assert gate["evaluated_at"] == "2026-03-25 10:00:00"


def test_replay_temp_db_feedback_is_isolated_from_live_db(tmp_path):
    live_db = tmp_path / "live.db"
    replay_db = tmp_path / "replay.db"
    live_portfolio = PortfolioService(db_file=live_db)
    live_signals = SignalCenterService(db_file=live_db)
    replay_portfolio = PortfolioService(db_file=replay_db)
    replay_signals = SignalCenterService(db_file=replay_db)
    live_portfolio.configure_account(100000)
    replay_portfolio.configure_account(100000)
    _seed_stop_loss_round(live_portfolio, live_signals, "300857", "2026-01-01 10:00:00", "2026-01-05 10:00:00")
    _seed_stop_loss_round(live_portfolio, live_signals, "300857", "2026-01-06 10:00:00", "2026-01-07 10:00:00")

    live_summary = QuantSimDB(live_db).get_stock_execution_feedback_summary("300857", as_of="2026-01-08 10:00:00")
    replay_summary = QuantSimDB(replay_db).get_stock_execution_feedback_summary("300857", as_of="2026-01-08 10:00:00")

    assert live_summary["recent_stop_loss_count"] == 2
    assert replay_summary["recent_stop_loss_count"] == 0

    replay_signal = replay_signals.create_signal(
        {"stock_code": "300857", "stock_name": "协创数据", "source": "main_force"},
        {
            "action": "BUY",
            "confidence": 88,
            "position_size_pct": 50,
            "reasoning": "replay retry",
            "decision_time": "2026-01-08 10:00:00",
            "strategy_profile": {
                "stock_execution_feedback_policy": _policy(),
                "market_snapshot": _snapshot(),
            },
        },
        notify=False,
    )

    assert replay_signal["action"] == "BUY"
    assert "stock_execution_feedback_gate" not in replay_signal["strategy_profile"]
