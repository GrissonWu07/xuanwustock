from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.gateway.artifact_diagnostics import artifact_diagnostics_from_payload
from app.quant_sim.market_technical_artifact import LIVE_DOMAIN, InvalidArtifactRef, parse_artifact_ref
from app.quant_sim.market_technical_artifact_store import MarketTechnicalArtifactStore
from app.stock_refresh_artifact_writer import derive_runtime_entry_from_artifact, write_live_artifacts_for_refresh
from app.watchlist_selector_integration import normalize_stock_code


@dataclass(frozen=True)
class PageArtifactProjectionRequest:
    db_file: str | Path
    row: dict[str, Any]
    runtime_entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    price_cell_index: int | None = None
    industry_cell_index: int | None = None


def apply_live_artifact_projection(request: PageArtifactProjectionRequest) -> dict[str, Any]:
    """Hydrate a page row from the live artifact referenced by runtime metadata."""

    row = dict(request.row)
    code = normalize_stock_code(row.get("code") or row.get("stock_code") or row.get("id"))
    runtime = request.runtime_entries.get(code) if code else None
    runtime = runtime if isinstance(runtime, dict) else {}
    artifact_ref = str(row.get("artifact_ref") or runtime.get("artifact_ref") or "").strip()
    if not artifact_ref:
        projection = _materialize_runtime_projection(request, code, runtime)
        if projection:
            _merge_projection(row, projection, request)
            row["artifactDiagnostics"] = artifact_diagnostics_from_payload(projection)
            row["marketTechnicalBacked"] = True
            return row
        _clear_market_projection(row, request)
        row["artifactDiagnostics"] = artifact_diagnostics_from_payload({})
        row["marketTechnicalBacked"] = False
        return row
    parsed = parse_artifact_ref(artifact_ref)
    if isinstance(parsed, InvalidArtifactRef) or parsed.domain != LIVE_DOMAIN:
        _clear_market_projection(row, request)
        row["artifactDiagnostics"] = {
            **artifact_diagnostics_from_payload({"artifact_ref": artifact_ref}),
            "source_status": "invalid",
            "reason_code": "invalid_artifact_ref",
        }
        row["marketTechnicalBacked"] = False
        return row
    result = MarketTechnicalArtifactStore(request.db_file).get_by_ref(parsed.to_ref())
    if result.artifact is None:
        _clear_market_projection(row, request)
        row["artifactDiagnostics"] = artifact_diagnostics_from_payload(
            {
                "artifact_ref": parsed.to_ref(),
                "source_status": result.source_status,
                "reason_code": result.reason_code,
                "missing_fields": result.missing_fields,
            }
        )
        row["marketTechnicalBacked"] = False
        return row
    projection = derive_runtime_entry_from_artifact(result.artifact, existing_entry=runtime)
    _merge_projection(row, projection, request)
    row["artifactDiagnostics"] = artifact_diagnostics_from_payload(projection)
    row["marketTechnicalBacked"] = True
    return row


def _materialize_runtime_projection(
    request: PageArtifactProjectionRequest,
    code: str,
    runtime: dict[str, Any],
) -> dict[str, Any]:
    if not code or not _runtime_ready_for_artifact(runtime):
        return {}
    projections = write_live_artifacts_for_refresh(
        db_file=request.db_file,
        entries={code: runtime},
        market=str(request.row.get("market") or runtime.get("market") or "CN"),
        run_reason="page-artifact-projection",
    )
    return projections.get(code) if isinstance(projections.get(code), dict) else {}


def _runtime_ready_for_artifact(runtime: dict[str, Any]) -> bool:
    return (
        bool(runtime.get("technical_snapshot_ready"))
        and str(runtime.get("technical_snapshot_status") or "").strip() == "ready"
    )


def apply_live_artifact_projection_to_rows(
    *,
    db_file: str | Path,
    rows: list[dict[str, Any]],
    runtime_entries: dict[str, dict[str, Any]],
    price_cell_index: int | None = None,
    industry_cell_index: int | None = None,
) -> list[dict[str, Any]]:
    return [
        apply_live_artifact_projection(
            PageArtifactProjectionRequest(
                db_file=db_file,
                row=row,
                runtime_entries=runtime_entries,
                price_cell_index=price_cell_index,
                industry_cell_index=industry_cell_index,
            )
        )
        for row in rows
        if isinstance(row, dict)
    ]


def _merge_projection(
    row: dict[str, Any],
    projection: dict[str, Any],
    request: PageArtifactProjectionRequest,
) -> None:
    latest_price = projection.get("latest_price")
    if latest_price not in (None, ""):
        row["latest_price"] = latest_price
        row["price"] = latest_price
        row["latestPrice"] = _num(latest_price)
        _set_cell(row, request.price_cell_index, _num(latest_price))
    sector = str(projection.get("sector") or "").strip()
    if sector:
        row["industry"] = sector
        _set_cell(row, request.industry_cell_index, sector)
    for key in (
        "artifact_ref",
        "source_status",
        "reason_code",
        "technical_snapshot_ready",
        "technical_snapshot_status",
        "technical_snapshot_missing_fields",
        "technical_snapshot_timeframe",
        "technical_snapshot_provider",
        "technical_snapshot_at",
        "technical_snapshot_prepared_at",
        "technical_snapshot_indicator_version",
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
    ):
        if key in projection:
            row[key] = projection.get(key)


def _clear_market_projection(row: dict[str, Any], request: PageArtifactProjectionRequest) -> None:
    for key in (
        "latest_price",
        "price",
        "latestPrice",
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
    ):
        row.pop(key, None)
    _set_cell(row, request.price_cell_index, "--")


def _set_cell(row: dict[str, Any], index: int | None, value: Any) -> None:
    if index is None:
        return
    cells = row.get("cells")
    if not isinstance(cells, list) or index < 0 or index >= len(cells):
        return
    cells[index] = value


def _num(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "--"


__all__ = [
    "PageArtifactProjectionRequest",
    "apply_live_artifact_projection",
    "apply_live_artifact_projection_to_rows",
]
