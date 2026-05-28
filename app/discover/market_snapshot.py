"""Discovery-time 30m technical snapshot preparation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from typing import Any, Callable


DISCOVERY_TECHNICAL_SNAPSHOT_PERIOD = "minute30"
DISCOVERY_TECHNICAL_SNAPSHOT_TIMEFRAME = "30m"
MISSING_TECHNICAL_SNAPSHOT_REASON = "missing_technical_snapshot"

REQUIRED_TECHNICAL_SNAPSHOT_FIELDS = (
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
    "snapshot_at",
    "provider",
    "timeframe",
    "indicator_version",
)


@dataclass(frozen=True)
class DiscoveryMarketSnapshotResult:
    """Prepared discovery rows and aggregate diagnostics."""

    rows: list[dict[str, Any]]
    summary: dict[str, Any]


def prepare_discovery_market_snapshots(
    rows: list[dict[str, Any]],
    *,
    market_data_service: Any | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> DiscoveryMarketSnapshotResult:
    """Prepare 30m technical snapshots for discovery rows."""

    current_time = (now_fn or datetime.now)()
    service = market_data_service or _default_market_data_service()
    prepared_rows = [dict(row) for row in rows if isinstance(row, dict)]
    unique_codes = _unique_codes(prepared_rows)
    snapshots: dict[str, dict[str, Any]] = {}

    for code in unique_codes:
        snapshots[code] = _prepare_code_snapshot(service, code, current_time=current_time)

    summary = _empty_summary(len(unique_codes))
    for row in prepared_rows:
        code = _normalize_stock_code(row.get("code") or row.get("stock_code") or row.get("id"))
        prepared = snapshots.get(code) or _failed_snapshot(
            code,
            current_time=current_time,
            reason="missing_stock_code",
        )
        _merge_snapshot(row, prepared)

    for code in unique_codes:
        prepared = snapshots[code]
        summary["items"].append(
            {
                "stock_code": code,
                "status": prepared["technical_snapshot_status"],
                "ready": prepared["technical_snapshot_ready"],
                "missing_fields": list(prepared["technical_snapshot_missing_fields"]),
                "reason": prepared.get("technical_snapshot_error") or "",
            }
        )
        if prepared["technical_snapshot_status"] == "ready":
            summary["prepared"] += 1
            summary["complete"] += 1
        elif prepared["technical_snapshot_status"] == "failed":
            summary["failed"] += 1
            summary["blocked"] += 1
        else:
            summary["prepared"] += 1
            summary["incomplete"] += 1
            summary["blocked"] += 1
    return DiscoveryMarketSnapshotResult(rows=prepared_rows, summary=summary)


def prepare_discovery_market_snapshot(
    code: str,
    *,
    market_data_service: Any | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Prepare a single 30m technical snapshot for shared refresh paths."""

    current_time = (now_fn or datetime.now)()
    service = market_data_service or _default_market_data_service()
    return _prepare_code_snapshot(service, _normalize_stock_code(code), current_time=current_time)


def prepare_discovery_market_snapshot_safely(code: str) -> dict[str, Any]:
    """Return a failed technical snapshot instead of leaking provider exceptions."""

    normalized_code = _normalize_stock_code(code)
    try:
        return prepare_discovery_market_snapshot(normalized_code)
    except Exception as exc:
        return _failed_snapshot(
            normalized_code,
            current_time=datetime.now(),
            reason=str(exc) or type(exc).__name__,
        )


def _prepare_code_snapshot(service: Any, code: str, *, current_time: datetime) -> dict[str, Any]:
    try:
        start_date = current_time - timedelta(days=120)
        raw = service.get_latest_snapshot(
            code,
            period=DISCOVERY_TECHNICAL_SNAPSHOT_PERIOD,
            start_date=start_date,
            end_date=current_time,
        )
    except Exception as exc:
        return _failed_snapshot(code, current_time=current_time, reason=str(exc) or type(exc).__name__)
    if not isinstance(raw, dict) or not raw:
        return _failed_snapshot(code, current_time=current_time, reason="market_data_unavailable")
    return _normalize_snapshot(raw, code=code, current_time=current_time)


def _normalize_snapshot(raw: dict[str, Any], *, code: str, current_time: datetime) -> dict[str, Any]:
    snapshot = dict(raw)
    normalized = {
        "price": _pick(snapshot, "price", "current_price", "latest_price", "close"),
        "ma5": _pick(snapshot, "ma5", "MA5"),
        "ma10": _pick(snapshot, "ma10", "MA10"),
        "ma20": _pick(snapshot, "ma20", "MA20"),
        "ma20_slope": _pick(snapshot, "ma20_slope", "MA20_slope", "ma20Slope"),
        "ma60": _pick(snapshot, "ma60", "MA60"),
        "amount": _pick(snapshot, "amount", "turnover", "成交额"),
        "volume_ratio": _pick(snapshot, "volume_ratio", "量比"),
        "rsi": _pick(snapshot, "rsi", "rsi14", "rsi12", "rsi6", "RSI"),
        "macd": _pick(snapshot, "macd", "MACD"),
        "trend": _pick(snapshot, "trend", "trend_direction"),
        "snapshot_at": _pick(snapshot, "snapshot_at", "datetime", "date", "time", "quote_time"),
        "provider": _pick(snapshot, "provider", "source") or "tdx",
        "timeframe": _normalize_timeframe(_pick(snapshot, "timeframe", "period")) or DISCOVERY_TECHNICAL_SNAPSHOT_TIMEFRAME,
        "indicator_version": _pick(snapshot, "indicator_version"),
    }
    missing = _missing_fields(normalized)
    ready = not missing
    status = "ready" if ready else "incomplete"
    return {
        **normalized,
        "stock_code": code,
        "technical_snapshot_ready": ready,
        "technical_snapshot_status": status,
        "technical_snapshot_missing_fields": missing,
        "technical_snapshot_timeframe": normalized["timeframe"],
        "technical_snapshot_provider": str(normalized["provider"] or ""),
        "technical_snapshot_at": _format_local_time(normalized["snapshot_at"]),
        "technical_snapshot_prepared_at": _format_local_time(current_time),
        "technical_snapshot_row_count": _row_count(snapshot),
        "technical_snapshot_indicator_version": str(normalized["indicator_version"] or ""),
    }


