"""Prepared evidence helpers for discovery-to-quant lifecycle handoff."""

from __future__ import annotations

from typing import Any

from app.quant_sim.evidence_models import PreparedEvidenceInput
from app.quant_sim.technical_entry_score import calculate_technical_entry_score
from app.quant_sim.time_utils import format_system_time, format_utc_iso_z
from app.watchlist_selector_integration import normalize_stock_code


SCORE_SEMANTICS = {
    "sourceScore": "discovery_source_audit_only",
    "sourceConfidence": "discovery_source_audit_only",
    "candidateScore": "quant_technical_entry_score",
    "candidateConfidence": "quant_technical_confidence",
}

PAYLOAD_SCORE_SEMANTICS = {
    "source_score": SCORE_SEMANTICS["sourceScore"],
    "source_confidence": SCORE_SEMANTICS["sourceConfidence"],
    "candidate_score": SCORE_SEMANTICS["candidateScore"],
    "candidate_confidence": SCORE_SEMANTICS["candidateConfidence"],
}


def build_prepared_evidence(request: PreparedEvidenceInput) -> dict[str, Any]:
    """Build a stable prepared evidence object from a hydrated candidate row."""

    row = request.row if isinstance(request.row, dict) else {}
    code = normalize_stock_code(row.get("code") or row.get("stock_code") or row.get("id"))
    source_key = _source_key(row, source_type=request.source_type)
    technical_payload = _technical_payload(row)
    score = calculate_technical_entry_score(
        [{"payload": technical_payload}],
        {},
        profile_id=request.profile_id,
    )
    status = _evidence_status(row, score)
    entry_gate = _entry_gate(row, score, status=status)
    evidence_at = _system_time(request.evaluated_at or format_utc_iso_z())
    return {
        "id": f"{request.run_id or 'unknown'}:{code or 'unknown'}:{source_key or request.source_type}",
        "runId": request.run_id,
        "stockCode": code,
        "stockName": str(row.get("name") or row.get("stock_name") or code or "").strip(),
        "source": {
            "type": request.source_type,
            "key": source_key,
            "name": str(row.get("source") or row.get("strategyName") or source_key or "").strip(),
            "auditScore": _float(row.get("source_score") or row.get("score")),
            "auditConfidence": _float(row.get("confidence") or row.get("source_confidence")),
        },
        "status": status,
        "technicalSnapshot": {
            "ready": bool(row.get("technical_snapshot_ready")),
            "status": str(row.get("technical_snapshot_status") or "unprepared").strip() or "unprepared",
            "missingFields": _missing_fields(row, score),
            "timeframe": str(row.get("technical_snapshot_timeframe") or "").strip(),
            "provider": str(row.get("technical_snapshot_provider") or "").strip(),
            "asOf": _system_time(row.get("technical_snapshot_at")),
            "preparedAt": _system_time(row.get("technical_snapshot_prepared_at")),
            "rowCount": int(_float(row.get("technical_snapshot_row_count"))),
            "indicatorVersion": str(row.get("technical_snapshot_indicator_version") or "").strip(),
        },
        "quantTechnical": {
            "candidateScore": round(float(score.get("candidate_score") or 0), 4),
            "candidateConfidence": round(float(score.get("candidate_confidence") or 0), 4),
            "breakdown": score.get("breakdown") if isinstance(score.get("breakdown"), dict) else {},
        },
        "entryGate": entry_gate,
        "refresh": {
            "artifactStatus": str(row.get("discoveryArtifactStatus") or "").strip(),
            "evaluatedAt": evidence_at,
            "lastReevaluation": row.get("refreshReEvaluation") if isinstance(row.get("refreshReEvaluation"), dict) else {},
        },
        "scoreSemantics": dict(SCORE_SEMANTICS),
        "evidenceAt": evidence_at,
    }


def attach_prepared_evidence(row: dict[str, Any], *, run_id: str, source_type: str = "discover") -> dict[str, Any]:
    """Attach prepared evidence and quant score aliases to a hydrated row."""

    evidence = build_prepared_evidence(
        PreparedEvidenceInput(
            row=row,
            run_id=run_id,
            source_type=source_type,
        )
    )
    technical = evidence.get("quantTechnical") if isinstance(evidence.get("quantTechnical"), dict) else {}
    row["preparedEvidence"] = evidence
    row["scoreSemantics"] = dict(SCORE_SEMANTICS)
    row["quant_technical_entry_score"] = technical.get("candidateScore", 0.0)
    row["technical_confidence"] = technical.get("candidateConfidence", 0.0)
    row["candidate_score"] = technical.get("candidateScore", 0.0)
    row["candidate_confidence"] = technical.get("candidateConfidence", 0.0)
    return row


