"""Pure technical scoring for quant universe candidate entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


TECHNICAL_REQUIRED_FIELDS = (
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
)

TECHNICAL_REQUIRED_SNAPSHOT_METADATA_FIELDS = (
    "technical_snapshot_at",
    "technical_snapshot_timeframe",
    "technical_snapshot_provider",
    "technical_snapshot_indicator_version",
)

PROFILE_MIN_CONFIDENCE = {
    "aggressive": 0.70,
    "stable": 0.75,
    "conservative": 0.80,
}

PROFILE_AMOUNT_FLOOR = {
    "aggressive": 30_000_000.0,
    "stable": 50_000_000.0,
    "conservative": 80_000_000.0,
}


@dataclass(frozen=True)
class TechnicalEntryScoreResult:
    candidate_score: float
    candidate_confidence: float
    breakdown: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_score": round(self.candidate_score, 4),
            "candidate_confidence": round(self.candidate_confidence, 4),
            "breakdown": self.breakdown,
        }


def min_candidate_confidence(profile_id: str | None) -> float:
    return PROFILE_MIN_CONFIDENCE[_profile(profile_id)]


def calculate_technical_entry_score(
    events: list[dict[str, Any]],
    stock_snapshot: dict[str, Any] | None = None,
    *,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """Score candidate events using only market and technical evidence."""

    if not events:
        return _zero_result("missing_candidate_event", {}, profile_id).as_dict()

    profile = _profile(profile_id)
    scored = [_score_event(event, stock_snapshot or {}, profile) for event in events]
    best = max(scored, key=lambda item: (item.candidate_score, item.candidate_confidence))
    return best.as_dict()


def _score_event(event: dict[str, Any], stock_snapshot: dict[str, Any], profile: str) -> TechnicalEntryScoreResult:
    evidence = _evidence(event)
    missing = _missing_technical_fields(evidence)
    if missing:
        result = _zero_result("missing_technical_snapshot", evidence, profile)
        result.breakdown["missing_fields"] = missing
        return result
    snapshot_block = _required_snapshot_blocking_reason(evidence)
    if snapshot_block:
        result = _zero_result(snapshot_block, evidence, profile)
        result.breakdown["snapshot_status"] = str(_pick(evidence, "technical_snapshot_status", "snapshot_status") or "").strip()
        missing_snapshot_fields = _missing_required_snapshot_metadata(evidence)
        if missing_snapshot_fields:
            result.breakdown["missing_snapshot_fields"] = missing_snapshot_fields
        return result

    price = _num(_pick(evidence, "price", "current_price", "latest_price", "close"))
    ma5 = _num(_pick(evidence, "ma5", "MA5"))
    ma10 = _num(_pick(evidence, "ma10", "MA10"))
    ma20 = _num(_pick(evidence, "ma20", "MA20"))
    ma20_slope = _num(_pick(evidence, "ma20_slope", "MA20_slope", "ma20Slope"))
    ma60 = _num(_pick(evidence, "ma60", "MA60"))
    amount = _num(_pick(evidence, "amount", "turnover", "成交额"))
    volume_ratio = _num(_pick(evidence, "volume_ratio", "量比"))
    rsi = _num(_pick(evidence, "rsi", "rsi14", "rsi12", "RSI"))
    macd = _num(_pick(evidence, "macd", "MACD"))
    trend = str(_pick(evidence, "trend", "trend_direction") or "neutral").strip().lower()

    trend_structure_score = _weighted(
        (0.25, _bool_score(price >= ma20)),
        (0.15, _bool_score(price >= ma60)),
        (0.25, _ma_stack_score(price, ma5, ma10, ma20)),
        (0.20, _slope_score(ma20_slope)),
        (0.15, _trend_alignment_score(trend, price, ma20, ma20_slope)),
    )
    momentum_score = _weighted(
        (0.40, _bool_score(macd > 0)),
        (0.30, _rsi_constructive_score(rsi)),
        (0.20, _distance_quality(price, ma20, ideal_high=0.08, warn_high=0.15, allow_negative=False)),
        (0.10, _distance_quality(ma20, ma60, ideal_high=0.18, warn_high=0.30, allow_negative=False)),
    )
    volume_liquidity_score = _weighted(
        (0.55, _amount_floor_score(amount, profile)),
        (0.45, _volume_constructive_score(volume_ratio)),
    )
    confirmation_score, confirmation_source = _confirmation_score(evidence, trend_structure_score)
    risk_quality_score = _weighted(
        (0.40, _distance_quality(price, ma20, ideal_high=0.08, warn_high=0.25, allow_negative=False)),
        (0.25, _distance_quality(price, ma60, ideal_high=0.25, warn_high=0.40, allow_negative=False)),
        (0.20, _rsi_risk_quality(rsi)),
        (0.15, _volume_risk_quality(volume_ratio)),
    )

    overextension_penalty = _overextension_penalty(price, ma20, ma60)
    overheated_penalty = _overheated_penalty(rsi, volume_ratio)
    stale_data_penalty = _stale_data_penalty(evidence)
    score = _clamp01(
        0.35 * trend_structure_score
        + 0.20 * momentum_score
        + 0.15 * volume_liquidity_score
        + 0.20 * confirmation_score
        + 0.10 * risk_quality_score
        - overextension_penalty
        - overheated_penalty
        - stale_data_penalty
    )
    confidence = _technical_confidence(evidence, profile)
    if not stock_snapshot.get("is_liquid", True):
        score = max(0.0, score - 0.10)

    breakdown = {
        "trend_structure_score": round(trend_structure_score, 4),
        "momentum_score": round(momentum_score, 4),
        "volume_liquidity_score": round(volume_liquidity_score, 4),
        "confirmation_score": round(confirmation_score, 4),
        "confirmation_source": confirmation_source,
        "risk_quality_score": round(risk_quality_score, 4),
        "overextension_penalty": round(overextension_penalty, 4),
        "overheated_penalty": round(overheated_penalty, 4),
        "stale_data_penalty": round(stale_data_penalty, 4),
        "technical_field_coverage": round(_technical_field_coverage(evidence), 4),
        "snapshot_freshness": round(_snapshot_freshness(evidence), 4),
        "indicator_consistency": round(_indicator_consistency(evidence), 4),
        "history_depth": round(_history_depth(evidence), 4),
        "min_candidate_confidence": PROFILE_MIN_CONFIDENCE[profile],
    }
    return TechnicalEntryScoreResult(round(score, 4), round(confidence, 4), breakdown)


def _zero_result(reason: str, evidence: dict[str, Any], profile_id: str | None) -> TechnicalEntryScoreResult:
    profile = _profile(profile_id)
    return TechnicalEntryScoreResult(
        0.0,
        0.0,
        {
            "blocking_reason": reason,
            "trend_structure_score": 0.0,
            "momentum_score": 0.0,
            "volume_liquidity_score": 0.0,
            "confirmation_score": 0.0,
            "risk_quality_score": 0.0,
            "overextension_penalty": 0.0,
            "overheated_penalty": 0.0,
            "stale_data_penalty": round(_stale_data_penalty(evidence), 4),
            "technical_field_coverage": round(_technical_field_coverage(evidence), 4),
            "snapshot_freshness": round(_snapshot_freshness(evidence), 4),
            "indicator_consistency": round(_indicator_consistency(evidence), 4),
            "history_depth": round(_history_depth(evidence), 4),
            "min_candidate_confidence": PROFILE_MIN_CONFIDENCE[profile],
        },
    )


def _required_snapshot_blocking_reason(evidence: dict[str, Any]) -> str:
    ready_flag = evidence.get("technical_snapshot_ready")
    if ready_flag is False:
        return "missing_required_snapshot"

    status = str(_pick(evidence, "technical_snapshot_status", "snapshot_status") or "").strip().lower()
    if status and status != "ready":
        if status in {"stale", "stale_unprepared"}:
            return "stale_required_snapshot"
        return "missing_required_snapshot"

    if not (_truthy(ready_flag) or status == "ready"):
        return "missing_required_snapshot"
    if _missing_required_snapshot_metadata(evidence):
        return "missing_required_snapshot"
    return ""


def _missing_required_snapshot_metadata(evidence: dict[str, Any]) -> list[str]:
    return [
        field
        for field in TECHNICAL_REQUIRED_SNAPSHOT_METADATA_FIELDS
        if not _snapshot_metadata_present(evidence, field)
    ]


def _snapshot_metadata_present(evidence: dict[str, Any], field: str) -> bool:
    if field == "technical_snapshot_at":
        value = _pick(evidence, "technical_snapshot_at", "snapshot_at", "checkpoint_at", "datetime", "time")
    elif field == "technical_snapshot_timeframe":
        value = _pick(evidence, "technical_snapshot_timeframe", "timeframe", "period")
    elif field == "technical_snapshot_provider":
        value = _pick(evidence, "technical_snapshot_provider", "provider", "source")
    elif field == "technical_snapshot_indicator_version":
        value = _pick(evidence, "technical_snapshot_indicator_version", "indicator_version")
    else:
        value = evidence.get(field)
    return bool(str(value or "").strip())


def _technical_confidence(evidence: dict[str, Any], profile: str) -> float:
    return _clamp01(
        0.40 * _technical_field_coverage(evidence)
        + 0.25 * _snapshot_freshness(evidence)
        + 0.20 * _indicator_consistency(evidence)
        + 0.15 * _history_depth(evidence)
    )


def _technical_field_coverage(evidence: dict[str, Any]) -> float:
    if not evidence:
        return 0.0
    present = len(TECHNICAL_REQUIRED_FIELDS) - len(_missing_technical_fields(evidence))
    return _clamp01(present / len(TECHNICAL_REQUIRED_FIELDS))


def _snapshot_freshness(evidence: dict[str, Any]) -> float:
    status = str(_pick(evidence, "technical_snapshot_status", "snapshot_status") or "").strip().lower()
    ready = _truthy(_pick(evidence, "technical_snapshot_ready")) or status == "ready"
    at = _pick(evidence, "technical_snapshot_at", "snapshot_at", "checkpoint_at", "datetime", "time")
    if ready and at:
        return 1.0
    if ready:
        return 0.5
    return 0.0


def _indicator_consistency(evidence: dict[str, Any]) -> float:
    price = _num(_pick(evidence, "price", "current_price", "latest_price", "close"))
    ma5 = _num(_pick(evidence, "ma5", "MA5"))
    ma10 = _num(_pick(evidence, "ma10", "MA10"))
    ma20 = _num(_pick(evidence, "ma20", "MA20"))
    ma20_slope = _num(_pick(evidence, "ma20_slope", "MA20_slope", "ma20Slope"))
    macd = _num(_pick(evidence, "macd", "MACD"))
    trend = str(_pick(evidence, "trend", "trend_direction") or "neutral").strip().lower()
    contradictions = 0
    if trend in {"up", "bullish", "多头", "上行"} and price > 0 and ma20 > 0 and price < ma20:
        contradictions += 1
    if trend in {"up", "bullish", "多头", "上行"} and ma20_slope < 0:
        contradictions += 1
    if ma5 > 0 and ma10 > 0 and ma20 > 0 and ma5 < ma10 < ma20 and macd > 0:
        contradictions += 1
    return max(0.0, 1.0 - contradictions * 0.35)


def _history_depth(evidence: dict[str, Any]) -> float:
    count = _num(_pick(evidence, "technical_snapshot_row_count", "row_count", "history_depth"))
    if count >= 120:
        return 1.0
    if count >= 60:
        return 0.7
    if count > 0:
        return 0.3
    return 0.0


def _confirmation_score(evidence: dict[str, Any], trend_structure_score: float) -> tuple[float, str]:
    explicit_consecutive = _optional_num(_pick(evidence, "consecutive_checkpoint_score"))
    explicit_retest = _optional_num(_pick(evidence, "ma20_breakout_retest_score", "retest_score"))
    if explicit_consecutive is not None or explicit_retest is not None:
        return (
            _weighted(
                (0.60, _clamp01(explicit_consecutive or 0.0)),
                (0.40, _clamp01(explicit_retest or 0.0)),
            ),
            "multi_checkpoint",
        )
    confirmations = _num(_pick(evidence, "technical_confirmation_count", "confirmations"))
    if confirmations <= 0:
        confirmations = trend_structure_score * 5.0
    return min(0.5, confirmations / 5.0), "single_snapshot_cap"


def _missing_technical_fields(evidence: dict[str, Any]) -> list[str]:
    return [field for field in TECHNICAL_REQUIRED_FIELDS if not _field_present(evidence, field)]


def _field_present(evidence: dict[str, Any], field: str) -> bool:
    if field == "price":
        value = _pick(evidence, "price", "current_price", "latest_price", "close")
    elif field == "rsi":
        value = _pick(evidence, "rsi", "rsi14", "rsi12", "RSI")
    elif field == "trend":
        value = _pick(evidence, "trend", "trend_direction")
    else:
        value = _pick(evidence, field, field.upper())
    if value in (None, ""):
        return False
    if field == "trend":
        return bool(str(value).strip())
    if field in {"ma20_slope", "macd", "rsi"}:
        return True
    return _num(value) > 0


def _ma_stack_score(price: float, ma5: float, ma10: float, ma20: float) -> float:
    if ma5 > 0 and ma10 > 0 and ma20 > 0 and ma5 >= ma10 >= ma20:
        return 1.0
    if price > 0 and ma20 > 0 and price >= ma20 and ma5 > 0 and ma10 > 0 and ma5 >= ma10:
        return 0.5
    return 0.0


def _slope_score(slope: float) -> float:
    if slope > 0:
        return 1.0
    if slope == 0:
        return 0.5
    return 0.0


def _trend_alignment_score(trend: str, price: float, ma20: float, ma20_slope: float) -> float:
    if trend in {"up", "bullish", "多头", "上行"} and price >= ma20 and ma20_slope >= 0:
        return 1.0
    if trend in {"neutral", "flat", "sideways", "震荡", "中性"} and price >= ma20:
        return 0.5
    return 0.0


def _rsi_constructive_score(rsi: float) -> float:
    if 50 <= rsi <= 70:
        return 1.0
    if 45 <= rsi < 50 or 70 < rsi <= 75:
        return 0.75
    if 40 <= rsi < 45 or 75 < rsi <= 82:
        return 0.4
    return 0.0


def _amount_floor_score(amount: float, profile: str) -> float:
    floor = PROFILE_AMOUNT_FLOOR[profile]
    if amount < floor:
        return 0.0
    if amount >= floor * 2:
        return 1.0
    return 0.7


def _volume_constructive_score(volume_ratio: float) -> float:
    if 1.0 <= volume_ratio <= 2.5:
        return 1.0
    if 0.8 <= volume_ratio < 1.0 or 2.5 < volume_ratio <= 3.5:
        return 0.7
    if 0 < volume_ratio < 0.8 or 3.5 < volume_ratio <= 5.0:
        return 0.3
    return 0.0


def _distance_quality(base: float, reference: float, *, ideal_high: float, warn_high: float, allow_negative: bool) -> float:
    if base <= 0 or reference <= 0:
        return 0.0
    distance = (base - reference) / reference
    if distance < 0:
        return 0.5 if allow_negative and distance >= -0.03 else 0.0
    if distance <= ideal_high:
        return 1.0
    if distance <= warn_high:
        return 0.7
    if distance <= warn_high * 1.6:
        return 0.3
    return 0.0


def _rsi_risk_quality(rsi: float) -> float:
    if 45 <= rsi <= 75:
        return 1.0
    if 35 <= rsi < 45 or 75 < rsi <= 82:
        return 0.5
    return 0.0


def _volume_risk_quality(volume_ratio: float) -> float:
    if 0.8 <= volume_ratio <= 3.0:
        return 1.0
    if 0.5 <= volume_ratio < 0.8 or 3.0 < volume_ratio <= 5.0:
        return 0.5
    return 0.0


def _overextension_penalty(price: float, ma20: float, ma60: float) -> float:
    price_ma20 = price / ma20 if price > 0 and ma20 > 0 else 0.0
    price_ma60 = price / ma60 if price > 0 and ma60 > 0 else 0.0
    if price_ma20 > 1.15 or price_ma60 > 1.40:
        return 0.10
    if price_ma20 > 1.08 or price_ma60 > 1.25:
        return 0.05
    return 0.0


def _overheated_penalty(rsi: float, volume_ratio: float) -> float:
    if rsi > 82 or volume_ratio > 5.0:
        return 0.10
    if rsi > 75 or volume_ratio > 3.0:
        return 0.05
    return 0.0


def _stale_data_penalty(evidence: dict[str, Any]) -> float:
    status = str(_pick(evidence, "technical_snapshot_status", "snapshot_status") or "").strip().lower()
    if status and status != "ready":
        return 0.10
    if _pick(evidence, "technical_snapshot_at", "snapshot_at", "checkpoint_at", "datetime", "time"):
        return 0.0
    return 0.10


def _evidence(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload_json")
    if isinstance(payload, dict):
        evidence = dict(payload)
    else:
        payload = event.get("payload")
        evidence = dict(payload) if isinstance(payload, dict) else {}
    for key in ("trend",):
        if key not in evidence and event.get(key) not in (None, ""):
            evidence[key] = event.get(key)
    return evidence


def _weighted(*parts: tuple[float, float]) -> float:
    return _clamp01(sum(weight * _clamp01(value) for weight, value in parts))


def _bool_score(value: bool) -> float:
    return 1.0 if value else 0.0


def _pick(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _optional_num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "ready", "ok"}


def _clamp01(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def _profile(profile_id: str | None) -> str:
    text = str(profile_id or "").strip().lower()
    if "aggressive" in text:
        return "aggressive"
    if "conservative" in text:
        return "conservative"
    return "stable"
