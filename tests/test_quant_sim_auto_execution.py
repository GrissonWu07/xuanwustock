from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.db import QuantSimDB, QuantSimReplayDB
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.scheduler import QuantSimScheduler
from app.quant_sim.signal_center_service import SignalCenterService
from app.watchlist_integration import add_watchlist_rows_to_quant_pool
from app.watchlist_service import WatchlistService


def test_auto_execute_uses_execution_sizing_final_budget(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=400000)
    CandidatePoolService(db_file=db_path).add_manual_candidate("000001", "平安银行", "manual", latest_price=10.0)
    signal_id = db.add_signal(
        {
            "stock_code": "000001",
            "stock_name": "平安银行",
            "action": "BUY",
            "confidence": 80,
            "reasoning": "test",
            "position_size_pct": 50,
            "stop_loss_pct": 5,
            "take_profit_pct": 12,
            "decision_type": "dual_track_weighted_buy",
            "strategy_profile": {
                "portfolio_execution_guard": {"status": "downgraded", "buy_tier": "weak_buy"},
                "execution_sizing_plan": {
                    "final_budget": 12000.0,
                    "effective_position_pct": 3.0,
                    "buy_tier": "weak_buy",
                },
            },
            "status": "pending",
        }
    )

    service = PortfolioService(db_file=db_path)
    executed = service.auto_execute_signal(db.get_signal(signal_id), executed_at="2026-01-05T10:00:00Z")

    assert executed is True
    trade = db.get_trade_history(limit=1)[0]
    assert trade["quantity"] == 1100
    assert trade["gross_amount"] <= 12000


def test_auto_execute_success_persists_buy_sizing_diagnostics(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=100000)
    CandidatePoolService(db_file=db_path).add_manual_candidate("000001", "平安银行", "manual", latest_price=10.0)
    signal_id = db.add_signal(
        {
            "stock_code": "000001",
            "stock_name": "平安银行",
            "action": "BUY",
            "confidence": 80,
            "reasoning": "test",
            "position_size_pct": 3,
            "stop_loss_pct": 5,
            "take_profit_pct": 12,
            "decision_type": "dual_track_weighted_buy",
            "strategy_profile": {
                "portfolio_execution_guard": {"status": "downgraded", "buy_tier": "weak_buy"},
                "execution_sizing_plan": {
                    "buy_tier": "weak_buy",
                    "final_budget": 3000.0,
                    "effective_position_pct": 3.0,
                    "risk_budget_pct": 0.3,
                    "expected_stop_loss_pct": 5.0,
                },
            },
            "status": "pending",
        }
    )

    service = PortfolioService(db_file=db_path)
    executed = service.auto_execute_signal(db.get_signal(signal_id), executed_at="2026-01-05T10:00:00Z")
    signal = db.get_signal(signal_id)

    assert executed is True
    assert signal["status"] == "executed"
    assert signal["execution_diagnostics"]["blocked_reason"] == ""
    assert signal["execution_diagnostics"]["sizing"]["quantity"] == 200
    assert signal["execution_diagnostics"]["sizing"]["sizing"]["buy_tier"] == "weak_buy"


def test_auto_execute_confirmed_recovery_allows_one_lot_within_account_cap(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=100000)
    CandidatePoolService(db_file=db_path).add_manual_candidate("301369", "联动科技", "manual", latest_price=136.52)
    db.upsert_quant_universe_state("301369", {"stock_name": "联动科技", "quant_status": "trial", "health_score": 70})
    signal_id = db.add_signal(
        {
            "stock_code": "301369",
            "stock_name": "联动科技",
            "action": "BUY",
            "confidence": 82,
            "reasoning": "confirmed recovery normal buy",
            "position_size_pct": 9.0,
            "stop_loss_pct": 5,
            "take_profit_pct": 12,
            "price": 136.52,
            "decision_type": "dual_track_weighted_buy",
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "portfolio_execution_guard": {
                    "status": "passed",
                    "buy_tier": "normal_buy",
                    "buy_strength_score": 0.73,
                },
                "lifecycle_gate": {"mode": "recovery_probe_confirmed"},
                "execution_sizing_plan": {
                    "buy_tier": "normal_buy",
                    "final_budget": 9000.0,
                    "effective_position_pct": 9.0,
                    "account_equity_tier_cap_pct": 15.0,
                    "one_lot_cost": 13652.0,
                    "lifecycle_gate_mode": "recovery_probe_confirmed",
                    "skip_reason": None,
                },
                "quant_status": "trial",
            },
            "status": "pending",
        }
    )

    service = PortfolioService(db_file=db_path)
    executed = service.auto_execute_signal(db.get_signal(signal_id), executed_at="2026-02-27T10:00:00Z")

    assert executed is True
    trade = db.get_trade_history(limit=1)[0]
    assert trade["stock_code"] == "301369"
    assert trade["quantity"] == 100
    signal = db.get_signal(signal_id)
    sizing = signal["strategy_profile"]["position_sizing"]
    assert sizing["one_lot_floor_override"] is True
    assert sizing["quantity"] == 100


