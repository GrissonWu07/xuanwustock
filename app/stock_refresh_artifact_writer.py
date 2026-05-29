"""Live stock refresh artifact writer.

This module converts existing refresh/runtime entries into live market technical
artifacts. It does not fetch provider data; provider/cache data is only an
upstream input for artifact production.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.quant_sim.market_technical_artifact import (
    ArtifactWriteRequest,
    MarketTechnicalArtifact,
    MarketTechnicalArtifactData,
    MarketTechnicalArtifactRef,
)
from app.quant_sim.market_technical_artifact_store import MarketTechnicalArtifactStore
from app.quant_sim.time_utils import (
    format_local_time,
    market_timezone,
    parse_datetime_with_default_timezone,
    local_now_text,
)
from app.watchlist_selector_integration import normalize_stock_code


EXPECTED_ARTIFACT_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "latest_price",
    "prev_close",
    "volume",
    "amount",
    "turnover_rate",
    "volume_ratio",
    "ma5",
    "ma10",
    "ma20",
    "ma60",
    "ma20_slope",
    "rsi",
    "macd",
    "macd_signal",
    "macd_histogram",
    "trend",
    "price_vs_ma20",
    "price_vs_ma60",
    "ma_stack",
    "above_ma20_checkpoints",
    "retest_confirmed",
    "is_suspended",
    "is_limit_up",
    "is_limit_down",
    "liquidity_ready",
    "provider",
    "indicator_version",
)
CRITICAL_ARTIFACT_FIELDS = (
    "latest_price",
    "ma20",
    "rsi",
    "macd",
    "volume_ratio",
)


@dataclass(frozen=True)
class StockRefreshArtifactRequest:
    db_file: str | Path
    entries: dict[str, dict[str, Any]]
    market: str = "CN"
    trace_id: str = "NO_TRACE"
    data_version: str = "mta_v1"


def write_live_artifacts(request: StockRefreshArtifactRequest) -> dict[str, dict[str, Any]]:
    """Persist live artifacts and return artifact-derived runtime projections."""

    store = MarketTechnicalArtifactStore(request.db_file)
    projections: dict[str, dict[str, Any]] = {}
    for raw_code, entry in request.entries.items():
        code = normalize_stock_code(raw_code or entry.get("stock_code"))
        if not code or not isinstance(entry, dict):
            continue
        artifact = store.upsert(_write_request_for_entry(request, code, entry))
        projections[code] = derive_runtime_entry_from_artifact(artifact, existing_entry=entry)
    return projections


def write_live_artifacts_for_refresh(
    *,
    db_file: str | Path,
    entries: dict[str, dict[str, Any]],
    market: str,
    run_reason: str,
) -> dict[str, dict[str, Any]]:
    return write_live_artifacts(
        StockRefreshArtifactRequest(
            db_file=db_file,
            entries=entries,
            market=market,
            trace_id=f"stock-refresh:{run_reason}",
        )
    )


def derive_runtime_entry_from_artifact(
    artifact: MarketTechnicalArtifact,
    *,
    existing_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the runtime export from artifact facts, not from provider cache."""

    data = artifact.data
    base = dict(existing_entry or {})
    base.update(
        {
            "stock_code": artifact.ref.stock_code,
            "latest_price": data.latest_price,
            "price": data.latest_price,
            "data_source": data.provider or base.get("data_source") or "",
            "price_as_of": artifact.ref.checkpoint_at,
            "artifact_ref": artifact.artifact_ref,
            "source_status": data.source_status,
            "reason_code": data.reason_code,
            "technical_snapshot_ready": data.source_status == "ready",
            "technical_snapshot_status": _technical_status_from_source(data.source_status),
            "technical_snapshot_missing_fields": list(data.missing_fields),
            "technical_snapshot_timeframe": artifact.ref.timeframe,
            "technical_snapshot_provider": data.provider or "",
            "technical_snapshot_at": artifact.ref.checkpoint_at,
            "technical_snapshot_prepared_at": data.computed_at or "",
            "technical_snapshot_indicator_version": data.indicator_version or "",
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
        }
    )
    return base


