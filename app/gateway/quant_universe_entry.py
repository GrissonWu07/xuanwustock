from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.gateway.deps import normalize_stock_code
from app.quant_sim.quant_universe_lifecycle import QuantUniverseLifecyclePolicy, QuantUniverseManager


ENTRY_QUANT_STATUSES = {"trial", "active", "exit_only"}
def ingest_lifecycle_entry_rows(
    context: Any,
    rows: list[dict[str, Any]],
    *,
    source_type: str,
) -> dict[str, Any]:
    """Create quant lifecycle candidate events for discovery/research output rows.

    Discovery and research rows are already model-filtered outputs. When lifecycle
    auto-entry is enabled, they must enter the quant lifecycle path without a
    separate manual watchlist step.
    """
    summary: dict[str, Any] = {
        "attempted": 0,
        "events": 0,
        "eligible": 0,
        "promoted": 0,
        "skipped": [],
    }
    try:
        db = context.quant_db()
        settings = db.get_quant_universe_settings()
    except Exception as exc:
        summary["skipped"].append({"reason": f"quant_db_unavailable: {exc}"})
        return summary

    if not settings.get("quant_universe_lifecycle_enabled"):
        summary["skipped"].append({"reason": "lifecycle_disabled"})
        return summary
    auto_entry_mode = str(settings.get("auto_entry_mode") or "auto_trial")

    manager = QuantUniverseManager(
        db=db,
        profile_id=_selected_profile_id(db),
        policy=_policy_for_db(db),
    )
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = normalize_stock_code(row.get("code") or row.get("stock_code") or row.get("id"))
        if not code or code in seen:
            continue
        seen.add(code)
        if bool(row.get("already_in_quant")):
            summary["skipped"].append({"stock_code": code, "reason": "already_in_quant"})
            continue
        summary["attempted"] += 1
        try:
            _ensure_stock_universe_row(context, row, source_type=source_type)
            candidate_payload = _candidate_event_payload(row, source_type=source_type)
            if auto_entry_mode == "manual_only":
                db.add_candidate_event({**candidate_payload, "status": "active"})
                summary["events"] += 1
                summary["skipped"].append({"stock_code": code, "reason": "manual_only"})
                continue
            result = manager.ingest_candidate_event(candidate_payload)
        except Exception as exc:
            summary["skipped"].append({"stock_code": code, "reason": str(exc) or "ingest_failed"})
            continue
        summary["events"] += 1
        decision = str(result.get("decision") or "")
        if decision == "promoted_to_trial":
            summary["promoted"] += 1
        elif decision == "eligible":
            summary["eligible"] += 1
        else:
            summary["skipped"].append({"stock_code": code, "reason": str(result.get("skip_reason") or decision or "skipped")})
    return summary


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
        fields = _lifecycle_entry_fields(db, code)
        if _float(fields.get("candidate_score")) <= 0:
            score = _first_number(row.get("candidate_score"), row.get("source_score"), row.get("score"))
            if score is not None and score > 0:
                fields["candidate_score"] = round(_normalized_unit_score(score), 4)
        if _float(fields.get("candidate_confidence")) <= 0:
            confidence = _first_number(row.get("candidate_confidence"), row.get("confidence"), row.get("source_confidence"))
            if confidence is not None and confidence > 0:
                fields["candidate_confidence"] = round(_normalized_unit_score(confidence), 4)
        row.update(fields)
    return rows


