from __future__ import annotations

from app.gateway.deps import *
from app.gateway.context import UIApiContext
from app.gateway.scheduler_config import _latest_replay_defaults, _normalize_dynamic_lookback, _normalize_dynamic_strength
from app.gateway.table_query import _normalize_replay_table_page, _normalize_replay_table_page_size, _replay_table_pagination

def _snapshot_history(context: UIApiContext, table_query: dict[str, Any] | None = None) -> dict[str, Any]:
    db = context.stock_analysis_db()
    page_size = _normalize_replay_table_page_size((table_query or {}).get("pageSize"), default=50)
    page = _normalize_replay_table_page((table_query or {}).get("page"))
    search = _txt((table_query or {}).get("search"))
    total_records = db.count_records()
    filtered_total = db.count_records(search=search)
    pagination = _replay_table_pagination(page, page_size, filtered_total)
    records = db.get_records_page(
        search=search,
        limit=page_size,
        offset=(pagination["page"] - 1) * page_size,
    )
    timeline_records = db.get_records_page(limit=10)
    replay_db = context.replay_db()
    runs = replay_db.get_sim_runs(limit=20)
    latest = runs[0] if runs else None
    snapshots = replay_db.get_sim_run_snapshots(int(latest.get("id") or 0)) if latest else []
    recent_replay = {"title": "暂无最近回放", "body": "当前还没有可展示的回放记录。", "tags": []}
    if latest:
        recent_replay = {"title": f"#{latest.get('id')} {_txt(latest.get('mode'), '历史回放')}", "body": _txt(latest.get("status_message") or "最近一次回放已完成。"), "tags": [_txt(latest.get("checkpoint_count"), "0") + " 检查点", _txt(latest.get("trade_count"), "0") + " 笔成交", _pct(latest.get("total_return_pct"))]}
    records_table = _table(["时间", "股票", "模式", "结论"], [{"id": _txt(item.get("id"), str(i)), "cells": [_system_time_text(item.get("created_at") or item.get("analysis_date"), "--"), _txt(item.get("stock_name") or item.get("symbol")), _txt(item.get("period") or "analysis"), _txt(item.get("rating") or "--")], "code": normalize_stock_code(item.get("symbol")), "name": _txt(item.get("stock_name") or item.get("symbol"))} for i, item in enumerate(records)], "暂无分析记录")
    records_table["pagination"] = pagination
    return {"updatedAt": _now(), "metrics": [_metric("分析记录", total_records), _metric("最近回放", "完成" if latest else "无"), _metric("操作轨迹", min(total_records, 10)), _metric("活跃任务", len(runs))], "records": records_table, "recentReplay": recent_replay, "curve": [{"label": _system_time_text(item.get("created_at"), str(i)), "value": float(item.get("total_equity") or 0)} for i, item in enumerate(snapshots[:20])], "timeline": [_timeline(_system_time_text(item.get("created_at") or item.get("analysis_date"), "--"), _txt(item.get("stock_name") or item.get("symbol"), "历史记录"), _txt(item.get("rating") or item.get("analysis_mode") or "已记录")) for item in timeline_records]}
def _action_history_rerun(context: UIApiContext, payload: Any) -> dict[str, Any]:
    defaults = _latest_replay_defaults(context)
    context.replay_service().enqueue_historical_range(
        start_datetime=defaults["start_datetime"],
        end_datetime=defaults["end_datetime"],
        timeframe=defaults["timeframe"],
        market=defaults["market"],
        strategy_mode=defaults["strategy_mode"],
        strategy_profile_id=defaults.get("strategy_profile_id"),
        ai_dynamic_strategy=defaults.get("ai_dynamic_strategy", DEFAULT_AI_DYNAMIC_STRATEGY),
        ai_dynamic_strength=_normalize_dynamic_strength(defaults.get("ai_dynamic_strength"), DEFAULT_AI_DYNAMIC_STRENGTH),
        ai_dynamic_lookback=_normalize_dynamic_lookback(defaults.get("ai_dynamic_lookback"), DEFAULT_AI_DYNAMIC_LOOKBACK),
        commission_rate=float(defaults["commission_rate"]),
        sell_tax_rate=float(defaults["sell_tax_rate"]),
    )
    return _snapshot_history(context)
