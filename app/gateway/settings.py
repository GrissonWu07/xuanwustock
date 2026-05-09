from __future__ import annotations

from app.gateway.deps import *
from app.gateway.context import UIApiContext

def _snapshot_settings(context: UIApiContext) -> dict[str, Any]:
    info = context.config_manager.get_config_info()

    def pick(keys: list[str]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for key in keys:
            meta = info.get(key, {})
            raw_value = _txt(meta.get("value"))
            description = _txt(meta.get("description"))
            item = _insight(
                key,
                description,
                "warning" if meta.get("required") else "neutral",
            )
            item["key"] = key
            item["value"] = raw_value
            item["required"] = bool(meta.get("required"))
            item["type"] = _txt(meta.get("type"), "text")
            item["hint"] = description
            options = meta.get("options")
            if isinstance(options, list):
                item["options"] = [str(option) for option in options]
            items.append(item)
        return items

    db = context.quant_db()
    scheduler_cfg = db.get_scheduler_config()
    quant_lifecycle_settings = db.get_quant_universe_settings()
    profile_rows = db.list_strategy_profiles(include_disabled=True)
    strategy_profiles: list[dict[str, Any]] = []
    for row in profile_rows:
        profile_id = str(row.get("id") or "").strip()
        latest_version = db.get_latest_strategy_profile_version(profile_id) if profile_id else None
        strategy_profiles.append(
            {
                "id": profile_id,
                "name": _txt(row.get("name"), profile_id),
                "description": _txt(row.get("description")),
                "enabled": bool(row.get("enabled", True)),
                "isDefault": bool(row.get("is_default", False)),
                "updatedAt": _system_time_text(row.get("updated_at"), ""),
                "latestVersionId": _txt((latest_version or {}).get("id"), "--"),
                "latestVersion": _txt((latest_version or {}).get("version"), "--"),
                "config": (latest_version or {}).get("config") if isinstance((latest_version or {}).get("config"), dict) else {},
            }
        )

    model_keys = ["AI_API_KEY", "AI_API_BASE_URL", "DEFAULT_MODEL_NAME"]
    source_keys = ["TUSHARE_TOKEN", "MINIQMT_ENABLED", "MINIQMT_ACCOUNT_ID", "MINIQMT_HOST", "MINIQMT_PORT"]
    runtime_keys = ["DISCOVER_TOP_N", "RESEARCH_TOP_N", "EMAIL_ENABLED", "SMTP_SERVER", "SMTP_PORT", "EMAIL_FROM", "EMAIL_PASSWORD", "EMAIL_TO", "WEBHOOK_ENABLED", "WEBHOOK_TYPE", "WEBHOOK_URL", "WEBHOOK_KEYWORD"]
    return {
        "updatedAt": _now(),
        "metrics": [
            _metric("模型配置", len(model_keys)),
            _metric("数据源", len(source_keys)),
            _metric("运行参数", len(runtime_keys)),
            _metric("通知通道", 2),
        ],
        "modelConfig": pick(model_keys),
        "dataSources": pick(source_keys),
        "runtimeParams": pick(runtime_keys),
        "strategyProfiles": strategy_profiles,
        "selectedStrategyProfileId": _txt(scheduler_cfg.get("strategy_profile_id")),
        "quantLifecycleSettings": quant_lifecycle_settings,
        "paths": [
            str(context.quant_sim_db_file),
            str(context.monitor_db_file),
            str(context.smart_monitor_db_file),
            str(context.stock_analysis_db_file),
            str(context.main_force_batch_db_file),
            str(context.selector_result_dir),
            str(LOGS_DIR),
        ],
    }
def _action_settings_save(context: UIApiContext, payload: dict[str, Any]) -> dict[str, Any]:
    body = _payload_dict(payload)
    env_payload = body.get("env") if isinstance(body.get("env"), dict) else {}
    if not env_payload:
        env_payload = {
            str(key): value
            for key, value in body.items()
            if str(key) not in {"strategyProfileId", "strategy_profile_id", "env", "quantLifecycleSettings"}
        }
    if env_payload:
        persisted = context.config_manager.write_env(
            {str(key): "" if value is None else str(value) for key, value in env_payload.items()}
        )
        if not persisted:
            raise HTTPException(status_code=500, detail="保存配置失败")
    context.config_manager.reload_config()
    strategy_profile_id = _txt(body.get("strategyProfileId") if "strategyProfileId" in body else body.get("strategy_profile_id")).strip()
    if strategy_profile_id:
        context.quant_db().update_scheduler_config(strategy_profile_id=strategy_profile_id)
    lifecycle_payload = body.get("quantLifecycleSettings")
    if isinstance(lifecycle_payload, dict):
        context.quant_db().update_quant_universe_settings(lifecycle_payload)
    return _snapshot_settings(context)
