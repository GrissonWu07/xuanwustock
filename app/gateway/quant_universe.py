from __future__ import annotations

from typing import Any

from app.gateway.context import UIApiContext
from app.gateway.deps import _int, _payload_dict
from app.quant_sim.quant_universe_lifecycle import (
    QuantUniverseDomainError,
    QuantUniverseLifecyclePolicy,
    QuantUniverseManager,
)


def quant_universe_state(
    context: UIApiContext,
    *,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    statuses = [item.strip() for item in str(status or "").split(",") if item.strip()]
    safe_page = max(1, int(page or 1))
    safe_page_size = max(1, min(200, int(page_size or 50)))
    payload = context.quant_db().list_quant_universe_state(
        statuses=statuses or None,
        keyword=keyword,
        limit=safe_page_size,
        offset=(safe_page - 1) * safe_page_size,
    )
    for item in payload.get("items", []):
        if isinstance(item, dict):
            item["latest_reason"] = str(item.get("retire_reason") or "")
    return payload


def quant_universe_overview(context: UIApiContext) -> dict[str, Any]:
    cards = context.quant_db().get_quant_universe_overview()
    allowed_keys = ("pending_eligible", "trial", "exit_only", "cooling", "retired")
    return {"cards": {key: _light_card(cards.get(key)) for key in allowed_keys}}


def quant_universe_settings(context: UIApiContext) -> dict[str, Any]:
    return context.quant_db().get_quant_universe_settings()


def update_quant_universe_settings(context: UIApiContext, payload: Any) -> dict[str, Any]:
    return context.quant_db().update_quant_universe_settings(_payload_dict(payload))


def promote_to_trial(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    manager = _manager(context)
    result = manager.promote_to_trial(
        _stock_codes(body),
        source_type=str(body.get("source_type") or "manual"),
        source_key=body.get("source_key"),
    )
    return {
        "success": [{"stock_code": code, "new_status": "trial"} for code in result.get("success", [])],
        "skipped": [
            {
                "stock_code": item.get("stock_code"),
                "reason_code": item.get("reason"),
                "reason_text": item.get("reason"),
            }
            for item in result.get("skipped", [])
        ],
        "failed": [],
    }


def ignore_auto_entry(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    manager = _manager(context)
    result = manager.ignore_auto_entry(_stock_codes(body), source_type=body.get("source_type"))
    return {"success": result.get("ignored", []), "failed": []}


def set_override(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    manager = _manager(context)
    return manager.set_override(str(body.get("stock_code") or body.get("code") or ""), str(body.get("override_type") or "none"))


def restore_to_trial(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    manager = _manager(context)
    return manager.restore_to_trial(str(body.get("stock_code") or body.get("code") or ""))


def _manager(context: UIApiContext) -> QuantUniverseManager:
    db = context.quant_db()
    profile_id = _selected_profile_id(db)
    return QuantUniverseManager(
        db=db,
        profile_id=profile_id,
        policy=_policy_for_profile(profile_id),
    )


def _selected_profile_id(db: Any) -> str:
    config = db.get_scheduler_config()
    configured = str(config.get("strategy_profile_id") or "").strip()
    return configured or str(db.get_default_strategy_profile_id() or "").strip() or "stable"


def _policy_for_profile(profile_id: str) -> QuantUniverseLifecyclePolicy:
    normalized = str(profile_id or "").strip().lower()
    if normalized == "aggressive":
        return QuantUniverseLifecyclePolicy.aggressive_defaults()
    if normalized == "conservative":
        return QuantUniverseLifecyclePolicy.conservative_defaults()
    return QuantUniverseLifecyclePolicy.stable_defaults()


def _stock_codes(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("stock_codes")
    if raw is None:
        raw = payload.get("codes")
    if raw is None:
        raw = payload.get("stock_code") or payload.get("code")
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list):
        values = raw
    else:
        values = []
    return [str(item).strip().upper() for item in values if str(item or "").strip()]


def _light_card(card: Any) -> dict[str, Any]:
    source = card if isinstance(card, dict) else {}
    top_items = [
        {
            "stock_code": str(item.get("stock_code") or ""),
            "stock_name": str(item.get("stock_name") or item.get("stock_code") or ""),
            "latest_reason": str(item.get("latest_reason") or ""),
        }
        for item in source.get("top_items", [])
        if isinstance(item, dict)
    ]
    return {
        "count": _int(source.get("count"), 0),
        "top_items": top_items,
        "latest_reason": top_items[0]["latest_reason"] if top_items else "",
    }


__all__ = [
    "QuantUniverseDomainError",
    "ignore_auto_entry",
    "promote_to_trial",
    "quant_universe_overview",
    "quant_universe_settings",
    "quant_universe_state",
    "restore_to_trial",
    "set_override",
    "update_quant_universe_settings",
]