def test_auto_execute_quality_limited_strong_recovery_allows_high_quality_one_lot(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=400000)
    CandidatePoolService(db_file=db_path).add_manual_candidate("603986", "兆易创新", "manual", latest_price=265.09)
    db.upsert_quant_universe_state("603986", {"stock_name": "兆易创新", "quant_status": "trial", "health_score": 70})
    signal_id = db.add_signal(
        {
            "stock_code": "603986",
            "stock_name": "兆易创新",
            "action": "BUY",
            "confidence": 92,
            "reasoning": "quality limited strong recovery",
            "position_size_pct": 3.0,
            "stop_loss_pct": 5,
            "take_profit_pct": 12,
            "price": 265.09,
            "decision_type": "dual_track_weighted_buy",
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "market_snapshot": {"rsi": 76.94},
                "portfolio_execution_guard": {
                    "status": "passed",
                    "buy_tier": "strong_buy",
                    "buy_strength_score": 0.911665,
                    "score_components": {"edge_strength": 1.0, "confirmation_score": 1.0},
                    "trend_confirmation": {"recent_5d_return": 0.064191},
                },
                "lifecycle_gate": {"mode": "recovery_probe_quality_limited"},
                "execution_sizing_plan": {
                    "buy_tier": "strong_buy",
                    "final_budget": 11809.0,
                    "effective_position_pct": 3.0,
                    "account_equity_tier_cap_pct": 12.5,
                    "one_lot_cost": 26509.0,
                    "lifecycle_gate_mode": "recovery_probe_quality_limited",
                    "skip_reason": None,
                },
                "quant_status": "trial",
            },
            "status": "pending",
        }
    )

    executed = PortfolioService(db_file=db_path).auto_execute_signal(
        db.get_signal(signal_id),
        executed_at="2026-04-10 15:00:00",
    )

    assert executed is True
    trade = db.get_trade_history(limit=1)[0]
    assert trade["stock_code"] == "603986"
    assert trade["quantity"] == 100
    signal = db.get_signal(signal_id)
    assert signal["strategy_profile"]["position_sizing"]["one_lot_floor_override"] is True


def test_auto_execute_quality_limited_recovery_does_not_allow_overheated_one_lot(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=400000)
    CandidatePoolService(db_file=db_path).add_manual_candidate("300508", "维宏股份", "manual", latest_price=250.0)
    db.upsert_quant_universe_state("300508", {"stock_name": "维宏股份", "quant_status": "trial", "health_score": 70})
    signal_id = db.add_signal(
        {
            "stock_code": "300508",
            "stock_name": "维宏股份",
            "action": "BUY",
            "confidence": 92,
            "reasoning": "overextended quality limited recovery",
            "position_size_pct": 3.0,
            "stop_loss_pct": 5,
            "take_profit_pct": 12,
            "price": 250.0,
            "decision_type": "dual_track_weighted_buy",
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "market_snapshot": {"rsi": 74.0},
                "portfolio_execution_guard": {
                    "status": "passed",
                    "buy_tier": "strong_buy",
                    "buy_strength_score": 0.95,
                    "score_components": {"edge_strength": 1.0, "confirmation_score": 1.0},
                    "trend_confirmation": {"recent_5d_return": 0.1495},
                },
                "lifecycle_gate": {"mode": "recovery_probe_quality_limited"},
                "execution_sizing_plan": {
                    "buy_tier": "strong_buy",
                    "final_budget": 11500.0,
                    "effective_position_pct": 3.0,
                    "account_equity_tier_cap_pct": 12.5,
                    "one_lot_cost": 25000.0,
                    "lifecycle_gate_mode": "recovery_probe_quality_limited",
                    "skip_reason": None,
                },
                "quant_status": "trial",
            },
            "status": "pending",
        }
    )

    executed = PortfolioService(db_file=db_path).auto_execute_signal(
        db.get_signal(signal_id),
        executed_at="2026-05-08 10:00:00",
    )

    assert executed is False
    signal = db.get_signal(signal_id)
    assert signal["status"] == "pending"
    assert "不足买入一手" in str(signal["execution_note"])
    assert signal["execution_diagnostics"]["blocked_reason"] == "sizing_skip"


