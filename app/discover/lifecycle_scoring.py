"""Discovery candidate scoring normalization for lifecycle entry."""

from __future__ import annotations

import math
from typing import Any


SCORE_KEYS = ("source_score", "score", "scanner_score", "candidate_score")
CONFIDENCE_KEYS = ("confidence", "confidence_score", "source_confidence")

PRICE_KEYS = ("最新价", "股价", "latestPrice", "latest_price", "当前价", "收盘价", "price", "close")
MARKET_CAP_KEYS = ("总市值", "market_cap", "marketCap", "total_market_value", "total_market_cap", "市值")
PE_KEYS = ("市盈率", "市盈率TTM", "pe", "pe_ratio", "pe_ttm", "PE", "PE(TTM)")
PB_KEYS = ("市净率", "pb", "pb_ratio", "PB")
LIQUIDITY_AMOUNT_KEYS = ("amount", "turnover", "成交额", "成交额(元)", "成交额[20260509]")
VOLUME_RATIO_KEYS = ("volume_ratio", "量比")
TECHNICAL_KEYS = ("ma5", "MA5", "ma10", "MA10", "ma20", "MA20", "ma20_slope", "MA20_slope", "rsi", "rsi12", "RSI", "macd", "MACD")

POSITIVE_TECHNICAL_TOKENS = {
    "trend=up",
    "ma_short_up",
    "close_above_ma20",
    "ma20_slope_up",
    "macd_bullish",
    "volume_expansion",
    "momentum_20d_positive",
}
NEGATIVE_TECHNICAL_TOKENS = {
    "trend=down",
    "ma_short_down",
    "close_below_ma20",
    "ma20_slope_down",
    "macd_bearish",
    "momentum_20d_negative",
}
STANDARD_NUMERIC_KEYS = set(
    PRICE_KEYS
    + MARKET_CAP_KEYS
    + PE_KEYS
    + PB_KEYS
    + LIQUIDITY_AMOUNT_KEYS
    + VOLUME_RATIO_KEYS
    + TECHNICAL_KEYS
    + SCORE_KEYS
    + CONFIDENCE_KEYS
)


def normalize_discovery_lifecycle_row(
    row: dict[str, Any],
    *,
    strategy_key: str,
    strategy_name: str,
    rank: int,
    total: int,
) -> dict[str, Any]:
    """Return a discovery row with lifecycle score/confidence evidence."""

    normalized = dict(row)
    strategy = str(strategy_key or strategy_name or "").strip().lower()
    explicit_score = _first_number(row, SCORE_KEYS)
    explicit_confidence = _first_number(row, CONFIDENCE_KEYS)
    source_score = _normalize_unit(explicit_score) if explicit_score is not None else None
    confidence = _normalize_unit(explicit_confidence) if explicit_confidence is not None else None
    technical_confirmation_count = _technical_confirmation_count(row)
    trend = _derive_trend(row, technical_confirmation_count)
    data_quality = _data_quality(row)
    evidence_buckets = _evidence_buckets(row, rank=rank, total=total, technical_count=technical_confirmation_count)
    score_source = "explicit" if source_score is not None else "derived"
    confidence_source = "explicit" if confidence is not None else "derived"

    if source_score is None:
        if strategy == "ai_scanner":
            source_score = _normalize_unit(_number(row.get("scanner_score"), 0.0))
        elif _has_minimum_measurable_evidence(evidence_buckets):
            source_score = _derived_source_score(
                row,
                rank=rank,
                total=total,
                data_quality=data_quality,
                technical_count=technical_confirmation_count,
            )
        else:
            source_score = 0.0
            score_source = "missing"

    if confidence is None:
        if strategy == "ai_scanner":
            confidence = _ai_confidence(row, data_quality=data_quality)
        elif _has_minimum_measurable_evidence(evidence_buckets):
            confidence = _derived_confidence(
                row,
                rank=rank,
                total=total,
                data_quality=data_quality,
                technical_count=technical_confirmation_count,
            )
        else:
            confidence = 0.0
            confidence_source = "missing"

    reason_code = ""
    if source_score <= 0 and confidence <= 0 and not _has_minimum_measurable_evidence(evidence_buckets):
        reason_code = "insufficient_measurable_evidence"

    source_score = round(_clamp01(source_score), 4)
    confidence = round(_clamp01(confidence), 4)
    normalized.update(
        {
            "source_score": source_score,
            "score": source_score,
            "confidence": confidence,
            "candidate_confidence": confidence,
            "trend": trend,
            "technical_confirmation_count": int(max(technical_confirmation_count, 0)),
            "lifecycle_score_diagnostics": {
                "score_source": score_source,
                "confidence_source": confidence_source,
                "reason_code": reason_code,
                "evidence_buckets": evidence_buckets,
                "data_quality": round(data_quality, 4),
                "rank_component": round(_rank_component(rank, total), 4),
                "strategy_key": strategy_key,
            },
        }
    )
    return normalized


