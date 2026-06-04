"""Preload run-scoped market technical artifacts before replay/drill loops."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from app.quant_sim.replay_artifact_adapter import (
    RunArtifactContext,
    RunArtifactItem,
    ensure_run_artifacts_for_checkpoint,
)
from app.quant_sim.time_utils import format_local_time, market_timezone, parse_datetime_with_default_timezone
from app.watchlist_selector_integration import normalize_stock_code


@dataclass(frozen=True)
class RunMarketArtifactPreloadRequest:
    db_file: str | Path
    shared_db_file: str | Path
    run_id: int | str
    run_type: str
    market: str
    timeframe: str
    stock_items: list[dict[str, Any]]
    checkpoints: list[datetime]
    snapshot_loader: Callable[[RunArtifactItem], dict[str, Any] | None]
    data_version: str = "mta_v1"
    trace_id: str = "NO_TRACE"


def preload_run_market_artifacts(request: RunMarketArtifactPreloadRequest) -> dict[str, Any]:
    """Materialize all selected quant stocks for the target checkpoint range.

    The preloader writes stable shared artifacts and run-scoped references before
    the execution loop starts. Later checkpoint code can then read by artifact
    identity instead of rebuilding the same data frame row-by-row.
    """

    started = perf_counter()
    stocks = _normalize_stock_items(request.stock_items)
    checkpoints = list(request.checkpoints or [])
    context = RunArtifactContext(
        db_file=request.db_file,
        shared_db_file=request.shared_db_file,
        run_id=request.run_id,
        run_type=request.run_type,
        market=request.market,
        timeframe=request.timeframe,
        data_version=request.data_version,
        trace_id=request.trace_id,
    )
    stats = {
        "stock_count": len(stocks),
        "checkpoint_count": len(checkpoints),
        "requested": len(stocks) * len(checkpoints),
        "ready": 0,
        "missing": 0,
        "partial": 0,
        "source_failed": 0,
        "elapsed_seconds": 0.0,
        "first_checkpoint_at": _checkpoint_text(checkpoints[0], request.market) if checkpoints else "",
        "last_checkpoint_at": _checkpoint_text(checkpoints[-1], request.market) if checkpoints else "",
    }
    if not stocks or not checkpoints:
        stats["elapsed_seconds"] = round(perf_counter() - started, 3)
        return stats

    for checkpoint in checkpoints:
        items = [
            RunArtifactItem(
                stock_code=stock["stock_code"],
                stock_name=stock.get("stock_name") or stock["stock_code"],
                checkpoint=checkpoint,
            )
            for stock in stocks
        ]
        payloads = ensure_run_artifacts_for_checkpoint(
            context,
            items=items,
            snapshot_loader=request.snapshot_loader,
        )
        _accumulate_status_counts(stats, payloads.values(), len(items))

    stats["elapsed_seconds"] = round(perf_counter() - started, 3)
    return stats


def _normalize_stock_items(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items or []:
        code = normalize_stock_code(str(item.get("stock_code") or ""))
        if not code or code in seen:
            continue
        seen.add(code)
        name = str(item.get("stock_name") or item.get("name") or code).strip() or code
        normalized.append({"stock_code": code, "stock_name": name})
    return normalized


def _accumulate_status_counts(stats: dict[str, Any], payloads: Any, expected_count: int) -> None:
    seen_count = 0
    for payload in payloads:
        seen_count += 1
        source_status = str(payload.get("source_status") or "").strip()
        reason_code = str(payload.get("reason_code") or "").strip()
        if source_status in {"ready", "stale"} and reason_code != "missing_artifact":
            stats["ready"] += 1
        elif source_status == "partial":
            stats["partial"] += 1
        elif source_status in {"source_failed", "invalid"}:
            stats["source_failed"] += 1
        else:
            stats["missing"] += 1
    if seen_count < expected_count:
        stats["missing"] += expected_count - seen_count


def _checkpoint_text(value: datetime | str, market: str) -> str:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = parse_datetime_with_default_timezone(value, market_timezone(market))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=market_timezone(market))
    return format_local_time(dt)