def _lifecycle_entry_fields(db: Any, stock_code: str) -> dict[str, Any]:
    if db is None or not stock_code:
        return _empty_entry_fields()
    try:
        state = db.get_quant_universe_state(stock_code) or {}
        eligible_events = db.list_candidate_events(stock_code=stock_code, status="eligible", limit=20)
        active_events = db.list_candidate_events(stock_code=stock_code, status="active", limit=20)
        blocked_events = db.list_candidate_events(stock_code=stock_code, status="blocked", limit=20)
        recommended_events = db.list_candidate_events(stock_code=stock_code, status="recommended_only", limit=20)
        rejected_events = db.list_candidate_events(stock_code=stock_code, status="rejected", limit=20)
    except Exception:
        return _empty_entry_fields()

    best_event = _best_event(eligible_events + active_events + blocked_events + recommended_events + rejected_events)
    quant_status = str(state.get("quant_status") or "inactive").strip() or "inactive"
    manual_override = str(state.get("quant_manual_override") or "").strip()
    candidate_score = _score_from_state_or_event(state, best_event)
    candidate_confidence = _confidence_from_event(best_event)
    blocking_reason = _blocking_reason(state, quant_status, manual_override)
    already_in_quant = quant_status in ENTRY_QUANT_STATUSES

    if quant_status == "cooling" or blocking_reason == "cooling_blocked":
        eligible_status = "cooling_blocked"
    elif already_in_quant:
        eligible_status = "already_in_quant"
    elif blocking_reason:
        eligible_status = "skipped"
    elif recommended_events:
        eligible_status = "recommended_only"
        blocking_reason = _event_gate_reason(best_event) or "recommended_only"
    elif blocked_events:
        eligible_status = "blocked"
        blocking_reason = _event_gate_reason(best_event) or "entry_gate_blocked"
    elif rejected_events:
        eligible_status = "rejected"
        blocking_reason = _event_gate_reason(best_event) or "entry_gate_rejected"
    elif eligible_events:
        eligible_status = "eligible"
    else:
        eligible_status = "skipped"
        blocking_reason = "not_evaluated"

    return {
        "eligible_status": eligible_status,
        "candidate_score": candidate_score,
        "candidate_confidence": candidate_confidence,
        "blocking_reason": blocking_reason,
        "already_in_quant": already_in_quant,
    }


