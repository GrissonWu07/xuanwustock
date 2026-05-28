"""Run-scoped market technical artifact helpers for replay and drill runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.quant_sim.market_technical_artifact import (
    ArtifactWriteRequest,
    MarketTechnicalArtifactData,
    MarketTechnicalArtifactRef,
)
from app.quant_sim.market_technical_artifact_store import MarketTechnicalArtifactStore
from app.quant_sim.time_utils import format_utc_iso_z, market_timezone, parse_datetime_with_default_timezone, utc_now_iso_z
from app.quant_sim.lifecycle_artifact_adapter import artifact_to_payload
from app.stock_refresh_artifact_writer import EXPECTED_ARTIFACT_FIELDS, build_market_technical_data_from_entry
from app.watchlist_selector_integration import normalize_stock_code


@dataclass(frozen=True)
class RunArtifactContext:
    db_file: str | Path
    run_id: int | str
    run_type: str
    market: str = "CN"
    timeframe: str = "30m"
    data_version: str = "mta_v1"
    trace_id: str = "NO_TRACE"


def write_run_artifact_from_snapshot(
    context: RunArtifactContext,
    *,
    stock_code: str,
    checkpoint: datetime | str,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    code = normalize_stock_code(stock_code)
    if not code:
        return {"artifact_ref": "", "source_status": "missing", "reason_code": "missing_artifact_reference"}
    entry = _snapshot_entry(snapshot, checkpoint=checkpoint, market=context.market, timeframe=context.timeframe)
    ref = MarketTechnicalArtifactRef(
        domain=_domain_for_run_type(context.run_type),
        run_id=str(context.run_id),
        run_type=context.run_type,
        stock_code=code,
        market=context.market,
        checkpoint_at=_checkpoint_at(checkpoint, context.market),
        timeframe=context.timeframe,
        data_version=context.data_version,
    )
    artifact = MarketTechnicalArtifactStore(context.db_file).upsert(
        ArtifactWriteRequest(
            ref=ref,
            data=build_market_technical_data_from_entry(entry, computed_at=utc_now_iso_z()),
            trace_id=context.trace_id,
        )
    )
    return {
        "artifact_ref": artifact.artifact_ref,
        "source_status": artifact.data.source_status,
        "reason_code": artifact.data.reason_code,
    }


def write_missing_run_artifact(
    context: RunArtifactContext,
    *,
    stock_code: str,
    checkpoint: datetime | str,
    reason_code: str = "missing_artifact",
) -> dict[str, Any]:
    code = normalize_stock_code(stock_code)
    if not code:
        return {"artifact_ref": "", "source_status": "missing", "reason_code": "missing_artifact_reference"}
    ref = MarketTechnicalArtifactRef(
        domain=_domain_for_run_type(context.run_type),
        run_id=str(context.run_id),
        run_type=context.run_type,
        stock_code=code,
        market=context.market,
        checkpoint_at=_checkpoint_at(checkpoint, context.market),
        timeframe=context.timeframe,
        data_version=context.data_version,
    )
    artifact = MarketTechnicalArtifactStore(context.db_file).upsert(
        ArtifactWriteRequest(
            ref=ref,
            data=MarketTechnicalArtifactData(
                source_status="missing",
                reason_code=reason_code,
                computed_at=utc_now_iso_z(),
                provider="historical_snapshot",
                missing_fields=list(EXPECTED_ARTIFACT_FIELDS),
            ),
            trace_id=context.trace_id,
        )
    )
    return {
        "artifact_ref": artifact.artifact_ref,
        "source_status": artifact.data.source_status,
        "reason_code": artifact.data.reason_code,
    }


def read_run_artifact(
    context: RunArtifactContext,
    *,
    stock_code: str,
    checkpoint: datetime | str,
) -> dict[str, Any]:
    ref = MarketTechnicalArtifactRef(
        domain=_domain_for_run_type(context.run_type),
        run_id=str(context.run_id),
        run_type=context.run_type,
        stock_code=normalize_stock_code(stock_code),
        market=context.market,
        checkpoint_at=_checkpoint_at(checkpoint, context.market),
        timeframe=context.timeframe,
        data_version=context.data_version,
    ).to_ref()
    result = MarketTechnicalArtifactStore(context.db_file).get_by_ref(ref)
    if result.artifact is None:
        return {"artifact_ref": ref, "source_status": "missing", "reason_code": result.reason_code}
    return artifact_to_payload(result.artifact)


def _snapshot_entry(snapshot: dict[str, Any], *, checkpoint: datetime | str, market: str, timeframe: str) -> dict[str, Any]:
    entry = dict(snapshot or {})
    entry.setdefault("latest_price", entry.get("current_price") or entry.get("close"))
    entry.setdefault("price", entry.get("latest_price"))
    if "technical_snapshot_ready" not in entry and "technical_snapshot_status" not in entry:
        entry["technical_snapshot_ready"] = True
        entry["technical_snapshot_status"] = "ready"
    entry.setdefault("technical_snapshot_timeframe", timeframe)
    entry.setdefault("technical_snapshot_provider", entry.get("provider") or "historical_snapshot")
    entry.setdefault("technical_snapshot_at", _checkpoint_at(checkpoint, market))
    entry.setdefault("technical_snapshot_indicator_version", entry.get("indicator_version") or f"{contextless_run_version()}-v1")
    return entry


def contextless_run_version() -> str:
    return "run-artifact"


def _checkpoint_at(value: datetime | str, market: str) -> str:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = parse_datetime_with_default_timezone(value, market_timezone(market))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=market_timezone(market))
    return format_utc_iso_z(dt)


def _domain_for_run_type(run_type: str) -> str:
    text = str(run_type or "").strip()
    if text == "live_quant_drill":
        return "drill"
    return "replay"