def test_auto_execute_pending_signals_applies_checkpoint_trial_risk_budget(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=100000)
    candidate_service = CandidatePoolService(db_file=db_path)
    for code in ("000001", "000002", "000003"):
        candidate_service.add_manual_candidate(code, code, "manual", latest_price=10.0)
        db.upsert_quant_universe_state(code, {"quant_status": "trial", "health_score": 100})

    signal_ids = []
    for index, code in enumerate(("000001", "000002", "000003"), start=1):
        signal_ids.append(
            db.add_signal(
                {
                    "stock_code": code,
                    "stock_name": code,
                    "action": "BUY",
                    "confidence": 90 - index,
                    "reasoning": "trial weak",
                    "position_size_pct": 6.0,
                    "stop_loss_pct": 5,
                    "take_profit_pct": 12,
                    "decision_type": "dual_track_weighted_buy",
                    "strategy_profile": {
                        "selected_strategy_profile": {"id": "aggressive"},
                        "portfolio_execution_guard": {
                            "status": "downgraded",
                            "buy_tier": "weak_buy",
                            "buy_strength_score": 0.6,
                        },
                        "execution_sizing_plan": {
                            "buy_tier": "weak_buy",
                            "final_budget": 6000.0,
                            "risk_budget_pct": 0.30,
                            "effective_position_pct": 6.0,
                            "expected_stop_loss_pct": 5.0,
                        },
                        "quant_status": "trial",
                    },
                    "status": "pending",
                }
            )
        )

    portfolio = PortfolioService(db_file=db_path)
    pending = [db.get_signal(signal_id) for signal_id in signal_ids]
    executed = portfolio.auto_execute_pending_signals(pending, executed_at="2026-01-05T10:00:00Z")

    assert executed == 2
    signals = {item["stock_code"]: item for item in db.get_signals(limit=10)}
    skipped = [item for item in signals.values() if "checkpoint_buy_count_limit_hit" in str(item.get("execution_note") or "")]
    assert len(skipped) == 1
    skip_profile = skipped[0]["strategy_profile"]
    assert skip_profile["auto_execution_skip"]["blocked_reason"] == "batch_execution_cap"
    assert skip_profile["auto_execution_skip"]["cap_reason"] == "checkpoint_buy_count_limit_hit"
    assert skipped[0]["execution_diagnostics"]["batch_cap"]["reason_code"] == "checkpoint_buy_count_limit_hit"
    assert skipped[0]["execution_diagnostics"]["sizing"]["sizing"]["buy_tier"] == "weak_buy"