def prepared_evidence_payload_fields(row: dict[str, Any], *, source_type: str) -> dict[str, Any]:
    """Return event payload fields that preserve evidence semantics."""

    evidence = row.get("preparedEvidence")
    if not isinstance(evidence, dict):
        evidence = build_prepared_evidence(
            PreparedEvidenceInput(
                row=row,
                run_id=str(row.get("discoveryRunId") or ""),
                source_type=source_type,
            )
        )
    technical = evidence.get("quantTechnical") if isinstance(evidence.get("quantTechnical"), dict) else {}
    payload = {
        "prepared_evidence": evidence,
        "score_semantics": dict(PAYLOAD_SCORE_SEMANTICS),
        "technical_entry_score": technical.get("candidateScore", 0.0),
        "technical_confidence": technical.get("candidateConfidence", 0.0),
        "candidate_score_source": SCORE_SEMANTICS["candidateScore"],
    }
    if isinstance(row.get("refreshReEvaluation"), dict):
        payload["refresh_re_evaluation"] = row.get("refreshReEvaluation")
    return payload


def _technical_payload(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "price",
        "latestPrice",
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
        "technical_confirmation_count",
        "technical_snapshot_ready",
        "technical_snapshot_status",
        "technical_snapshot_missing_fields",
        "technical_snapshot_timeframe",
        "technical_snapshot_provider",
        "technical_snapshot_at",
        "technical_snapshot_prepared_at",
        "technical_snapshot_row_count",
        "technical_snapshot_indicator_version",
    )
    payload = {key: row.get(key) for key in keys if row.get(key) not in (None, "")}
    if "price" not in payload and row.get("latestPrice") not in (None, ""):
        payload["price"] = row.get("latestPrice")
    return payload


def _entry_gate(row: dict[str, Any], score: dict[str, Any], *, status: str) -> dict[str, Any]:
    existing = row.get("entry_gate")
    if isinstance(existing, dict):
        return existing
    breakdown = score.get("breakdown") if isinstance(score.get("breakdown"), dict) else {}
    reason = str(row.get("blocking_reason") or breakdown.get("blocking_reason") or "").strip()
    if status == "ready" and not reason:
        return {"status": "not_evaluated", "passed": None, "reasonCode": ""}
    return {
        "status": "blocked" if reason else status,
        "passed": False if reason else None,
        "reasonCode": reason,
        "missingFields": _missing_fields(row, score),
    }


def _evidence_status(row: dict[str, Any], score: dict[str, Any]) -> str:
    if bool(row.get("technical_snapshot_ready")) and str(row.get("technical_snapshot_status") or "") == "ready":
        return "ready"
    breakdown = score.get("breakdown") if isinstance(score.get("breakdown"), dict) else {}
    reason = str(row.get("blocking_reason") or breakdown.get("blocking_reason") or "").strip()
    return reason or str(row.get("technical_snapshot_status") or "unprepared").strip() or "unprepared"


def _missing_fields(row: dict[str, Any], score: dict[str, Any]) -> list[str]:
    explicit = row.get("technical_snapshot_missing_fields")
    if isinstance(explicit, list):
        return [str(item) for item in explicit if str(item).strip()]
    breakdown = score.get("breakdown") if isinstance(score.get("breakdown"), dict) else {}
    missing = breakdown.get("missing_fields")
    if isinstance(missing, list):
        return [str(item) for item in missing if str(item).strip()]
    return []


def _source_key(row: dict[str, Any], *, source_type: str) -> str:
    for key in ("source_key", "strategyKey", "moduleKey"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return str(row.get("source") or row.get("strategyName") or source_type).strip()


def _system_time(value: Any) -> str:
    if value in (None, ""):
        return ""
    return format_system_time(value)


def _float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return round(float(str(value).replace(",", "").strip()), 4)
    except (TypeError, ValueError):
        return 0.0
