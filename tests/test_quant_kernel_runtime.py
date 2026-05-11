from datetime import datetime

from app.quant_kernel.config import StrategyScoringConfig
from app.quant_kernel.models import ContextualScore
from app.quant_kernel.runtime import KernelStrategyRuntime


def _strategy_binding_with_profit_protection(config: dict) -> dict:
    payload = StrategyScoringConfig.default()
    base = dict(payload.base)
    base["veto"] = {
        **(base.get("veto") or {}),
        "profit_protection": config,
    }
    return {
        "profile_id": "test",
        "profile_name": "测试策略",
        "version_id": 1,
        "version": 1,
        "config": {
            "schema_version": payload.schema_version,
            "base": base,
            "profiles": payload.profiles,
        },
    }


def test_kernel_candidate_decision_exposes_structured_vote_breakdown():
    runtime = KernelStrategyRuntime()

    decision = runtime.evaluate_candidate(
        candidate={
            "stock_code": "002824",
            "stock_name": "和胜股份",
            "source": "main_force",
            "sources": ["main_force"],
            "metadata": {"profit_growth_pct": 18.0, "roe_pct": 9.5},
        },
        market_snapshot={
            "current_price": 22.97,
            "latest_price": 22.97,
            "ma5": 22.60,
            "ma20": 20.88,
            "ma60": 20.17,
            "macd": 0.532,
            "rsi12": 90.63,
            "volume_ratio": 0.15,
            "trend": "up",
        },
        current_time=datetime(2026, 4, 10, 14, 30),
        analysis_timeframe="30m",
        strategy_mode="auto",
    )

    explainability = (decision.strategy_profile or {}).get("explainability") or {}

    assert "tech_votes" in explainability
    assert "context_votes" in explainability
    assert "dual_track" in explainability
    assert any(vote["factor"] == "MACD" for vote in explainability["tech_votes"])
    assert any(vote["component"] == "source_prior" for vote in explainability["context_votes"])
    source_prior_vote = next(vote for vote in explainability["context_votes"] if vote["component"] == "source_prior")
    assert source_prior_vote["score"] == 0
    assert "不参与评分加分" in source_prior_vote["reason"]
    assert explainability["dual_track"]["tech_signal"] in {"BUY", "SELL", "HOLD"}
    assert "rule_hit" in explainability["dual_track"]


def test_kernel_candidate_uses_extended_snapshot_indicators_when_present():
    runtime = KernelStrategyRuntime()

    decision = runtime.evaluate_candidate(
        candidate={
            "stock_code": "300390",
            "stock_name": "天华新能",
            "source": "main_force",
            "sources": ["main_force"],
        },
        market_snapshot={
            "current_price": 24.5,
            "latest_price": 24.5,
            "ma5": 24.1,
            "ma20": 23.2,
            "ma60": 21.8,
            "ma20_slope": 0.012,
            "macd": 0.86,
            "dif": 0.43,
            "dea": 0.21,
            "hist": 0.22,
            "hist_prev": 0.14,
            "rsi12": 61.5,
            "volume_ratio": 1.38,
            "obv": 182000.0,
            "obv_prev": 176500.0,
            "atr": 0.82,
            "boll_upper": 25.4,
            "boll_lower": 21.2,
            "k": 72.0,
            "d": 66.0,
            "j": 84.0,
            "trend": "up",
        },
        current_time=datetime(2026, 4, 23, 14, 30),
        analysis_timeframe="30m",
        strategy_mode="auto",
    )

    explainability = (decision.strategy_profile or {}).get("explainability") or {}
    market_snapshot = (decision.strategy_profile or {}).get("market_snapshot") or {}
    technical_breakdown = explainability.get("technical_breakdown") or {}
    dimensions = {item["id"]: item for item in technical_breakdown.get("dimensions") or []}

    assert market_snapshot["current_price"] == 24.5
    assert market_snapshot["dif"] == 0.43
    assert market_snapshot["k"] == 72.0
    assert dimensions["ma_slope"]["available"] is True
    assert dimensions["obv_trend"]["available"] is True
    assert dimensions["atr_risk"]["available"] is True
    assert dimensions["kdj_cross"]["available"] is True