def _has_minimum_measurable_evidence(evidence_buckets: list[str]) -> bool:
    non_rank = [bucket for bucket in evidence_buckets if bucket != "rank"]
    return len(evidence_buckets) >= 2 and bool(non_rank)


def _derived_source_score(
    row: dict[str, Any],
    *,
    rank: int,
    total: int,
    data_quality: float,
    technical_count: int,
) -> float:
    rank_component = _rank_component(rank, total)
    strategy_component = _strategy_component(row, rank_component=rank_component, data_quality=data_quality)
    liquidity_component = _liquidity_component(row)
    technical_component = _clamp01(float(technical_count) / 4.0)
    return _clamp01(
        0.35 * rank_component
        + 0.25 * strategy_component
        + 0.20 * data_quality
        + 0.10 * liquidity_component
        + 0.10 * technical_component
    )


def _derived_confidence(
    row: dict[str, Any],
    *,
    rank: int,
    total: int,
    data_quality: float,
    technical_count: int,
) -> float:
    rank_component = _rank_component(rank, total)
    return _clamp01(
        0.35 * data_quality
        + 0.25 * _liquidity_component(row)
        + 0.20 * _technical_data_quality(row, technical_count=technical_count)
        + 0.20 * _strategy_evidence_quality(row, rank_component=rank_component, data_quality=data_quality)
    )


def _ai_confidence(row: dict[str, Any], *, data_quality: float) -> float:
    technical_score = _normalize_unit(_number(row.get("technical_score"), 0.5))
    theme_score = _normalize_unit(_number(row.get("theme_score"), 0.5))
    sector_score = _normalize_unit(_number(row.get("sector_score"), 0.5))
    return _clamp01(0.45 * technical_score + 0.25 * theme_score + 0.20 * sector_score + 0.10 * data_quality)


def _evidence_buckets(row: dict[str, Any], *, rank: int, total: int, technical_count: int) -> list[str]:
    buckets: list[str] = []
    if total > 1 and rank > 0:
        buckets.append("rank")
    if _data_quality(row) > 0:
        buckets.append("market_data")
    if _liquidity_component(row) > 0:
        buckets.append("liquidity")
    if technical_count > 0 or _technical_data_quality(row, technical_count=technical_count) > 0:
        buckets.append("technical")
    if _strategy_numeric_values(row):
        buckets.append("strategy")
    return buckets


def _technical_confirmation_count(row: dict[str, Any]) -> int:
    explicit = _number(_pick(row, "technical_confirmation_count", "confirmations"), None)
    count = int(explicit) if explicit is not None else 0
    price = _number(_pick(row, *PRICE_KEYS), 0.0)
    ma5 = _number(_pick(row, "ma5", "MA5"), 0.0)
    ma10 = _number(_pick(row, "ma10", "MA10"), 0.0)
    ma20 = _number(_pick(row, "ma20", "MA20"), 0.0)
    ma20_slope = _number(_pick(row, "ma20_slope", "MA20_slope", "ma20Slope"), 0.0)
    macd = _number(_pick(row, "macd", "MACD"), 0.0)
    if ma5 > 0 and ma10 > 0 and ma20 > 0 and ma5 >= ma10 >= ma20:
        count += 1
    if price > 0 and ma20 > 0 and price >= ma20:
        count += 1
    if ma20_slope > 0:
        count += 1
    if macd > 0:
        count += 1
    tokens = _technical_reason_tokens(row)
    return max(count, len(tokens & POSITIVE_TECHNICAL_TOKENS))