def test_replay_signals_persist_structured_ignored_execution_reason(tmp_path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=100000)
    CandidatePoolService(db_file=db_path).add_manual_candidate("000001", "平安银行", "manual", latest_price=10.0)
    db.upsert_quant_universe_state("000001", {"quant_status": "trial", "health_score": 100})
    signal_id = db.add_signal(
        {
            "stock_code": "000001",
            "stock_name": "平安银行",
            "action": "BUY",
            "confidence": 90,
            "reasoning": "trial weak",
            "position_size_pct": 6.0,
            "stop_loss_pct": 5,
            "take_profit_pct": 12,
            "decision_type": "dual_track_weighted_buy",
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "portfolio_execution_guard": {
                    "status": "downgraded",
                    "buy_tier": "weak_buy",
                    "buy_strength_score": 0.6,
                },
                "execution_sizing_plan": {
                    "buy_tier": "weak_buy",
                    "final_budget": 6000.0,
                    "risk_budget_pct": 0.90,
                    "effective_position_pct": 6.0,
                    "expected_stop_loss_pct": 15.0,
                },
                "quant_status": "trial",
            },
            "status": "pending",
        }
    )

    portfolio = PortfolioService(db_file=db_path)
    portfolio.auto_execute_pending_signals([db.get_signal(signal_id)], executed_at="2026-01-05T10:00:00Z")
    skipped = db.get_signal(signal_id)

    replay_db = QuantSimReplayDB(tmp_path / "replay.db")
    run_id = replay_db.create_sim_run(
        mode="live_quant_drill",
        timeframe="30m",
        market="CN",
        start_datetime="2026-01-05 10:00:00",
        end_datetime="2026-01-05 10:00:00",
        initial_cash=100000,
        metadata={"run_type": "live_quant_drill"},
    )
    persisted = replay_db.upsert_sim_run_signals(run_id, [skipped])
    replay_signal = replay_db.get_sim_run_signal(persisted[signal_id])

    assert replay_signal["status"] == "pending"
    assert replay_signal["execution_note"].startswith("自动执行跳过")
    assert replay_signal["blocked_reason"] == "batch_execution_cap"
    assert replay_signal["cap_reason"] == "portfolio_trial_risk_budget_exhausted"
    assert replay_signal["execution_diagnostics"]["batch_cap"]["reason_code"] == "portfolio_trial_risk_budget_exhausted"


def test_scheduler_auto_executes_buy_signal_when_enabled(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate("300390", "天华新能", "main_force", latest_price=62.0)

    scheduler = QuantSimScheduler(db_file=tmp_path / "app.quant_sim.db")
    scheduler.update_config(enabled=True, auto_execute=True)
    monkeypatch.setattr(scheduler, "_is_trading_time", lambda market: True)

    monkeypatch.setattr(
        scheduler.engine.adapter,
        "analyze_candidate",
        lambda candidate, market_snapshot=None: {
            "action": "BUY",
            "confidence": 84,
            "reasoning": "双轨共振",
            "position_size_pct": 20,
            "price": 62.0,
        },
    )

    summary = scheduler.run_once(run_reason="manual_scan")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")

    positions = portfolio_service.list_positions()
    pending = signal_service.list_pending_signals()
    history = signal_service.list_signals(stock_code="300390")
    trades = portfolio_service.get_trade_history()

    assert summary["auto_executed"] == 1
    assert len(positions) == 1
    assert positions[0]["stock_code"] == "300390"
    assert pending == []
    assert history[0]["status"] == "executed"
    assert trades[0]["action"] == "buy"


def test_auto_execute_skips_buy_when_stock_is_limit_up(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate("600000", "浦发银行", "manual", latest_price=11.0)
    candidate = candidate_service.list_candidates()[0]

    signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 84,
            "reasoning": "涨停测试",
            "position_size_pct": 20,
            "strategy_profile": {
                "market_snapshot": {
                    "current_price": 11.0,
                    "prev_close": 10.0,
                    "volume": 100000,
                }
            },
        },
    )

    executed = portfolio_service.auto_execute_signal(signal, note="自动买入")
    history = signal_service.list_signals(stock_code="600000")

    assert executed is False
    assert portfolio_service.list_positions() == []
    assert history[0]["status"] == "pending"
    assert "涨停不可买入" in history[0]["execution_note"]


def test_auto_execute_skips_sell_when_stock_is_limit_down(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate("600000", "浦发银行", "manual", latest_price=10.0)
    candidate = candidate_service.list_candidates()[0]
    buy_signal = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 84, "reasoning": "建仓", "position_size_pct": 20},
    )
    portfolio_service.confirm_buy(
        buy_signal["id"],
        price=10.0,
        quantity=100,
        note="预先持仓",
        executed_at="2026-04-08 10:00:00",
    )
    candidate_service.add_manual_candidate("600000", "浦发银行", "manual", latest_price=9.0)
    sell_signal = signal_service.create_signal(
        candidate,
        {
            "action": "SELL",
            "confidence": 84,
            "reasoning": "跌停测试",
            "position_size_pct": 0,
            "strategy_profile": {
                "market_snapshot": {
                    "current_price": 9.0,
                    "prev_close": 10.0,
                    "volume": 100000,
                }
            },
        },
    )

    executed = portfolio_service.auto_execute_signal(sell_signal, note="自动卖出", executed_at="2026-04-09 10:00:00")
    history = signal_service.list_signals(stock_code="600000")

    assert executed is False
    assert len(portfolio_service.db.get_positions(as_of="2026-04-09 10:00:00")) == 1
    assert history[0]["status"] == "pending"
    assert "跌停不可卖出" in history[0]["execution_note"]