def _write_request_for_entry(
    request: StockRefreshArtifactRequest,
    code: str,
    entry: dict[str, Any],
) -> ArtifactWriteRequest:
    checkpoint_at = _checkpoint_at(entry, market=request.market)
    ref = MarketTechnicalArtifactRef.live(
        stock_code=code,
        market=request.market,
        checkpoint_at=checkpoint_at,
        timeframe=str(entry.get("technical_snapshot_timeframe") or entry.get("timeframe") or "30m"),
        data_version=request.data_version,
    )
    return ArtifactWriteRequest(
        ref=ref,
        data=_artifact_data_from_entry(entry, computed_at=local_now_text()),
        trace_id=request.trace_id,
    )


def _artifact_data_from_entry(entry: dict[str, Any], *, computed_at: str) -> MarketTechnicalArtifactData:
    return build_market_technical_data_from_entry(entry, computed_at=computed_at)


def build_market_technical_data_from_entry(entry: dict[str, Any], *, computed_at: str) -> MarketTechnicalArtifactData:
    source_status, reason_code = _status_and_reason(entry)
    missing_fields = entry.get("technical_snapshot_missing_fields")
    missing_list = missing_fields if isinstance(missing_fields, list) else []
    latest_price = _number(entry.get("latest_price")) or _number(entry.get("price"))
    rsi = _first_number(entry, "rsi", "rsi12", "rsi_12")
    field_values = _artifact_field_values(entry, latest_price=latest_price, rsi=rsi)
    all_missing = _missing_fields_from_values(field_values, EXPECTED_ARTIFACT_FIELDS)
    critical_missing = [field for field in CRITICAL_ARTIFACT_FIELDS if field in all_missing]
    if all_missing:
        missing_list = sorted(set([*missing_list, *all_missing]))
    if critical_missing:
        if source_status == "ready":
            source_status, reason_code = "partial", "incomplete_artifact"
    return MarketTechnicalArtifactData(
        open=_number(entry.get("open")),
        high=_number(entry.get("high")),
        low=_number(entry.get("low")),
        close=_number(entry.get("close")) or latest_price,
        latest_price=latest_price,
        prev_close=_number(entry.get("prev_close")),
        volume=_number(entry.get("volume")),
        amount=_number(entry.get("amount")),
        turnover_rate=_number(entry.get("turnover_rate")),
        volume_ratio=_number(entry.get("volume_ratio")),
        ma5=_number(entry.get("ma5")),
        ma10=_number(entry.get("ma10")),
        ma20=_number(entry.get("ma20")),
        ma60=_number(entry.get("ma60")),
        ma20_slope=_number(entry.get("ma20_slope")),
        rsi=rsi,
        macd=_number(entry.get("macd")),
        macd_signal=_number(entry.get("macd_signal")),
        macd_histogram=_number(entry.get("macd_histogram")),
        trend=_text(entry.get("trend")),
        price_vs_ma20=_number(entry.get("price_vs_ma20")),
        price_vs_ma60=_number(entry.get("price_vs_ma60")),
        ma_stack=_text(entry.get("ma_stack")),
        above_ma20_checkpoints=_integer(entry.get("above_ma20_checkpoints")),
        retest_confirmed=_boolean(entry.get("retest_confirmed")),
        is_suspended=_boolean(entry.get("is_suspended")),
        is_limit_up=_boolean(entry.get("is_limit_up")),
        is_limit_down=_boolean(entry.get("is_limit_down")),
        liquidity_ready=_boolean(entry.get("liquidity_ready")),
        provider=_text(entry.get("technical_snapshot_provider") or entry.get("provider") or entry.get("data_source")),
        indicator_version=_text(entry.get("technical_snapshot_indicator_version") or entry.get("indicator_version")),
        source_status=source_status,
        reason_code=reason_code,
        missing_fields=missing_list,
        computed_at=computed_at,
        provider_diagnostics={"technical_snapshot_error": _safe_error_marker(entry.get("technical_snapshot_error"))},
    )


