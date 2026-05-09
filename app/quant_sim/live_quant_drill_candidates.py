"""Historical candidate generation gates for live quant drill runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class CandidateSourceAvailability(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    CONDITIONAL = "conditional"


@dataclass(frozen=True)
class CandidateGenerationConfig:
    frequency: str = "daily_first_checkpoint"
    checkpoint_interval: int = 8
    candidate_event_dedup_days: int = 5
    confirm_long_running: bool = False


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    return None


def source_availability_for_checkpoint(
    *,
    source_type: str,
    checkpoint: datetime,
    available_fields: dict[str, Any],
) -> CandidateSourceAvailability:
    source = str(source_type or "").strip().lower()
    if source in {"current_ai_analysis", "current_discover_result", "current_research_summary"}:
        return CandidateSourceAvailability.DISABLED
    if source == "low_price":
        required = ("ohlcv", "price", "volume")
        return CandidateSourceAvailability.ENABLED if all(available_fields.get(key) for key in required) else CandidateSourceAvailability.DISABLED
    if source in {"small_cap", "low_valuation"}:
        return CandidateSourceAvailability.ENABLED if bool(available_fields.get("as_of_fundamental")) else CandidateSourceAvailability.DISABLED
    if source == "profit_growth":
        return CandidateSourceAvailability.ENABLED if bool(available_fields.get("as_of_financial_report")) else CandidateSourceAvailability.DISABLED
    if source == "main_force":
        return CandidateSourceAvailability.ENABLED if bool(available_fields.get("historical_capital_flow")) else CandidateSourceAvailability.DISABLED
    if source == "historical_research":
        occurred_at = _parse_datetime(available_fields.get("occurred_at"))
        if occurred_at is None:
            return CandidateSourceAvailability.DISABLED
        return CandidateSourceAvailability.CONDITIONAL if occurred_at <= checkpoint.replace(tzinfo=None) else CandidateSourceAvailability.DISABLED
    if source == "manual_seed":
        return CandidateSourceAvailability.ENABLED
    return CandidateSourceAvailability.DISABLED


def should_generate_candidates(
    config: CandidateGenerationConfig,
    checkpoints: list[datetime],
    index: int,
) -> bool:
    if index < 0 or index >= len(checkpoints):
        return False
    frequency = str(config.frequency or "daily_first_checkpoint").strip().lower()
    if frequency == "every_n_checkpoints":
        interval = max(2, int(config.checkpoint_interval or 8))
        return index % interval == 0
    current = checkpoints[index]
    if index == 0:
        return True
    previous = checkpoints[index - 1]
    return current.date() != previous.date()


def estimate_candidate_generation(
    *,
    checkpoints: list[datetime],
    config: CandidateGenerationConfig,
    enabled_sources: list[str],
) -> dict[str, Any]:
    sources = [str(source).strip() for source in enabled_sources if str(source or "").strip()]
    generation_runs = sum(
        1
        for index in range(len(checkpoints))
        if should_generate_candidates(config, checkpoints, index)
    )
    return {
        "estimated_candidate_generation_runs": generation_runs,
        "enabled_candidate_sources": sources,
        "estimated_strategy_invocations": generation_runs * len(sources),
    }


def should_skip_candidate_event_due_to_dedup(
    *,
    config: CandidateGenerationConfig,
    stock_code: str,
    source_type: str,
    checkpoint: datetime,
    previous_events: list[dict[str, Any]],
) -> bool:
    window_days = max(0, int(config.candidate_event_dedup_days or 0))
    if window_days <= 0:
        return False
    normalized_code = str(stock_code or "").strip()
    normalized_source = str(source_type or "").strip()
    checkpoint_naive = checkpoint.replace(tzinfo=None)
    for event in previous_events:
        if str(event.get("stock_code") or "").strip() != normalized_code:
            continue
        if str(event.get("source_type") or "").strip() != normalized_source:
            continue
        if str(event.get("status") or "new").strip().lower() == "consumed":
            continue
        occurred_at = _parse_datetime(event.get("checkpoint_at_utc") or event.get("checkpoint_at") or event.get("occurred_at"))
        if occurred_at is None:
            continue
        delta_days = (checkpoint_naive - occurred_at).days
        if 0 <= delta_days < window_days:
            return True
    return False