def test_auto_execute_observes_weak_dual_track_sell(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate("600000", "浦发银行", "manual", latest_price=10.2)
    candidate = candidate_service.list_candidates()[0]
    buy_signal = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 84, "reasoning": "建仓", "position_size_pct": 20},
    )
    portfolio_service.confirm_buy(
        buy_signal["id"],
        price=10.0,
        quantity=100,
        note="预先持仓",
        executed_at="2026-04-08 10:00:00",
    )
    weak_sell_id = portfolio_service.db.add_signal(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "action": "SELL",
            "confidence": 70,
            "reasoning": "普通双轨卖出",
            "position_size_pct": 0,
            "decision_type": "dual_track_weighted_sell",
            "strategy_profile": {
                "explainability": {
                    "fusion_breakdown": {
                        "final_action": "SELL",
                        "weighted_action_raw": "SELL",
                    }
                }
            },
            "status": "pending",
        }
    )

    executed = portfolio_service.auto_execute_signal(
        portfolio_service.db.get_signal(weak_sell_id),
        note="自动卖出",
        executed_at="2026-04-09 10:00:00",
    )
    signal = portfolio_service.db.get_signal(weak_sell_id)

    assert executed is False
    assert len(portfolio_service.get_trade_history()) == 1
    assert signal["execution_note"].startswith("自动执行跳过：弱SELL观察")
    assert signal["blocked_reason"] == "weak_sell_observe"
    assert signal["execution_diagnostics"]["sellable_quantity"] == 100
    assert signal["execution_diagnostics"]["locked_quantity"] == 0
    assert signal["execution_diagnostics"]["is_weak_sell_observe"] is True
    assert signal["strategy_profile"]["auto_execution_skip"]["blocked_reason"] == "weak_sell_observe"
    assert signal["strategy_profile"]["auto_execution_skip"]["execution_diagnostics"]["sell_trigger_type"] == "weak_sell_observe"


def test_replay_signal_upsert_persists_execution_diagnostics(tmp_path):
    db = QuantSimReplayDB(tmp_path / "replay.db")
    db.upsert_sim_run_signals(
        1,
        [
            {
                "id": 100,
                "stock_code": "600000",
                "stock_name": "浦发银行",
                "action": "SELL",
                "status": "ignored",
                "execution_note": "自动执行跳过：当前无可卖数量",
                "blocked_reason": "no_sellable_quantity",
                "strategy_profile": {
                    "auto_execution_skip": {
                        "blocked_reason": "no_sellable_quantity",
                        "execution_diagnostics": {
                            "sellable_quantity": 0,
                            "locked_quantity": 100,
                            "blocked_reason": "no_sellable_quantity",
                        },
                    }
                },
            }
        ],
    )

    saved = db.get_sim_run_signals(1, include_strategy_profile=True)[0]
    assert saved["blocked_reason"] == "no_sellable_quantity"
    assert saved["execution_diagnostics"]["sellable_quantity"] == 0
    assert saved["execution_diagnostics"]["locked_quantity"] == 100