def test_kernel_candidate_uses_stock_analysis_context_when_present():
    runtime = KernelStrategyRuntime()

    decision = runtime.evaluate_candidate(
        candidate={
            "stock_code": "002518",
            "stock_name": "科士达",
            "source": "manual",
            "sources": ["manual"],
        },
        market_snapshot={
            "current_price": 20.0,
            "latest_price": 20.0,
            "ma5": 20.4,
            "ma20": 20.1,
            "ma60": 19.2,
            "macd": 0.12,
            "dif": 0.08,
            "dea": 0.02,
            "hist": 0.06,
            "hist_prev": 0.04,
            "rsi14": 58.0,
            "volume_ratio": 1.1,
            "trend": "up",
            "stock_analysis_context": {
                "used": True,
                "record_id": 99,
                "score": 0.55,
                "effective_score": 0.44,
                "confidence": 0.8,
                "summary": "AI团队结论偏多。",
                "data_as_of": "2026-04-24 14:30:00",
                "valid_until": "2026-04-26 14:30:00",
            },
        },
        current_time=datetime(2026, 4, 24, 14, 30),
        analysis_timeframe="30m",
        strategy_mode="auto",
    )

    explainability = (decision.strategy_profile or {}).get("explainability") or {}
    context_breakdown = explainability.get("context_breakdown") or {}
    dimensions = {item["id"]: item for item in context_breakdown.get("dimensions") or []}

    assert dimensions["stock_analysis"]["available"] is True
    assert dimensions["stock_analysis"]["score"] == 0.44
    assert explainability["stock_analysis_context"]["record_id"] == 99


def test_candidate_sell_is_downgraded_to_non_tradable_reject_in_explainability():
    runtime = KernelStrategyRuntime()

    decision = runtime.evaluate_candidate(
        candidate={
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "source": "manual",
            "sources": ["manual"],
        },
        market_snapshot={
            "current_price": 8.0,
            "latest_price": 8.0,
            "ma5": 9.0,
            "ma10": 10.0,
            "ma20": 11.0,
            "ma60": 12.0,
            "ma20_slope": -0.02,
            "macd": -1.2,
            "dif": -1.2,
            "dea": -0.3,
            "hist": -0.9,
            "hist_prev": -0.3,
            "rsi14": 80.0,
            "rsi12": 80.0,
            "volume_ratio": 0.5,
            "obv": 100.0,
            "obv_prev": 200.0,
            "atr": 2.0,
            "boll_upper": 14.0,
            "boll_lower": 9.0,
            "k": 20.0,
            "d": 30.0,
            "j": 10.0,
            "trend": "down",
        },
        current_time=datetime(2026, 4, 24, 14, 30),
        analysis_timeframe="30m",
        strategy_mode="aggressive",
    )

    explainability = (decision.strategy_profile or {}).get("explainability") or {}
    fusion = explainability.get("fusion_breakdown") or {}

    assert decision.action == "HOLD"
    assert decision.decision_type == "candidate_reject"
    assert fusion["raw_weighted_action_raw"] == "SELL"
    assert fusion["weighted_action_raw"] == "HOLD"
    assert fusion["final_action"] == "HOLD"
    assert fusion["matched_branch"] == "candidate_sell_rejected"


def test_position_guarded_profit_does_not_emit_buy_vote():
    runtime = KernelStrategyRuntime()

    score, votes = runtime._calculate_position_tech_votes(
        current_price=10.5,
        ma20=10.0,
        macd=0.18,
        rsi12=58.0,
        pnl_pct=5.0,
    )

    profit_vote = next(vote for vote in votes if vote["factor"] == "盈亏保护")
    assert profit_vote["signal"] == "HOLD"
    assert profit_vote["score"] == 0.0
    assert "停止加仓" in profit_vote["reason"]
    assert score == 0.0


def test_position_stop_loss_is_audited_as_risk_veto():
    runtime = KernelStrategyRuntime()

    decision = runtime.evaluate_position(
        candidate={
            "stock_code": "002518",
            "stock_name": "科士达",
            "source": "manual",
            "sources": ["manual"],
        },
        position={
            "stock_code": "002518",
            "stock_name": "科士达",
            "quantity": 100,
            "avg_price": 10.0,
            "stop_loss": 9.8,
        },
        market_snapshot={
            "current_price": 9.5,
            "latest_price": 9.5,
            "ma5": 9.4,
            "ma20": 9.0,
            "ma60": 8.6,
            "macd": 0.18,
            "dif": 0.12,
            "dea": 0.03,
            "hist": 0.09,
            "hist_prev": 0.05,
            "rsi14": 56.0,
            "volume_ratio": 1.1,
            "trend": "up",
        },
        current_time=datetime(2026, 4, 24, 14, 30),
        analysis_timeframe="30m",
        strategy_mode="aggressive",
    )

    explainability = (decision.strategy_profile or {}).get("explainability") or {}
    vetoes = explainability.get("vetoes") or []
    fusion = explainability.get("fusion_breakdown") or {}

    assert decision.action == "SELL"
    assert vetoes[0]["id"] == "stop_loss"
    assert vetoes[0]["trigger_type"] == "stop_loss"
    assert vetoes[0]["display_label"] == "止损线触发"
    assert fusion["matched_branch"] == "veto_first"


