"""Replay checkpoint coverage and context parity response helpers."""

from __future__ import annotations

from typing import Any


def enrich_replay_tasks_with_coverage(payload: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach coverage/context metadata from replay run metadata to task rows."""

    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return payload
    runs_by_id = {str(run.get("id") or ""): run for run in runs if isinstance(run, dict)}
    for task in tasks:
        if not isinstance(task, dict):
            continue
        run = runs_by_id.get(str(task.get("runId") or ""))
        metadata = run.get("metadata") if isinstance(run, dict) and isinstance(run.get("metadata"), dict) else {}
        task["checkpointCoverage"] = _checkpoint_coverage(metadata, task)
        task["contextParity"] = _context_parity(metadata)
    return payload


def _checkpoint_coverage(metadata: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    raw = metadata.get("checkpoint_coverage") if isinstance(metadata.get("checkpoint_coverage"), dict) else {}
    checkpoint_count = _int(raw.get("checkpoint_count"), _int(task.get("checkpointCount"), 0))
    exact_count = _int(raw.get("exact_count"), 0)
    nearest_count = _int(raw.get("nearest_count"), 0)
    missing_count = _int(raw.get("missing_count"), 0)
    skipped_count = _int(raw.get("skipped_count"), 0)
    total = exact_count + nearest_count + missing_count + skipped_count
    return {
        "status": "ready" if raw else "unavailable",
        "stockCount": _int(raw.get("stock_count"), 0),
        "checkpointCount": checkpoint_count,
        "exactCount": exact_count,
        "nearestCount": nearest_count,
        "missingCount": missing_count,
        "skippedCount": skipped_count,
        "readyCount": exact_count + nearest_count,
        "coverageCount": total,
        "failureReasons": _string_list(raw.get("failure_reasons")),
    }


def _context_parity(metadata: dict[str, Any]) -> dict[str, Any]:
    raw = metadata.get("context_parity") if isinstance(metadata.get("context_parity"), dict) else {}
    stock_context = raw.get("stock_analysis_context") if isinstance(raw.get("stock_analysis_context"), dict) else {}
    status = str(stock_context.get("status") or "omitted").strip() or "omitted"
    reason = str(stock_context.get("omitted_reason") or stock_context.get("omittedReason") or "").strip()
    if status == "omitted" and not reason:
        reason = "historical_replay_asof_safety"
    return {
        "stockAnalysisContext": {
            "status": status,
            "omittedReason": reason,
        }
    }


def _int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return default


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