def test_auto_execute_keeps_hard_risk_sell_executable(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate("600000", "浦发银行", "manual", latest_price=9.4)
    candidate = candidate_service.list_candidates()[0]
    buy_signal = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 84, "reasoning": "建仓", "position_size_pct": 20},
    )
    portfolio_service.confirm_buy(
        buy_signal["id"],
        price=10.0,
        quantity=100,
        note="预先持仓",
        executed_at="2026-04-08 10:00:00",
    )
    hard_sell_id = portfolio_service.db.add_signal(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "action": "SELL",
            "confidence": 90,
            "reasoning": "硬止损",
            "position_size_pct": 0,
            "decision_type": "dual_track_weighted_sell",
            "strategy_profile": {
                "explainability": {
                    "fusion_breakdown": {
                        "final_action": "SELL",
                        "weighted_action_raw": "SELL",
                        "veto_id": "hard_stop_loss",
                        "veto_trigger_type": "hard_stop_loss",
                    }
                }
            },
            "status": "pending",
        }
    )

    executed = portfolio_service.auto_execute_signal(
        portfolio_service.db.get_signal(hard_sell_id),
        note="自动卖出",
        executed_at="2026-04-09 10:00:00",
    )

    assert executed is True
    assert portfolio_service.get_trade_history(limit=1)[0]["action"] == "sell"


def test_scheduler_auto_executes_buy_signal_from_watchlist_candidate_and_syncs_watchlist(tmp_path, monkeypatch):
    quant_db = tmp_path / "app.quant_sim.db"
    watch_db = quant_db

    watchlist = WatchlistService(db_file=watch_db)
    quant_pool = CandidatePoolService(db_file=quant_db)
    watchlist.add_stock("300390", "天华新能", "main_force", 62.0, None, {})
    add_watchlist_rows_to_quant_pool(["300390"], watchlist, quant_pool)

    scheduler = QuantSimScheduler(db_file=quant_db)
    scheduler.update_config(enabled=True, auto_execute=True)
    monkeypatch.setattr(scheduler, "_is_trading_time", lambda market: True)

    monkeypatch.setattr(
        scheduler.engine.adapter,
        "analyze_candidate",
        lambda candidate, market_snapshot=None, analysis_timeframe="1d", strategy_mode="auto": {
            "action": "BUY",
            "confidence": 84,
            "reasoning": "关注池量化建仓",
            "position_size_pct": 20,
            "price": 62.0,
        },
    )

    summary = scheduler.run_once(run_reason="manual_scan")
    portfolio_service = PortfolioService(db_file=quant_db)

    watch = watchlist.get_watch("300390")
    positions = portfolio_service.list_positions()

    assert summary["auto_executed"] == 1
    assert watch is not None
    assert watch["in_quant_pool"] is True
    assert watch["latest_signal"] == "BUY"
    assert watch["latest_price"] == 62.0
    assert len(positions) == 1
    assert positions[0]["stock_code"] == "300390"


def test_scheduler_auto_executes_sell_signal_when_enabled(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate("301291", "明阳电气", "main_force", latest_price=53.0)
    candidate = candidate_service.list_candidates()[0]
    buy_signal = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 82, "reasoning": "先建仓", "position_size_pct": 20},
    )
    portfolio_service.confirm_buy(
        buy_signal["id"],
        price=53.0,
        quantity=100,
        note="预先持仓",
        executed_at="2026-04-08 10:00:00",
    )

    scheduler = QuantSimScheduler(db_file=tmp_path / "app.quant_sim.db")
    scheduler.update_config(enabled=True, auto_execute=True)
    monkeypatch.setattr(scheduler, "_is_trading_time", lambda market: True)

    monkeypatch.setattr(
        scheduler.engine.adapter,
        "analyze_position",
        lambda candidate, position, market_snapshot=None: {
            "action": "SELL",
            "confidence": 78,
            "reasoning": "走弱退出",
            "position_size_pct": 0,
            "price": 52.5,
        },
    )

    summary = scheduler.run_once(run_reason="manual_scan")

    positions = portfolio_service.list_positions()
    pending = signal_service.list_pending_signals()
    history = signal_service.list_signals(stock_code="301291")
    trades = portfolio_service.get_trade_history()

    assert summary["auto_executed"] == 1
    assert positions == []
    assert pending == []
    assert history[0]["action"] == "SELL"
    assert history[0]["status"] == "executed"
    assert trades[0]["action"] == "sell"


