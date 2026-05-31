from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.gateway.context import UIApiContext
from app.quant_sim.db import OutcomeScoreFilters
from app.quant_sim.market_technical_artifact_store import MarketTechnicalArtifactStore
from app.quant_sim.outcome_scoring_entrypoints import (
    OutcomeBatchRequest,
    OutcomeBatchScope,
    score_signal_batch,
    summarize_outcome_rows,
)
from app.quant_sim.time_utils import format_local_time


@dataclass(frozen=True)
class SignalOutcomeQuery:
    signal_id: int
    source: str
    run_id: int | None = None
    run_type: str | None = None
    horizon: int | None = None


def signal_outcome_rows(context: UIApiContext, query: SignalOutcomeQuery) -> list[dict[str, Any]]:
    filters = OutcomeScoreFilters(signal_id=query.signal_id, limit=50)
    rows = (
        context.replay_db().list_sim_run_signal_outcome_scores(
            int(query.run_id),
            str(query.run_type or "historical_replay"),
            filters,
        )
        if query.source == "replay" and query.run_id is not None
        else context.quant_db().list_signal_outcome_scores(filters)
    )
    if query.horizon is not None:
        rows = [row for row in rows if int(row.get("horizon_checkpoints") or 0) == int(query.horizon)]
    return sorted(rows, key=lambda row: (int(row.get("horizon_checkpoints") or 0), int(row.get("id") or 0)))


def run_outcome_summary(
    context: UIApiContext,
    *,
    run_id: int,
    run_type: str,
    stock_code: str | None = None,
) -> dict[str, Any]:
    filters = OutcomeScoreFilters(stock_code=stock_code, limit=5000) if stock_code else OutcomeScoreFilters(limit=5000)
    rows = context.replay_db().list_sim_run_signal_outcome_scores(int(run_id), run_type, filters)
    return summarize_outcome_rows(rows)


def score_run_outcomes(
    context: UIApiContext,
    *,
    run_id: int,
    run_type: str,
    limit: int = 500,
) -> dict[str, Any]:
    db = context.replay_db()
    result = score_signal_batch(
        OutcomeBatchRequest(
            db=db,
            artifact_store=MarketTechnicalArtifactStore(context.quant_sim_replay_db_file),
            scope=OutcomeBatchScope(
                run_id=int(run_id),
                run_type=run_type,
                domain="drill" if run_type == "live_quant_drill" else "replay",
            ),
            as_of_checkpoint=_run_latest_checkpoint(db, int(run_id)),
            limit=limit,
            trace_id=f"api_run_outcomes_{run_id}",
        )
    )
    return {"run_id": int(run_id), "run_type": run_type, **result}


def score_live_matured_outcomes(context: UIApiContext, *, limit: int = 500) -> dict[str, Any]:
    db = context.quant_db()
    return score_signal_batch(
        OutcomeBatchRequest(
            db=db,
            artifact_store=MarketTechnicalArtifactStore(context.quant_sim_db_file),
            scope=OutcomeBatchScope(),
            as_of_checkpoint=format_local_time(),
            limit=limit,
            trace_id="api_live_outcomes",
        )
    )


def _run_latest_checkpoint(db: Any, run_id: int) -> str | None:
    checkpoints = db.get_sim_run_checkpoints(run_id, limit=1, order="desc")
    if not checkpoints:
        return None
    return str(checkpoints[0].get("checkpoint_at") or "") or None
