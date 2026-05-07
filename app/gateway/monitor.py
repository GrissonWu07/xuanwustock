from __future__ import annotations

from app.gateway.deps import *
from app.gateway.context import UIApiContext
from app.gateway.table_query import _normalize_replay_table_page, _normalize_replay_table_page_size, _replay_table_pagination

def _snapshot_ai_monitor(context: UIApiContext, table_query: dict[str, Any] | None = None) -> dict[str, Any]:
    db = context.smart_monitor_db()
    page_size = _normalize_replay_table_page_size((table_query or {}).get("pageSize"), default=50)
    page = _normalize_replay_table_page((table_query or {}).get("page"))
    search = _txt((table_query or {}).get("search"))
    task_total = db.count_monitor_tasks(enabled_only=False, search=search)
    task_pagination = _replay_table_pagination(page, page_size, task_total)
    tasks = db.get_monitor_tasks(
        enabled_only=False,
        search=search,
        limit=page_size,
        offset=(task_pagination["page"] - 1) * page_size,
    )
    decisions = db.get_ai_decisions(limit=20)
    trades = db.get_trade_records(limit=20)
    positions = db.get_positions()
    queue_table = _table(["代码", "名称", "启用", "间隔", "自动交易"], [{"id": _txt(item.get("stock_code"), str(i)), "cells": [_txt(item.get("stock_code")), _txt(item.get("stock_name") or item.get("task_name")), _txt(item.get("enabled"), "0"), _txt(item.get("check_interval"), "0"), "是" if item.get("auto_trade") else "否"], "code": _txt(item.get("stock_code")), "name": _txt(item.get("stock_name") or item.get("task_name"))} for i, item in enumerate(tasks)], "暂无监控任务")
    queue_table["pagination"] = task_pagination
    return {"updatedAt": _now(), "metrics": [_metric("盯盘队列", task_total), _metric("最新信号", len(decisions)), _metric("观察中", len(positions)), _metric("通知状态", "在线")], "queue": queue_table, "signals": [{"title": _txt(item.get("stock_name") or item.get("stock_code") or "AI 决策"), "body": _txt(item.get("reasoning") or "暂无说明"), "tags": [_txt(item.get("action") or "HOLD"), _txt(item.get("trading_session") or "session")]} for item in decisions[:10]], "timeline": [_timeline(_system_time_text(item.get("trade_time"), "--"), _txt(item.get("stock_code"), "交易记录"), _txt(item.get("trade_type") or item.get("order_status") or "已记录")) for item in trades[:10]] or [_timeline(_now(), "AI 盯盘", "当前没有交易记录，监控任务稍后会在这里写入时间线。")], "actions": ["启动", "停止", "分析", "删除"]}


def _snapshot_real_monitor(context: UIApiContext) -> dict[str, Any]:
    db = context.monitor_db()
    stocks = db.get_monitored_stocks()
    pending = db.get_pending_notifications()
    recent = db.get_all_recent_notifications(limit=10)
    return {"updatedAt": _now(), "metrics": [_metric("监控规则", len(stocks)), _metric("触发记录", len(recent)), _metric("通知通道", len({item.get("type") for item in recent if item.get("type")})), _metric("连接状态", "在线")], "rules": [_insight(_txt(item.get("name") or item.get("symbol") or "监控规则"), f"{_txt(item.get('symbol'))} 的监控阈值和通知设置由数据库中已保存的规则驱动。") for item in stocks[:3]] or [_insight("价格突破提醒", "监控上破 / 下破关键位，并把触发结果推到通知链路。", "accent"), _insight("量价异动提醒", "监控量比、涨跌幅和短时波动，供实时决策参考。", "warning")], "triggers": [_timeline(_system_time_text(item.get("triggered_at"), "--"), _txt(item.get("symbol") or item.get("name") or "触发记录"), _txt(item.get("message") or "通知已生成")) for item in pending[:10]] or [_timeline(_now(), "实时监控", "当前没有待发送提醒。")], "notificationStatus": ["已生成提醒" if pending else "暂无待发送提醒", "最近通知" if recent else "暂无历史通知"], "actions": ["启动", "停止", "刷新", "更新规则", "删除规则"]}
def _action_ai_monitor_start(context: UIApiContext, payload: Any) -> dict[str, Any]:
    code = _code_from_payload(payload)
    if not code:
        raise HTTPException(status_code=400, detail="Missing monitor stock code")
    context.smart_monitor_engine().start_monitor(code)
    return _snapshot_ai_monitor(context)


def _action_ai_monitor_stop(context: UIApiContext, payload: Any) -> dict[str, Any]:
    code = _code_from_payload(payload)
    if not code:
        raise HTTPException(status_code=400, detail="Missing monitor stock code")
    context.smart_monitor_engine().stop_monitor(code)
    return _snapshot_ai_monitor(context)


def _action_ai_monitor_analyze(context: UIApiContext, payload: Any) -> dict[str, Any]:
    code = _code_from_payload(payload)
    if not code:
        raise HTTPException(status_code=400, detail="Missing monitor stock code")
    context.smart_monitor_engine().analyze_stock(code)
    return _snapshot_ai_monitor(context)


def _action_ai_monitor_delete(context: UIApiContext, payload: Any) -> dict[str, Any]:
    code = _code_from_payload(payload)
    if not code:
        raise HTTPException(status_code=400, detail="Missing monitor stock code")
    db = context.smart_monitor_db()
    for task in db.get_monitor_tasks(enabled_only=False):
        if normalize_stock_code(task.get("stock_code")) == code:
            db.delete_monitor_task(int(task["id"]))
    return _snapshot_ai_monitor(context)


def _action_real_monitor_start(context: UIApiContext, payload: Any) -> dict[str, Any]:
    context.real_monitor_scheduler().start_scheduler()
    return _snapshot_real_monitor(context)


def _action_real_monitor_stop(context: UIApiContext, payload: Any) -> dict[str, Any]:
    context.real_monitor_scheduler().stop_scheduler()
    return _snapshot_real_monitor(context)


def _action_real_monitor_refresh(context: UIApiContext, payload: Any) -> dict[str, Any]:
    return _snapshot_real_monitor(context)


def _action_real_monitor_update_rule(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    stocks = context.monitor_db().get_monitored_stocks()
    index = _int(body.get("index"), 0) or 0
    if index < 0 or index >= len(stocks):
        raise HTTPException(status_code=404, detail="Monitor rule not found")
    stock = stocks[index]
    entry_range = dict(stock.get("entry_range") or {})
    entry_range["note"] = _txt(body.get("body"), _txt(entry_range.get("note")))
    context.monitor_db().update_monitored_stock(
        int(stock["id"]),
        rating=_txt(body.get("title"), _txt(stock.get("rating"))),
        entry_range=entry_range,
        take_profit=stock.get("take_profit"),
        stop_loss=stock.get("stop_loss"),
        check_interval=stock.get("check_interval"),
        notification_enabled=stock.get("notification_enabled", True),
    )
    return _snapshot_real_monitor(context)


def _action_real_monitor_delete_rule(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    stocks = context.monitor_db().get_monitored_stocks()
    index = _int(body.get("index"), 0) or 0
    if index < 0 or index >= len(stocks):
        raise HTTPException(status_code=404, detail="Monitor rule not found")
    context.monitor_db().remove_monitored_stock(int(stocks[index]["id"]))
    return _snapshot_real_monitor(context)