def _empty_entry_fields() -> dict[str, Any]:
    return {
        "eligible_status": "skipped",
        "candidate_score": 0.0,
        "candidate_confidence": 0.0,
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


def _confidence_from_event(event: dict[str, Any] | None) -> float:
    if isinstance(event, dict):
        return round(_float(event.get("confidence")), 4)
    return 0.0


def _best_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not events:
        return None
    return max(events, key=lambda event: (_float(event.get("source_score")), _float(event.get("confidence"))))


def _event_gate_reason(event: dict[str, Any] | None) -> str:
    if not isinstance(event, dict):
        return ""
    payload = event.get("payload_json")
    if not isinstance(payload, dict):
        return ""
    gate = payload.get("entry_gate")
    if not isinstance(gate, dict):
        return ""
    reason = str(gate.get("reason_code") or "").strip()
    if reason:
        return reason
    reason_codes = gate.get("reason_codes")
    if isinstance(reason_codes, list) and reason_codes:
        return str(reason_codes[0] or "").strip()
    return ""


def _ensure_stock_universe_row(context: Any, row: dict[str, Any], *, source_type: str) -> None:
    code = normalize_stock_code(row.get("code") or row.get("stock_code") or row.get("id"))
    if not code:
        return
    name = str(row.get("name") or row.get("stock_name") or code).strip() or code
    industry = str(row.get("industry") or row.get("sector") or "").strip()
    source_key = _source_key(row, source_type=source_type)
    source_label = str(row.get("source") or row.get("strategyName") or source_key or source_type).strip() or source_type
    try:
        watchlist = context.watchlist()
        watchlist.add_stock(
            code,
            name,
            source_label,
            latest_price=_optional_float(row.get("latestPrice") or row.get("latest_price") or row.get("price")),
            notes=str(row.get("reason") or row.get("summary") or "").strip() or None,
            metadata={
                "industry": industry,
                "entry_source_type": source_type,
                "entry_source_key": source_key,
                "basic_info_missing": name == code and not industry,
            },
        )
    except Exception:
        # Candidate events still create a stock_universe member; watchlist
        # enrichment is best-effort so a stale UI row cannot block lifecycle flow.
        return


def _candidate_event_payload(row: dict[str, Any], *, source_type: str) -> dict[str, Any]:
    code = normalize_stock_code(row.get("code") or row.get("stock_code") or row.get("id"))
    source_key = _source_key(row, source_type=source_type)
    name = str(row.get("name") or row.get("stock_name") or code).strip() or code
    source_score = _source_score(row, source_type=source_type, source_key=source_key)
    confidence = _confidence(row, source_type=source_type)
    trend = _trend(row)
    return {
        "stock_code": code,
        "stock_name": name,
        "source_type": source_type,
        "source_key": source_key,
        "source_score": source_score,
        "confidence": confidence,
        "trend": trend,
        "event_weight": 1.0,
        "reason_text": str(row.get("reason") or row.get("summary") or row.get("source") or "").strip(),
        "payload": {
            "name": name,
            "industry": row.get("industry") or row.get("sector") or "",
            "source": row.get("source") or row.get("strategyName") or "",
            "latest_price": row.get("latestPrice") or row.get("latest_price") or row.get("price"),
            "price": row.get("price") or row.get("latestPrice") or row.get("latest_price"),
            "ma5": row.get("ma5") or row.get("MA5"),
            "ma10": row.get("ma10") or row.get("MA10"),
            "ma20": row.get("ma20") or row.get("MA20"),
            "ma20_slope": row.get("ma20_slope") or row.get("MA20_slope") or row.get("ma20Slope"),
            "ma60": row.get("ma60") or row.get("MA60"),
            "amount": row.get("amount") or row.get("turnover") or row.get("成交额"),
            "volume_ratio": row.get("volume_ratio") or row.get("量比"),
            "rsi": row.get("rsi") or row.get("rsi12") or row.get("RSI"),
            "macd": row.get("macd") or row.get("MACD"),
            "technical_confirmation_count": row.get("technical_confirmation_count"),
            "technical_reasons": row.get("technical_reasons"),
            "source_score": source_score,
            "confidence": confidence,
            "trend": trend,
            "lifecycle_score_diagnostics": row.get("lifecycle_score_diagnostics"),
            "eligible_status_before": row.get("eligible_status"),
        },
    }


def _source_key(row: dict[str, Any], *, source_type: str) -> str:
    explicit = row.get("source_key") or row.get("strategyKey") or row.get("moduleKey")
    if explicit:
        return str(explicit).strip()
    source = str(row.get("source") or row.get("strategyName") or "").strip().lower()
    if source:
        return source
    return source_type


def _source_score(row: dict[str, Any], *, source_type: str, source_key: str) -> float:
    explicit = _first_number(
        row.get("source_score"),
        row.get("score"),
        row.get("scanner_score"),
    )
    if explicit is not None:
        return round(_normalized_unit_score(explicit), 4)
    return 0.0


def _confidence(row: dict[str, Any], *, source_type: str) -> float:
    explicit = _first_number(row.get("confidence"), row.get("confidence_score"), row.get("source_confidence"))
    if explicit is not None:
        return round(_normalized_unit_score(explicit), 4)
    return 0.0


def _trend(row: dict[str, Any]) -> str:
    raw = str(row.get("trend") or row.get("trend_direction") or row.get("direction") or "").strip().lower()
    if raw in {"up", "bullish", "向上", "上行", "多头"}:
        return "up"
    if raw in {"down", "bearish", "向下", "下行", "空头"}:
        return "down"
    if raw in {"flat", "neutral", "震荡", "中性"}:
        return "neutral"
    return "neutral"


def _policy_for_db(db: Any) -> QuantUniverseLifecyclePolicy:
    profile_id = _selected_profile_id(db)
    if profile_id == "aggressive":
        return QuantUniverseLifecyclePolicy.aggressive_defaults()
    if profile_id == "conservative":
        return QuantUniverseLifecyclePolicy.conservative_defaults()
    return QuantUniverseLifecyclePolicy.stable_defaults()


def _selected_profile_id(db: Any) -> str:
    try:
        config = db.get_scheduler_config()
        configured = str(config.get("strategy_profile_id") or "").strip().lower()
        if configured:
            return configured
    except Exception:
        pass
    try:
        return str(db.get_default_strategy_profile_id() or "stable").strip().lower() or "stable"
    except Exception:
        return "stable"


def _optional_float(value: Any) -> float | None:
    number = _first_number(value)
    return number if number is not None else None


def _first_number(*values: Any) -> float | None:
    for value in values:
        if value in (None, ""):
            continue
        try:
            number = float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            continue
        return number
    return None


def _clamp01(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def _normalized_unit_score(value: float) -> float:
    number = float(value)
    if number > 1.0 and number <= 100.0:
        number = number / 100.0
    return _clamp01(number)


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
