"""Run-scoped market technical artifact helpers for replay and drill runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app.quant_sim.market_technical_artifact import (
    ArtifactWriteRequest,
    MarketTechnicalArtifactData,
    MarketTechnicalArtifactRef,
)
from app.quant_sim.market_technical_artifact_store import MarketTechnicalArtifactStore
from app.quant_sim.time_utils import format_local_time, market_timezone, parse_datetime_with_default_timezone, local_now_text
from app.quant_sim.lifecycle_artifact_adapter import artifact_to_payload
from app.stock_refresh_artifact_writer import EXPECTED_ARTIFACT_FIELDS, build_market_technical_data_from_entry
from app.watchlist_selector_integration import normalize_stock_code


@dataclass(frozen=True)
class RunArtifactContext:
    db_file: str | Path
    run_id: int | str
    run_type: str
    shared_db_file: str | Path | None = None
    market: str = "CN"
    timeframe: str = "30m"
    data_version: str = "mta_v1"
    trace_id: str = "NO_TRACE"


@dataclass(frozen=True)
class RunArtifactItem:
    stock_code: str
    checkpoint: datetime | str
    stock_name: str | None = None
    reason_code: str = "missing_artifact"


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
    checkpoint_text = _checkpoint_at(checkpoint, context.market)
    shared = _read_shared_checkpoint_artifact(context, stock_code=code, checkpoint_at=checkpoint_text)
    if shared is not None:
        data = shared.data
    else:
        entry = _snapshot_entry(snapshot, checkpoint=checkpoint, market=context.market, timeframe=context.timeframe)
        data = _write_shared_checkpoint_artifact(context, stock_code=code, checkpoint_at=checkpoint_text, entry=entry)
    artifact = _write_run_checkpoint_artifact(context, stock_code=code, checkpoint_at=checkpoint_text, data=data)
    return {
        "artifact_ref": artifact.artifact_ref,
        "source_status": artifact.data.source_status,
        "reason_code": artifact.data.reason_code,
    }


def ensure_run_artifacts_for_checkpoint(
    context: RunArtifactContext,
    *,
    items: list[RunArtifactItem],
    snapshot_loader: Callable[[RunArtifactItem], dict[str, Any] | None],
) -> dict[str, dict[str, Any]]:
    """Ensure a run-scoped artifact set with one batched run write for the checkpoint."""

    if not items:
        return {}
    run_store = MarketTechnicalArtifactStore(context.db_file)
    shared_store = MarketTechnicalArtifactStore(context.shared_db_file) if context.shared_db_file is not None else None
    results: dict[str, dict[str, Any]] = {}
    run_requests: list[ArtifactWriteRequest] = []
    shared_requests: list[ArtifactWriteRequest] = []
    seen: set[tuple[str, str]] = set()

    for item in items:
        code = normalize_stock_code(item.stock_code)
        if not code:
            continue
        checkpoint_text = _checkpoint_at(item.checkpoint, context.market)
        key = (code, checkpoint_text)
        if key in seen:
            continue
        seen.add(key)
        run_ref = MarketTechnicalArtifactRef(
            domain=_domain_for_run_type(context.run_type),
            run_id=str(context.run_id),
            run_type=context.run_type,
            stock_code=code,
            market=context.market,
            checkpoint_at=checkpoint_text,
            timeframe=context.timeframe,
            data_version=context.data_version,
        )
        existing_run = run_store.get_by_ref(run_ref.to_ref(), log_missing=False)
        if existing_run.artifact is not None:
            results[code] = artifact_to_payload(existing_run.artifact)
            continue
        shared = _read_shared_checkpoint_artifact(context, stock_code=code, checkpoint_at=checkpoint_text)
        if shared is not None:
            data = shared.data
        else:
            snapshot = snapshot_loader(item)
            if snapshot:
                entry = _snapshot_entry(snapshot, checkpoint=item.checkpoint, market=context.market, timeframe=context.timeframe)
                data = build_market_technical_data_from_entry(entry, computed_at=local_now_text())
                if shared_store is not None:
                    shared_requests.append(
                        ArtifactWriteRequest(
                            ref=MarketTechnicalArtifactRef.live(
                                stock_code=code,
                                market=context.market,
                                checkpoint_at=checkpoint_text,
                                timeframe=context.timeframe,
                                data_version=context.data_version,
                            ),
                            data=data,
                            trace_id=context.trace_id,
                        )
                    )
            else:
                data = MarketTechnicalArtifactData(
                    source_status="missing",
                    reason_code=item.reason_code,
                    computed_at=local_now_text(),
                    provider="historical_snapshot",
                    missing_fields=list(EXPECTED_ARTIFACT_FIELDS),
                )
        run_requests.append(ArtifactWriteRequest(ref=run_ref, data=data, trace_id=context.trace_id))

    if shared_requests and shared_store is not None:
        shared_store.upsert_many(shared_requests)
    if run_requests:
        for artifact in run_store.upsert_many(run_requests):
            results[artifact.ref.stock_code] = artifact_to_payload(artifact)
    return results


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
    checkpoint_text = _checkpoint_at(checkpoint, context.market)
    shared = _read_shared_checkpoint_artifact(context, stock_code=code, checkpoint_at=checkpoint_text)
    if shared is not None:
        artifact = _write_run_checkpoint_artifact(context, stock_code=code, checkpoint_at=checkpoint_text, data=shared.data)
        return {
            "artifact_ref": artifact.artifact_ref,
            "source_status": artifact.data.source_status,
            "reason_code": artifact.data.reason_code,
        }
    artifact = _write_run_checkpoint_artifact(
        context,
        stock_code=code,
        checkpoint_at=checkpoint_text,
        data=MarketTechnicalArtifactData(
            source_status="missing",
            reason_code=reason_code,
            computed_at=local_now_text(),
            provider="historical_snapshot",
            missing_fields=list(EXPECTED_ARTIFACT_FIELDS),
        ),
    )
    return {
        "artifact_ref": artifact.artifact_ref,
        "source_status": artifact.data.source_status,
        "reason_code": artifact.data.reason_code,
    }


def _write_run_checkpoint_artifact(
    context: RunArtifactContext,
    *,
    stock_code: str,
    checkpoint_at: str,
    data: MarketTechnicalArtifactData,
):
    ref = MarketTechnicalArtifactRef(
        domain=_domain_for_run_type(context.run_type),
        run_id=str(context.run_id),
        run_type=context.run_type,
        stock_code=stock_code,
        market=context.market,
        checkpoint_at=checkpoint_at,
        timeframe=context.timeframe,
        data_version=context.data_version,
    )
    return MarketTechnicalArtifactStore(context.db_file).upsert(
        ArtifactWriteRequest(
            ref=ref,
            data=data,
            trace_id=context.trace_id,
        )
    )


def _write_shared_checkpoint_artifact(
    context: RunArtifactContext,
    *,
    stock_code: str,
    checkpoint_at: str,
    entry: dict[str, Any],
):
    data = build_market_technical_data_from_entry(entry, computed_at=local_now_text())
    if context.shared_db_file is None:
        return data
    ref = MarketTechnicalArtifactRef.live(
        stock_code=stock_code,
        market=context.market,
        checkpoint_at=checkpoint_at,
        timeframe=context.timeframe,
        data_version=context.data_version,
    )
    return MarketTechnicalArtifactStore(context.shared_db_file).upsert(
        ArtifactWriteRequest(ref=ref, data=data, trace_id=context.trace_id)
    ).data


def _read_shared_checkpoint_artifact(
    context: RunArtifactContext,
    *,
    stock_code: str,
    checkpoint_at: str,
):
    if context.shared_db_file is None:
        return None
    ref = MarketTechnicalArtifactRef.live(
        stock_code=stock_code,
        market=context.market,
        checkpoint_at=checkpoint_at,
        timeframe=context.timeframe,
        data_version=context.data_version,
    )
    result = MarketTechnicalArtifactStore(context.shared_db_file).get_by_ref(ref.to_ref(), log_missing=False)
    if result.artifact is None or not _is_stable_shared_artifact(result.artifact.data):
        return None
    return result.artifact


def _is_stable_shared_artifact(data: MarketTechnicalArtifactData) -> bool:
    return data.source_status not in {"missing", "source_failed", "invalid"} and data.reason_code != "missing_artifact"


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
    result = MarketTechnicalArtifactStore(context.db_file).get_by_ref(ref, log_missing=False)
    if result.artifact is None:
        shared = _read_shared_checkpoint_artifact(
            context,
            stock_code=normalize_stock_code(stock_code),
            checkpoint_at=_checkpoint_at(checkpoint, context.market),
        )
        if shared is not None:
            artifact = _write_run_checkpoint_artifact(
                context,
                stock_code=normalize_stock_code(stock_code),
                checkpoint_at=_checkpoint_at(checkpoint, context.market),
                data=shared.data,
            )
            return artifact_to_payload(artifact)
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
    return format_local_time(dt)


def _domain_for_run_type(run_type: str) -> str:
    text = str(run_type or "").strip()
    if text == "live_quant_drill":
        return "drill"
    return "replay"
