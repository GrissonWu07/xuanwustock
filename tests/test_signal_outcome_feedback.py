from __future__ import annotations

from pathlib import Path

from app.quant_sim.db import OutcomeFeedbackFilters, QuantSimDB, QuantSimReplayDB
from app.quant_sim.outcome_feedback import OutcomeFeedbackAggregator, OutcomeFeedbackRequest
from app.quant_sim.portfolio_execution_guard import evaluate_portfolio_execution_guard
from app.quant_sim.signal_outcome_scoring import OutcomeRunScope
from app.quant_sim.stock_execution_feedback import (
    StockExecutionFeedbackSummary,
    evaluate_stock_execution_feedback_gate,
)


def _outcome(signal_id: int, *, score: float, matured_at: str, action: str = "BUY") -> dict:
    return {
        "signal_id": signal_id,
        "stock_code": "600000",
        "action": action,
        "horizon_checkpoints": 3,
        "signal_checkpoint_at": "2026-01-05 10:00:00",
        "matured_at": matured_at,
        "source_artifact_ref": "mta:v1/test",
        "outcome_score": score,
        "status": "mature",
        "reason_code": "ok",
        "metrics": {
            "invalidation_hit": score < 45,
            "ma20_break_after_buy": score < 45,
            "sell_validated": score >= 60,
        },
        "formula": {"scoring_version": "test"},
    }


def test_outcome_feedback_uses_only_mature_rows_before_checkpoint(tmp_path: Path) -> None:
    db = QuantSimDB(tmp_path / "quant_sim.db")
    db.upsert_signal_outcome_score(_outcome(1, score=35, matured_at="2026-01-06 10:00:00"))
    db.upsert_signal_outcome_score(_outcome(2, score=55, matured_at="2026-01-07 10:00:00"))
    db.upsert_signal_outcome_score(_outcome(3, score=90, matured_at="2026-01-10 10:00:00"))

    summary = OutcomeFeedbackAggregator(db).aggregate(
        OutcomeFeedbackRequest(
            stock_code="600000",
            profile_id="aggressive",
            as_of_checkpoint="2026-01-08 10:00:00",
            policy={"min_feedback_samples": 2, "feedback_lookback_days": 30},
        )
    )
    latest = db.get_latest_outcome_feedback(
        OutcomeFeedbackFilters(
            stock_code="600000",
            profile_id="aggressive",
            as_of_checkpoint_lte="2026-01-08 10:00:00",
        )
    )

    assert summary.sample_count == 2
    assert summary.latest_matured_at == "2026-01-07 10:00:00"
    assert latest is not None
    assert latest["summary"]["sample_count"] == 2
    assert latest["summary"]["actionable"] is True


def test_poor_outcome_feedback_downgrades_future_buy_gate() -> None:
    market_snapshot = {
        "latest_price": 10.0,
        "ma5": 10.4,
        "ma10": 10.2,
        "ma20": 10.0,
        "ma20_slope": 0.05,
        "recent_checkpoints": [
            {"close": 10.2, "ma20": 10.0, "ma20_slope": 0.01, "low": 10.05},
            {"close": 10.3, "ma20": 10.0, "ma20_slope": 0.02, "low": 10.1},
            {"close": 10.4, "ma20": 10.0, "ma20_slope": 0.03, "low": 10.1},
        ],
        "outcome_feedback": {
            "summary": {
                "actionable": True,
                "sample_count": 3,
                "outcome_feedback_score": 35,
                "recommended_size_multiplier": 0.4,
                "requires_stronger_confirmation": False,
                "reason_code": "poor_buy_outcome_feedback",
            }
        },
    }

    gate = evaluate_stock_execution_feedback_gate(
        action="BUY",
        stock_code="600000",
        policy={"enabled": True, "require_trend_confirmation": False},
        summary=StockExecutionFeedbackSummary(stock_code="600000", lookback_days=20),
        market_snapshot=market_snapshot,
        current_time="2026-01-08 10:00:00",
    )

    assert gate["status"] == "downgraded"
    assert gate["size_multiplier"] == 0.4
    assert gate["outcome_feedback"]["reason_code"] == "poor_buy_outcome_feedback"


def test_portfolio_guard_applies_outcome_feedback_penalty_after_signal_context_passes() -> None:
    signal = {
        "action": "BUY",
        "tech_score": 0.7,
        "strategy_profile": {
            "market_snapshot": {
                "latest_price": 10.5,
                "ma5": 10.6,
                "ma10": 10.4,
                "ma20": 10.0,
                "ma20_slope": 0.03,
                "volume_ratio": 1.4,
                "recent_checkpoints": [
                    {"close": 10.2, "ma20": 10.0},
                    {"close": 10.4, "ma20": 10.0},
                    {"close": 10.5, "ma20": 10.0},
                ],
                "outcome_feedback": {
                    "summary": {
                        "actionable": True,
                        "outcome_feedback_score": 20,
                        "reason_code": "poor_buy_outcome_feedback",
                    }
                },
            },
            "effective_thresholds": {"tech_buy_threshold": 0.35},
            "explainability": {
                "fusion_breakdown": {
                    "fusion_score": 0.55,
                    "buy_threshold_eff": 0.35,
                    "fusion_confidence": 0.7,
                }
            },
        },
    }

    gate = evaluate_portfolio_execution_guard(signal=signal, policy={"enabled": True})

    assert gate["score_components"]["risk_penalties"]["outcome_feedback"] > 0
    assert "outcome_feedback_penalty" in gate["reasons"]


def test_run_feedback_does_not_create_live_feedback(tmp_path: Path) -> None:
    live_db = QuantSimDB(tmp_path / "live.db")
    replay_db = QuantSimReplayDB(tmp_path / "replay.db")
    replay_db.upsert_sim_run_signal_outcome_score(
        {
            **_outcome(10, score=30, matured_at="2026-01-06 10:00:00"),
            "run_id": 9,
            "run_type": "historical_replay",
            "domain": "replay",
        }
    )

    OutcomeFeedbackAggregator(replay_db).aggregate(
        OutcomeFeedbackRequest(
            stock_code="600000",
            profile_id="aggressive",
            as_of_checkpoint="2026-01-08 10:00:00",
            policy={"min_feedback_samples": 1},
            run_scope=OutcomeRunScope(run_id=9, run_type="historical_replay", domain="replay"),
        )
    )
    live_feedback = live_db.get_latest_outcome_feedback(
        OutcomeFeedbackFilters(stock_code="600000", profile_id="aggressive")
    )
    run_feedback = replay_db.get_latest_outcome_feedback(
        OutcomeFeedbackFilters(stock_code="600000", profile_id="aggressive"),
        run_scope={"run_id": 9, "run_type": "historical_replay"},
    )

    assert live_feedback is None
    assert run_feedback is not None
    assert run_feedback["summary"]["reason_code"] == "poor_buy_outcome_feedback"
