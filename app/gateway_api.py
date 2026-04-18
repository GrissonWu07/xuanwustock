from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config_manager import ConfigManager, config_manager
from app.database import StockAnalysisDatabase
from app.gateway_common import (
    code_from_payload as _code_from_payload,
    float_value as _float,
    insight as _insight,
    int_value as _int,
    metric as _metric,
    now as _now,
    num as _num,
    p as _p,
    payload_dict as _payload_dict,
    pct as _pct,
    table as _table,
    timeline as _timeline,
    txt as _txt,
)
from app.gateway_discover import (
    action_discover_batch as _action_discover_batch,
    action_discover_item as _action_discover_item,
    action_discover_run_strategy as _action_discover_run_strategy,
    discover_task_manager,
    snapshot_discover as _snapshot_discover,
)
from app.gateway_research import (
    action_research_batch as _action_research_batch,
    action_research_item as _action_research_item,
    action_research_run_module as _action_research_run_module,
    research_task_manager,
    snapshot_research as _snapshot_research,
)
from app.gateway_workbench import (
    action_workbench_add_watchlist as _action_workbench_add_watchlist,
    action_workbench_analysis as _action_workbench_analysis,
    action_workbench_analysis_batch as _action_workbench_analysis_batch,
    action_workbench_batch_quant as _action_workbench_batch_quant,
    action_workbench_delete as _action_workbench_delete,
    action_workbench_refresh as _action_workbench_refresh,
    snapshot_workbench as _snapshot_workbench,
)
from app.main_force_batch_db import MainForceBatchDatabase
from app.monitor_db import monitor_db
from app.portfolio_db import portfolio_db
from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.db import QuantSimDB
from app.quant_sim.engine import QuantSimEngine
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.replay_service import QuantSimReplayService
from app.quant_sim.scheduler import get_quant_sim_scheduler
from app.runtime_paths import DATA_DIR, LOGS_DIR, default_db_path
from app.selector_result_store import DEFAULT_SELECTOR_RESULT_DIR
from app.watchlist_selector_integration import normalize_stock_code
from app.monitor_db import StockMonitorDatabase
from app.watchlist_service import WatchlistService
from app.workbench_analysis_tasks import analysis_task_manager

SERVICE_NAME = "xuanwu-api"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
UI_DIST_DIR = PROJECT_ROOT / "ui" / "dist"


async def _json(request: Request) -> Any:
    try:
        return await request.json()
    except Exception:
        return {}





