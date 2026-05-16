"""Discovery candidate artifact and refresh hydration helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.discover.lifecycle_scoring import normalize_discovery_lifecycle_row
from app.discover.market_snapshot import (
    MISSING_TECHNICAL_SNAPSHOT_REASON,
    REQUIRED_TECHNICAL_SNAPSHOT_FIELDS,
)
from app.quant_sim.time_utils import format_utc_iso_z
from app.selector_result_store import DEFAULT_SELECTOR_RESULT_DIR, load_latest_result, save_latest_result
from app.watchlist_selector_integration import normalize_stock_code


DISCOVERY_CANDIDATE_ARTIFACT_KEY = "discovery_candidate_artifact"

TECHNICAL_RUNTIME_KEYS = (
    "price",
    "ma5",
    "ma10",
    "ma20",
    "ma20_slope",
    "ma60",
    "amount",
    "volume_ratio",
    "rsi",
    "macd",
    "trend",
    "technical_snapshot_ready",
    "technical_snapshot_status",
    "technical_snapshot_missing_fields",
    "technical_snapshot_timeframe",
    "technical_snapshot_provider",
    "technical_snapshot_at",
    "technical_snapshot_prepared_at",
    "technical_snapshot_row_count",
    "technical_snapshot_indicator_version",
    "technical_snapshot_error",
)


def save_discovery_candidate_artifact(
    rows: list[dict[str, Any]],
    *,
    run_id: str,
    selected_at: str,
    summary: dict[str, Any] | None = None,
    refresh_summary: dict[str, Any] | None = None,
    base_dir: str | Path = DEFAULT_SELECTOR_RESULT_DIR,
) -> None:
    """Persist the latest aggregate discovery candidate set."""

    safe_rows = [dict(row) for row in rows if isinstance(row, dict)]
    save_latest_result(
        DISCOVERY_CANDIDATE_ARTIFACT_KEY,
        {
            "runId": str(run_id or "").strip(),
            "selectedAt": str(selected_at or "").strip(),
            "updatedAt": format_utc_iso_z(),
            "rows": safe_rows,
            "summary": dict(summary or {}),
            "refreshSummary": dict(refresh_summary or {}),
        },
        base_dir=base_dir,
    )


def load_discovery_candidate_artifact(
    base_dir: str | Path = DEFAULT_SELECTOR_RESULT_DIR,
) -> dict[str, Any]:
    """Return the latest discovery candidate artifact payload."""

    payload = load_latest_result(DISCOVERY_CANDIDATE_ARTIFACT_KEY, base_dir=base_dir)
    return payload if isinstance(payload, dict) else {}


def discovery_candidate_codes(base_dir: str | Path = DEFAULT_SELECTOR_RESULT_DIR) -> set[str]:
    """Return current discovery candidate codes for unified refresh."""

    payload = load_discovery_candidate_artifact(base_dir=base_dir)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return set()
    codes: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = _code(row.get("code") or row.get("stock_code") or row.get("id"))
        if code:
            codes.add(code)
    return codes


def hydrate_discovery_candidate_rows(
    rows: list[dict[str, Any]],
    runtime_entries: dict[str, dict[str, Any]],
    *,
    run_id: str = "",
    artifact_status: str = "current",
) -> list[dict[str, Any]]:
    """Merge latest runtime snapshot entries into discovery candidate rows."""

    hydrated: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        next_row = dict(row)
        code = _code(next_row.get("code") or next_row.get("stock_code") or next_row.get("id"))
        next_row["discoveryRunId"] = run_id
        next_row["discoveryArtifactStatus"] = artifact_status
        runtime = runtime_entries.get(code) if code else None
        if isinstance(runtime, dict):
            _merge_runtime_entry(next_row, runtime)
        if not _is_ready(next_row):
            _mark_unprepared(next_row, runtime)
        hydrated.append(next_row)
    return hydrated


def mark_rows_stale_unprepared(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark raw selector fallback rows as stale and not technically prepared."""

    stale_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        next_row = dict(row)
        next_row["discoveryArtifactStatus"] = "stale_unprepared"
        next_row["technical_snapshot_ready"] = False
        next_row["technical_snapshot_status"] = "stale_unprepared"
        next_row["technical_snapshot_missing_fields"] = list(REQUIRED_TECHNICAL_SNAPSHOT_FIELDS)
        next_row["blocking_reason"] = MISSING_TECHNICAL_SNAPSHOT_REASON
        next_row["eligible_status"] = "blocked"
        stale_rows.append(next_row)
    return stale_rows