def test_position_forced_risk_and_hard_stop_veto_labels_are_distinct():
    runtime = KernelStrategyRuntime()

    forced = runtime._build_position_risk_vetoes(
        position={"stock_code": "002518", "avg_price": 10.0, "force_sell": True},
        market_snapshot={"current_price": 10.5},
    )
    hard_stop = runtime._build_position_risk_vetoes(
        position={"stock_code": "002518", "avg_price": 10.0, "hard_stop_loss": 9.0},
        market_snapshot={"current_price": 8.8},
    )

    assert forced[0]["id"] == "forced_risk"
    assert forced[0]["display_label"] == "强制风控触发"
    assert hard_stop[0]["id"] == "hard_stop_loss"
    assert hard_stop[0]["display_label"] == "硬止损线触发"


def test_position_profit_tech_sell_veto_forces_sell_after_large_peak_drawdown():
    runtime = KernelStrategyRuntime()
    binding = _strategy_binding_with_profit_protection(
        {
            "tech_sell_enabled": True,
            "tech_sell_peak_pct": 50.0,
            "tech_sell_drawdown_pct": 15.0,
            "tech_sell_min_price_gain": 2.5,
            "tech_sell_min_price_gain_pct": 12.0,
            "tech_sell_min_profit_amount": 1500.0,
            "tech_sell_min_profit_amount_pct": 12.0,
            "hard_trailing_enabled": False,
        }
    )

    decision = runtime.evaluate_position(
        candidate={"stock_code": "605298", "stock_name": "必得科技", "source": "manual", "sources": ["manual"]},
        position={
            "stock_code": "605298",
            "stock_name": "必得科技",
            "quantity": 900,
            "avg_price": 12.8939,
            "latest_price": 50.0,
            "peak_price": 54.37,
            "peak_unrealized_pnl_pct": 321.6723,
            "peak_unrealized_pnl": 37328.49,
        },
        market_snapshot={
            "current_price": 50.0,
            "ma5": 50.8,
            "ma10": 51.2,
            "ma20": 52.0,
            "ma60": 42.0,
            "ma20_slope": -0.01,
            "macd": -0.8,
            "dif": -0.8,
            "dea": -0.2,
            "hist": -0.6,
            "hist_prev": -0.2,
            "rsi14": 82.0,
            "rsi12": 82.0,
            "volume_ratio": 0.7,
            "trend": "down",
        },
        current_time=datetime(2025, 9, 18, 10, 0),
        analysis_timeframe="30m",
        strategy_mode="aggressive",
        strategy_profile_binding=binding,
    )

    explainability = (decision.strategy_profile or {}).get("explainability") or {}
    vetoes = explainability.get("vetoes") or []
    fusion = explainability.get("fusion_breakdown") or {}

    assert decision.action == "SELL"
    assert vetoes[0]["id"] == "profit_tech_sell"
    assert vetoes[0]["display_label"] == "高浮盈技术卖出"
    assert fusion["matched_branch"] == "veto_first"


def test_position_profit_veto_ranks_above_context_hold_veto():
    runtime = KernelStrategyRuntime()

    vetoes = runtime._build_vetoes(
        profile_kind="position",
        contextual_score=ContextualScore(score=-0.95, signal="bearish", confidence=0.9, components={}, reason="弱环境"),
        dual_track={"fusion_sell_threshold": -0.7},
        veto_config={
            "thresholds": {"context_veto": {"enabled": True, "min_context_score": -0.7}},
            "profit_protection": {
                "tech_sell_enabled": True,
                "tech_sell_peak_pct": 50.0,
                "tech_sell_drawdown_pct": 15.0,
                "tech_sell_min_price_gain": 2.5,
                "tech_sell_min_price_gain_pct": 12.0,
                "tech_sell_min_profit_amount": 1500.0,
                "tech_sell_min_profit_amount_pct": 12.0,
                "hard_trailing_enabled": False,
            },
        },
        position={
            "stock_code": "605298",
            "quantity": 900,
            "avg_price": 12.8939,
            "peak_price": 54.37,
            "peak_unrealized_pnl_pct": 321.6723,
            "peak_unrealized_pnl": 37328.49,
        },
        market_snapshot={"current_price": 50.0},
        core_rule_action="SELL",
    )

    assert [item["id"] for item in vetoes[:2]] == ["profit_tech_sell", "context_veto"]
    assert vetoes[0]["action"] == "SELL"