def test_auto_execute_sell_clamps_quantity_to_historical_sellable_quantity(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate("301291", "明阳电气", "main_force", latest_price=53.0)
    candidate = candidate_service.list_candidates()[0]

    first_buy = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 82, "reasoning": "第一笔建仓", "position_size_pct": 20},
    )
    portfolio_service.confirm_buy(
        first_buy["id"],
        price=53.0,
        quantity=100,
        note="第一笔",
        executed_at="2026-04-08 10:00:00",
    )

    second_buy = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 80, "reasoning": "第二笔建仓", "position_size_pct": 20},
    )
    portfolio_service.confirm_buy(
        second_buy["id"],
        price=52.0,
        quantity=100,
        note="第二笔",
        executed_at="2026-04-09 10:00:00",
    )

    sell_signal = signal_service.create_signal(
        candidate,
        {"action": "SELL", "confidence": 78, "reasoning": "自动卖出", "position_size_pct": 0},
    )

    executed = portfolio_service.auto_execute_signal(
        sell_signal,
        note="历史回放自动卖出",
        executed_at="2026-04-09 10:30:00",
    )

    positions = portfolio_service.db.get_positions(as_of="2026-04-09 10:30:00")
    lots = portfolio_service.db.get_position_lots("301291", as_of="2026-04-09 10:30:00")
    trades = portfolio_service.get_trade_history()

    assert executed is True
    assert len(positions) == 1
    assert positions[0]["quantity"] == 100
    assert positions[0]["sellable_quantity"] == 0
    assert positions[0]["locked_quantity"] == 100
    assert len(lots) == 1
    assert lots[0]["remaining_quantity"] == 100
    assert trades[0]["action"] == "sell"
    assert trades[0]["quantity"] == 100


def test_scheduler_auto_execute_buy_signal_records_skip_reason_when_under_one_lot(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate("002463", "沪电股份", "main_force", latest_price=89.99)

    scheduler = QuantSimScheduler(db_file=tmp_path / "app.quant_sim.db")
    scheduler.update_config(enabled=True, auto_execute=True)
    PortfolioService(db_file=tmp_path / "app.quant_sim.db").configure_account(10000.0)
    monkeypatch.setattr(scheduler, "_is_trading_time", lambda market: True)

    monkeypatch.setattr(
        scheduler.engine.adapter,
        "analyze_candidate",
        lambda candidate, market_snapshot=None, analysis_timeframe="1d", strategy_mode="auto": {
            "action": "BUY",
            "confidence": 81,
            "reasoning": "共振建仓",
            "position_size_pct": 50,
            "price": 89.99,
        },
    )

    summary = scheduler.run_once(run_reason="manual_scan")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    pending = signal_service.list_pending_signals()

    assert summary["auto_executed"] == 0
    assert len(pending) == 1
    assert pending[0]["action"] == "BUY"
    assert pending[0]["status"] == "pending"
    assert "不足买入一手" in str(pending[0].get("execution_note") or "")


def test_auto_execute_position_add_uses_add_delta_not_full_target(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)
    portfolio_service = PortfolioService(db_file=db_file)
    portfolio_service.configure_account(100000.0)

    candidate_service.add_manual_candidate("300390", "天华新能", "main_force", latest_price=52.0)
    candidate = candidate_service.list_candidates()[0]
    first_signal = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 82, "reasoning": "先建仓", "position_size_pct": 5},
    )
    portfolio_service.confirm_buy(first_signal["id"], price=50.0, quantity=100, note="已有底仓")
    portfolio_service.db.update_position_market_price("300390", 52.0)

    add_signal = signal_service.create_signal(
        {**candidate, "latest_price": 52.0},
        {
            "action": "BUY",
            "confidence": 86,
            "reasoning": "持仓趋势增强",
            "position_size_pct": 20,
            "tech_score": 0.32,
            "strategy_profile": {
                "effective_thresholds": {
                    "max_position_ratio": 0.3,
                    "allow_pyramiding": True,
                    "add_min_unrealized_pnl_pct": 2.0,
                    "add_min_tech_score": 0.25,
                    "portfolio_execution_guard_policy": {"enabled": False},
                },
                "explainability": {"fusion_breakdown": {"fusion_confidence": 0.74}},
            },
        },
    )

    executed = portfolio_service.auto_execute_signal(add_signal, note="自动加仓")
    position = portfolio_service.list_positions()[0]
    trades = portfolio_service.get_trade_history(limit=5)

    assert executed is True
    assert add_signal["decision_type"] == "position_add"
    assert position["quantity"] == 200
    assert trades[0]["action"] == "buy"
    assert trades[0]["quantity"] == 100
