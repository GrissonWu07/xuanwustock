from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.signal_center_service import SignalCenterService
from app.notification_service import notification_service


def test_false_strong_is_downgraded_when_overheated_without_structure():
    payload = {
        "action": "BUY",
        "strategy_profile": {
            "portfolio_execution_guard": {
                "buy_tier": "strong_buy",
                "buy_strength_score": 0.72,
                "trend_confirmation": {
                    "ma_stack": False,
                    "ma20_rising": False,
                    "above_ma20_checkpoints": 1,
                    "ma20_distance_pct": 12.0,
                    "rsi": 88.0,
                },
                "score_components": {"confirmation_score": 0.2},
            }
        },
    }

    result = SignalCenterService._apply_false_strong_filter(payload)

    guard = result["strategy_profile"]["portfolio_execution_guard"]
    assert guard["buy_tier"] == "normal_buy"
    assert guard["strong_filter_result"] == "downgraded"
    assert "weak_trend_structure" in guard["strong_filter_reasons"]
    assert "overheated_distance" in guard["strong_filter_reasons"]


def test_candidate_pool_service_adds_manual_candidate(tmp_path):
    service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")

    candidate_id = service.add_manual_candidate(
        stock_code="000001",
        stock_name="平安银行",
        source="profit_growth",
        latest_price=12.34,
    )

    rows = service.list_candidates()

    assert candidate_id > 0
    assert len(rows) == 1
    assert rows[0]["stock_code"] == "000001"
    assert rows[0]["source"] == "profit_growth"
    assert rows[0]["sources"] == ["profit_growth"]


def test_signal_center_creates_pending_and_observed_signals(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")

    candidate_id = candidate_service.add_manual_candidate(
        stock_code="600519",
        stock_name="贵州茅台",
        source="value_stock",
    )
    candidate = candidate_service.list_candidates()[0]

    buy_signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 81,
            "reasoning": "均线修复",
            "position_size_pct": 20,
        },
    )
    hold_signal = signal_service.create_signal(
        candidate,
        {
            "action": "HOLD",
            "confidence": 65,
            "reasoning": "等待右侧确认",
            "position_size_pct": 0,
        },
    )

    pending = signal_service.list_pending_signals()
    history = signal_service.list_signals(stock_code="600519")

    assert candidate_id > 0
    assert buy_signal["status"] == "pending"
    assert hold_signal["status"] == "observed"
    assert len(pending) == 1
    assert pending[0]["action"] == "BUY"
    assert len(history) == 2


def test_signal_center_persists_canonical_scores_when_available(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate("002518", "科士达", "main_force", latest_price=10.0)
    candidate = candidate_service.list_candidates()[0]

    signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 91,
            "reasoning": "legacy summary",
            "position_size_pct": 20,
            "tech_score": 0.91,
            "context_score": 0.88,
            "strategy_profile": {
                "explainability": {
                    "fusion_breakdown": {
                        "tech_score": 0.096633,
                        "context_score": 0.0728,
                        "fusion_confidence": 0.925028,
                    }
                }
            },
        },
        notify=False,
        mirror_to_ai=False,
    )

    assert signal["tech_score"] == 0.096633
    assert signal["context_score"] == 0.0728


def test_signal_center_observes_weak_sell_instead_of_pending_sell(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)
    portfolio_service = PortfolioService(db_file=db_file)
    candidate_service.add_manual_candidate("301387", "光大同创", "manual", latest_price=53.66)
    candidate = candidate_service.list_candidates()[0]
    buy_signal = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 90, "reasoning": "seed", "position_size_pct": 20},
        notify=False,
    )
    portfolio_service.confirm_buy(
        buy_signal["id"],
        price=51.66,
        quantity=100,
        note="seed",
        executed_at="2026-04-01T10:00:00Z",
    )

    signal = signal_service.create_signal(
        candidate,
        {
            "action": "SELL",
            "confidence": 72,
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
        },
        notify=False,
    )

    assert signal["action"] == "HOLD"
    assert signal["status"] == "observed"
    assert signal["decision_type"] == "weak_sell_observe"
    assert "弱SELL" in signal["reasoning"]
    assert signal_service.list_pending_signals() == []