def test_position_hard_profit_trailing_veto_does_not_require_technical_sell():
    runtime = KernelStrategyRuntime()
    binding = _strategy_binding_with_profit_protection(
        {
            "tech_sell_enabled": False,
            "hard_trailing_enabled": True,
            "hard_trailing_peak_pct": 80.0,
            "hard_trailing_drawdown_pct": 25.0,
            "hard_trailing_min_price_gain": 4.0,
            "hard_trailing_min_price_gain_pct": 18.0,
            "hard_trailing_min_profit_amount": 2500.0,
            "hard_trailing_min_profit_amount_pct": 18.0,
        }
    )

    decision = runtime.evaluate_position(
        candidate={"stock_code": "301662", "stock_name": "宏工科技", "source": "manual", "sources": ["manual"]},
        position={
            "stock_code": "301662",
            "stock_name": "宏工科技",
            "quantity": 200,
            "avg_price": 55.9168,
            "latest_price": 170.0,
            "peak_price": 201.93,
            "peak_unrealized_pnl_pct": 261.1258,
            "peak_unrealized_pnl": 29202.64,
        },
        market_snapshot={
            "current_price": 170.0,
            "ma5": 168.0,
            "ma10": 165.0,
            "ma20": 150.0,
            "ma60": 120.0,
            "macd": 0.6,
            "dif": 0.6,
            "dea": 0.3,
            "hist": 0.3,
            "hist_prev": 0.2,
            "rsi14": 62.0,
            "rsi12": 62.0,
            "volume_ratio": 1.1,
            "trend": "up",
        },
        current_time=datetime(2026, 2, 10, 10, 0),
        analysis_timeframe="30m",
        strategy_mode="aggressive",
        strategy_profile_binding=binding,
    )

    explainability = (decision.strategy_profile or {}).get("explainability") or {}
    vetoes = explainability.get("vetoes") or []

    assert decision.action == "SELL"
    assert vetoes[0]["id"] == "hard_profit_trailing_stop"
    assert vetoes[0]["display_label"] == "硬移动止盈触发"


def test_default_hard_profit_trailing_triggers_after_modest_gain_drawdown():
    runtime = KernelStrategyRuntime()

    decision = runtime.evaluate_position(
        candidate={"stock_code": "600000", "stock_name": "浦发银行", "source": "manual", "sources": ["manual"]},
        position={
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "quantity": 500,
            "avg_price": 20.0,
            "latest_price": 21.0,
            "peak_price": 22.0,
            "peak_unrealized_pnl_pct": 10.0,
            "peak_unrealized_pnl": 1000.0,
        },
        market_snapshot={
            "current_price": 21.0,
            "ma5": 20.8,
            "ma10": 20.5,
            "ma20": 20.0,
            "ma60": 19.0,
            "macd": 0.2,
            "dif": 0.2,
            "dea": 0.1,
            "hist": 0.1,
            "hist_prev": 0.08,
            "rsi14": 58.0,
            "rsi12": 58.0,
            "volume_ratio": 1.0,
            "trend": "up",
        },
        current_time=datetime(2026, 2, 10, 10, 0),
        analysis_timeframe="30m",
        strategy_mode="stable",
    )

    explainability = (decision.strategy_profile or {}).get("explainability") or {}
    vetoes = explainability.get("vetoes") or []

    assert decision.action == "SELL"
    assert vetoes[0]["id"] == "hard_profit_trailing_stop"


def test_profit_protection_ignores_large_pct_when_absolute_gain_is_too_small():
    runtime = KernelStrategyRuntime()
    binding = _strategy_binding_with_profit_protection(
        {
            "tech_sell_enabled": True,
            "tech_sell_peak_pct": 30.0,
            "tech_sell_drawdown_pct": 8.0,
            "tech_sell_min_price_gain": 1.5,
            "tech_sell_min_price_gain_pct": 8.0,
            "tech_sell_min_profit_amount": 800.0,
            "tech_sell_min_profit_amount_pct": 8.0,
            "hard_trailing_enabled": False,
        }
    )

    decision = runtime.evaluate_position(
        candidate={"stock_code": "000001", "stock_name": "小额测试", "source": "manual", "sources": ["manual"]},
        position={
            "stock_code": "000001",
            "stock_name": "小额测试",
            "quantity": 100,
            "avg_price": 2.0,
            "latest_price": 2.5,
            "peak_price": 2.8,
            "peak_unrealized_pnl_pct": 40.0,
            "peak_unrealized_pnl": 80.0,
        },
        market_snapshot={
            "current_price": 2.5,
            "ma5": 2.55,
            "ma10": 2.6,
            "ma20": 2.7,
            "ma60": 2.4,
            "ma20_slope": -0.01,
            "macd": -0.2,
            "dif": -0.2,
            "dea": -0.05,
            "hist": -0.15,
            "hist_prev": -0.05,
            "rsi14": 82.0,
            "rsi12": 82.0,
            "volume_ratio": 0.7,
            "trend": "down",
        },
        current_time=datetime(2026, 1, 5, 10, 0),
        analysis_timeframe="30m",
        strategy_mode="stable",
        strategy_profile_binding=binding,
    )

    explainability = (decision.strategy_profile or {}).get("explainability") or {}
    vetoes = explainability.get("vetoes") or []

    assert [item["id"] for item in vetoes] == []
