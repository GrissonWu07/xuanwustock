from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from app.quant_sim.market_technical_artifact import InvalidArtifactRef, parse_artifact_ref
from app.quant_sim.market_technical_artifact_store import MarketTechnicalArtifactStore


def artifact_diagnostics_from_payload(payload: Any) -> dict[str, Any]:
    source = _safe_dict(payload)
    artifact_ref = _txt(source.get("artifact_ref"))
    source_status = _txt(
        source.get("source_status")
        or source.get("technical_snapshot_status")
        or ("missing" if not artifact_ref else "")
    )
    reason_code = _txt(
        source.get("reason_code")
        or source.get("technical_snapshot_reason_code")
        or source.get("artifact_reason_code")
    )
    if not artifact_ref:
        reason_code = reason_code or "missing_artifact_reference"
        source_status = source_status or "missing"
    return _diagnostic_payload(
        artifact_ref=artifact_ref,
        source_status=source_status,
        reason_code=reason_code,
        missing_fields=_missing_fields(source),
    )


def artifact_diagnostics_from_signal_payload(
    signal: dict[str, Any],
    strategy_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = _safe_dict(strategy_profile if strategy_profile is not None else signal.get("strategy_profile"))
    artifact_ref, evidence = extract_signal_artifact_reference(signal, profile)
    if not artifact_ref:
        return artifact_diagnostics_from_payload(evidence)
    return _diagnostic_payload(
        artifact_ref=artifact_ref,
        source_status=_txt(evidence.get("source_status")),
        reason_code=_txt(evidence.get("reason_code")),
        missing_fields=_missing_fields(evidence),
    )


def build_signal_artifact_diagnostics(
    context: Any,
    *,
    signal: dict[str, Any],
    source: str,
    strategy_profile: dict[str, Any],
) -> dict[str, Any]:
    del source
    artifact_ref, evidence = extract_signal_artifact_reference(signal, strategy_profile)
    if not artifact_ref:
        return artifact_diagnostics_from_payload(evidence)
    parsed = parse_artifact_ref(artifact_ref)
    if isinstance(parsed, InvalidArtifactRef):
        return _diagnostic_payload(
            artifact_ref=artifact_ref,
            source_status="invalid",
            reason_code=parsed.reason_code,
            missing_fields=[],
        )
    store = MarketTechnicalArtifactStore(
        context.quant_sim_db_file if parsed.domain == "live" else context.quant_sim_replay_db_file
    )
    result = store.get_by_ref(artifact_ref)
    if result.artifact is None:
        return _diagnostic_payload(
            artifact_ref=artifact_ref,
            source_status=result.source_status,
            reason_code=result.reason_code,
            missing_fields=result.missing_fields,
        )
    artifact = result.artifact
    return _diagnostic_payload(
        artifact_ref=artifact.artifact_ref,
        source_status=artifact.data.source_status,
        reason_code=artifact.data.reason_code,
        missing_fields=artifact.data.missing_fields,
        domain=artifact.ref.domain,
        run_id=artifact.ref.run_id,
        run_type=artifact.ref.run_type,
        checkpoint_at=artifact.ref.checkpoint_at,
        timeframe=artifact.ref.timeframe,
    )


def latest_candidate_artifact_diagnostics(
    db: Any,
    stock_code: str,
    *,
    db_file: Any = None,
) -> dict[str, Any]:
    list_candidate_events = getattr(db, "list_candidate_events", None)
    if not callable(list_candidate_events):
        return artifact_diagnostics_from_payload({})
    events = list_candidate_events(stock_code=stock_code, limit=1)
    if not events:
        return artifact_diagnostics_from_payload({})
    payload = events[0].get("payload_json")
    diagnostics = artifact_diagnostics_from_payload(payload)
    artifact_ref = str(diagnostics.get("artifact_ref") or "").strip()
    if not artifact_ref or not db_file:
        return diagnostics
    parsed = parse_artifact_ref(artifact_ref)
    if isinstance(parsed, InvalidArtifactRef):
        return _diagnostic_payload(
            artifact_ref=artifact_ref,
            source_status="invalid",
            reason_code=parsed.reason_code,
            missing_fields=[],
        )
    if parsed.domain != "live":
        return _diagnostic_payload(
            artifact_ref=artifact_ref,
            source_status="invalid",
            reason_code="invalid_artifact_ref",
            missing_fields=[],
        )
    result = MarketTechnicalArtifactStore(db_file).get_by_ref(artifact_ref)
    if result.artifact is None:
        return _diagnostic_payload(
            artifact_ref=artifact_ref,
            source_status=result.source_status,
            reason_code=result.reason_code,
            missing_fields=result.missing_fields,
        )
    artifact = result.artifact
    return _diagnostic_payload(
        artifact_ref=artifact.artifact_ref,
        source_status=artifact.data.source_status,
        reason_code=artifact.data.reason_code,
        missing_fields=artifact.data.missing_fields,
        domain=artifact.ref.domain,
        run_id=artifact.ref.run_id,
        run_type=artifact.ref.run_type,
        checkpoint_at=artifact.ref.checkpoint_at,
        timeframe=artifact.ref.timeframe,
    )


def extract_signal_artifact_reference(
    signal: dict[str, Any],
    strategy_profile: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    direct = _safe_dict(signal)
    profile = _safe_dict(strategy_profile)
    explainability = _safe_dict(profile.get("explainability"))
    for source in (
        direct,
        profile.get("market_snapshot"),
        explainability.get("market_snapshot"),
        profile.get("snapshot"),
        profile,
    ):
        payload = _safe_dict(source)
        artifact_ref = _txt(payload.get("artifact_ref"))
        if artifact_ref:
            return artifact_ref, payload
    return "", {}


def _diagnostic_payload(
    *,
    artifact_ref: str,
    source_status: str,
    reason_code: str,
    missing_fields: list[str],
    domain: str = "",
    run_id: str = "",
    run_type: str = "",
    checkpoint_at: str = "",
    timeframe: str = "",
) -> dict[str, Any]:
    reason = reason_code or ("ok" if source_status == "ready" else "missing_artifact_reference")
    status = source_status or ("ready" if reason == "ok" else "missing")
    payload = {
        "artifact_ref": artifact_ref,
        "source_status": status,
        "reason_code": reason,
        "missing_fields": missing_fields,
        "query_path": f"/api/v1/quant/market-technical-artifacts/{quote(artifact_ref, safe='')}" if artifact_ref else "",
        "available": bool(artifact_ref and status == "ready" and reason == "ok"),
    }
    if domain:
        payload.update(
            {
                "domain": domain,
                "run_id": run_id,
                "run_type": run_type,
                "checkpoint_at": checkpoint_at,
                "timeframe": timeframe,
            }
        )
    return payload


def _missing_fields(payload: dict[str, Any]) -> list[str]:
    raw = (
        payload.get("missing_fields")
        or payload.get("technical_snapshot_missing_fields")
        or payload.get("artifact_missing_fields")
        or []
    )
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.split(",")]
    if not isinstance(raw, list):
        return []
    return sorted(str(item) for item in raw if str(item).strip())


def _safe_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _txt(value: Any) -> str:
    return str(value or "").strip()


__all__ = [
    "artifact_diagnostics_from_payload",
    "artifact_diagnostics_from_signal_payload",
    "build_signal_artifact_diagnostics",
    "extract_signal_artifact_reference",
    "latest_candidate_artifact_diagnostics",
]
