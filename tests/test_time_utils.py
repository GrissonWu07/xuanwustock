from __future__ import annotations

from datetime import datetime

from app.quant_sim.time_utils import format_local_time, parse_system_datetime


def test_format_local_time_uses_plain_local_text() -> None:
    assert format_local_time(datetime(2026, 1, 5, 10, 0, 1)) == "2026-01-05 10:00:01"


def test_parse_system_datetime_returns_naive_local_datetime_for_existing_local_text() -> None:
    parsed = parse_system_datetime("2026-01-05 10:00:00")

    assert parsed == datetime(2026, 1, 5, 10, 0, 0)
    assert parsed.tzinfo is None


def test_format_local_time_never_emits_utc_iso_suffix() -> None:
    text = format_local_time("2026-01-05 10:00:00")

    assert "T" not in text
    assert not text.endswith("Z")