def test_signal_center_keeps_hard_risk_sell_pending(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)
    portfolio_service = PortfolioService(db_file=db_file)
    candidate_service.add_manual_candidate("301387", "光大同创", "manual", latest_price=49.0)
    candidate = candidate_service.list_candidates()[0]
    buy_signal = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 90, "reasoning": "seed", "position_size_pct": 20},
        notify=False,
    )
    portfolio_service.confirm_buy(
        buy_signal["id"],
        price=51.66,
        quantity=100,
        note="seed",
        executed_at="2026-04-01T10:00:00Z",
    )

    signal = signal_service.create_signal(
        candidate,
        {
            "action": "SELL",
            "confidence": 91,
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
        },
        notify=False,
    )

    assert signal["action"] == "SELL"
    assert signal["status"] == "pending"
    assert signal["decision_type"] == "dual_track_weighted_sell"


def test_signal_center_blocks_buy_for_exit_only_stock(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)
    candidate_service.add_manual_candidate("600824", "益民集团", "main_force", latest_price=5.0)
    signal_service.db.upsert_quant_universe_state("600824", {"quant_status": "exit_only", "health_score": 25})
    candidate = candidate_service.list_candidates()[0]

    signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 90,
            "reasoning": "融合分达标",
            "position_size_pct": 50,
            "decision_type": "weighted_buy",
            "strategy_profile": {"explainability": {}},
        },
        notify=False,
    )

    lifecycle = signal["strategy_profile"]["explainability"]["lifecycle"]
    assert signal["action"] == "HOLD"
    assert signal["status"] == "observed"
    assert signal["position_size_pct"] == 0
    assert signal["decision_type"] == "exit_only_blocked"
    assert lifecycle["quant_status"] == "exit_only"
    assert lifecycle["original_action"] == "BUY"


def test_portfolio_service_confirm_buy_and_delay_signal(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    portfolio_service = PortfolioService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate(
        stock_code="300750",
        stock_name="宁德时代",
        source="main_force",
    )
    candidate = candidate_service.list_candidates()[0]
    signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 84,
            "reasoning": "量价共振",
            "position_size_pct": 25,
        },
    )

    portfolio_service.delay_signal(signal["id"], note="等尾盘再看")
    delayed_signal = signal_service.list_pending_signals()[0]
    portfolio_service.confirm_buy(signal["id"], price=201.5, quantity=100, note="已在券商端买入")

    positions = portfolio_service.list_positions()
    executed = signal_service.list_signals(stock_code="300750")[0]

    assert delayed_signal["delay_count"] == 1
    assert positions[0]["stock_code"] == "300750"
    assert positions[0]["quantity"] == 100
    assert executed["status"] == "executed"


def test_portfolio_legacy_sizing_applies_gate_multiplier_when_slots_disabled(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    portfolio_service = PortfolioService(db_file=db_file)
    portfolio_service.db.update_scheduler_config(capital_slot_enabled=False, commission_rate=0.0)
    signal = {
        "action": "BUY",
        "confidence": 90,
        "position_size_pct": 50,
        "strategy_profile": {
            "reentry_gate": {
                "status": "downgraded",
                "size_multiplier": 0.5,
            }
        },
    }

    quantity, explain = portfolio_service._estimate_buy_quantity(signal, 10.0)

    assert quantity == 2500
    assert explain["mode"] == "legacy_position_pct"


def test_signal_center_upserts_repeated_pending_signal_for_same_stock_and_action(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate(
        stock_code="600519",
        stock_name="贵州茅台",
        source="value_stock",
    )
    candidate = candidate_service.list_candidates()[0]

    first_signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 78,
            "reasoning": "第一次建仓建议",
            "position_size_pct": 20,
        },
    )
    second_signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 84,
            "reasoning": "第二次刷新后的建仓建议",
            "position_size_pct": 25,
        },
    )

    pending = signal_service.list_pending_signals()
    history = signal_service.list_signals(stock_code="600519")

    assert first_signal["id"] != second_signal["id"]
    assert len(pending) == 1
    assert len(history) == 2
    assert pending[0]["id"] == first_signal["id"]
    assert history[0]["action"] == "HOLD"
    assert history[0]["decision_type"] == "portfolio_execution_guard_blocked"