def _failed_snapshot(code: str, *, current_time: datetime, reason: str) -> dict[str, Any]:
    missing = list(REQUIRED_TECHNICAL_SNAPSHOT_FIELDS)
    return {
        "stock_code": code,
        "technical_snapshot_ready": False,
        "technical_snapshot_status": "failed",
        "technical_snapshot_missing_fields": missing,
        "technical_snapshot_timeframe": DISCOVERY_TECHNICAL_SNAPSHOT_TIMEFRAME,
        "technical_snapshot_provider": "tdx",
        "technical_snapshot_at": "",
        "technical_snapshot_prepared_at": _format_local_time(current_time),
        "technical_snapshot_row_count": 0,
        "technical_snapshot_indicator_version": "",
        "technical_snapshot_error": reason,
    }


def _merge_snapshot(row: dict[str, Any], prepared: dict[str, Any]) -> None:
    for key in (
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
        if prepared.get(key) not in (None, ""):
            row[key] = prepared[key]
    if prepared.get("price") not in (None, ""):
        row["price"] = prepared["price"]
        row["latestPrice"] = prepared["price"]
        row["latest_price"] = prepared["price"]
        if isinstance(row.get("cells"), list) and len(row["cells"]) > 4:
            row["cells"][4] = prepared["price"]
    for key in (
        "technical_snapshot_ready",
        "technical_snapshot_status",
        "technical_snapshot_missing_fields",
        "technical_snapshot_timeframe",
        "technical_snapshot_provider",
        "technical_snapshot_at",
        "technical_snapshot_prepared_at",
        "technical_snapshot_row_count",
        "technical_snapshot_indicator_version",
    ):
        row[key] = prepared.get(key)
    if not bool(prepared.get("technical_snapshot_ready")):
        row["eligible_status"] = "blocked"
        row["blocking_reason"] = MISSING_TECHNICAL_SNAPSHOT_REASON
        if prepared.get("technical_snapshot_error"):
            row["technical_snapshot_error"] = prepared["technical_snapshot_error"]


def _unique_codes(rows: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    codes: list[str] = []
    for row in rows:
        code = _normalize_stock_code(row.get("code") or row.get("stock_code") or row.get("id"))
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def _normalize_stock_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    for delimiter in (".", " "):
        if delimiter in text:
            text = text.split(delimiter)[0]
    return text


def _empty_summary(unique_count: int) -> dict[str, Any]:
    return {
        "uniqueStocks": unique_count,
        "prepared": 0,
        "complete": 0,
        "incomplete": 0,
        "failed": 0,
        "blocked": 0,
        "items": [],
    }


def _missing_fields(snapshot: dict[str, Any]) -> list[str]:
    return [
        field
        for field in REQUIRED_TECHNICAL_SNAPSHOT_FIELDS
        if not _field_is_present(field, snapshot.get(field))
    ]


def _field_is_present(field: str, value: Any) -> bool:
    if value in (None, ""):
        return False
    if field in {"trend", "provider", "timeframe", "indicator_version", "snapshot_at"}:
        return bool(str(value).strip())
    number = _number(value)
    if number is None:
        return False
    if field in {"ma20_slope", "macd", "rsi"}:
        return True
    return number > 0


def _pick(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalize_timeframe(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"minute30", "30min", "30m"}:
        return DISCOVERY_TECHNICAL_SNAPSHOT_TIMEFRAME
    return text


def _format_local_time(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, datetime):
        return value.astimezone().replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S") if value.tzinfo else value.strftime("%Y-%m-%d %H:%M:%S")
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text.replace("T", " "))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        text = str(value).strip()
        return text.replace("T", " ").replace("Z", "")


def _row_count(snapshot: dict[str, Any]) -> int:
    value = _pick(snapshot, "row_count", "technical_snapshot_row_count")
    number = _number(value)
    return int(number) if number is not None and number >= 0 else 0


def _default_market_data_service() -> Any:
    from app.data.services.market_data_service import MarketDataService

    return MarketDataService(provider="tdx")


__all__ = [
    "DISCOVERY_TECHNICAL_SNAPSHOT_PERIOD",
    "DISCOVERY_TECHNICAL_SNAPSHOT_TIMEFRAME",
    "MISSING_TECHNICAL_SNAPSHOT_REASON",
    "REQUIRED_TECHNICAL_SNAPSHOT_FIELDS",
    "DiscoveryMarketSnapshotResult",
    "prepare_discovery_market_snapshot",
    "prepare_discovery_market_snapshot_safely",
    "prepare_discovery_market_snapshots",
]