def _derive_trend(row: dict[str, Any], technical_count: int) -> str:
    raw = str(_pick(row, "trend", "trend_direction", "direction") or "").strip().lower()
    if raw in {"up", "bullish", "向上", "上行", "多头"}:
        return "up"
    if raw in {"down", "bearish", "向下", "下行", "空头"}:
        return "down"
    if raw in {"flat", "neutral", "震荡", "中性"}:
        return "neutral"
    tokens = _technical_reason_tokens(row)
    if tokens & NEGATIVE_TECHNICAL_TOKENS:
        ma20_down = "ma20_slope_down" in tokens or "close_below_ma20" in tokens
        if ma20_down or "macd_bearish" in tokens:
            return "down"
    if technical_count >= 2 or len(tokens & POSITIVE_TECHNICAL_TOKENS) >= 2:
        return "up"
    return "neutral"


def _data_quality(row: dict[str, Any]) -> float:
    fields = [
        _pick(row, *PRICE_KEYS),
        _pick(row, *MARKET_CAP_KEYS),
        _pick(row, *PE_KEYS),
        _pick(row, *PB_KEYS),
    ]
    return _filled_ratio(fields)


def _technical_data_quality(row: dict[str, Any], *, technical_count: int) -> float:
    fields = [
        _pick(row, "ma5", "MA5"),
        _pick(row, "ma10", "MA10"),
        _pick(row, "ma20", "MA20"),
        _pick(row, "ma20_slope", "MA20_slope", "ma20Slope"),
        _pick(row, "rsi", "rsi12", "RSI"),
        _pick(row, "macd", "MACD"),
    ]
    if technical_count > 0:
        return max(_filled_ratio(fields), min(float(technical_count) / 4.0, 1.0))
    return _filled_ratio(fields)


def _strategy_component(row: dict[str, Any], *, rank_component: float, data_quality: float) -> float:
    values = _strategy_numeric_values(row)
    if values:
        return max(_normalize_unit(value) for value in values)
    return rank_component if data_quality > 0 else 0.0


def _strategy_evidence_quality(row: dict[str, Any], *, rank_component: float, data_quality: float) -> float:
    values = _strategy_numeric_values(row)
    if values:
        return 1.0
    return rank_component if data_quality > 0 else 0.0


def _strategy_numeric_values(row: dict[str, Any]) -> list[float]:
    values: list[float] = []
    needles = ("score", "rank", "净流入", "增长", "growth", "valuation", "change", "涨跌", "涨幅")
    for key, value in row.items():
        key_text = str(key).strip().lower()
        if key_text in STANDARD_NUMERIC_KEYS:
            continue
        if not any(needle in key_text for needle in needles):
            continue
        number = _number(value, None)
        if number is not None:
            values.append(number)
    return values


def _rank_component(rank: int, total: int) -> float:
    safe_total = max(int(total or 1), 1)
    safe_rank = min(max(int(rank or 1), 1), safe_total)
    if safe_total == 1:
        return 1.0
    return _clamp01(1.0 - ((safe_rank - 1) / max(safe_total - 1, 1)) * 0.55)


def _liquidity_component(row: dict[str, Any]) -> float:
    amount = _number(_pick(row, *LIQUIDITY_AMOUNT_KEYS), None)
    if amount is not None and amount > 0:
        return _clamp01(amount / 80_000_000.0)
    volume_ratio = _number(_pick(row, *VOLUME_RATIO_KEYS), None)
    if volume_ratio is not None and volume_ratio > 0:
        return _clamp01(volume_ratio / 2.0)
    return 0.0


def _technical_reason_tokens(row: dict[str, Any]) -> set[str]:
    raw = str(row.get("technical_reasons") or row.get("technical_reason") or "")
    return {token.strip().lower() for token in raw.replace("/", ";").replace(",", ";").split(";") if token.strip()}


def _first_number(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        number = _number(row.get(key), None)
        if number is not None:
            return number
    return None


def _pick(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    for key, value in row.items():
        if value in (None, ""):
            continue
        normalized_key = str(key).strip().lower().replace(" ", "")
        for alias in keys:
            normalized_alias = str(alias).strip().lower().replace(" ", "")
            if normalized_alias and normalized_alias in normalized_key:
                return value
    return None


def _number(value: Any, default: float | None) -> float | None:
    if value in (None, ""):
        return default
    try:
        number = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _normalize_unit(value: float | None) -> float:
    number = float(value or 0.0)
    if 1.0 < number <= 100.0:
        number = number / 100.0
    return _clamp01(number)


def _clamp01(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def _filled_ratio(values: list[Any]) -> float:
    if not values:
        return 0.0
    filled = 0
    for value in values:
        if _number(value, None) is not None or (isinstance(value, str) and value.strip() not in {"", "-", "--"}):
            filled += 1
    return filled / len(values)
