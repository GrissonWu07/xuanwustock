"""Timezone helpers for quant simulation persistence and scheduling."""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo


MARKET_TIMEZONES = {
    "CN": "Asia/Shanghai",
    "HK": "Asia/Hong_Kong",
    "US": "America/New_York",
}


def market_timezone_name(market: str | None) -> str:
    return MARKET_TIMEZONES.get(str(market or "CN").upper(), MARKET_TIMEZONES["CN"])


def market_timezone(market: str | None) -> ZoneInfo:
    return ZoneInfo(market_timezone_name(market))


def system_timezone() -> tzinfo:
    return datetime.now().astimezone().tzinfo or timezone.utc


def system_timezone_name() -> str:
    local_tz = system_timezone()
    return getattr(local_tz, "key", None) or str(local_tz)


def parse_datetime_with_default_timezone(value: str | datetime, default_timezone: tzinfo | None = None) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        elif "T" not in text and " " in text:
            text = text.replace(" ", "T", 1)
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_timezone or system_timezone())
    return dt


def parse_system_datetime(value: str | datetime) -> datetime:
    return (
        parse_datetime_with_default_timezone(value, system_timezone())
        .astimezone(system_timezone())
        .replace(tzinfo=None, microsecond=0)
    )


def ensure_utc_datetime(value: str | datetime | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0)
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        elif "T" not in text and "+" not in text:
            text = text.replace(" ", "T")
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def format_utc_iso_z(value: str | datetime | None = None) -> str:
    return ensure_utc_datetime(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def ensure_utc_datetime_from_system_time(value: str | datetime | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0)
    return parse_datetime_with_default_timezone(value, system_timezone()).astimezone(timezone.utc).replace(microsecond=0)


def format_system_time(value: str | datetime | None, default: str = "--") -> str:
    if value is None or str(value).strip() == "":
        return default
    try:
        return parse_system_datetime(value).isoformat(sep=" ")
    except (TypeError, ValueError):
        return str(value).strip() or default


def format_system_short_time(value: str | datetime | None, default: str = "--") -> str:
    text = format_system_time(value, default=default)
    if text == default:
        return default
    try:
        return datetime.fromisoformat(text).strftime("%m-%d %H:%M")
    except ValueError:
        return text


def system_now_text() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def format_market_iso(value: str | datetime | None, market: str | None) -> str:
    return ensure_utc_datetime(value).astimezone(market_timezone(market)).isoformat(timespec="seconds")


def utc_now_iso_z() -> str:
    return format_utc_iso_z()
