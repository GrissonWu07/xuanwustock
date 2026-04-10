from datetime import datetime

from quant_kernel.runtime import KernelStrategyRuntime


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
    assert explainability["dual_track"]["tech_signal"] in {"BUY", "SELL", "HOLD"}
    assert "rule_hit" in explainability["dual_track"]
