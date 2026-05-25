"""Entry gates for quant universe candidate events."""

from __future__ import annotations

from typing import Any


PROFILE_LIQUIDITY_MIN_AMOUNT = {
    "aggressive": 30_000_000.0,
    "stable": 50_000_000.0,
    "conservative": 80_000_000.0,
}

DISCOVERY_REQUIRED_TECHNICAL_SNAPSHOT_FIELDS = (
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
    "technical_snapshot_status",
    "technical_snapshot_at",
    "technical_snapshot_timeframe",
    "technical_snapshot_provider",
    "technical_snapshot_indicator_version",
)
MISSING_TECHNICAL_SNAPSHOT_REASON = "missing_technical_snapshot"


def evaluate_candidate_entry_gate(event: dict[str, Any], *, profile_id: str | None = None) -> dict[str, Any]:
    """Return a normalized entry gate decision for a candidate event.

    Source identity is audit metadata only. A passing result means the event may
    continue into lifecycle scoring with the same data-readiness semantics no
    matter where the candidate came from.
    """

    profile = _profile(profile_id)
    evidence = _evidence(event)
    if _is_discovery_event(event):
        technical_snapshot = _discovery_technical_snapshot_gate(evidence)
        if not technical_snapshot["passed"]:
            return _block_result(
                evidence,
                result="eligible_blocked",
                status="blocked",
                reason_code=MISSING_TECHNICAL_SNAPSHOT_REASON,
                missing_fields=technical_snapshot["missing_fields"],
            )

    common = _common_gate(evidence, profile=profile)
    if not common["passed"]:
        return common
    technical_snapshot = _discovery_technical_snapshot_gate(evidence)
    if not technical_snapshot["passed"]:
        return _block_result(
            evidence,
            result="eligible_blocked",
            status="blocked",
            reason_code=MISSING_TECHNICAL_SNAPSHOT_REASON,
            missing_fields=technical_snapshot["missing_fields"],
        )
    return _pass_result(evidence)


def _common_gate(
    evidence: dict[str, Any],
    *,
    profile: str,
) -> dict[str, Any]:
    if not evidence:
        return _block_result(evidence, result="rejected", status="rejected", reason_code="data_incomplete")

    price = _num(_pick(evidence, "price", "current_price", "latest_price", "close"), 0.0)
    ma20 = _num(_pick(evidence, "ma20", "MA20"), 0.0)
    ma20_slope = _num(_pick(evidence, "ma20_slope", "MA20_slope"), 0.0)
    amount = _num(_pick(evidence, "amount", "turnover", "成交额"), 0.0)

    if price <= 0:
        return _block_result(evidence, result="rejected", status="rejected", reason_code="data_incomplete")
    if amount > 0:
        min_amount = PROFILE_LIQUIDITY_MIN_AMOUNT[profile]
        if amount < min_amount:
            return _block_result(evidence, result="eligible_blocked", status="blocked", reason_code="liquidity_weak")
    if ma20 > 0 and price > 0 and price < ma20 and ma20_slope < 0:
        return _block_result(evidence, result="eligible_blocked", status="blocked", reason_code="persistent_downtrend")
    return _pass_result(evidence)


def _pass_result(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "passed": True,
        "result": "passed",
        "status": "active",
        "reason_code": "",
        "reason_codes": [],
        "common_gate": {"passed": True},
        "source_gate": {"passed": True},
        "evidence_keys": sorted(str(key) for key in evidence.keys()),
    }


def _block_result(
    evidence: dict[str, Any],
    *,
    result: str,
    status: str,
    reason_code: str,
    missing_fields: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "passed": False,
        "result": result,
        "status": status,
        "reason_code": reason_code,
        "reason_codes": [reason_code],
        "common_gate": {"passed": reason_code not in {"data_incomplete", "liquidity_weak", "persistent_downtrend", MISSING_TECHNICAL_SNAPSHOT_REASON}},
        "source_gate": {"passed": False},
        "evidence_keys": sorted(str(key) for key in evidence.keys()),
        "missing_fields": list(missing_fields or []),
    }


def _is_discovery_event(event: dict[str, Any]) -> bool:
    return str(event.get("source_type") or "").strip().lower() == "discover"


def _discovery_technical_snapshot_gate(evidence: dict[str, Any]) -> dict[str, Any]:
    explicit_missing = evidence.get("technical_snapshot_missing_fields")
    if isinstance(explicit_missing, list) and explicit_missing:
        return {"passed": False, "missing_fields": [str(item) for item in explicit_missing if str(item).strip()]}
    missing = _missing_technical_snapshot_fields(evidence)
    if missing:
        return {"passed": False, "missing_fields": missing}
    status = str(evidence.get("technical_snapshot_status") or "").strip().lower()
    if status and status != "ready":
        return {"passed": False, "missing_fields": []}
    return {"passed": True, "missing_fields": []}


def _missing_technical_snapshot_fields(evidence: dict[str, Any]) -> list[str]:
    return [
        field
        for field in DISCOVERY_REQUIRED_TECHNICAL_SNAPSHOT_FIELDS
        if not _technical_snapshot_field_present(evidence, field)
    ]


def _technical_snapshot_field_present(evidence: dict[str, Any], field: str) -> bool:
    if field == "price":
        value = _pick(evidence, "price", "current_price", "latest_price", "close")
    elif field == "rsi":
        value = _pick(evidence, "rsi", "rsi14", "rsi12", "rsi6", "RSI")
    elif field == "technical_snapshot_at":
        value = _pick(evidence, "technical_snapshot_at", "snapshot_at", "datetime", "date", "time", "quote_time")
    elif field == "technical_snapshot_status":
        value = _pick(evidence, "technical_snapshot_status", "snapshot_status")
    elif field == "technical_snapshot_timeframe":
        value = _pick(evidence, "technical_snapshot_timeframe", "timeframe", "period")
    elif field == "technical_snapshot_provider":
        value = _pick(evidence, "technical_snapshot_provider", "provider", "source")
    elif field == "technical_snapshot_indicator_version":
        value = _pick(evidence, "technical_snapshot_indicator_version", "indicator_version")
    else:
        value = _pick(evidence, field, field.upper())
    if value in (None, ""):
        return False
    if field in {
        "trend",
        "technical_snapshot_status",
        "technical_snapshot_at",
        "technical_snapshot_timeframe",
        "technical_snapshot_provider",
        "technical_snapshot_indicator_version",
    }:
        return bool(str(value).strip())
    number = _num(value, 0.0)
    if field in {"ma20_slope", "macd", "rsi"}:
        return True
    return number > 0


def _profile(profile_id: str | None) -> str:
    text = str(profile_id or "").strip().lower()
    if "aggressive" in text:
        return "aggressive"
    if "conservative" in text:
        return "conservative"
    return "stable"


def _evidence(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload_json")
    if isinstance(payload, dict):
        return dict(payload)
    payload = event.get("payload")
    if isinstance(payload, dict):
        return dict(payload)
    return {}


def _pick(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
