from __future__ import annotations

from app.gateway.deps import *
from app.gateway.context import UIApiContext

def _normalize_fee_rate(value: Any, default: float) -> float:
    rate = _float(value, default)
    if rate is None:
        rate = default
    parsed = float(rate)
    if parsed < 0:
        parsed = 0.0
    if parsed > 1:
        parsed = parsed / 100.0
    if parsed > 0.2:
        parsed = 0.2
    return round(parsed, 8)


def _normalize_dynamic_strength(value: Any, default: float = DEFAULT_AI_DYNAMIC_STRENGTH) -> float:
    parsed = _float(value, default)
    if parsed is None:
        parsed = default
    ratio = float(parsed)
    if ratio < 0:
        ratio = 0.0
    if ratio > 1:
        ratio = ratio / 100.0
    ratio = max(0.0, min(1.0, ratio))
    return round(ratio, 4)


def _normalize_dynamic_lookback(value: Any, default: int = DEFAULT_AI_DYNAMIC_LOOKBACK) -> int:
    parsed = _int(value, default)
    if parsed is None:
        parsed = default
    result = int(parsed)
    if result < 6:
        result = 6
    if result > 336:
        result = 336
    return result


def _fee_rate_pct_text(value: Any, default: float) -> str:
    return f"{_normalize_fee_rate(value, default) * 100:.4f}"


def _payload_fee_rate(
    body: dict[str, Any],
    *,
    pct_key: str,
    camel_key: str,
    snake_key: str,
    default: float,
) -> tuple[bool, float]:
    if pct_key in body:
        pct_value = _float(body.get(pct_key), default * 100)
        ratio = 0.0 if pct_value is None else float(pct_value) / 100.0
        return True, _normalize_fee_rate(ratio, default)
    if camel_key in body:
        return True, _normalize_fee_rate(body.get(camel_key), default)
    if snake_key in body:
        return True, _normalize_fee_rate(body.get(snake_key), default)
    return False, _normalize_fee_rate(default, default)


def _enabled_strategy_profile_id(context: UIApiContext, requested: Any = None) -> str:
    enabled_profiles = context.quant_db().list_strategy_profiles(include_disabled=False)
    enabled_ids = [_txt(item.get("id")).strip() for item in enabled_profiles if _txt(item.get("id")).strip()]
    enabled_id_set = set(enabled_ids)
    requested_id = _txt(requested).strip()
    if requested_id in enabled_id_set:
        return requested_id
    default_id = _txt(context.quant_db().get_default_strategy_profile_id()).strip()
    if default_id in enabled_id_set:
        return default_id
    return enabled_ids[0] if enabled_ids else ""


def _latest_replay_defaults(context: UIApiContext) -> dict[str, Any]:
    scheduler_cfg = context.quant_db().get_scheduler_config()
    account_summary = context.quant_db().get_account_summary()
    default_initial_cash = _float(account_summary.get("initial_cash"), 100000.0) or 100000.0
    default_commission_rate = _normalize_fee_rate(scheduler_cfg.get("commission_rate"), DEFAULT_COMMISSION_RATE)
    default_sell_tax_rate = _normalize_fee_rate(scheduler_cfg.get("sell_tax_rate"), DEFAULT_SELL_TAX_RATE)
    default_strategy_profile_id = _enabled_strategy_profile_id(context, scheduler_cfg.get("strategy_profile_id"))
    default_ai_dynamic_strategy = _txt(scheduler_cfg.get("ai_dynamic_strategy"), DEFAULT_AI_DYNAMIC_STRATEGY)
    default_ai_dynamic_strength = _normalize_dynamic_strength(scheduler_cfg.get("ai_dynamic_strength"), DEFAULT_AI_DYNAMIC_STRENGTH)
    default_ai_dynamic_lookback = _normalize_dynamic_lookback(scheduler_cfg.get("ai_dynamic_lookback"), DEFAULT_AI_DYNAMIC_LOOKBACK)
    latest = next(iter(context.quant_db().get_sim_runs(limit=20)), None)
    if latest:
        metadata = latest.get("metadata") if isinstance(latest.get("metadata"), dict) else {}
        return {
            "start_datetime": _txt(latest.get("start_datetime"), "--"),
            "end_datetime": latest.get("end_datetime"),
            "timeframe": _txt(latest.get("timeframe"), "30m"),
            "market": _txt(latest.get("market"), "CN"),
            "strategy_mode": _txt(latest.get("selected_strategy_mode") or latest.get("strategy_mode"), "auto"),
            "initial_cash": _float(latest.get("initial_cash"), default_initial_cash) or default_initial_cash,
            "commission_rate": _normalize_fee_rate(metadata.get("commission_rate"), default_commission_rate),
            "sell_tax_rate": _normalize_fee_rate(metadata.get("sell_tax_rate"), default_sell_tax_rate),
            "strategy_profile_id": _enabled_strategy_profile_id(context, latest.get("selected_strategy_profile_id")) or default_strategy_profile_id,
            "ai_dynamic_strategy": _txt(metadata.get("ai_dynamic_strategy"), default_ai_dynamic_strategy),
            "ai_dynamic_strength": _normalize_dynamic_strength(metadata.get("ai_dynamic_strength"), default_ai_dynamic_strength),
            "ai_dynamic_lookback": _normalize_dynamic_lookback(metadata.get("ai_dynamic_lookback"), default_ai_dynamic_lookback),
        }
    end_at = datetime.now().replace(second=0, microsecond=0)
    start_at = end_at - timedelta(days=30)
    return {
        "start_datetime": start_at.strftime("%Y-%m-%d %H:%M:%S"),
        "end_datetime": end_at.strftime("%Y-%m-%d %H:%M:%S"),
        "timeframe": "30m",
        "market": "CN",
        "strategy_mode": "auto",
        "initial_cash": default_initial_cash,
        "commission_rate": default_commission_rate,
        "sell_tax_rate": default_sell_tax_rate,
        "strategy_profile_id": default_strategy_profile_id,
        "ai_dynamic_strategy": default_ai_dynamic_strategy,
        "ai_dynamic_strength": default_ai_dynamic_strength,
        "ai_dynamic_lookback": default_ai_dynamic_lookback,
    }


