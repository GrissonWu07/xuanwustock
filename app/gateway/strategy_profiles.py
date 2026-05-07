from __future__ import annotations

from app.gateway.deps import *
from app.gateway.context import UIApiContext


def _strategy_profile_view(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    payload = dict(row)
    if "created_at" in payload:
        payload["created_at"] = _system_time_text(payload.get("created_at"), "")
    if "updated_at" in payload:
        payload["updated_at"] = _system_time_text(payload.get("updated_at"), "")
    return payload


def _strategy_profile_response(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    for key in ("profile", "version", "latestVersion"):
        if key in result:
            result[key] = _strategy_profile_view(result.get(key))
    if isinstance(result.get("versions"), list):
        result["versions"] = [
            item
            for item in (_strategy_profile_view(row) for row in result["versions"])
            if item is not None
        ]
    return result


def list_strategy_profiles(context: UIApiContext, *, include_disabled: bool = False) -> dict[str, Any]:
    db = context.quant_db()
    scheduler_cfg = db.get_scheduler_config()
    rows = db.list_strategy_profiles(include_disabled=include_disabled)
    items: list[dict[str, Any]] = []
    for row in rows:
        profile_id = _txt(row.get("id")).strip()
        latest = _strategy_profile_view(db.get_latest_strategy_profile_version(profile_id) if profile_id else None)
        items.append(
            {
                "id": profile_id,
                "name": _txt(row.get("name"), profile_id),
                "description": _txt(row.get("description")),
                "enabled": bool(row.get("enabled", True)),
                "isDefault": bool(row.get("is_default", False)),
                "createdAt": _system_time_text(row.get("created_at"), ""),
                "updatedAt": _system_time_text(row.get("updated_at"), ""),
                "latestVersion": latest,
            }
        )
    return {
        "updatedAt": _now(),
        "selectedStrategyProfileId": _txt(scheduler_cfg.get("strategy_profile_id")),
        "profiles": items,
    }


def get_strategy_profile(context: UIApiContext, profile_id: str, *, versions_limit: int = 20) -> dict[str, Any]:
    db = context.quant_db()
    profile = db.get_strategy_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Strategy profile not found: {profile_id}")
    return {
        "updatedAt": _now(),
        "profile": _strategy_profile_view(profile),
        "latestVersion": _strategy_profile_view(db.get_latest_strategy_profile_version(profile_id)),
        "versions": [
            item
            for item in (_strategy_profile_view(row) for row in db.list_strategy_profile_versions(profile_id, limit=versions_limit))
            if item is not None
        ],
    }


def create_strategy_profile(context: UIApiContext, body: dict[str, Any]) -> dict[str, Any]:
    config = body.get("config")
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="Missing strategy profile config")
    try:
        created = context.quant_db().create_strategy_profile(
            profile_id=_txt(body.get("profileId") if "profileId" in body else body.get("id")).strip() or None,
            name=_txt(body.get("name")).strip(),
            config=config,
            description=_txt(body.get("description")),
            enabled=bool(body.get("enabled", True)),
            set_default=bool(body.get("setDefault", False) or body.get("set_default", False)),
            note=_txt(body.get("note")),
        )
        return {"updatedAt": _now(), **_strategy_profile_response(created)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def update_strategy_profile(context: UIApiContext, profile_id: str, body: dict[str, Any]) -> dict[str, Any]:
    config = body.get("config")
    try:
        updated = context.quant_db().update_strategy_profile(
            profile_id,
            name=_txt(body.get("name")).strip() if "name" in body else None,
            config=config if isinstance(config, dict) else None,
            description=_txt(body.get("description")) if "description" in body else None,
            enabled=bool(body.get("enabled")) if "enabled" in body else None,
            set_default=bool(body.get("setDefault") if "setDefault" in body else body.get("set_default")) if ("setDefault" in body or "set_default" in body) else None,
            note=_txt(body.get("note")) if "note" in body else None,
        )
        return {"updatedAt": _now(), **_strategy_profile_response(updated)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def clone_strategy_profile(context: UIApiContext, profile_id: str, body: dict[str, Any]) -> dict[str, Any]:
    clone_name = _txt(body.get("name")).strip()
    if not clone_name:
        raise HTTPException(status_code=400, detail="Clone name is required")
    try:
        cloned = context.quant_db().clone_strategy_profile(
            profile_id,
            name=clone_name,
            profile_id=_txt(body.get("profileId") if "profileId" in body else body.get("id")).strip() or None,
            description=_txt(body.get("description")) if "description" in body else None,
        )
        return {"updatedAt": _now(), **_strategy_profile_response(cloned)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def validate_strategy_profile(context: UIApiContext, profile_id: str, body: dict[str, Any]) -> dict[str, Any]:
    config = body.get("config")
    db = context.quant_db()
    if not isinstance(config, dict):
        latest = db.get_latest_strategy_profile_version(profile_id)
        if latest is None:
            raise HTTPException(status_code=404, detail=f"Strategy profile version not found: {profile_id}")
        config = latest.get("config")
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="Invalid strategy profile config payload")
    try:
        normalized = db.validate_strategy_profile_config(config)
        return {"updatedAt": _now(), "valid": True, "normalizedConfig": normalized}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def set_default_strategy_profile(context: UIApiContext, profile_id: str) -> dict[str, Any]:
    try:
        profile = context.quant_db().set_default_strategy_profile(profile_id)
        return {"updatedAt": _now(), "profile": _strategy_profile_view(profile)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def delete_strategy_profile(context: UIApiContext, profile_id: str) -> dict[str, Any]:
    db = context.quant_db()
    profile = db.get_strategy_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Strategy profile not found: {profile_id}")
    if bool(profile.get("is_default", False)):
        raise HTTPException(status_code=400, detail="Default strategy profile cannot be deleted")
    try:
        updated = db.update_strategy_profile(profile_id, enabled=False, note="disabled_by_delete")
        return {"updatedAt": _now(), "ok": True, **_strategy_profile_response(updated)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
