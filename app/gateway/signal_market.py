from __future__ import annotations

from app.gateway.deps import *
from app.gateway.context import UIApiContext
from app.gateway.signal_indicators import _profile_text, _safe_json_load
from app.quant_sim.time_utils import parse_system_datetime

def _parse_signal_time(raw: Any) -> datetime | None:
    text = _txt(raw).strip()
    if not text or text == "--":
        return None
    try:
        return parse_system_datetime(text)
    except (TypeError, ValueError):
        return None


def _format_ai_metric_value(value: Any, *, digits: int = 2, pct: bool = False, signed: bool = False) -> str:
    number = _float(value)
    if number is None:
        return _txt(value, "--")
    if pct:
        return f"{number:+.{digits}f}%" if signed else f"{number:.{digits}f}%"
    return f"{number:+.{digits}f}" if signed else f"{number:.{digits}f}"


def _fetch_signal_market_snapshot(stock_code: str) -> dict[str, Any]:
    code = normalize_stock_code(stock_code)
    if not code:
        return {}
    try:
        from app.smart_monitor_data import SmartMonitorDataFetcher

        fetcher = SmartMonitorDataFetcher()
        snapshot = fetcher.get_comprehensive_data(code)
        return snapshot if isinstance(snapshot, dict) else {}
    except Exception:
        return {}