def _scheduler_update_kwargs(payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    commission_present, commission_rate = _payload_fee_rate(
        body,
        pct_key="commissionRatePct",
        camel_key="commissionRate",
        snake_key="commission_rate",
        default=DEFAULT_COMMISSION_RATE,
    )
    sell_tax_present, sell_tax_rate = _payload_fee_rate(
        body,
        pct_key="sellTaxRatePct",
        camel_key="sellTaxRate",
        snake_key="sell_tax_rate",
        default=DEFAULT_SELL_TAX_RATE,
    )
    mapping = {
        "strategy_mode": body.get("strategyMode") if "strategyMode" in body else body.get("strategy_mode"),
        "strategy_profile_id": body.get("strategyProfileId") if "strategyProfileId" in body else body.get("strategy_profile_id"),
        "ai_dynamic_strategy": body.get("aiDynamicStrategy") if "aiDynamicStrategy" in body else body.get("ai_dynamic_strategy"),
        "ai_dynamic_strength": body.get("aiDynamicStrength") if "aiDynamicStrength" in body else body.get("ai_dynamic_strength"),
        "ai_dynamic_lookback": body.get("aiDynamicLookback") if "aiDynamicLookback" in body else body.get("ai_dynamic_lookback"),
        "analysis_timeframe": body.get("analysisTimeframe") if "analysisTimeframe" in body else body.get("timeframe"),
        "auto_execute": body.get("autoExecute") if "autoExecute" in body else body.get("auto_execute"),
        "interval_minutes": body.get("intervalMinutes") if "intervalMinutes" in body else body.get("interval_minutes"),
        "trading_hours_only": body.get("tradingHoursOnly") if "tradingHoursOnly" in body else body.get("trading_hours_only"),
        "market": body.get("market"),
        "start_date": body.get("startDate") if "startDate" in body else body.get("start_date"),
        "capital_slot_enabled": body.get("capitalSlotEnabled")
        if "capitalSlotEnabled" in body
        else body.get("capital_slot_enabled"),
        "capital_pool_min_cash": body.get("capitalPoolMinCash")
        if "capitalPoolMinCash" in body
        else body.get("capital_pool_min_cash"),
        "capital_pool_max_cash": body.get("capitalPoolMaxCash")
        if "capitalPoolMaxCash" in body
        else body.get("capital_pool_max_cash"),
        "capital_slot_min_cash": body.get("capitalSlotMinCash")
        if "capitalSlotMinCash" in body
        else body.get("capital_slot_min_cash"),
        "capital_max_slots": body.get("capitalMaxSlots") if "capitalMaxSlots" in body else body.get("capital_max_slots"),
        "capital_min_buy_slot_fraction": body.get("capitalMinBuySlotFraction")
        if "capitalMinBuySlotFraction" in body
        else body.get("capital_min_buy_slot_fraction"),
        "capital_full_buy_edge": body.get("capitalFullBuyEdge")
        if "capitalFullBuyEdge" in body
        else body.get("capital_full_buy_edge"),
        "capital_confidence_weight": body.get("capitalConfidenceWeight")
        if "capitalConfidenceWeight" in body
        else body.get("capital_confidence_weight"),
        "capital_high_price_threshold": body.get("capitalHighPriceThreshold")
        if "capitalHighPriceThreshold" in body
        else body.get("capital_high_price_threshold"),
        "capital_high_price_max_slot_units": body.get("capitalHighPriceMaxSlotUnits")
        if "capitalHighPriceMaxSlotUnits" in body
        else body.get("capital_high_price_max_slot_units"),
        "capital_sell_cash_reuse_policy": body.get("capitalSellCashReusePolicy")
        if "capitalSellCashReusePolicy" in body
        else body.get("capital_sell_cash_reuse_policy"),
    }
    if commission_present:
        mapping["commission_rate"] = commission_rate
    if sell_tax_present:
        mapping["sell_tax_rate"] = sell_tax_rate
    return {key: value for key, value in mapping.items() if value is not None}