def test_signal_center_does_not_emit_sell_signal_without_open_position(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate(
        stock_code="301291",
        stock_name="明阳电气",
        source="main_force",
    )
    candidate = candidate_service.list_candidates()[0]

    signal = signal_service.create_signal(
        candidate,
        {
            "action": "SELL",
            "confidence": 72,
            "reasoning": "趋势走弱，建议卖出",
            "position_size_pct": 0,
        },
    )

    pending = signal_service.list_pending_signals()

    assert signal["action"] == "HOLD"
    assert signal["status"] == "observed"
    assert pending == []
    assert "无持仓" in signal["reasoning"]


def test_signal_center_zeros_hold_position_size(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate("601918", "新集能源", "main_force")
    candidate = candidate_service.list_candidates()[0]

    signal = signal_service.create_signal(
        candidate,
        {
            "action": "HOLD",
            "confidence": 90,
            "reasoning": "观察",
            "position_size_pct": 100,
        },
    )

    assert signal["action"] == "HOLD"
    assert signal["position_size_pct"] == 0


def test_signal_center_sanitizes_legacy_pending_sell_without_open_position(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate(
        stock_code="301291",
        stock_name="明阳电气",
        source="main_force",
    )
    candidate = candidate_service.list_candidates()[0]
    signal_id = signal_service.db.add_signal(
        {
            "candidate_id": candidate["id"],
            "stock_code": candidate["stock_code"],
            "stock_name": candidate["stock_name"],
            "action": "SELL",
            "confidence": 72,
            "reasoning": "历史遗留卖出信号",
            "position_size_pct": 0,
            "stop_loss_pct": 5,
            "take_profit_pct": 12,
            "decision_type": "legacy",
            "tech_score": -0.15,
            "context_score": 0.28,
            "status": "pending",
        }
    )

    pending = signal_service.list_pending_signals()
    history = signal_service.list_signals(stock_code="301291")

    assert pending == []
    assert history[0]["id"] == signal_id
    assert history[0]["action"] == "HOLD"
    assert history[0]["status"] == "observed"
    assert "无持仓" in history[0]["reasoning"]


def test_signal_center_persists_strategy_profile(tmp_path):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")

    candidate_service.add_manual_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        metadata={"profit_growth_pct": 35.0, "roe_pct": 19.0},
    )
    candidate = candidate_service.list_candidates()[0]

    signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 87,
            "reasoning": "策略共振买入",
            "position_size_pct": 60,
            "strategy_profile": {
                "market_regime": {"label": "牛市", "score": 0.66},
                "fundamental_quality": {"label": "强基本面", "score": 0.58},
                "risk_style": {"label": "激进", "max_position_ratio": 0.8},
                "analysis_timeframe": {"key": "30m"},
                "effective_thresholds": {"buy_threshold": 0.64, "sell_threshold": -0.25},
            },
        },
    )

    signal = signal_service.list_signals(stock_code="300390", limit=1)[0]

    assert signal["strategy_profile"]["market_regime"]["label"] == "牛市"
    assert signal["strategy_profile"]["fundamental_quality"]["label"] == "强基本面"
    assert signal["strategy_profile"]["risk_style"]["label"] == "激进"
    assert signal["strategy_profile"]["analysis_timeframe"]["key"] == "30m"


def test_signal_center_can_skip_live_notification(tmp_path, monkeypatch):
    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    sent_notifications: list[dict] = []

    monkeypatch.setattr(notification_service, "send_notification", lambda payload: sent_notifications.append(payload) or True)

    candidate_service.add_manual_candidate(
        stock_code="002594",
        stock_name="比亚迪",
        source="main_force",
        latest_price=256.3,
    )
    candidate = candidate_service.list_candidates()[0]

    signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 88,
            "reasoning": "强趋势突破",
            "position_size_pct": 35,
        },
        notify=False,
    )

    assert signal["status"] == "pending"
    assert sent_notifications == []


def test_signal_center_temp_db_does_not_emit_external_side_effects(tmp_path, monkeypatch):
    saved_ai_decisions: list[dict] = []
    sent_notifications: list[dict] = []

    class FakeSmartMonitorDB:
        def __init__(self, db_file):
            self.db_file = db_file

        def save_ai_decision(self, payload):
            saved_ai_decisions.append(payload)

    monkeypatch.setattr("app.quant_sim.signal_center_service.SmartMonitorDB", FakeSmartMonitorDB)
    monkeypatch.setattr(notification_service, "send_notification", lambda payload: sent_notifications.append(payload) or True)

    candidate_service = CandidatePoolService(db_file=tmp_path / "app.quant_sim.db")
    signal_service = SignalCenterService(db_file=tmp_path / "app.quant_sim.db")
    candidate_service.add_manual_candidate(
        stock_code="300750",
        stock_name="宁德时代",
        source="main_force",
        latest_price=201.5,
    )
    candidate = candidate_service.list_candidates()[0]

    signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 82,
            "reasoning": "建仓",
            "position_size_pct": 20,
        },
    )

    assert signal["status"] == "pending"
    assert saved_ai_decisions == []
    assert sent_notifications == []