def _build_ai_market_rows(market_data: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def _append_market(label: str, value: Any, note: str = "") -> None:
        if value in (None, ""):
            return
        row = {"label": label, "value": _txt(value, "--")}
        if note:
            row["note"] = note
        rows.append(row)

    _append_market("当前价", _format_ai_metric_value(market_data.get("current_price")))
    _append_market("涨跌幅", _format_ai_metric_value(market_data.get("change_pct"), pct=True, signed=True))
    _append_market("开盘价", _format_ai_metric_value(market_data.get("open")))
    _append_market("最高价", _format_ai_metric_value(market_data.get("high")))
    _append_market("最低价", _format_ai_metric_value(market_data.get("low")))
    _append_market("成交量(手)", _txt(market_data.get("volume"), "--"))
    _append_market("成交额(万)", _txt(market_data.get("amount"), "--"))
    _append_market("换手率", _format_ai_metric_value(market_data.get("turnover_rate"), pct=True))
    _append_market("量比", _format_ai_metric_value(market_data.get("volume_ratio")))
    _append_market("趋势", _txt(market_data.get("trend"), "--"))
    _append_market("MA5", _format_ai_metric_value(market_data.get("ma5")))
    _append_market("MA20", _format_ai_metric_value(market_data.get("ma20")))
    _append_market("MA60", _format_ai_metric_value(market_data.get("ma60")))
    _append_market("MACD", _format_ai_metric_value(market_data.get("macd"), digits=4, signed=True))
    _append_market("DIF", _format_ai_metric_value(market_data.get("macd_dif"), digits=4, signed=True))
    _append_market("DEA", _format_ai_metric_value(market_data.get("macd_dea"), digits=4, signed=True))
    _append_market("RSI6", _format_ai_metric_value(market_data.get("rsi6")))
    _append_market("RSI12", _format_ai_metric_value(market_data.get("rsi12")))
    _append_market("RSI24", _format_ai_metric_value(market_data.get("rsi24")))
    _append_market("KDJ-K", _format_ai_metric_value(market_data.get("kdj_k")))
    _append_market("KDJ-D", _format_ai_metric_value(market_data.get("kdj_d")))
    _append_market("KDJ-J", _format_ai_metric_value(market_data.get("kdj_j")))
    _append_market("布林上轨", _format_ai_metric_value(market_data.get("boll_upper")))
    _append_market("布林中轨", _format_ai_metric_value(market_data.get("boll_mid")))
    _append_market("布林下轨", _format_ai_metric_value(market_data.get("boll_lower")))
    _append_market("布林位置", _txt(market_data.get("boll_position"), "--"))
    return rows


def _is_empty_market_value(value: Any) -> bool:
    if value is None:
        return True
    text = _txt(value).strip()
    if not text:
        return True
    return text.lower() in {"--", "-", "n/a", "na", "none", "null", "nan"}


def _enrich_signal_strategy_profile_with_replay_snapshot(
    *,
    context: UIApiContext,
    signal: dict[str, Any],
    source: str,
    replay_run: dict[str, Any] | None,
    strategy_profile: dict[str, Any],
) -> dict[str, Any]:
    profile = dict(strategy_profile) if isinstance(strategy_profile, dict) else {}
    existing_snapshot = _safe_json_load(profile.get("market_snapshot"))
    required_fields = ("open", "high", "low", "volume", "amount")
    if all(not _is_empty_market_value(existing_snapshot.get(key)) for key in required_fields):
        profile["market_snapshot"] = existing_snapshot
        return profile
    if _txt(source).lower() != "replay":
        if existing_snapshot:
            profile["market_snapshot"] = existing_snapshot
        return profile

    stock_code = normalize_stock_code(signal.get("stock_code"))
    checkpoint_dt = _parse_signal_time(signal.get("checkpoint_at") or signal.get("created_at") or signal.get("updated_at"))
    if not stock_code or checkpoint_dt is None:
        if existing_snapshot:
            profile["market_snapshot"] = existing_snapshot
        return profile

    timeframe = _profile_text(
        (replay_run or {}).get("timeframe"),
        _profile_text(profile.get("analysis_timeframe"), "30m"),
    )
    try:
        provider = context.replay_service().snapshot_provider
        provider.prepare([stock_code], checkpoint_dt, checkpoint_dt, timeframe)
        snapshot = provider.get_snapshot(
            stock_code,
            checkpoint_dt,
            timeframe,
            stock_name=_txt(signal.get("stock_name"), stock_code),
        )
    except Exception:
        snapshot = None

    merged_snapshot = dict(existing_snapshot)
    if isinstance(snapshot, dict):
        for key, value in snapshot.items():
            if _is_empty_market_value(value):
                continue
            merged_snapshot[key] = value
    if merged_snapshot:
        profile["market_snapshot"] = merged_snapshot
    return profile


def _build_signal_ai_monitor_payload(
    *,
    context: UIApiContext,
    signal: dict[str, Any],
    checkpoint_at: Any,
    fetch_realtime_snapshot: bool = False,
) -> dict[str, Any]:
    stock_code = normalize_stock_code(signal.get("stock_code"))
    empty_payload = {
        "available": False,
        "stockCode": stock_code,
        "matchedMode": "none",
        "message": "当前股票暂无 AI 盯盘策略记录（请先触发一次股票分析以生成记录）",
        "decision": {},
        "keyLevels": [],
        "marketData": [],
        "accountData": [],
        "history": [],
        "trades": [],
    }
    if not stock_code:
        return empty_payload

    try:
        smart_db = context.smart_monitor_db()
        decision_rows = smart_db.get_ai_decisions(stock_code=stock_code, limit=30)
        trade_rows = smart_db.get_trade_records(stock_code=stock_code, limit=30)
    except Exception as exc:
        payload = dict(empty_payload)
        payload["message"] = f"读取 AI 盯盘策略失败: {exc}"
        return payload

    if not decision_rows:
        fallback_market_data = _fetch_signal_market_snapshot(stock_code) if fetch_realtime_snapshot else {}
        payload = dict(empty_payload)
        payload["marketData"] = _build_ai_market_rows(fallback_market_data if isinstance(fallback_market_data, dict) else {})
        if payload["marketData"]:
            payload["message"] = "无 AI 盯盘记录，已使用实时行情快照补全技术指标。"
        elif not fetch_realtime_snapshot:
            payload["message"] = "无 AI 盯盘记录，点击“刷新行情”可加载实时技术指标。"
        return payload

    checkpoint_dt = _parse_signal_time(checkpoint_at)
    selected = decision_rows[0]
    matched_mode = "latest"
    if checkpoint_dt is not None:
        for item in decision_rows:
            decision_dt = _parse_signal_time(item.get("decision_time"))
            if decision_dt is not None and decision_dt <= checkpoint_dt:
                selected = item
                matched_mode = "checkpoint_aligned"
                break

    decision_market_data = selected.get("market_data") if isinstance(selected.get("market_data"), dict) else {}
    fallback_market_data = _fetch_signal_market_snapshot(stock_code) if fetch_realtime_snapshot else {}
    market_data: dict[str, Any] = {}
    if isinstance(decision_market_data, dict):
        market_data.update(decision_market_data)
    if isinstance(fallback_market_data, dict):
        for key, value in fallback_market_data.items():
            if _is_empty_market_value(value):
                continue
            market_data[key] = value
    account_info = selected.get("account_info") if isinstance(selected.get("account_info"), dict) else {}
    key_levels = selected.get("key_price_levels") if isinstance(selected.get("key_price_levels"), dict) else {}

    market_rows = _build_ai_market_rows(market_data)

    account_rows: list[dict[str, str]] = []

    def _append_account(label: str, value: Any, note: str = "") -> None:
        if value in (None, ""):
            return
        row = {"label": label, "value": _txt(value, "--")}
        if note:
            row["note"] = note
        account_rows.append(row)

    _append_account("可用资金", _format_ai_metric_value(account_info.get("available_cash")))
    _append_account("总资产", _format_ai_metric_value(account_info.get("total_value")))
    _append_account("持仓数量", _txt(account_info.get("positions_count"), "--"))
    current_position = account_info.get("current_position")
    if isinstance(current_position, dict):
        _append_account("当前持仓成本", _format_ai_metric_value(current_position.get("cost_price")))
        _append_account("当前持仓股数", _txt(current_position.get("quantity"), "--"))
        pnl_pct = current_position.get("profit_loss_pct")
        if pnl_pct not in (None, ""):
            _append_account("当前持仓盈亏", _format_ai_metric_value(pnl_pct, pct=True, signed=True))

    level_rows = [
        {"label": _txt(key), "value": _txt(value, "--")}
        for key, value in key_levels.items()
        if _txt(key)
    ]

    history_rows = []
    for item in decision_rows[:12]:
        history_rows.append(
            {
                "id": _txt(item.get("id")),
                "decisionTime": _system_time_text(item.get("decision_time"), "--"),
                "action": _txt(item.get("action"), "HOLD").upper(),
                "confidence": _txt(item.get("confidence"), "--"),
                "riskLevel": _txt(item.get("risk_level"), "--"),
                "positionSizePct": _txt(item.get("position_size_pct"), "--"),
                "stopLossPct": _txt(item.get("stop_loss_pct"), "--"),
                "takeProfitPct": _txt(item.get("take_profit_pct"), "--"),
                "tradingSession": _txt(item.get("trading_session"), "--"),
                "executed": bool(_int(item.get("executed")) or 0),
                "executionResult": _txt(item.get("execution_result"), "--"),
                "reasoning": _txt(item.get("reasoning"), "--"),
            }
        )

    trades = []
    for item in trade_rows[:12]:
        trades.append(
            {
                "id": _txt(item.get("id")),
                "tradeTime": _system_time_text(item.get("trade_time"), "--"),
                "tradeType": _txt(item.get("trade_type"), "--").upper(),
                "quantity": _txt(item.get("quantity"), "--"),
                "price": _txt(item.get("price"), "--"),
                "amount": _txt(item.get("amount"), "--"),
                "commission": _txt(item.get("commission"), "--"),
                "tax": _txt(item.get("tax"), "--"),
                "profitLoss": _txt(item.get("profit_loss"), "--"),
                "orderStatus": _txt(item.get("order_status"), "--"),
            }
        )

    decision_payload = {
        "id": _txt(selected.get("id")),
        "decisionTime": _system_time_text(selected.get("decision_time"), "--"),
        "action": _txt(selected.get("action"), "HOLD").upper(),
        "confidence": _txt(selected.get("confidence"), "--"),
        "riskLevel": _txt(selected.get("risk_level"), "--"),
        "positionSizePct": _txt(selected.get("position_size_pct"), "--"),
        "stopLossPct": _txt(selected.get("stop_loss_pct"), "--"),
        "takeProfitPct": _txt(selected.get("take_profit_pct"), "--"),
        "tradingSession": _txt(selected.get("trading_session"), "--"),
        "executed": bool(_int(selected.get("executed")) or 0),
        "executionResult": _txt(selected.get("execution_result"), "--"),
        "reasoning": _txt(selected.get("reasoning"), "--"),
    }

    return {
        "available": True,
        "stockCode": stock_code,
        "matchedMode": matched_mode,
        "message": "已关联 AI 盯盘策略分析",
        "decision": decision_payload,
        "keyLevels": level_rows,
        "marketData": market_rows,
        "accountData": account_rows,
        "history": history_rows,
        "trades": trades,
    }
