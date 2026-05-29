"""Refresh-triggered re-evaluation for prepared discovery candidates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.discover.candidate_artifact import (
    hydrate_discovery_candidate_rows,
    load_discovery_candidate_artifact,
    renormalize_hydrated_discovery_rows,
)
from app.gateway.quant_universe_entry import ingest_lifecycle_entry_rows
from app.quant_sim.evidence_models import CandidateReevaluationRequest
from app.quant_sim.evidence_service import attach_prepared_evidence
from app.quant_sim.time_utils import format_system_time, local_now_text
from app.stock_refresh_artifact_writer import write_live_artifacts_for_refresh
from app.selector_result_store import DEFAULT_SELECTOR_RESULT_DIR, load_latest_result
from app.watchlist_selector_integration import normalize_stock_code


RUNTIME_SNAPSHOT_KEY = "stock_runtime_snapshot"
DATA_BLOCK_REASONS = {
    "missing_technical_snapshot",
    "stale_technical_snapshot",
    "stale_unprepared",
}


def reevaluate_refreshed_discovery_candidates(
    context: Any,
    *,
    run_reason: str = "refresh",
) -> dict[str, Any]:
    """Re-evaluate current discovery candidates after runtime snapshot refresh."""

    return _reevaluate(CandidateReevaluationRequest(context=context, run_reason=run_reason))


def _reevaluate(request: CandidateReevaluationRequest) -> dict[str, Any]:
    context = request.context
    artifact = load_discovery_candidate_artifact(base_dir=context.selector_result_dir)
    artifact_rows = artifact.get("rows") if isinstance(artifact.get("rows"), list) else []
    if not artifact_rows:
        return _summary(request.run_reason)

    runtime_entries = _load_runtime_entries(context.selector_result_dir)
    db = context.quant_db()
    runtime_entries = _ensure_runtime_artifacts(
        db,
        runtime_entries,
        run_reason=request.run_reason,
    )
    rows = hydrate_discovery_candidate_rows(
        artifact_rows,
        runtime_entries,
        run_id=str(artifact.get("runId") or ""),
        artifact_status="current",
    )
    rows = renormalize_hydrated_discovery_rows(rows)
    summary = _summary(request.run_reason)
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = normalize_stock_code(row.get("code") or row.get("stock_code") or row.get("id"))
        if not code or not _needs_re_evaluation(db, code):
            continue
        summary["attempted"] += 1
        if not _is_ready(row):
            summary["skipped"].append({"stockCode": code, "reason": "technical_snapshot_not_ready"})
            continue
        row["refreshReEvaluation"] = {
            "run_reason": request.run_reason,
            "evaluated_at": _system_time(request.evaluated_at or local_now_text()),
            "previous_reason": "missing_technical_snapshot",
        }
        attach_prepared_evidence(
            row,
            run_id=str(row.get("discoveryRunId") or artifact.get("runId") or ""),
            source_type="discover",
        )
        result = ingest_lifecycle_entry_rows(context, [row], source_type="discover")
        if int(result.get("events") or 0) > 0:
            summary["reEvaluated"] += 1
        summary["events"] += int(result.get("events") or 0)
        summary["promoted"] += int(result.get("promoted") or 0)
        summary["eligible"] += int(result.get("eligible") or 0)
        for skipped in result.get("skipped") or []:
            if isinstance(skipped, dict):
                summary["skipped"].append(skipped)
    summary["updatedAt"] = _system_time(request.evaluated_at or local_now_text())
    return summary


def _needs_re_evaluation(db: Any, stock_code: str) -> bool:
    events = _list_candidate_events(db, stock_code)
    if not events:
        return False
    return any(_is_data_blocked_event(event) for event in events)


def _list_candidate_events(db: Any, stock_code: str) -> list[dict[str, Any]]:
    try:
        return db.list_candidate_events(stock_code=stock_code, limit=20)
    except TypeError:
        return db.list_candidate_events(stock_code=stock_code, source_type="discover", limit=20)


def _is_data_blocked_event(event: dict[str, Any]) -> bool:
    if str(event.get("status") or "").strip() not in {"blocked", "recommended_only"}:
        return False
    payload = event.get("payload_json") if isinstance(event.get("payload_json"), dict) else {}
    gate = payload.get("entry_gate") if isinstance(payload.get("entry_gate"), dict) else {}
    reason = str(gate.get("reason_code") or payload.get("blocking_reason") or "").strip()
    status = str(payload.get("technical_snapshot_status") or "").strip()
    return reason in DATA_BLOCK_REASONS or status in DATA_BLOCK_REASONS


def _ensure_runtime_artifacts(
    db: Any,
    runtime_entries: dict[str, dict[str, Any]],
    *,
    run_reason: str,
) -> dict[str, dict[str, Any]]:
    db_file = str(getattr(db, "db_file", "") or "").strip()
    if not db_file:
        return runtime_entries
    ready_without_artifact = {
        code: entry
        for code, entry in runtime_entries.items()
        if isinstance(entry, dict)
        and bool(entry.get("technical_snapshot_ready"))
        and str(entry.get("technical_snapshot_status") or "").strip() == "ready"
        and not str(entry.get("artifact_ref") or "").strip()
    }
    if not ready_without_artifact:
        return runtime_entries
    projections = write_live_artifacts_for_refresh(
        db_file=db_file,
        entries=ready_without_artifact,
        market="CN",
        run_reason=f"candidate-reevaluation:{run_reason}",
    )
    if not projections:
        return runtime_entries
    next_entries = dict(runtime_entries)
    for code, projection in projections.items():
        next_entries[code] = {**next_entries.get(code, {}), **projection}
    return next_entries


def _load_runtime_entries(base_dir: str | Path = DEFAULT_SELECTOR_RESULT_DIR) -> dict[str, dict[str, Any]]:
    payload = load_latest_result(RUNTIME_SNAPSHOT_KEY, base_dir=base_dir) or {}
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_code, item in entries.items():
        code = normalize_stock_code(raw_code)
        if code and isinstance(item, dict):
            normalized[code] = dict(item)
    return normalized


def _is_ready(row: dict[str, Any]) -> bool:
    return bool(row.get("technical_snapshot_ready")) and str(row.get("technical_snapshot_status") or "") == "ready"


def _summary(run_reason: str) -> dict[str, Any]:
    return {
        "runReason": run_reason,
        "attempted": 0,
        "reEvaluated": 0,
        "events": 0,
        "eligible": 0,
        "promoted": 0,
        "skipped": [],
        "updatedAt": _system_time(local_now_text()),
    }


def _system_time(value: Any) -> str:
    if value in (None, ""):
        return ""
    return format_system_time(value)
