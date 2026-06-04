"""Shared entry points for live and run-scoped outcome scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.quant_sim.db import OutcomeFeedbackFilters, OutcomeScoreFilters, QuantSimDB
from app.quant_sim.market_technical_artifact_store import MarketTechnicalArtifactStore
from app.quant_sim.outcome_feedback import OutcomeFeedbackAggregator, OutcomeFeedbackRequest
from app.quant_sim.signal_outcome_policy import normalize_signal_outcome_policy
from app.quant_sim.signal_outcome_scoring import OutcomeRunScope, OutcomeScoringRequest, SignalOutcomeScoringService
from app.quant_sim.time_utils import format_local_time


@dataclass(frozen=True)
class OutcomeBatchScope:
    run_id: int | None = None
    run_type: str | None = None
    domain: str = "live"

    @property
    def run_scope(self) -> OutcomeRunScope | None:
        if self.run_id is None:
            return None
        return OutcomeRunScope(run_id=int(self.run_id), run_type=str(self.run_type or "historical_replay"), domain=self.domain)


@dataclass(frozen=True)
class OutcomeBatchRequest:
    db: QuantSimDB
    artifact_store: MarketTechnicalArtifactStore
    scope: OutcomeBatchScope
    as_of_checkpoint: str | None = None
    limit: int = 500
    trace_id: str = "NO_TRACE"


def score_signal_batch(request: OutcomeBatchRequest) -> dict[str, Any]:
    service = SignalOutcomeScoringService(request.db, request.artifact_store)
    signals = _signals_for_request(request)
    mature_horizons = _mature_horizons_by_signal(request)
    scored = 0
    mature_count = 0
    stock_profiles: dict[str, str] = {}
    for signal in signals:
        if str(signal.get("action") or "").upper() not in {"BUY", "SELL"}:
            continue
        if _all_expected_horizons_mature(signal, mature_horizons):
            continue
        results = service.score_signal(
            OutcomeScoringRequest(
                signal=signal,
                run_scope=request.scope.run_scope,
                as_of_checkpoint=request.as_of_checkpoint,
                trace_id=request.trace_id,
            )
        )
        scored += 1
        signal_mature_count = sum(1 for item in results if item.status == "mature")
        mature_count += signal_mature_count
        code = str(signal.get("stock_code") or "").strip()
        if code and signal_mature_count > 0:
            stock_profiles[code] = _profile_id_from_signal(signal)

    feedback_rows = _aggregate_feedback(request, stock_profiles)
    rows = _outcome_rows_for_request(request)
    return {
        "scored_signals": scored,
        "mature_count": mature_count,
        "feedback_count": feedback_rows,
        "feedback_stocks": sorted(stock_profiles),
        "summary": summarize_outcome_rows(rows),
    }


def summarize_outcome_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    mature = [row for row in rows if row.get("status") == "mature"]
    buy = [row for row in mature if str(row.get("action") or "").upper() == "BUY"]
    sell = [row for row in mature if str(row.get("action") or "").upper() == "SELL"]
    bad_buy = [row for row in buy if float(row.get("outcome_score") or 0) < 45]
    good_sell = [row for row in sell if float(row.get("outcome_score") or 0) >= 65]
    return {
        "total_count": len(rows),
        "mature_count": len(mature),
        "skipped_count": len(rows) - len(mature),
        "buy_count": len(buy),
        "sell_count": len(sell),
        "buy_avg_score": _avg(buy),
        "sell_avg_score": _avg(sell),
        "bad_buy_count": len(bad_buy),
        "good_sell_count": len(good_sell),
        "top_positive": _top(mature, reverse=True),
        "top_negative": _top(mature, reverse=False),
    }


def _signals_for_request(request: OutcomeBatchRequest) -> list[dict[str, Any]]:
    limit = max(1, min(int(request.limit or 500), 10000))
    if request.scope.run_id is not None:
        return request.db.get_sim_run_signals(
            int(request.scope.run_id),
            limit=limit,
            actions=("BUY", "SELL"),
            include_strategy_profile=True,
        )
    return request.db.get_signals(limit=limit, actions=("BUY", "SELL"))


def _outcome_rows_for_request(request: OutcomeBatchRequest) -> list[dict[str, Any]]:
    filters = OutcomeScoreFilters(limit=5000)
    if request.scope.run_id is not None:
        return request.db.list_sim_run_signal_outcome_scores(
            int(request.scope.run_id),
            str(request.scope.run_type or "historical_replay"),
            filters,
        )
    return request.db.list_signal_outcome_scores(filters)


def _mature_horizons_by_signal(request: OutcomeBatchRequest) -> dict[int, set[int]]:
    filters = OutcomeScoreFilters(status="mature", limit=None)
    if request.scope.run_id is not None:
        rows = request.db.list_sim_run_signal_outcome_scores(
            int(request.scope.run_id),
            str(request.scope.run_type or "historical_replay"),
            filters,
        )
    else:
        rows = request.db.list_signal_outcome_scores(filters)
    mature_horizons: dict[int, set[int]] = {}
    for row in rows:
        signal_id = _signal_id(row)
        horizon = _int_value(row.get("horizon_checkpoints"))
        if signal_id > 0 and horizon > 0:
            mature_horizons.setdefault(signal_id, set()).add(horizon)
    return mature_horizons


def _all_expected_horizons_mature(signal: dict[str, Any], mature_horizons: dict[int, set[int]]) -> bool:
    signal_id = _signal_id(signal)
    if signal_id <= 0:
        return False
    existing = mature_horizons.get(signal_id)
    if not existing:
        return False
    policy = normalize_signal_outcome_policy(None, profile_id=_profile_id_from_signal(signal))
    expected = {int(item) for item in policy.get("outcome_horizons_checkpoints") or [] if _int_value(item) > 0}
    return bool(expected) and expected.issubset(existing)


def _aggregate_feedback(request: OutcomeBatchRequest, stock_profiles: dict[str, str]) -> int:
    if not stock_profiles:
        return 0
    as_of_checkpoint = request.as_of_checkpoint or _latest_matured_at(request) or format_local_time()
    aggregator = OutcomeFeedbackAggregator(request.db)
    written = 0
    for code in sorted(stock_profiles):
        aggregator.aggregate(
            OutcomeFeedbackRequest(
                stock_code=code,
                profile_id=stock_profiles[code],
                as_of_checkpoint=as_of_checkpoint,
                run_scope=request.scope.run_scope,
            )
        )
        written += 1
    return written


def _latest_matured_at(request: OutcomeBatchRequest) -> str | None:
    row = request.db.get_latest_outcome_feedback(
        OutcomeFeedbackFilters(as_of_checkpoint_lte=format_local_time()),
        run_scope=(
            {"run_id": int(request.scope.run_id), "run_type": str(request.scope.run_type or "historical_replay")}
            if request.scope.run_id is not None
            else None
        ),
    )
    return str(row.get("latest_matured_at") or "") if row else None


def _profile_id_from_signal(signal: dict[str, Any]) -> str:
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    selected = profile.get("selected_strategy_profile") if isinstance(profile.get("selected_strategy_profile"), dict) else {}
    return (
        str(selected.get("id") or "").strip()
        or str(profile.get("strategy_profile_id") or profile.get("profile_id") or "").strip()
        or "aggressive"
    )


def _signal_id(payload: dict[str, Any]) -> int:
    return _int_value(payload.get("signal_id") or payload.get("id"))


def _int_value(value: Any) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _avg(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    return round(sum(float(row.get("outcome_score") or 0) for row in rows) / len(rows), 4)


def _top(rows: list[dict[str, Any]], *, reverse: bool) -> list[dict[str, Any]]:
    sorted_rows = sorted(
        rows,
        key=lambda row: (float(row.get("outcome_score") or 0), str(row.get("stock_code") or ""), int(row.get("id") or 0)),
        reverse=reverse,
    )
    return [
        {
            "stock_code": row.get("stock_code"),
            "action": row.get("action"),
            "horizon_checkpoints": row.get("horizon_checkpoints"),
            "outcome_score": row.get("outcome_score"),
            "reason_code": row.get("reason_code"),
        }
        for row in sorted_rows[:5]
    ]
