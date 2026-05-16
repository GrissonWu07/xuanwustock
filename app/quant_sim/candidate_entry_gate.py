"""Source-specific entry gates for quant universe candidate events."""

from __future__ import annotations

from typing import Any


PROFILE_LIQUIDITY_MIN_AMOUNT = {
    "aggressive": 30_000_000.0,
    "stable": 50_000_000.0,
    "conservative": 80_000_000.0,
}

LOW_PRICE_THRESHOLDS = {
    "aggressive": {"score": 0.72, "confidence": 0.68},
    "stable": {"score": 0.78, "confidence": 0.72},
    "conservative": {"score": 0.84, "confidence": 0.78},
}

RESEARCH_THRESHOLDS = {
    "aggressive": {"score": 0.75, "confidence": 0.72, "confirmations": 1},
    "stable": {"score": 0.80, "confidence": 0.76, "confirmations": 2},
    "conservative": {"score": 0.86, "confidence": 0.82, "confirmations": 3},
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
    "technical_snapshot_at",
    "technical_snapshot_timeframe",
    "technical_snapshot_provider",
    "technical_snapshot_indicator_version",
)
MISSING_TECHNICAL_SNAPSHOT_REASON = "missing_technical_snapshot"


def evaluate_candidate_entry_gate(event: dict[str, Any], *, profile_id: str | None = None) -> dict[str, Any]:
    """Return a normalized source gate decision for a candidate event.

    The source identity selects the rule family, but it never adds points by
    itself. A passing result means the event may continue into lifecycle scoring.
    """

    profile = _profile(profile_id)
    source_family = _source_family(event)
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

    if source_family == "low_price":
        return _low_price_gate(evidence, profile=profile)
    if source_family in {"research", "ai"}:
        return _research_gate(evidence, profile=profile)
    if source_family == "small_cap":
        common = _common_gate(evidence, profile=profile, liquidity_multiplier=1.5)
        return common if not common["passed"] else _pass_result(evidence)
    if source_family in {"main_force", "growth", "valuation"}:
        common = _common_gate(evidence, profile=profile, allow_missing_market_data=True)
        return common if not common["passed"] else _pass_result(evidence)
    return _pass_result(evidence)


def _low_price_gate(evidence: dict[str, Any], *, profile: str) -> dict[str, Any]:
    common = _common_gate(evidence, profile=profile)
    if not common["passed"]:
        if common["reason_code"] == "liquidity_weak":
            reason = "low_price_liquidity_weak"
        elif common["reason_code"] == "persistent_downtrend":
            reason = "low_price_below_falling_ma20"
        else:
            reason = common["reason_code"]
        return _block_result(evidence, result="eligible_blocked", status="blocked", reason_code=reason)

    price = _num(_pick(evidence, "price", "current_price", "latest_price", "close"), 0.0)
    ma5 = _num(_pick(evidence, "ma5", "MA5"), 0.0)
    ma10 = _num(_pick(evidence, "ma10", "MA10"), 0.0)
    ma20 = _num(_pick(evidence, "ma20", "MA20"), 0.0)
    ma20_slope = _num(_pick(evidence, "ma20_slope", "MA20_slope"), 0.0)
    volume_ratio = _num(_pick(evidence, "volume_ratio", "量比"), 0.0)
    rsi = _num(_pick(evidence, "rsi", "rsi12", "RSI"), 0.0)

    if ma20 > 0 and price > 0 and price < ma20 and ma20_slope < 0:
        return _block_result(evidence, result="eligible_blocked", status="blocked", reason_code="low_price_below_falling_ma20")
    if rsi > 82:
        return _block_result(evidence, result="eligible_blocked", status="blocked", reason_code="low_price_rebound_tail_risk")
    if volume_ratio and volume_ratio < 1.0:
        return _block_result(evidence, result="eligible_blocked", status="blocked", reason_code="low_price_liquidity_weak")

    price_reclaimed_ma20 = ma20 > 0 and price >= ma20
    ma_stack = ma5 > 0 and ma10 > 0 and ma20 > 0 and ma5 >= ma10 >= ma20
    ma20_rising = ma20_slope >= 0
    if not ((price_reclaimed_ma20 and ma20_rising) or ma_stack):
        return _block_result(evidence, result="eligible_blocked", status="blocked", reason_code="low_price_trend_not_confirmed")
    return _pass_result(evidence)


