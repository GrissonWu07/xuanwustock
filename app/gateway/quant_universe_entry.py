from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.gateway.deps import normalize_stock_code


ENTRY_QUANT_STATUSES = {"trial", "active", "exit_only"}


def enrich_lifecycle_entry_rows(context: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append read-only quant lifecycle entry fields to stock-linked UI rows."""
    try:
        db = context.quant_db()
    except Exception:
        db = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = normalize_stock_code(row.get("code") or row.get("stock_code") or row.get("id"))
        row.update(_lifecycle_entry_fields(db, code))
    return rows


def _lifecycle_entry_fields(db: Any, stock_code: str) -> dict[str, Any]:
    if db is None or not stock_code:
        return _empty_entry_fields()
    try:
        state = db.get_quant_universe_state(stock_code) or {}
        eligible_events = db.list_candidate_events(stock_code=stock_code, status="eligible", limit=20)
        active_events = db.list_candidate_events(stock_code=stock_code, status="active", limit=20)
    except Exception:
        return _empty_entry_fields()

    best_event = _best_event(eligible_events + active_events)
    quant_status = str(state.get("quant_status") or "inactive").strip() or "inactive"
    manual_override = str(state.get("quant_manual_override") or "").strip()
    candidate_score = _score_from_state_or_event(state, best_event)
    blocking_reason = _blocking_reason(state, quant_status, manual_override)
    already_in_quant = quant_status in ENTRY_QUANT_STATUSES

    if quant_status == "cooling" or blocking_reason == "cooling_blocked":
        eligible_status = "cooling_blocked"
    elif already_in_quant:
        eligible_status = "already_in_quant"
    elif blocking_reason:
        eligible_status = "skipped"
    elif eligible_events:
        eligible_status = "eligible"
    else:
        eligible_status = "skipped"
        blocking_reason = "not_evaluated"

    return {
        "eligible_status": eligible_status,
        "candidate_score": candidate_score,
        "blocking_reason": blocking_reason,
        "already_in_quant": already_in_quant,
    }


def _empty_entry_fields() -> dict[str, Any]:
    return {
        "eligible_status": "skipped",
        "candidate_score": 0.0,
        "blocking_reason": "not_evaluated",
        "already_in_quant": False,
    }


def _score_from_state_or_event(state: dict[str, Any], event: dict[str, Any] | None) -> float:
    state_score = _float(state.get("candidate_score"))
    if state_score > 0:
        return round(state_score, 4)
    if isinstance(event, dict):
        return round(_float(event.get("source_score")), 4)
    return 0.0


def _best_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not events:
        return None
    return max(events, key=lambda event: (_float(event.get("source_score")), _float(event.get("confidence"))))


def _blocking_reason(state: dict[str, Any], quant_status: str, manual_override: str) -> str:
    if manual_override == "manual_ban":
        return "manual_ban"
    if quant_status == "manual_paused" or manual_override == "manual_pause":
        return "manual_paused"
    if bool(state.get("basic_info_missing")):
        return "basic_info_missing"
    if _future_utc(state.get("cooling_until")):
        return "cooling_blocked"
    return ""


def _future_utc(value: Any) -> bool:
    if not value:
        return False
    text = str(value).strip()
    if not text:
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed > datetime.now(timezone.utc)


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