def test_signal_center_notify_false_skips_ai_decision_mirror(tmp_path, monkeypatch):
    db_file = tmp_path / "app.quant_sim.db"
    saved_ai_decisions: list[dict] = []

    class FakeSmartMonitorDB:
        def __init__(self, db_file):
            self.db_file = db_file

        def save_ai_decision(self, payload):
            saved_ai_decisions.append(payload)

    monkeypatch.setattr("app.quant_sim.signal_center_service.DEFAULT_DB_FILE", str(db_file))
    monkeypatch.setattr("app.quant_sim.signal_center_service.SmartMonitorDB", FakeSmartMonitorDB)

    candidate_service = CandidatePoolService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)
    candidate_service.add_manual_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        latest_price=86.5,
    )
    candidate = candidate_service.list_candidates()[0]

    signal = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 82,
            "reasoning": "历史回放买入信号",
            "position_size_pct": 60,
        },
        notify=False,
    )

    assert signal["status"] == "pending"
    assert saved_ai_decisions == []


def test_signal_center_marks_position_buy_as_add_and_uses_target_delta(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)
    portfolio_service = PortfolioService(db_file=db_file)

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
                },
                "explainability": {
                    "fusion_breakdown": {
                        "fusion_confidence": 0.74,
                    }
                },
            },
        },
        notify=False,
    )

    gate = add_signal["strategy_profile"]["position_add_gate"]

    assert add_signal["action"] == "BUY"
    assert add_signal["decision_type"] == "position_add"
    assert add_signal["position_size_pct"] < 20
    assert gate["intent"] == "position_add"
    assert gate["status"] == "passed"
    assert gate["target_position_pct"] == 20.0
    assert gate["add_position_delta_pct"] == 14.81
    assert add_signal["strategy_profile"]["execution_sizing_plan"]["kernel_quality_position_pct"] == 14.81
    assert add_signal["strategy_profile"]["execution_sizing_plan"]["effective_position_pct"] == add_signal["position_size_pct"]


def test_signal_center_blocks_position_add_when_gate_fails(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)
    portfolio_service = PortfolioService(db_file=db_file)

    candidate_service.add_manual_candidate("300390", "天华新能", "main_force", latest_price=49.0)
    candidate = candidate_service.list_candidates()[0]
    first_signal = signal_service.create_signal(
        candidate,
        {"action": "BUY", "confidence": 82, "reasoning": "先建仓", "position_size_pct": 5},
    )
    portfolio_service.confirm_buy(first_signal["id"], price=50.0, quantity=100, note="已有底仓")
    portfolio_service.db.update_position_market_price("300390", 49.0)

    blocked = signal_service.create_signal(
        {**candidate, "latest_price": 49.0},
        {
            "action": "BUY",
            "confidence": 86,
            "reasoning": "持仓尝试加仓",
            "position_size_pct": 20,
            "tech_score": 0.1,
            "strategy_profile": {
                "effective_thresholds": {
                    "max_position_ratio": 0.3,
                    "allow_pyramiding": False,
                    "add_min_unrealized_pnl_pct": 2.0,
                    "add_min_tech_score": 0.25,
                }
            },
        },
        notify=False,
    )

    gate = blocked["strategy_profile"]["position_add_gate"]

    assert blocked["action"] == "HOLD"
    assert blocked["status"] == "observed"
    assert blocked["position_size_pct"] == 0
    assert blocked["decision_type"] == "position_add_blocked"
    assert gate["status"] == "blocked"
    assert "不允许加仓" in "；".join(gate["reasons"])


def _reentry_profile(
    *,
    price: float,
    ma5: float,
    ma10: float,
    ma20: float,
    ma60: float,
    rsi12: float,
    macd: float = 1.0,
    update_time: str = "2025-09-29 13:30:00",
    tech_signal: str = "HOLD",
    context_signal: str = "BUY",
) -> dict:
    return {
        "market_snapshot": {
            "current_price": price,
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "ma60": ma60,
            "ma20_slope": 0.01,
            "rsi12": rsi12,
            "macd": macd,
            "update_time": update_time,
        },
        "effective_thresholds": {
            "profit_reentry_cooldown_days": 5,
            "profit_reentry_size_multiplier": 0.5,
            "profit_reentry_hot_rsi_size_multiplier": 0.5,
            "profit_reentry_very_hot_rsi_size_multiplier": 0.25,
            "profit_reentry_extreme_rsi": 88,
            "profit_reentry_extreme_ma20_distance_pct": 5.0,
        },
        "explainability": {
            "dual_track": {
                "tech_signal": tech_signal,
                "context_signal": context_signal,
                "final_action": "BUY",
            },
            "fusion_breakdown": {
                "fusion_score": 0.39,
                "buy_threshold_eff": 0.35,
                "fusion_confidence": 0.9,
            },
        },
    }


