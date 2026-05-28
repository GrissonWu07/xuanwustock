from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.gateway.context import UIApiContext
from app.quant_sim.market_technical_artifact import (
    DEFAULT_DATA_VERSION,
    DRILL_DOMAIN,
    LIVE_DOMAIN,
    REPLAY_DOMAIN,
    ArtifactQuery,
    ArtifactReadResult,
    InvalidArtifactRef,
    parse_artifact_ref,
)
from app.quant_sim.market_technical_artifact_store import MarketTechnicalArtifactStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArtifactApiError(Exception):
    status_code: int
    payload: dict[str, Any]


def trace_id_from_request(request: Request) -> str:
    return str(
        request.headers.get("x-trace-id")
        or request.headers.get("x-request-id")
        or "NO_TRACE"
    )


def artifact_error_response(exc: ArtifactApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.payload)


def get_artifact_by_ref(
    context: UIApiContext,
    artifact_ref: str,
    *,
    trace_id: str = "NO_TRACE",
) -> dict[str, Any]:
    parsed = parse_artifact_ref(artifact_ref)
    if isinstance(parsed, InvalidArtifactRef):
        logger.warning(
            "market_artifact_query_rejected trace_id=%s reason_code=%s",
            trace_id,
            parsed.reason_code,
        )
        raise ArtifactApiError(400, _error_payload(artifact_ref, parsed.reason_code))
    canonical_ref = parsed.to_ref()
    result = _store_for_domain(context, parsed.domain).get_by_ref(canonical_ref)
    return _payload_or_raise(result, artifact_ref=canonical_ref, trace_id=trace_id)


def get_artifact_by_identity(
    context: UIApiContext,
    *,
    domain: str,
    stock_code: str,
    market: str,
    checkpoint_at: str,
    timeframe: str,
    data_version: str = DEFAULT_DATA_VERSION,
    run_id: str | None = None,
    run_type: str | None = None,
    trace_id: str = "NO_TRACE",
) -> dict[str, Any]:
    query = ArtifactQuery(
        domain=str(domain or "").strip(),
        run_id=str(run_id).strip() if run_id is not None else None,
        run_type=str(run_type).strip() if run_type is not None else None,
        stock_code=str(stock_code or "").strip(),
        market=str(market or "").strip(),
        checkpoint_at=str(checkpoint_at or "").strip(),
        timeframe=str(timeframe or "").strip(),
        data_version=str(data_version or DEFAULT_DATA_VERSION).strip(),
    )
    ref_or_reason = query.to_ref_or_reason()
    if isinstance(ref_or_reason, str):
        logger.warning(
            "market_artifact_identity_query_rejected trace_id=%s domain=%s reason_code=%s",
            trace_id,
            query.domain,
            ref_or_reason,
        )
        raise ArtifactApiError(400, _error_payload("", ref_or_reason))
    artifact_ref = ref_or_reason.to_ref()
    result = _store_for_domain(context, ref_or_reason.domain).get_by_query(query)
    return _payload_or_raise(result, artifact_ref=artifact_ref, trace_id=trace_id)


def _payload_or_raise(
    result: ArtifactReadResult,
    *,
    artifact_ref: str,
    trace_id: str,
) -> dict[str, Any]:
    if result.artifact is None:
        logger.info(
            "market_artifact_query_missing trace_id=%s reason_code=%s artifact_ref=%s",
            trace_id,
            result.reason_code,
            artifact_ref,
        )
        raise ArtifactApiError(
            404,
            _error_payload(
                artifact_ref,
                result.reason_code or "missing_artifact",
                source_status=result.source_status,
                missing_fields=result.missing_fields,
            ),
        )
    payload = result.artifact.to_dict()
    payload["found"] = True
    return payload


def _error_payload(
    artifact_ref: str,
    reason_code: str,
    *,
    source_status: str = "missing",
    missing_fields: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "found": False,
        "artifact_ref": artifact_ref or "",
        "source_status": source_status or "missing",
        "reason_code": reason_code or "missing_artifact",
        "missing_fields": [str(item) for item in (missing_fields or []) if str(item).strip()],
    }


def _store_for_domain(context: UIApiContext, domain: str) -> MarketTechnicalArtifactStore:
    if domain == LIVE_DOMAIN:
        return MarketTechnicalArtifactStore(context.quant_sim_db_file)
    if domain in {REPLAY_DOMAIN, DRILL_DOMAIN}:
        return MarketTechnicalArtifactStore(context.quant_sim_replay_db_file)
    raise ArtifactApiError(400, _error_payload("", "invalid_artifact_ref"))


__all__ = [
    "ArtifactApiError",
    "artifact_error_response",
    "get_artifact_by_identity",
    "get_artifact_by_ref",
    "trace_id_from_request",
]