def _checkpoint_at(entry: dict[str, Any], *, market: str) -> str:
    raw_value = (
        entry.get("technical_snapshot_at")
        or entry.get("price_as_of")
        or entry.get("updated_at")
        or datetime.now(market_timezone(market))
    )
    parsed = parse_datetime_with_default_timezone(raw_value, market_timezone(market))
    return format_local_time(parsed)


def _safe_error_marker(value: Any) -> str:
    return "provider_error" if _text(value) else ""


def _status_and_reason(entry: dict[str, Any]) -> tuple[str, str]:
    status = _text(entry.get("technical_snapshot_status")).lower()
    ready = bool(entry.get("technical_snapshot_ready"))
    if ready and status == "ready":
        return "ready", "ok"
    if status == "failed":
        return "source_failed", "source_failed"
    if "stale" in status:
        return "stale", "stale_artifact"
    return "partial", "incomplete_artifact"


def _artifact_field_values(entry: dict[str, Any], *, latest_price: float | None, rsi: float | None) -> dict[str, Any]:
    return {
        "open": _number(entry.get("open")),
        "high": _number(entry.get("high")),
        "low": _number(entry.get("low")),
        "close": _number(entry.get("close")) or latest_price,
        "latest_price": latest_price,
        "prev_close": _number(entry.get("prev_close")),
        "volume": _number(entry.get("volume")),
        "amount": _number(entry.get("amount")),
        "turnover_rate": _number(entry.get("turnover_rate")),
        "volume_ratio": _number(entry.get("volume_ratio")),
        "ma5": _number(entry.get("ma5")),
        "ma10": _number(entry.get("ma10")),
        "ma20": _number(entry.get("ma20")),
        "ma60": _number(entry.get("ma60")),
        "ma20_slope": _number(entry.get("ma20_slope")),
        "rsi": rsi,
        "macd": _number(entry.get("macd")),
        "macd_signal": _number(entry.get("macd_signal")),
        "macd_histogram": _number(entry.get("macd_histogram")),
        "trend": _text(entry.get("trend")),
        "price_vs_ma20": _number(entry.get("price_vs_ma20")),
        "price_vs_ma60": _number(entry.get("price_vs_ma60")),
        "ma_stack": _text(entry.get("ma_stack")),
        "above_ma20_checkpoints": _integer(entry.get("above_ma20_checkpoints")),
        "retest_confirmed": _boolean(entry.get("retest_confirmed")),
        "is_suspended": _boolean(entry.get("is_suspended")),
        "is_limit_up": _boolean(entry.get("is_limit_up")),
        "is_limit_down": _boolean(entry.get("is_limit_down")),
        "liquidity_ready": _boolean(entry.get("liquidity_ready")),
        "provider": _text(entry.get("technical_snapshot_provider") or entry.get("provider") or entry.get("data_source")),
        "indicator_version": _text(entry.get("technical_snapshot_indicator_version") or entry.get("indicator_version")),
    }


def _missing_fields_from_values(values: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
    missing: list[str] = []
    for field in fields:
        value = values.get(field)
        if value is None or value == "":
            missing.append(field)
    return missing


def _technical_status_from_source(source_status: str) -> str:
    if source_status == "ready":
        return "ready"
    if source_status == "source_failed":
        return "failed"
    if source_status == "stale":
        return "stale"
    return "incomplete"


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        text = str(value).strip().replace(",", "")
        if not text or text.lower() in {"nan", "none", "n/a", "na", "-", "--"}:
            return None
        number = float(text)
        return number if number == number else None
    except (TypeError, ValueError):
        return None


def _first_number(entry: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _number(entry.get(key))
        if value is not None:
            return value
    return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _boolean(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _text(value: Any) -> str:
    return str(value or "").strip()