def test_signal_center_downgrades_short_profit_sell_reentry_size(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)
    portfolio_service = PortfolioService(db_file=db_file)
    signal_service.db.reset_runtime_state(initial_cash=600000)

    candidate_service.add_manual_candidate("300857", "协创数据", "main_force", latest_price=180.59)
    candidate = candidate_service.list_candidates()[0]
    buy = signal_service.create_signal(candidate, {"action": "BUY", "confidence": 90, "reasoning": "seed", "position_size_pct": 50}, notify=False)
    portfolio_service.confirm_buy(buy["id"], price=104.59, quantity=500, note="seed", executed_at="2025-09-05 14:00:00")
    sell = signal_service.create_signal(
        candidate,
        {
            "action": "SELL",
            "confidence": 92,
            "reasoning": "profit",
            "position_size_pct": 0,
            "strategy_profile": {
                "explainability": {
                    "fusion_breakdown": {
                        "veto_id": "profit_tech_sell",
                        "veto_trigger_type": "profit_tech_sell",
                    }
                }
            },
        },
        notify=False,
    )
    portfolio_service.confirm_sell(sell["id"], price=160.4, quantity=500, note="profit", executed_at="2025-09-26 10:30:00")

    reentry = signal_service.create_signal(
        {**candidate, "latest_price": 180.59},
        {
            "action": "BUY",
            "confidence": 88,
            "reasoning": "short reentry",
            "position_size_pct": 50,
            "strategy_profile": _reentry_profile(
                price=180.59,
                ma5=172.0,
                ma10=170.0,
                ma20=167.09,
                ma60=168.07,
                rsi12=78.64,
            ),
        },
        notify=False,
    )

    gate = reentry["strategy_profile"]["reentry_gate"]
    assert reentry["action"] == "BUY"
    assert reentry["position_size_pct"] < 50
    assert gate["status"] == "downgraded"
    assert gate["last_sell_trigger"] == "profit_tech_sell"
    assert gate["size_multiplier"] == 0.5
    assert reentry["strategy_profile"]["execution_sizing_plan"]["effective_position_pct"] == reentry["position_size_pct"]


def test_signal_center_blocks_extreme_overheat_buy_even_without_profit_reentry(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)
    signal_service.db.reset_runtime_state(initial_cash=600000)

    candidate_service.add_manual_candidate("300857", "协创数据", "main_force", latest_price=147.35)
    candidate = candidate_service.list_candidates()[0]

    blocked = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 86,
            "reasoning": "overheat resonance",
            "position_size_pct": 50,
            "strategy_profile": _reentry_profile(
                price=147.35,
                ma5=142.69,
                ma10=141.0,
                ma20=139.23,
                ma60=138.52,
                rsi12=89.47,
                tech_signal="BUY",
                context_signal="BUY",
                update_time="2025-12-09 10:00:00",
            ),
        },
        notify=False,
    )

    gate = blocked["strategy_profile"]["reentry_gate"]
    assert blocked["action"] == "HOLD"
    assert blocked["status"] == "observed"
    assert blocked["position_size_pct"] == 0
    assert blocked["decision_type"] == "reentry_overheat_blocked"
    assert gate["status"] == "blocked"
    assert gate["rsi12"] == 89.47


def test_signal_center_allows_hot_buy_with_reduced_size_when_trend_confirmed(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)
    signal_service.db.reset_runtime_state(initial_cash=600000)

    candidate_service.add_manual_candidate("300857", "协创数据", "main_force", latest_price=140.61)
    candidate = candidate_service.list_candidates()[0]

    hot = signal_service.create_signal(
        candidate,
        {
            "action": "BUY",
            "confidence": 89,
            "reasoning": "hot trend",
            "position_size_pct": 50,
            "strategy_profile": _reentry_profile(
                price=140.61,
                ma5=138.75,
                ma10=138.0,
                ma20=137.11,
                ma60=137.90,
                rsi12=80.15,
                update_time="2025-12-24 14:00:00",
            ),
        },
        notify=False,
    )

    gate = hot["strategy_profile"]["reentry_gate"]
    assert hot["action"] == "BUY"
    assert hot["position_size_pct"] < 50
    assert gate["status"] == "downgraded"
    assert gate["size_multiplier"] == 0.5
    assert hot["strategy_profile"]["execution_sizing_plan"]["effective_position_pct"] == hot["position_size_pct"]