def _research_gate(evidence: dict[str, Any], *, profile: str) -> dict[str, Any]:
    if not _has_quant_technical_evidence(evidence):
        return _block_result(evidence, result="recommended_only", status="recommended_only", reason_code="ai_requires_technical_confirmation")
    common = _common_gate(evidence, profile=profile, allow_missing_market_data=True)
    if not common["passed"]:
        if common["reason_code"] == "persistent_downtrend":
            return _block_result(evidence, result="recommended_only", status="recommended_only", reason_code="ai_requires_technical_confirmation")
        return common
    return _pass_result(evidence)


def _common_gate(
    evidence: dict[str, Any],
    *,
    profile: str,
    liquidity_multiplier: float = 1.0,
    allow_missing_market_data: bool = False,
) -> dict[str, Any]:
    if not evidence:
        return _pass_result(evidence) if allow_missing_market_data else _block_result(evidence, result="rejected", status="rejected", reason_code="data_incomplete")

    price = _num(_pick(evidence, "price", "current_price", "latest_price", "close"), 0.0)
    ma20 = _num(_pick(evidence, "ma20", "MA20"), 0.0)
    ma20_slope = _num(_pick(evidence, "ma20_slope", "MA20_slope"), 0.0)
    amount = _num(_pick(evidence, "amount", "turnover", "成交额"), 0.0)

    if price <= 0 and not allow_missing_market_data:
        return _block_result(evidence, result="rejected", status="rejected", reason_code="data_incomplete")
    if amount > 0:
        min_amount = PROFILE_LIQUIDITY_MIN_AMOUNT[profile] * float(liquidity_multiplier)
        if amount < min_amount:
            return _block_result(evidence, result="eligible_blocked", status="blocked", reason_code="liquidity_weak")
    if ma20 > 0 and price > 0 and price < ma20 and ma20_slope < 0:
        return _block_result(evidence, result="eligible_blocked", status="blocked", reason_code="persistent_downtrend")
    return _pass_result(evidence)


def _technical_confirmation_count(evidence: dict[str, Any]) -> int:
    price = _num(_pick(evidence, "price", "current_price", "latest_price", "close"), 0.0)
    ma5 = _num(_pick(evidence, "ma5", "MA5"), 0.0)
    ma10 = _num(_pick(evidence, "ma10", "MA10"), 0.0)
    ma20 = _num(_pick(evidence, "ma20", "MA20"), 0.0)
    ma20_slope = _num(_pick(evidence, "ma20_slope", "MA20_slope"), 0.0)
    macd = _num(_pick(evidence, "macd", "MACD"), 0.0)
    count = 0
    if ma5 > 0 and ma10 > 0 and ma20 > 0 and ma5 >= ma10 >= ma20:
        count += 1
    if price > 0 and ma20 > 0 and price >= ma20:
        count += 1
    if ma20_slope > 0:
        count += 1
    if macd > 0:
        count += 1
    if bool(_pick(evidence, "ma20_retest_passed", "retest_confirmed")):
        count += 1
    return count


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
    if field in {"trend", "technical_snapshot_at", "technical_snapshot_timeframe", "technical_snapshot_provider", "technical_snapshot_indicator_version"}:
        return bool(str(value).strip())
    number = _num(value, 0.0)
    if field in {"ma20_slope", "macd", "rsi"}:
        return True
    return number > 0


def _has_quant_technical_evidence(evidence: dict[str, Any]) -> bool:
    required = ("price", "ma20", "ma60", "amount", "volume_ratio", "rsi", "macd")
    return all(_technical_snapshot_field_present(evidence, field) for field in required)


def _source_family(event: dict[str, Any]) -> str:
    text = " ".join(
        str(value or "").strip().lower()
        for value in (event.get("source_type"), event.get("source_key"), event.get("reason_text"))
    )
    if "low_price" in text or "低价" in text:
        return "low_price"
    if "main_force" in text or "主力" in text:
        return "main_force"
    if "small_cap" in text or "小市值" in text:
        return "small_cap"
    if "valuation" in text or "估值" in text:
        return "valuation"
    if "growth" in text or "成长" in text or "净利" in text:
        return "growth"
    if "research" in text or "ai" in text or "研究" in text:
        return "research"
    if "manual" in text or "手工" in text:
        return "manual"
    return str(event.get("source_type") or "unknown").strip().lower() or "unknown"


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