def _candidate_rows(
    context: "UIApiContext",
    status: str | None = None,
    *,
    include_actions: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in context.candidate_pool().list_candidates(status=status):
        code = normalize_stock_code(item.get("stock_code"))
        actions = []
        if include_actions:
            actions = [
                {"label": "分析候选股", "icon": "🔎", "tone": "accent", "action": "analyze-candidate"},
                {"label": "删除候选股", "icon": "🗑", "tone": "danger", "action": "delete-candidate"},
            ]
        rows.append(
            {
                "id": code,
                "cells": [code, _txt(item.get("stock_name") or code), _txt(item.get("source") or "watchlist"), _num(item.get("latest_price"))],
                "actions": actions,
                "code": code,
                "name": _txt(item.get("stock_name") or code),
                "source": _txt(item.get("source") or "watchlist"),
                "latestPrice": _num(item.get("latest_price")),
            }
        )
    return rows


@dataclass
class UIApiContext:
    data_dir: Path | str = DATA_DIR
    selector_result_dir: Path | str = DEFAULT_SELECTOR_RESULT_DIR
    watchlist_db_file: Path | str = field(default_factory=lambda: default_db_path("watchlist.db"))
    quant_sim_db_file: Path | str = field(default_factory=lambda: default_db_path("quant_sim.db"))
    portfolio_db_file: Path | str = field(default_factory=lambda: default_db_path("portfolio_stocks.db"))
    monitor_db_file: Path | str = field(default_factory=lambda: default_db_path("stock_monitor.db"))
    smart_monitor_db_file: Path | str = field(default_factory=lambda: default_db_path("smart_monitor.db"))
    stock_analysis_db_file: Path | str = field(default_factory=lambda: default_db_path("stock_analysis.db"))
    main_force_batch_db_file: Path | str = field(default_factory=lambda: default_db_path("main_force_batch.db"))
    logs_dir: Path | str = LOGS_DIR
    config_manager: ConfigManager = config_manager
    stock_name_resolver: Callable[[str], str] | None = None
    quote_fetcher: Callable[[str, str | None], dict[str, Any] | None] | None = None
    discover_result_key: str = "main_force"
    research_result_key: str = "research"

    def __post_init__(self) -> None:
        self.data_dir = _p(self.data_dir)
        self.selector_result_dir = _p(self.selector_result_dir)
        self.watchlist_db_file = _p(self.watchlist_db_file)
        self.quant_sim_db_file = _p(self.quant_sim_db_file)
        self.portfolio_db_file = _p(self.portfolio_db_file)
        self.monitor_db_file = _p(self.monitor_db_file)
        self.smart_monitor_db_file = _p(self.smart_monitor_db_file)
        self.stock_analysis_db_file = _p(self.stock_analysis_db_file)
        self.main_force_batch_db_file = _p(self.main_force_batch_db_file)
        self.logs_dir = _p(self.logs_dir)

    def watchlist(self) -> WatchlistService:
        return WatchlistService(self.watchlist_db_file, stock_name_resolver=self.stock_name_resolver, quote_fetcher=self.quote_fetcher)

    def candidate_pool(self) -> CandidatePoolService:
        return CandidatePoolService(self.quant_sim_db_file)

    def portfolio(self) -> PortfolioService:
        return PortfolioService(self.quant_sim_db_file)

    def quant_db(self) -> QuantSimDB:
        return QuantSimDB(self.quant_sim_db_file)

    def scheduler(self):
        return get_quant_sim_scheduler(
            db_file=self.quant_sim_db_file,
            watchlist_db_file=self.watchlist_db_file,
        )

    def replay_service(self):
        return QuantSimReplayService(db_file=self.quant_sim_db_file)

    def portfolio_manager(self):
        from app.portfolio_manager import PortfolioManager

        portfolio_db.db_path = str(self.portfolio_db_file)
        try:
            portfolio_db._init_database()
        except Exception:
            pass
        return PortfolioManager()

    def portfolio_scheduler(self):
        from app.portfolio_scheduler import portfolio_scheduler

        portfolio_db.db_path = str(self.portfolio_db_file)
        try:
            portfolio_db._init_database()
        except Exception:
            pass
        return portfolio_scheduler

    def smart_monitor_db(self):
        from app.smart_monitor_db import SmartMonitorDB

        return SmartMonitorDB(str(self.smart_monitor_db_file))

    def smart_monitor_engine(self):
        from app.smart_monitor_engine import SmartMonitorEngine

        return SmartMonitorEngine()

    def monitor_db(self):
        monitor_db.db_path = str(self.monitor_db_file)
        try:
            monitor_db.init_database()
        except Exception:
            pass
        return monitor_db

    def real_monitor_scheduler(self):
        from app.monitor_scheduler import get_scheduler
        from app.monitor_service import monitor_service

        self.monitor_db()
        return get_scheduler(monitor_service)

    def stock_analysis_db(self):
        return StockAnalysisDatabase(str(self.stock_analysis_db_file))

    def main_force_batch_db(self):
        return MainForceBatchDatabase(str(self.main_force_batch_db_file))




def _snapshot_portfolio(context: UIApiContext) -> dict[str, Any]:
    manager = context.portfolio_manager()
    rows = []
    for item in manager.get_all_latest_analysis():
        code = normalize_stock_code(item.get("code") or item.get("symbol"))
        rows.append(
            {
                "id": code,
                "cells": [code, _txt(item.get("name") or item.get("stock_name") or code), _txt(item.get("quantity") or item.get("cost_price") or "0"), _txt(item.get("rating") or "持有"), _num(item.get("current_price")), _num(item.get("target_price"))],
                "actions": [{"label": "分析", "icon": "🔎", "tone": "accent", "action": "analyze"}],
                "code": code,
                "name": _txt(item.get("name") or item.get("stock_name") or code),
            }
        )
    summary = context.portfolio().get_account_summary()
    return {"updatedAt": _now(), "metrics": [_metric("当前持仓", len(rows)), _metric("组合收益", _pct(summary.get("total_return_pct"))), _metric("最大回撤", _pct(summary.get("max_drawdown_pct"))), _metric("风险暴露", "中性")], "holdings": _table(["代码", "名称", "持仓数量", "评级", "当前价", "目标价"], rows, "暂无持仓"), "attribution": [_insight("盈利来源", "主要盈利来自趋势持仓和及时的仓位管理。", "success"), _insight("回撤来源", "回撤主要来自震荡市下的仓位切换不够快。", "warning")], "curve": [], "actions": ["调整仓位", "查看明细", "导出风险"]}


def _snapshot_live_sim(context: UIApiContext) -> dict[str, Any]:
    db = context.quant_db()
    scheduler = context.scheduler().get_status()
    account = db.get_account_summary()
    return {"updatedAt": _now(), "config": {"interval": f"{scheduler.get('interval_minutes', 0)} 分钟", "timeframe": _txt(scheduler.get("analysis_timeframe"), "30m"), "strategyMode": _txt(scheduler.get("strategy_mode"), "auto"), "autoExecute": "开启" if scheduler.get("auto_execute") else "关闭", "market": _txt(scheduler.get("market"), "CN"), "initialCapital": _txt(account.get("initial_cash"), "0")}, "status": {"running": "运行中" if scheduler.get("running") else "已停止", "lastRun": _txt(scheduler.get("last_run_at"), "--"), "nextRun": _txt(scheduler.get("next_run"), "--"), "candidateCount": _txt(len(context.candidate_pool().list_candidates(status="active")), "0")}, "metrics": [_metric("账户结果", account.get("total_equity", 0)), _metric("当前持仓", account.get("position_count", 0)), _metric("总收益率", _pct(account.get("total_return_pct"))), _metric("可用现金", account.get("available_cash"),)], "candidatePool": _table(["股票代码", "股票名称", "来源", "最新价格"], _candidate_rows(context, status="active", include_actions=True), "暂无候选股票"), "pendingSignals": [_insight(_txt(item.get("stock_name") or item.get("stock_code") or "待执行信号"), _txt(item.get("reasoning") or item.get("execution_note") or "待处理"), "warning" if _txt(item.get("action")) in {"BUY", "SELL"} else "neutral") for item in db.get_pending_signals()], "executionCenter": {"title": "执行中心", "body": "待执行信号会放在最上方，重点解释为什么成交、为什么跳过。", "chips": ["待执行", "信号列表", "详情"]}, "holdings": _table(["代码", "名称", "数量", "成本", "现价", "浮盈亏"], [{"id": _txt(item.get("stock_code"), str(i)), "cells": [_txt(item.get("stock_code")), _txt(item.get("stock_name")), _txt(item.get("quantity"), "0"), _num(item.get("avg_price")), _num(item.get("latest_price")), _pct(item.get("unrealized_pnl_pct"))], "code": _txt(item.get("stock_code")), "name": _txt(item.get("stock_name"))} for i, item in enumerate(db.get_positions())], "暂无持仓"), "trades": _table(["时间", "代码", "动作", "数量", "价格", "备注"], [{"id": _txt(item.get("id"), str(i)), "cells": [_txt(item.get("executed_at") or item.get("created_at"), "--"), _txt(item.get("stock_code")), _txt(item.get("action")), _txt(item.get("quantity"), "0"), _num(item.get("price")), _txt(item.get("note") or "自动执行")], "code": _txt(item.get("stock_code")), "name": _txt(item.get("stock_name"))} for i, item in enumerate(db.get_trade_history(limit=50))], "暂无交易记录"), "curve": [{"label": _txt(item.get("created_at"), str(i)), "value": float(item.get("total_equity") or 0)} for i, item in enumerate(db.get_account_snapshots(limit=20))]}


def _snapshot_his_replay(context: UIApiContext) -> dict[str, Any]:
    db = context.quant_db()
    runs = db.get_sim_runs(limit=20)
    run = runs[0] if runs else None
    candidate_rows = [
        {
            "id": _txt(item.get("stock_code"), str(i)),
            "cells": [
                _txt(item.get("stock_code")),
                _txt(item.get("stock_name")),
                _num(item.get("latest_price")),
            ],
            "code": _txt(item.get("stock_code")),
            "name": _txt(item.get("stock_name")),
            "latestPrice": _num(item.get("latest_price")),
        }
        for i, item in enumerate(context.candidate_pool().list_candidates(status="active"))
    ]
    if not run:
        return {"updatedAt": _now(), "config": {"mode": "历史区间", "range": "--", "timeframe": "30m", "market": "CN", "strategyMode": "auto"}, "metrics": [_metric("回放结果", "--"), _metric("最终总权益", "--"), _metric("交易笔数", "0"), _metric("胜率", "--")], "candidatePool": _table(["股票代码", "股票名称", "最新价格"], candidate_rows, "暂无候选股票"), "tasks": [], "tradingAnalysis": {"title": "交易分析", "body": "暂无回放记录。", "chips": []}, "holdings": _table(["代码", "名称", "数量", "成本", "现价", "浮盈亏"], [], "暂无持仓"), "trades": _table(["时间", "代码", "动作", "数量", "价格", "备注"], [], "暂无交易记录"), "signals": _table(["时间", "代码", "动作", "策略", "执行结果"], [], "暂无信号"), "curve": []}
    rid = int(run["id"])
    return {"updatedAt": _now(), "config": {"mode": _txt(run.get("mode"), "historical_range"), "range": f"{_txt(run.get('start_datetime'), '--')} -> {_txt(run.get('end_datetime'), 'now')}", "timeframe": _txt(run.get("timeframe"), "30m"), "market": _txt(run.get("market"), "CN"), "strategyMode": _txt(run.get("selected_strategy_mode") or run.get("strategy_mode"), "auto")}, "metrics": [_metric("回放结果", _pct(run.get("total_return_pct"))), _metric("最终总权益", _num(run.get("final_equity"), 0)), _metric("交易笔数", _txt(run.get("trade_count"), "0")), _metric("胜率", _pct(run.get("win_rate")))], "candidatePool": _table(["股票代码", "股票名称", "最新价格"], candidate_rows, "暂无候选股票"), "tasks": [{"id": f"#{item.get('id')}", "status": _txt(item.get("status"), "completed"), "range": f"{_txt(item.get('start_datetime'), '--')} -> {_txt(item.get('end_datetime'), 'now')}", "note": _txt(item.get("status_message") or f"{item.get('checkpoint_count', 0)} 个检查点")} for item in runs[:10]], "tradingAnalysis": {"title": "交易分析", "body": "回放页会把交易分析拆成“人话结论 + 策略解释 + 量化证据”三层。", "chips": [_txt(f"已实现盈亏 {run.get('realized_pnl', 0)}"), _txt(f"最终总权益 {run.get('final_equity', 0)}"), _txt(f"交易笔数 {run.get('trade_count', 0)}")]}, "holdings": _table(["代码", "名称", "数量", "成本", "现价", "浮盈亏"], [{"id": _txt(item.get("stock_code"), str(i)), "cells": [_txt(item.get("stock_code")), _txt(item.get("stock_name")), _txt(item.get("quantity"), "0"), _num(item.get("avg_price")), _num(item.get("latest_price")), _pct(item.get("unrealized_pnl"))], "code": _txt(item.get("stock_code")), "name": _txt(item.get("stock_name"))} for i, item in enumerate(db.get_sim_run_positions(rid))], "暂无持仓"), "trades": _table(["时间", "代码", "动作", "数量", "价格", "备注"], [{"id": _txt(item.get("id"), str(i)), "cells": [_txt(item.get("executed_at") or item.get("created_at"), "--"), _txt(item.get("stock_code")), _txt(item.get("action")), _txt(item.get("quantity"), "0"), _num(item.get("price")), _txt(item.get("note") or "自动执行")]} for i, item in enumerate(db.get_sim_run_trades(rid))], "暂无交易记录"), "signals": _table(["时间", "代码", "动作", "策略", "执行结果"], [{"id": _txt(item.get("id"), str(i)), "cells": [_txt(item.get("created_at") or item.get("checkpoint_at"), "--"), _txt(item.get("stock_code")), _txt(item.get("action")), _txt(item.get("decision_type") or "自动"), _txt(item.get("signal_status") or item.get("execution_note") or "待处理")], "actions": [{"label": "详情", "icon": "🔎"}]} for i, item in enumerate(db.get_sim_run_signals(rid))], "暂无信号"), "curve": [{"label": _txt(item.get("created_at"), str(i)), "value": float(item.get("total_equity") or 0)} for i, item in enumerate(db.get_sim_run_snapshots(rid))]}


def _snapshot_ai_monitor(context: UIApiContext) -> dict[str, Any]:
    db = context.smart_monitor_db()
    tasks = db.get_monitor_tasks(enabled_only=False)
    decisions = db.get_ai_decisions(limit=20)
    trades = db.get_trade_records(limit=20)
    positions = db.get_positions()
    return {"updatedAt": _now(), "metrics": [_metric("盯盘队列", len(tasks)), _metric("最新信号", len(decisions)), _metric("观察中", len(positions)), _metric("通知状态", "在线")], "queue": _table(["代码", "名称", "启用", "间隔", "自动交易"], [{"id": _txt(item.get("stock_code"), str(i)), "cells": [_txt(item.get("stock_code")), _txt(item.get("stock_name") or item.get("task_name")), _txt(item.get("enabled"), "0"), _txt(item.get("check_interval"), "0"), "是" if item.get("auto_trade") else "否"], "code": _txt(item.get("stock_code")), "name": _txt(item.get("stock_name") or item.get("task_name"))} for i, item in enumerate(tasks)], "暂无监控任务"), "signals": [{"title": _txt(item.get("stock_name") or item.get("stock_code") or "AI 决策"), "body": _txt(item.get("reasoning") or "暂无说明"), "tags": [_txt(item.get("action") or "HOLD"), _txt(item.get("trading_session") or "session")]} for item in decisions[:10]], "timeline": [_timeline(_txt(item.get("trade_time"), "--"), _txt(item.get("stock_code"), "交易记录"), _txt(item.get("trade_type") or item.get("order_status") or "已记录")) for item in trades[:10]] or [_timeline(_now(), "AI 盯盘", "当前没有交易记录，监控任务稍后会在这里写入时间线。")], "actions": ["启动", "停止", "分析", "删除"]}


def _snapshot_real_monitor(context: UIApiContext) -> dict[str, Any]:
    db = context.monitor_db()
    stocks = db.get_monitored_stocks()
    pending = db.get_pending_notifications()
    recent = db.get_all_recent_notifications(limit=10)
    return {"updatedAt": _now(), "metrics": [_metric("监控规则", len(stocks)), _metric("触发记录", len(recent)), _metric("通知通道", len({item.get("type") for item in recent if item.get("type")})), _metric("连接状态", "在线")], "rules": [_insight(_txt(item.get("name") or item.get("symbol") or "监控规则"), f"{_txt(item.get('symbol'))} 的监控阈值和通知设置由数据库中已保存的规则驱动。") for item in stocks[:3]] or [_insight("价格突破提醒", "监控上破 / 下破关键位，并把触发结果推到通知链路。", "accent"), _insight("量价异动提醒", "监控量比、涨跌幅和短时波动，供实时决策参考。", "warning")], "triggers": [_timeline(_txt(item.get("triggered_at"), "--"), _txt(item.get("symbol") or item.get("name") or "触发记录"), _txt(item.get("message") or "通知已生成")) for item in pending[:10]] or [_timeline(_now(), "实时监控", "当前没有待发送提醒。")], "notificationStatus": ["已生成提醒" if pending else "暂无待发送提醒", "最近通知" if recent else "暂无历史通知"], "actions": ["启动", "停止", "刷新", "更新规则", "删除规则"]}


def _snapshot_history(context: UIApiContext) -> dict[str, Any]:
    records = context.stock_analysis_db().get_all_records()
    runs = context.quant_db().get_sim_runs(limit=20)
    latest = runs[0] if runs else None
    snapshots = context.quant_db().get_sim_run_snapshots(int(latest.get("id") or 0)) if latest else []
    recent_replay = {"title": "暂无最近回放", "body": "当前还没有可展示的回放记录。", "tags": []}
    if latest:
        recent_replay = {"title": f"#{latest.get('id')} {_txt(latest.get('mode'), '历史回放')}", "body": _txt(latest.get("status_message") or "最近一次回放已完成。"), "tags": [_txt(latest.get("checkpoint_count"), "0") + " 检查点", _txt(latest.get("trade_count"), "0") + " 笔成交", _pct(latest.get("total_return_pct"))]}
    return {"updatedAt": _now(), "metrics": [_metric("分析记录", len(records)), _metric("最近回放", "完成" if latest else "无"), _metric("操作轨迹", len(records[:10])), _metric("活跃任务", len(runs))], "records": _table(["时间", "股票", "模式", "结论"], [{"id": _txt(item.get("id"), str(i)), "cells": [_txt(item.get("created_at") or item.get("analysis_date"), "--"), _txt(item.get("stock_name") or item.get("symbol")), _txt(item.get("period") or "analysis"), _txt(item.get("rating") or "--")], "code": normalize_stock_code(item.get("symbol")), "name": _txt(item.get("stock_name") or item.get("symbol"))} for i, item in enumerate(records[:50])], "暂无分析记录"), "recentReplay": recent_replay, "curve": [{"label": _txt(item.get("created_at"), str(i)), "value": float(item.get("total_equity") or 0)} for i, item in enumerate(snapshots[:20])], "timeline": [_timeline(_txt(item.get("created_at") or item.get("analysis_date"), "--"), _txt(item.get("stock_name") or item.get("symbol"), "历史记录"), _txt(item.get("rating") or item.get("analysis_mode") or "已记录")) for item in records[:10]]}


def _snapshot_settings(context: UIApiContext) -> dict[str, Any]:
    info = context.config_manager.get_config_info()
    def pick(keys: list[str]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for key in keys:
            meta = info.get(key, {})
            raw_value = _txt(meta.get("value"))
            display_value = raw_value
            if _txt(meta.get("type")) == "password":
                if raw_value:
                    display_value = f"{raw_value[:4]}***{raw_value[-4:]}" if len(raw_value) > 8 else "***"
                else:
                    display_value = "--"
            item = _insight(
                key,
                f"{meta.get('description', '')} 当前值: {_txt(display_value, '--')}",
                "warning" if meta.get("required") else "neutral",
            )
            item["key"] = key
            item["value"] = raw_value
            item["required"] = bool(meta.get("required"))
            item["type"] = _txt(meta.get("type"), "text")
            options = meta.get("options")
            if isinstance(options, list):
                item["options"] = [str(option) for option in options]
            items.append(item)
        return items
    model_keys = ["AI_API_KEY", "AI_API_BASE_URL", "DEFAULT_MODEL_NAME"]
    source_keys = ["TUSHARE_TOKEN", "MINIQMT_ENABLED", "MINIQMT_ACCOUNT_ID", "MINIQMT_HOST", "MINIQMT_PORT"]
    runtime_keys = ["EMAIL_ENABLED", "SMTP_SERVER", "SMTP_PORT", "EMAIL_FROM", "EMAIL_PASSWORD", "EMAIL_TO", "WEBHOOK_ENABLED", "WEBHOOK_TYPE", "WEBHOOK_URL", "WEBHOOK_KEYWORD"]
    return {"updatedAt": _now(), "metrics": [_metric("模型配置", len(model_keys)), _metric("数据源", len(source_keys)), _metric("运行参数", len(runtime_keys)), _metric("通知通道", 2)], "modelConfig": pick(model_keys), "dataSources": pick(source_keys), "runtimeParams": pick(runtime_keys), "paths": [str(context.data_dir / "watchlist.db"), str(context.quant_sim_db_file), str(context.portfolio_db_file), str(context.monitor_db_file), str(context.smart_monitor_db_file), str(context.stock_analysis_db_file), str(context.main_force_batch_db_file), str(context.selector_result_dir), str(LOGS_DIR)]}


def _action_settings_save(context: UIApiContext, payload: dict[str, Any]) -> dict[str, Any]:
    persisted = context.config_manager.write_env(
        {str(key): "" if value is None else str(value) for key, value in payload.items()}
    )
    if not persisted:
        raise HTTPException(status_code=500, detail="保存配置失败")
    context.config_manager.reload_config()
    return _snapshot_settings(context)




def _latest_replay_defaults(context: UIApiContext) -> dict[str, Any]:
    latest = next(iter(context.quant_db().get_sim_runs(limit=20)), None)
    if latest:
        return {
            "start_datetime": _txt(latest.get("start_datetime"), "--"),
            "end_datetime": latest.get("end_datetime"),
            "timeframe": _txt(latest.get("timeframe"), "30m"),
            "market": _txt(latest.get("market"), "CN"),
            "strategy_mode": _txt(latest.get("selected_strategy_mode") or latest.get("strategy_mode"), "auto"),
        }
    end_at = datetime.now().replace(second=0, microsecond=0)
    start_at = end_at - timedelta(days=30)
    return {
        "start_datetime": start_at.strftime("%Y-%m-%d %H:%M:%S"),
        "end_datetime": end_at.strftime("%Y-%m-%d %H:%M:%S"),
        "timeframe": "30m",
        "market": "CN",
        "strategy_mode": "auto",
    }


def _scheduler_update_kwargs(payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    mapping = {
        "strategy_mode": body.get("strategyMode") if "strategyMode" in body else body.get("strategy_mode"),
        "analysis_timeframe": body.get("analysisTimeframe") if "analysisTimeframe" in body else body.get("timeframe"),
        "auto_execute": body.get("autoExecute") if "autoExecute" in body else body.get("auto_execute"),
        "interval_minutes": body.get("intervalMinutes") if "intervalMinutes" in body else body.get("interval_minutes"),
        "trading_hours_only": body.get("tradingHoursOnly") if "tradingHoursOnly" in body else body.get("trading_hours_only"),
        "market": body.get("market"),
        "start_date": body.get("startDate") if "startDate" in body else body.get("start_date"),
    }
    return {key: value for key, value in mapping.items() if value is not None}


def _action_live_sim_save(context: UIApiContext, payload: Any) -> dict[str, Any]:
    updates = _scheduler_update_kwargs(payload)
    if updates:
        context.scheduler().update_config(**updates)
    return _snapshot_live_sim(context)


def _action_live_sim_start(context: UIApiContext, payload: Any) -> dict[str, Any]:
    scheduler = context.scheduler()
    updates = _scheduler_update_kwargs(payload)
    updates["enabled"] = True
    scheduler.update_config(**updates)
    scheduler.start()
    return _snapshot_live_sim(context)


def _action_live_sim_stop(context: UIApiContext, payload: Any) -> dict[str, Any]:
    scheduler = context.scheduler()
    scheduler.stop()
    scheduler.update_config(enabled=False)
    return _snapshot_live_sim(context)


def _action_live_sim_reset(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    initial_cash = _float(body.get("initialCash") if "initialCash" in body else body.get("initial_cash"))
    context.portfolio().reset_account(initial_cash=initial_cash)
    return _snapshot_live_sim(context)


def _action_live_sim_analyze_candidate(context: UIApiContext, payload: Any) -> dict[str, Any]:
    code = _code_from_payload(payload)
    if not code:
        raise HTTPException(status_code=400, detail="Missing candidate code")
    scheduler_state = context.scheduler().get_status()
    candidate = next((item for item in context.candidate_pool().list_candidates(status="active") if normalize_stock_code(item.get("stock_code")) == code), None)
    if not candidate:
        raise HTTPException(status_code=404, detail=f"Candidate not found: {code}")
    engine = QuantSimEngine(db_file=context.quant_sim_db_file, watchlist_db_file=context.watchlist_db_file, watchlist_service=context.watchlist())
    engine.analyze_candidate(
        candidate,
        analysis_timeframe=_txt(scheduler_state.get("analysis_timeframe"), "1d"),
        strategy_mode=_txt(scheduler_state.get("strategy_mode"), "auto"),
    )
    return _snapshot_live_sim(context)


def _action_live_sim_delete_candidate(context: UIApiContext, payload: Any) -> dict[str, Any]:
    code = _code_from_payload(payload)
    if not code:
        raise HTTPException(status_code=400, detail="Missing candidate code")
    context.candidate_pool().delete_candidate(code)
    context.watchlist().mark_in_quant_pool(code, False)
    return _snapshot_live_sim(context)


def _action_live_sim_bulk_quant(context: UIApiContext, payload: Any) -> dict[str, Any]:
    context.scheduler().run_once(run_reason="ui_manual_run")
    return _snapshot_live_sim(context)


def _action_his_replay_start(context: UIApiContext, payload: Any) -> dict[str, Any]:
    defaults = _latest_replay_defaults(context)
    body = _payload_dict(payload)
    context.replay_service().enqueue_historical_range(
        start_datetime=body.get("startDateTime") or body.get("start_datetime") or defaults["start_datetime"],
        end_datetime=body.get("endDateTime") or body.get("end_datetime") or defaults["end_datetime"],
        timeframe=body.get("timeframe") or defaults["timeframe"],
        market=body.get("market") or defaults["market"],
        strategy_mode=body.get("strategyMode") or body.get("strategy_mode") or defaults["strategy_mode"],
    )
    return _snapshot_his_replay(context)


def _action_his_replay_continue(context: UIApiContext, payload: Any) -> dict[str, Any]:
    defaults = _latest_replay_defaults(context)
    body = _payload_dict(payload)
    context.replay_service().enqueue_past_to_live(
        start_datetime=body.get("startDateTime") or body.get("start_datetime") or defaults["start_datetime"],
        end_datetime=body.get("endDateTime") or body.get("end_datetime") or defaults["end_datetime"],
        timeframe=body.get("timeframe") or defaults["timeframe"],
        market=body.get("market") or defaults["market"],
        strategy_mode=body.get("strategyMode") or body.get("strategy_mode") or defaults["strategy_mode"],
        overwrite_live=bool(body.get("overwriteLive", False) or body.get("overwrite_live", False)),
        auto_start_scheduler=body.get("autoStartScheduler", True) if "autoStartScheduler" in body else body.get("auto_start_scheduler", True),
    )
    return _snapshot_his_replay(context)


def _action_his_replay_cancel(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    run_id = _int(body.get("id"))
    if run_id is None:
        latest = next(iter(context.quant_db().get_sim_runs(limit=1)), None)
        run_id = _int(latest.get("id")) if latest else None
    if run_id is not None:
        context.quant_db().request_sim_run_cancel(run_id)
    return _snapshot_his_replay(context)


def _action_his_replay_delete(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    run_id = _int(body.get("id"))
    if run_id is not None:
        context.quant_db().delete_sim_run(run_id)
    return _snapshot_his_replay(context)


def _action_history_rerun(context: UIApiContext, payload: Any) -> dict[str, Any]:
    defaults = _latest_replay_defaults(context)
    context.replay_service().enqueue_historical_range(
        start_datetime=defaults["start_datetime"],
        end_datetime=defaults["end_datetime"],
        timeframe=defaults["timeframe"],
        market=defaults["market"],
        strategy_mode=defaults["strategy_mode"],
    )
    return _snapshot_history(context)


def _action_portfolio_analyze(context: UIApiContext, payload: Any) -> dict[str, Any]:
    code = _code_from_payload(payload)
    if not code:
        raise HTTPException(status_code=400, detail="Missing portfolio stock code")
    context.portfolio_manager().analyze_single_stock(code)
    return _snapshot_portfolio(context)


def _action_portfolio_refresh(context: UIApiContext, payload: Any) -> dict[str, Any]:
    context.portfolio_scheduler().run_analysis_now()
    return _snapshot_portfolio(context)


def _action_portfolio_schedule_save(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    kwargs = {
        "schedule_time": body.get("scheduleTime") if "scheduleTime" in body else body.get("schedule_time"),
        "analysis_mode": body.get("analysisMode") if "analysisMode" in body else body.get("analysis_mode"),
        "max_workers": body.get("maxWorkers") if "maxWorkers" in body else body.get("max_workers"),
        "auto_sync_monitor": body.get("autoSyncMonitor") if "autoSyncMonitor" in body else body.get("auto_sync_monitor"),
        "send_notification": body.get("sendNotification") if "sendNotification" in body else body.get("send_notification"),
    }
    context.portfolio_scheduler().update_config(**{key: value for key, value in kwargs.items() if value is not None})
    return _snapshot_portfolio(context)


def _action_portfolio_schedule_start(context: UIApiContext, payload: Any) -> dict[str, Any]:
    context.portfolio_scheduler().start_scheduler()
    return _snapshot_portfolio(context)


def _action_portfolio_schedule_stop(context: UIApiContext, payload: Any) -> dict[str, Any]:
    context.portfolio_scheduler().stop_scheduler()
    return _snapshot_portfolio(context)


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


def _action_noop(context: UIApiContext, page: str) -> dict[str, Any]:
    return SNAPSHOT_BUILDERS[page](context)


SNAPSHOT_BUILDERS: dict[str, Callable[[UIApiContext], dict[str, Any]]] = {
    "workbench": _snapshot_workbench,
    "discover": _snapshot_discover,
    "research": _snapshot_research,
    "portfolio": _snapshot_portfolio,
    "live-sim": _snapshot_live_sim,
    "his-replay": _snapshot_his_replay,
    "ai-monitor": _snapshot_ai_monitor,
    "real-monitor": _snapshot_real_monitor,
    "history": _snapshot_history,
    "settings": _snapshot_settings,
}

ACTION_BUILDERS: dict[tuple[str, str], Callable[[UIApiContext, dict[str, Any]], dict[str, Any]]] = {
    ("workbench", "add-watchlist"): _action_workbench_add_watchlist,
    ("workbench", "refresh-watchlist"): _action_workbench_refresh,
    ("workbench", "batch-quant"): _action_workbench_batch_quant,
    ("workbench", "analysis"): _action_workbench_analysis,
    ("workbench", "analysis-batch"): _action_workbench_analysis_batch,
    ("workbench", "clear-selection"): lambda context, payload: _action_noop(context, "workbench"),
    ("workbench", "delete-watchlist"): _action_workbench_delete,
    ("discover", "run-strategy"): _action_discover_run_strategy,
    ("discover", "batch-watchlist"): _action_discover_batch,
    ("discover", "item-watchlist"): _action_discover_item,
    ("research", "run-module"): _action_research_run_module,
    ("research", "batch-watchlist"): _action_research_batch,
    ("research", "item-watchlist"): _action_research_item,
    ("portfolio", "analyze"): _action_portfolio_analyze,
    ("portfolio", "refresh-portfolio"): _action_portfolio_refresh,
    ("portfolio", "schedule-save"): _action_portfolio_schedule_save,
    ("portfolio", "schedule-start"): _action_portfolio_schedule_start,
    ("portfolio", "schedule-stop"): _action_portfolio_schedule_stop,
    ("live-sim", "save"): _action_live_sim_save,
    ("live-sim", "start"): _action_live_sim_start,
    ("live-sim", "stop"): _action_live_sim_stop,
    ("live-sim", "reset"): _action_live_sim_reset,
    ("live-sim", "analyze-candidate"): _action_live_sim_analyze_candidate,
    ("live-sim", "delete-candidate"): _action_live_sim_delete_candidate,
    ("live-sim", "bulk-quant"): _action_live_sim_bulk_quant,
    ("his-replay", "start"): _action_his_replay_start,
    ("his-replay", "continue"): _action_his_replay_continue,
    ("his-replay", "cancel"): _action_his_replay_cancel,
    ("his-replay", "delete"): _action_his_replay_delete,
    ("ai-monitor", "start"): _action_ai_monitor_start,
    ("ai-monitor", "stop"): _action_ai_monitor_stop,
    ("ai-monitor", "analyze"): _action_ai_monitor_analyze,
    ("ai-monitor", "delete"): _action_ai_monitor_delete,
    ("real-monitor", "start"): _action_real_monitor_start,
    ("real-monitor", "stop"): _action_real_monitor_stop,
    ("real-monitor", "refresh"): _action_real_monitor_refresh,
    ("real-monitor", "update-rule"): _action_real_monitor_update_rule,
    ("real-monitor", "delete-rule"): _action_real_monitor_delete_rule,
    ("history", "rerun"): _action_history_rerun,
    ("settings", "save"): _action_settings_save,
}


def _health(path: str) -> dict[str, str]:
    return {"status": "ok", "service": SERVICE_NAME, "path": path}


TASK_MANAGERS = [analysis_task_manager, discover_task_manager, research_task_manager]


def _resolve_task_manager(task_id: str):
    for manager in TASK_MANAGERS:
        if manager.owns_task(task_id):
            return manager
    for manager in TASK_MANAGERS:
        if manager.get_task(task_id):
            return manager
    return None


def create_app(context: UIApiContext | None = None) -> FastAPI:
    api_context = context or UIApiContext()
    app = FastAPI(title="玄武AI智能体股票团队分析系统 Backend API", version="0.1.0")
    app.state.ui_context = api_context

    @app.get("/api/health")
    def api_health() -> dict[str, str]:
        return _health("/api/health")

    @app.get("/health")
    def health() -> dict[str, str]:
        return _health("/health")

    @app.get("/api/v1/tasks/{task_id}")
    def get_analysis_task(task_id: str) -> dict[str, Any]:
        manager = _resolve_task_manager(task_id)
        task = manager.get_task(task_id) if manager else None
        if not task:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        return manager.task_response(task, txt=_txt, int_fn=_int)

    for path, page in {
        "/api/v1/workbench": "workbench",
        "/api/v1/discover": "discover",
        "/api/v1/research": "research",
        "/api/v1/portfolio": "portfolio",
        "/api/v1/quant/live-sim": "live-sim",
        "/api/v1/quant/his-replay": "his-replay",
        "/api/v1/monitor/ai": "ai-monitor",
        "/api/v1/monitor/real": "real-monitor",
        "/api/v1/history": "history",
        "/api/v1/settings": "settings",
    }.items():

        async def snapshot_handler(page: str = page) -> dict[str, Any]:
            return SNAPSHOT_BUILDERS[page](api_context)

        snapshot_handler.__name__ = f"get_{page.replace('-', '_').replace('/', '_')}_snapshot"
        app.get(path)(snapshot_handler)

    for path, page, action in [
        ("/api/v1/workbench/actions/add-watchlist", "workbench", "add-watchlist"),
        ("/api/v1/workbench/actions/refresh-watchlist", "workbench", "refresh-watchlist"),
        ("/api/v1/workbench/actions/batch-quant", "workbench", "batch-quant"),
        ("/api/v1/workbench/actions/analysis", "workbench", "analysis"),
        ("/api/v1/workbench/actions/analysis-batch", "workbench", "analysis-batch"),
        ("/api/v1/workbench/actions/clear-selection", "workbench", "clear-selection"),
        ("/api/v1/workbench/actions/delete-watchlist", "workbench", "delete-watchlist"),
        ("/api/v1/discover/actions/item-watchlist", "discover", "item-watchlist"),
        ("/api/v1/discover/actions/batch-watchlist", "discover", "batch-watchlist"),
        ("/api/v1/discover/actions/run-strategy", "discover", "run-strategy"),
        ("/api/v1/research/actions/item-watchlist", "research", "item-watchlist"),
        ("/api/v1/research/actions/batch-watchlist", "research", "batch-watchlist"),
        ("/api/v1/research/actions/run-module", "research", "run-module"),
        ("/api/v1/portfolio/actions/analyze", "portfolio", "analyze"),
        ("/api/v1/portfolio/actions/refresh-portfolio", "portfolio", "refresh-portfolio"),
        ("/api/v1/portfolio/actions/schedule-save", "portfolio", "schedule-save"),
        ("/api/v1/portfolio/actions/schedule-start", "portfolio", "schedule-start"),
        ("/api/v1/portfolio/actions/schedule-stop", "portfolio", "schedule-stop"),
        ("/api/v1/quant/live-sim/actions/save", "live-sim", "save"),
        ("/api/v1/quant/live-sim/actions/start", "live-sim", "start"),
        ("/api/v1/quant/live-sim/actions/stop", "live-sim", "stop"),
        ("/api/v1/quant/live-sim/actions/reset", "live-sim", "reset"),
        ("/api/v1/quant/live-sim/actions/analyze-candidate", "live-sim", "analyze-candidate"),
        ("/api/v1/quant/live-sim/actions/delete-candidate", "live-sim", "delete-candidate"),
        ("/api/v1/quant/live-sim/actions/bulk-quant", "live-sim", "bulk-quant"),
        ("/api/v1/quant/his-replay/actions/start", "his-replay", "start"),
        ("/api/v1/quant/his-replay/actions/continue", "his-replay", "continue"),
        ("/api/v1/quant/his-replay/actions/cancel", "his-replay", "cancel"),
        ("/api/v1/quant/his-replay/actions/delete", "his-replay", "delete"),
        ("/api/v1/monitor/ai/actions/start", "ai-monitor", "start"),
        ("/api/v1/monitor/ai/actions/stop", "ai-monitor", "stop"),
        ("/api/v1/monitor/ai/actions/analyze", "ai-monitor", "analyze"),
        ("/api/v1/monitor/ai/actions/delete", "ai-monitor", "delete"),
        ("/api/v1/monitor/real/actions/start", "real-monitor", "start"),
        ("/api/v1/monitor/real/actions/stop", "real-monitor", "stop"),
        ("/api/v1/monitor/real/actions/refresh", "real-monitor", "refresh"),
        ("/api/v1/monitor/real/actions/update-rule", "real-monitor", "update-rule"),
        ("/api/v1/monitor/real/actions/delete-rule", "real-monitor", "delete-rule"),
        ("/api/v1/history/actions/rerun", "history", "rerun"),
        ("/api/v1/settings/actions/save", "settings", "save"),
    ]:

        async def action_handler(request: Request, page: str = page, action: str = action) -> dict[str, Any]:
            payload = await _json(request)
            handler = ACTION_BUILDERS.get((page, action))
            if not handler:
                raise HTTPException(status_code=404, detail=f"Unsupported action: {page}/{action}")
            return handler(api_context, payload)

        action_handler.__name__ = f"post_{page.replace('-', '_').replace('/', '_')}_{action.replace('-', '_')}"
        app.post(path)(action_handler)

    if UI_DIST_DIR.exists():
        assets_dir = UI_DIST_DIR / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="ui-assets")

        @app.get("/", include_in_schema=False)
        @app.get("/{client_path:path}", include_in_schema=False)
        async def spa_entry(client_path: str = ""):
            if client_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not Found")
            requested = UI_DIST_DIR / client_path
            if client_path and requested.is_file():
                return FileResponse(requested)
            return FileResponse(UI_DIST_DIR / "index.html")

    return app


__all__ = ["UIApiContext", "create_app"]

