"""Notification payload builders for quant universe lifecycle events."""

from __future__ import annotations

from typing import Any

from app.quant_sim.time_utils import local_now_text

GROUP_DEFINITIONS = {
    "new_trial": {"title": "新进入 trial", "to_status": "trial"},
    "upgraded_active": {"title": "升级为 active", "to_status": "active"},
    "downgraded_exit_only": {"title": "进入只出场管理", "to_status": "exit_only"},
    "entered_cooling": {"title": "进入 cooling", "to_status": "cooling"},
    "entered_retired": {"title": "进入 retired", "to_status": "retired"},
    "recovered_from_cooling": {"title": "从 cooling 恢复", "to_status": "trial"},
}


def build_quant_universe_daily_summary(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        group_key = _group_key(event)
        if not group_key:
            continue
        grouped.setdefault(group_key, []).append(_event_row(event))

    if not grouped:
        return None

    groups: dict[str, dict[str, Any]] = {}
    for key, rows in grouped.items():
        groups[key] = {
            "title": GROUP_DEFINITIONS[key]["title"],
            "rows": rows[:10],
            "overflow_count": max(0, len(rows) - 10),
            "total": len(rows),
        }

    total_events = sum(group["total"] for group in groups.values())
    return {
        "symbol": "QUANT_UNIVERSE",
        "name": "量化股票池",
        "type": "量化池生命周期日报",
        "message": f"量化股票池生命周期发生 {total_events} 条状态变化。",
        "triggered_at": _now_text(),
        "groups": groups,
    }


def build_quant_universe_retired_notification(event: dict[str, Any]) -> dict[str, Any]:
    row = _event_row(event)
    reason = row["reason"] or "达到退出条件"
    message = (
        f"{row['stock_code']} {row['stock_name']} 已进入 retired，"
        f"{row['status_change']}，原因：{reason}，健康度变化 {row['health_delta']:+.2f}。"
    )
    return {
        "symbol": row["stock_code"],
        "name": row["stock_name"],
        "type": "量化池退出",
        "message": message,
        "triggered_at": event.get("created_at") or _now_text(),
        "lifecycle": row,
    }


def _group_key(event: dict[str, Any]) -> str:
    from_status = str(event.get("from_status") or "").strip()
    to_status = str(event.get("to_status") or "").strip()
    event_type = str(event.get("event_type") or "").strip()
    if from_status == "cooling" and to_status == "trial":
        return "recovered_from_cooling"
    if to_status == "trial" or event_type == "candidate_promoted_to_trial":
        return "new_trial"
    if to_status == "active":
        return "upgraded_active"
    if to_status == "exit_only":
        return "downgraded_exit_only"
    if to_status == "cooling":
        return "entered_cooling"
    if to_status == "retired":
        return "entered_retired"
    return ""


def _event_row(event: dict[str, Any]) -> dict[str, Any]:
    before = _float_or_none(event.get("health_score_before"))
    after = _float_or_none(event.get("health_score_after"))
    return {
        "stock_code": str(event.get("stock_code") or ""),
        "stock_name": str(event.get("stock_name") or event.get("stock_code") or ""),
        "from_status": str(event.get("from_status") or ""),
        "to_status": str(event.get("to_status") or ""),
        "status_change": f"{str(event.get('from_status') or '')} -> {str(event.get('to_status') or '')}",
        "reason": str(event.get("reason_text") or event.get("reason_code") or ""),
        "candidate_score": _float_or_none(event.get("candidate_score")),
        "health_score_before": before,
        "health_score_after": after,
        "health_delta": _health_delta(before, after),
        "manual_override": str(event.get("manual_override") or _evidence_value(event, "manual_override") or "none"),
    }


def _health_delta(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return round(after - before, 4)


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _evidence_value(event: dict[str, Any], key: str) -> Any:
    evidence = event.get("evidence_json")
    if isinstance(evidence, dict):
        return evidence.get(key)
    return None


def _now_text() -> str:
    return local_now_text()


__all__ = [
    "build_quant_universe_daily_summary",
    "build_quant_universe_retired_notification",
]

