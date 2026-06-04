"""Artifact reader helpers for candidate lifecycle and signal decisions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.quant_sim.market_technical_artifact_store import MarketTechnicalArtifactStore


TECHNICAL_PAYLOAD_KEYS = (
    "current_price",
    "price",
    "latest_price",
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
    "price_vs_ma20",
    "price_vs_ma60",
    "ma_stack",
    "above_ma20_checkpoints",
    "retest_confirmed",
    "recent_checkpoints",
    "recent_5d_return",
    "technical_snapshot_ready",
    "technical_snapshot_status",
    "technical_snapshot_missing_fields",
    "technical_snapshot_timeframe",
    "technical_snapshot_provider",
    "technical_snapshot_at",
    "technical_snapshot_prepared_at",
    "technical_snapshot_indicator_version",
    "source_status",
    "reason_code",
    "artifact_ref",
)
ARTIFACT_DIAGNOSTIC_KEYS = (
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
)


def candidate_artifact_payload(row: dict[str, Any], *, db_file: str | Path | None) -> dict[str, Any]:
    """Return technical payload from artifact_ref only.

    Discovery/research source fields remain audit metadata. Candidate admission
    and signal scoring must use the artifact facts returned here.
    """

    artifact_ref = str(row.get("artifact_ref") or "").strip()
    if not artifact_ref:
        return _blocked_payload("", "missing_artifact_reference")
    if not db_file:
        return _blocked_payload(artifact_ref, "missing_artifact")
    result = MarketTechnicalArtifactStore(db_file).get_by_ref(artifact_ref)
    if result.artifact is None:
        return _blocked_payload(artifact_ref, result.reason_code or "missing_artifact")
    return artifact_to_payload(result.artifact)


def candidate_artifact_diagnostics(row: dict[str, Any], *, db_file: str | Path | None) -> dict[str, Any]:
    """Return only persisted artifact diagnostics for candidate event payloads."""

    payload = candidate_artifact_payload(row, db_file=db_file)
    return {key: payload.get(key) for key in ARTIFACT_DIAGNOSTIC_KEYS if key in payload}


def artifact_to_payload(artifact: Any) -> dict[str, Any]:
    data = artifact.data
    price = data.latest_price or data.close
    return {
        "artifact_ref": artifact.artifact_ref,
        "source_status": data.source_status,
        "reason_code": data.reason_code,
        "current_price": price,
        "price": price,
        "latest_price": data.latest_price,
        "ma5": data.ma5,
        "ma10": data.ma10,
        "ma20": data.ma20,
        "ma20_slope": data.ma20_slope,
        "ma60": data.ma60,
        "amount": data.amount,
        "volume_ratio": data.volume_ratio,
        "rsi": data.rsi,
        "macd": data.macd,
        "trend": data.trend,
        "price_vs_ma20": data.price_vs_ma20,
        "price_vs_ma60": data.price_vs_ma60,
        "ma_stack": data.ma_stack,
        "above_ma20_checkpoints": data.above_ma20_checkpoints,
        "retest_confirmed": data.retest_confirmed,
        "recent_checkpoints": list(data.structure_json.get("recent_checkpoints") or []),
        "recent_5d_return": data.structure_json.get("recent_5d_return"),
        "technical_snapshot_ready": data.source_status == "ready",
        "technical_snapshot_status": _technical_status(data.source_status),
        "technical_snapshot_missing_fields": list(data.missing_fields),
        "technical_snapshot_timeframe": artifact.ref.timeframe,
        "technical_snapshot_provider": data.provider or "",
        "technical_snapshot_at": artifact.ref.checkpoint_at,
        "technical_snapshot_prepared_at": data.computed_at or "",
        "technical_snapshot_indicator_version": data.indicator_version or "",
    }


def artifact_market_snapshot(row: dict[str, Any], *, db_file: str | Path | None) -> dict[str, Any]:
    payload = candidate_artifact_payload(row, db_file=db_file)
    return {key: payload.get(key) for key in TECHNICAL_PAYLOAD_KEYS if key in payload}


def artifact_gate_from_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    artifact_ref = str(evidence.get("artifact_ref") or "").strip()
    if not artifact_ref:
        return {"passed": False, "reason_code": "missing_artifact_reference", "missing_fields": []}
    source_status = str(evidence.get("source_status") or "").strip()
    reason_code = str(evidence.get("reason_code") or "").strip()
    if source_status and source_status != "ready":
        return {
            "passed": False,
            "reason_code": reason_code or _reason_from_source_status(source_status),
            "missing_fields": _missing_fields(evidence),
        }
    if reason_code and reason_code != "ok":
        return {"passed": False, "reason_code": reason_code, "missing_fields": _missing_fields(evidence)}
    return {"passed": True, "reason_code": "ok", "missing_fields": []}


def _blocked_payload(artifact_ref: str, reason_code: str) -> dict[str, Any]:
    return {
        "artifact_ref": artifact_ref,
        "source_status": "missing",
        "reason_code": reason_code,
        "technical_snapshot_ready": False,
        "technical_snapshot_status": reason_code,
        "technical_snapshot_missing_fields": [],
    }


def _technical_status(source_status: str) -> str:
    if source_status == "ready":
        return "ready"
    if source_status == "source_failed":
        return "failed"
    if source_status == "partial":
        return "incomplete"
    if source_status == "stale":
        return "stale"
    return source_status or "unknown"


def _reason_from_source_status(source_status: str) -> str:
    if source_status == "source_failed":
        return "source_failed"
    if source_status == "partial":
        return "incomplete_artifact"
    if source_status == "stale":
        return "stale_artifact"
    return source_status or "missing_artifact"


def _missing_fields(evidence: dict[str, Any]) -> list[str]:
    value = evidence.get("technical_snapshot_missing_fields")
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