def renormalize_hydrated_discovery_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Recalculate lifecycle score fields after runtime snapshot hydration."""

    total = len(rows)
    normalized_rows: list[dict[str, Any]] = []
    for rank, row in enumerate(rows, start=1):
        score_input = dict(row)
        for key in (
            "source_score",
            "score",
            "confidence",
            "candidate_confidence",
            "trend",
            "technical_confirmation_count",
            "lifecycle_score_diagnostics",
        ):
            score_input.pop(key, None)
        normalized = normalize_discovery_lifecycle_row(
            score_input,
            strategy_key=_text(row.get("strategyKey") or row.get("source")),
            strategy_name=_text(row.get("strategyName") or row.get("source")),
            rank=rank,
            total=total,
        )
        row.update(
            {
                "source_score": normalized.get("source_score"),
                "score": normalized.get("score"),
                "confidence": normalized.get("confidence"),
                "candidate_confidence": normalized.get("candidate_confidence"),
                "trend": normalized.get("trend"),
                "technical_confirmation_count": normalized.get("technical_confirmation_count"),
                "lifecycle_score_diagnostics": normalized.get("lifecycle_score_diagnostics"),
            }
        )
        normalized_rows.append(row)
    return normalized_rows


def technical_summary_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build task diagnostics from hydrated discovery rows."""

    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = _code(row.get("code") or row.get("stock_code") or row.get("id"))
        if code and code not in unique:
            unique[code] = row

    summary = {
        "uniqueStocks": len(unique),
        "prepared": 0,
        "complete": 0,
        "incomplete": 0,
        "failed": 0,
        "blocked": 0,
        "items": [],
    }
    for code, row in unique.items():
        status = str(row.get("technical_snapshot_status") or "unprepared").strip() or "unprepared"
        ready = bool(row.get("technical_snapshot_ready"))
        missing = row.get("technical_snapshot_missing_fields")
        if not isinstance(missing, list):
            missing = list(REQUIRED_TECHNICAL_SNAPSHOT_FIELDS)
        item = {
            "stock_code": code,
            "status": status,
            "ready": ready,
            "missing_fields": list(missing),
            "reason": str(row.get("technical_snapshot_error") or row.get("blocking_reason") or ""),
        }
        summary["items"].append(item)
        if ready and status == "ready":
            summary["prepared"] += 1
            summary["complete"] += 1
        elif status == "failed":
            summary["failed"] += 1
            summary["blocked"] += 1
        else:
            summary["incomplete"] += 1
            summary["blocked"] += 1
    return summary


def _merge_runtime_entry(row: dict[str, Any], runtime: dict[str, Any]) -> None:
    name = str(runtime.get("stock_name") or "").strip()
    sector = str(runtime.get("sector") or "").strip()
    latest_price = runtime.get("latest_price")
    if name:
        row["name"] = name
        _set_cell(row, 1, name)
    if sector:
        row["industry"] = sector
        _set_cell(row, 2, sector)
    if latest_price not in (None, ""):
        row["latestPrice"] = latest_price
        row["price"] = latest_price
        _set_cell(row, 4, latest_price)
    for key in ("market_cap", "pe_ratio", "pb_ratio"):
        if runtime.get(key) not in (None, ""):
            row[key] = runtime.get(key)
    for key in TECHNICAL_RUNTIME_KEYS:
        if key in runtime and runtime.get(key) not in (None, ""):
            row[key] = runtime.get(key)


def _mark_unprepared(row: dict[str, Any], runtime: dict[str, Any] | None) -> None:
    runtime = runtime if isinstance(runtime, dict) else {}
    status = str(runtime.get("technical_snapshot_status") or row.get("technical_snapshot_status") or "unprepared")
    missing = runtime.get("technical_snapshot_missing_fields") or row.get("technical_snapshot_missing_fields")
    if not isinstance(missing, list) or not missing:
        missing = list(REQUIRED_TECHNICAL_SNAPSHOT_FIELDS)
    row["technical_snapshot_ready"] = False
    row["technical_snapshot_status"] = status
    row["technical_snapshot_missing_fields"] = list(missing)
    row["blocking_reason"] = MISSING_TECHNICAL_SNAPSHOT_REASON
    row["eligible_status"] = "blocked"
    if runtime.get("technical_snapshot_error"):
        row["technical_snapshot_error"] = runtime.get("technical_snapshot_error")


def _is_ready(row: dict[str, Any]) -> bool:
    return bool(row.get("technical_snapshot_ready")) and str(row.get("technical_snapshot_status") or "") == "ready"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _set_cell(row: dict[str, Any], index: int, value: Any) -> None:
    cells = row.get("cells")
    if isinstance(cells, list) and len(cells) > index:
        cells[index] = value


def _code(value: Any) -> str:
    code = normalize_stock_code(value)
    if code.isdigit() and len(code) < 6:
        try:
            return f"{int(code):06d}"
        except (TypeError, ValueError):
            return code
    return code


__all__ = [
    "DISCOVERY_CANDIDATE_ARTIFACT_KEY",
    "TECHNICAL_RUNTIME_KEYS",
    "discovery_candidate_codes",
    "hydrate_discovery_candidate_rows",
    "load_discovery_candidate_artifact",
    "mark_rows_stale_unprepared",
    "renormalize_hydrated_discovery_rows",
    "save_discovery_candidate_artifact",
    "technical_summary_from_rows",
]
