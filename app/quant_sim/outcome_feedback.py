"""Aggregate mature signal outcomes into stock-level feedback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from app.quant_sim.db import OutcomeFeedbackFilters, OutcomeScoreFilters, QuantSimDB
from app.quant_sim.signal_outcome_policy import normalize_signal_outcome_policy
from app.quant_sim.signal_outcome_scoring import OutcomeRunScope
from app.quant_sim.time_utils import format_local_time, parse_system_datetime


@dataclass(frozen=True)
class OutcomeFeedbackRequest:
    stock_code: str
    profile_id: str
    as_of_checkpoint: str
    policy: dict[str, Any] | None = None
    run_scope: OutcomeRunScope | None = None


@dataclass(frozen=True)
class OutcomeFeedbackSummary:
    stock_code: str
    profile_id: str
    as_of_checkpoint: str
    outcome_feedback_score: float
    sample_count: int
    buy_avg_score: float
    sell_avg_score: float
    latest_matured_at: str | None
    summary: dict[str, Any]


class OutcomeFeedbackAggregator:
    """Build matured-only feedback summaries for future decisions."""

    def __init__(self, db: QuantSimDB):
        self.db = db

    def aggregate(self, request: OutcomeFeedbackRequest, *, persist: bool = True) -> OutcomeFeedbackSummary:
        policy = normalize_signal_outcome_policy(request.policy, profile_id=request.profile_id)
        rows = self._mature_rows(request, int(policy["feedback_lookback_days"]))
        summary = self._summarize_rows(rows, policy)
        payload = OutcomeFeedbackSummary(
            stock_code=request.stock_code,
            profile_id=request.profile_id,
            as_of_checkpoint=format_local_time(request.as_of_checkpoint),
            outcome_feedback_score=float(summary["outcome_feedback_score"]),
            sample_count=int(summary["sample_count"]),
            buy_avg_score=float(summary["buy_avg_score"]),
            sell_avg_score=float(summary["sell_avg_score"]),
            latest_matured_at=summary.get("latest_matured_at"),
            summary=summary,
        )
        if persist:
            record = {
                "stock_code": payload.stock_code,
                "profile_id": payload.profile_id,
                "as_of_checkpoint": payload.as_of_checkpoint,
                "feedback_score": payload.outcome_feedback_score,
                "sample_count": payload.sample_count,
                "buy_avg_score": payload.buy_avg_score,
                "sell_avg_score": payload.sell_avg_score,
                "latest_matured_at": payload.latest_matured_at,
                "summary": payload.summary,
            }
            if request.run_scope:
                record.update(
                    {
                        "run_id": request.run_scope.run_id,
                        "run_type": request.run_scope.run_type,
                        "domain": request.run_scope.domain,
                    }
                )
                self.db.upsert_sim_run_outcome_feedback_score(record)
            else:
                record["domain"] = "live"
                self.db.upsert_outcome_feedback_score(record)
        return payload

    def latest(
        self,
        request: OutcomeFeedbackRequest,
    ) -> dict[str, Any] | None:
        run_scope = (
            {"run_id": request.run_scope.run_id, "run_type": request.run_scope.run_type}
            if request.run_scope
            else None
        )
        return self.db.get_latest_outcome_feedback(
            OutcomeFeedbackFilters(
                stock_code=request.stock_code,
                profile_id=request.profile_id,
                as_of_checkpoint_lte=format_local_time(request.as_of_checkpoint),
            ),
            run_scope=run_scope,
        )

    def _mature_rows(self, request: OutcomeFeedbackRequest, lookback_days: int) -> list[dict[str, Any]]:
        filters = OutcomeScoreFilters(
            stock_code=request.stock_code,
            matured_at_lte=format_local_time(request.as_of_checkpoint),
            status="mature",
            limit=500,
        )
        if request.run_scope:
            rows = self.db.list_sim_run_signal_outcome_scores(
                request.run_scope.run_id,
                request.run_scope.run_type,
                filters,
            )
        else:
            rows = self.db.list_signal_outcome_scores(filters)
        cutoff = parse_system_datetime(request.as_of_checkpoint) - timedelta(days=max(1, int(lookback_days)))
        return [
            row
            for row in rows
            if row.get("matured_at") and parse_system_datetime(row["matured_at"]) >= cutoff
        ]

    def _summarize_rows(self, rows: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
        mature_rows = sorted(
            rows,
            key=lambda row: (str(row.get("matured_at") or ""), int(row.get("id") or 0)),
            reverse=True,
        )
        buy_rows = [row for row in mature_rows if str(row.get("action") or "").upper() == "BUY"]
        sell_rows = [row for row in mature_rows if str(row.get("action") or "").upper() == "SELL"]
        score = _decay_weighted_score(mature_rows)
        buy_avg = _average_score(buy_rows)
        sell_avg = _average_score(sell_rows)
        poor_buy_threshold = float(policy["poor_buy_score_threshold"])
        good_sell_threshold = float(policy["good_sell_score_threshold"])
        failed_buy_rows = [
            row
            for row in buy_rows
            if float(row.get("outcome_score") or 0) < poor_buy_threshold
            or bool(row.get("metrics", {}).get("invalidation_hit"))
            or bool(row.get("metrics", {}).get("ma20_break_after_buy"))
        ]
        bad_sell_rows = [
            row
            for row in sell_rows
            if float(row.get("outcome_score") or 0) < 50
            or not bool(row.get("metrics", {}).get("sell_validated", False))
        ]
        sample_count = len(mature_rows)
        min_samples = int(policy["min_feedback_samples"])
        actionable = sample_count >= min_samples
        poor_buy_actionable = actionable and buy_rows and buy_avg < poor_buy_threshold
        multiplier = 1.0
        requires_stronger_confirmation = False
        if poor_buy_actionable:
            severity = min(1.0, max(0.0, (poor_buy_threshold - buy_avg) / max(poor_buy_threshold, 1.0)))
            floor = float(policy["feedback_size_multiplier_floor"])
            multiplier = max(floor, 1.0 - severity)
            requires_stronger_confirmation = True
        latest_matured_at = mature_rows[0].get("matured_at") if mature_rows else None
        return {
            "outcome_feedback_score": round(score, 4),
            "sample_count": sample_count,
            "buy_sample_count": len(buy_rows),
            "sell_sample_count": len(sell_rows),
            "buy_avg_score": round(buy_avg, 4),
            "sell_avg_score": round(sell_avg, 4),
            "latest_matured_at": latest_matured_at,
            "recent_failed_probe_count": len(failed_buy_rows),
            "repeated_weak_signal_count": len(failed_buy_rows),
            "good_sell_validation_count": len([row for row in sell_rows if float(row.get("outcome_score") or 0) >= good_sell_threshold]),
            "bad_sell_validation_count": len(bad_sell_rows),
            "decay_weighted_score": round(score, 4),
            "min_feedback_samples": min_samples,
            "actionable": actionable,
            "requires_stronger_confirmation": requires_stronger_confirmation,
            "recommended_size_multiplier": round(multiplier, 6),
            "reason_code": _reason_code(actionable, poor_buy_actionable, bool(bad_sell_rows)),
        }


def _decay_weighted_score(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 50.0
    weighted_total = 0.0
    weight_sum = 0.0
    for index, row in enumerate(rows):
        weight = 0.85 ** index
        weighted_total += float(row.get("outcome_score") or 0) * weight
        weight_sum += weight
    return weighted_total / weight_sum if weight_sum > 0 else 50.0


def _average_score(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 50.0
    return sum(float(row.get("outcome_score") or 0) for row in rows) / len(rows)


def _reason_code(actionable: bool, poor_buy: bool, bad_sell: bool) -> str:
    if not actionable:
        return "insufficient_mature_samples"
    if poor_buy:
        return "poor_buy_outcome_feedback"
    if bad_sell:
        return "weak_sell_outcome_feedback"
    return "neutral_or_positive_outcome_feedback"
