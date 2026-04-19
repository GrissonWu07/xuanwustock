from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import re
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
        return {
            "updatedAt": _now(),
            "config": {
                "mode": "历史区间",
                "range": "--",
                "timeframe": "30m",
                "market": "CN",
                "strategyMode": "auto",
            },
            "metrics": [
                _metric("回放结果", "--"),
                _metric("最终总权益", "--"),
                _metric("交易笔数", "0"),
                _metric("胜率", "--"),
            ],
            "candidatePool": _table(["股票代码", "股票名称", "最新价格"], candidate_rows, "暂无候选股票"),
            "tasks": [],
            "tradingAnalysis": {"title": "交易分析", "body": "暂无回放记录。", "chips": []},
            "holdings": _table(["代码", "名称", "数量", "成本", "现价", "浮盈亏"], [], "暂无持仓"),
            "trades": _table(["时间", "信号ID", "代码", "动作", "数量", "价格"], [], "暂无交易记录"),
            "signals": _table(["信号ID", "时间", "代码", "动作", "策略", "执行结果"], [], "暂无信号"),
            "curve": [],
        }

    rid = int(run["id"])

    def _format_vote_summary(raw_value: Any) -> str:
        if isinstance(raw_value, dict):
            parts = [f"{_txt(key)}: {_txt(value)}" for key, value in raw_value.items() if _txt(key)]
            return "；".join(parts)
        if isinstance(raw_value, list):
            parts = []
            for item in raw_value:
                if isinstance(item, dict):
                    title = _txt(item.get("name") or item.get("analyst") or item.get("source"))
                    vote = _txt(item.get("vote") or item.get("decision") or item.get("action"))
                    score = _txt(item.get("score") or item.get("confidence"))
                    values = [text for text in [title, vote, score] if text]
                    if values:
                        parts.append(" / ".join(values))
                else:
                    text = _txt(item)
                    if text:
                        parts.append(text)
            return "；".join(parts)
        return _txt(raw_value)

    def _format_explainability_votes(strategy_profile: dict[str, Any]) -> str:
        explainability = strategy_profile.get("explainability") if isinstance(strategy_profile.get("explainability"), dict) else {}
        if not explainability:
            return ""

        lines: list[str] = []
        tech_votes = explainability.get("tech_votes")
        if isinstance(tech_votes, list) and tech_votes:
            lines.append("技术投票")
            for item in tech_votes:
                if not isinstance(item, dict):
                    continue
                factor = _txt(item.get("factor") or item.get("name") or item.get("title"))
                signal = _txt(item.get("signal") or item.get("vote") or item.get("decision"))
                score = _txt(item.get("score"))
                reason = _txt(item.get("reason"))
                chunks = [part for part in [factor, signal, f"score={score}" if score else "", reason] if part]
                if chunks:
                    lines.append(f"- {' | '.join(chunks)}")

        context_votes = explainability.get("context_votes")
        if isinstance(context_votes, list) and context_votes:
            lines.append("环境投票")
            for item in context_votes:
                if not isinstance(item, dict):
                    continue
                component = _txt(item.get("component") or item.get("factor") or item.get("name"))
                score = _txt(item.get("score"))
                reason = _txt(item.get("reason"))
                chunks = [part for part in [component, f"score={score}" if score else "", reason] if part]
                if chunks:
                    lines.append(f"- {' | '.join(chunks)}")

        dual_track = explainability.get("dual_track")
        if isinstance(dual_track, dict) and dual_track:
            lines.append("双轨决策")
            pairs = [
                ("tech", _txt(dual_track.get("tech_signal"))),
                ("context", _txt(dual_track.get("context_signal"))),
                ("resonance", _txt(dual_track.get("resonance_type"))),
                ("rule", _txt(dual_track.get("rule_hit"))),
                ("final", _txt(dual_track.get("final_action"))),
            ]
            summary = " | ".join([f"{k}={v}" for k, v in pairs if v])
            if summary:
                lines.append(f"- {summary}")

        return "\n".join(lines)

    signal_rows: list[dict[str, Any]] = []
    for i, item in enumerate(db.get_sim_run_signals(rid)):
        signal_id = _txt(item.get("id"), str(i))
        strategy_profile = item.get("strategy_profile") if isinstance(item.get("strategy_profile"), dict) else {}
        explainability = strategy_profile.get("explainability") if isinstance(strategy_profile.get("explainability"), dict) else {}
        dual_track = explainability.get("dual_track") if isinstance(explainability.get("dual_track"), dict) else {}
        vote_payload = (
            strategy_profile.get("vote_summary")
            or strategy_profile.get("votes")
            or strategy_profile.get("vote")
            or strategy_profile.get("voting")
        )
        vote_text = (
            _format_vote_summary(vote_payload)
            or _format_explainability_votes(strategy_profile)
            or _txt(strategy_profile.get("vote_text"), "暂无投票数据")
        )
        analysis_text = _txt(
            strategy_profile.get("analysis")
            or strategy_profile.get("analysis_summary")
            or strategy_profile.get("decision_reason")
            or dual_track.get("final_reason")
            or item.get("reasoning"),
            "暂无分析数据",
        )
        decision_type = _txt(item.get("decision_type"), "自动")
        signal_status = _txt(item.get("signal_status") or item.get("execution_note"), "待处理")
        confidence = _txt(item.get("confidence"), "0")
        tech_score = _txt(item.get("tech_score"), "0")
        context_score = _txt(item.get("context_score"), "0")
        checkpoint_at = _txt(item.get("checkpoint_at") or item.get("created_at"), "--")
        action_text = _txt(item.get("action"), "HOLD").upper()
        signal_rows.append(
            {
                "id": signal_id,
                "cells": [
                    f"#{signal_id}",
                    checkpoint_at,
                    _txt(item.get("stock_code")),
                    action_text,
                    decision_type,
                    signal_status,
                ],
                "actions": [{"label": "详情", "icon": "🔎", "tone": "accent", "action": "show-signal-detail"}],
                "analysis": analysis_text,
                "votes": vote_text,
                "decisionType": decision_type,
                "signalStatus": signal_status,
                "confidence": confidence,
                "techScore": tech_score,
                "contextScore": context_score,
                "checkpointAt": checkpoint_at,
                "code": _txt(item.get("stock_code")),
                "name": _txt(item.get("stock_name")),
            }
        )

    trade_rows = [
        {
            "id": _txt(item.get("id"), str(i)),
            "cells": [
                _txt(item.get("executed_at") or item.get("created_at"), "--"),
                f"#{_txt(item.get('signal_id'))}" if _txt(item.get("signal_id")) else "--",
                _txt(item.get("stock_code")),
                _txt(item.get("action"), "HOLD").upper(),
                _txt(item.get("quantity"), "0"),
                _num(item.get("price")),
            ],
            "code": _txt(item.get("stock_code")),
            "name": _txt(item.get("stock_name")),
        }
        for i, item in enumerate(db.get_sim_run_trades(rid))
    ]

    task_items: list[dict[str, Any]] = []
    for item in runs[:10]:
        run_id = int(item.get("id") or 0)
        status_text = _txt(item.get("status"), "completed")
        progress_total = int(_float(item.get("progress_total"), 0.0) or 0.0)
        progress_current = int(_float(item.get("progress_current"), 0.0) or 0.0)
        if progress_total > 0:
            progress_pct = max(0, min(int(round((progress_current / progress_total) * 100)), 100))
        elif status_text in {"completed", "failed", "cancelled"}:
            progress_pct = 100
        else:
            progress_pct = 0
        position_rows: list[dict[str, Any]] = []
        for idx, position in enumerate(db.get_sim_run_positions(run_id)):
            avg_price = _float(position.get("avg_price"), 0.0) or 0.0
            latest_price = _float(position.get("latest_price"), 0.0) or 0.0
            unrealized_pnl = _float(position.get("unrealized_pnl"), 0.0) or 0.0
            unrealized_pnl_pct = ((latest_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
            position_rows.append(
                {
                    "id": _txt(position.get("stock_code"), str(idx)),
                    "cells": [
                        _txt(position.get("stock_code")),
                        _txt(position.get("stock_name")),
                        _txt(position.get("quantity"), "0"),
                        _num(position.get("avg_price")),
                        _num(position.get("latest_price")),
                        _num(unrealized_pnl),
                        _pct(unrealized_pnl_pct),
                    ],
                    "code": _txt(position.get("stock_code")),
                    "name": _txt(position.get("stock_name")),
                }
            )

        task_items.append(
            {
                "id": f"#{item.get('id')}",
                "runId": _txt(item.get("id")),
                "status": status_text,
                "stage": _txt(item.get("status_message") or f"{item.get('checkpoint_count', 0)} 个检查点"),
                "progress": progress_pct,
                "startAt": _txt(item.get("start_datetime"), "--"),
                "endAt": _txt(item.get("end_datetime"), "--"),
                "range": f"{_txt(item.get('start_datetime'), '--')} -> {_txt(item.get('end_datetime'), 'now')}",
                "returnPct": _pct(item.get("total_return_pct")),
                "finalEquity": _num(item.get("final_equity"), 0),
                "tradeCount": _txt(item.get("trade_count"), "0"),
                "winRate": _pct(item.get("win_rate")),
                "holdings": position_rows,
            }
        )

    return {
        "updatedAt": _now(),
        "config": {
            "mode": _txt(run.get("mode"), "historical_range"),
            "range": f"{_txt(run.get('start_datetime'), '--')} -> {_txt(run.get('end_datetime'), 'now')}",
            "timeframe": _txt(run.get("timeframe"), "30m"),
            "market": _txt(run.get("market"), "CN"),
            "strategyMode": _txt(run.get("selected_strategy_mode") or run.get("strategy_mode"), "auto"),
        },
        "metrics": [
            _metric("回放结果", _pct(run.get("total_return_pct"))),
            _metric("最终总权益", _num(run.get("final_equity"), 0)),
            _metric("交易笔数", _txt(run.get("trade_count"), "0")),
            _metric("胜率", _pct(run.get("win_rate"))),
        ],
        "candidatePool": _table(["股票代码", "股票名称", "最新价格"], candidate_rows, "暂无候选股票"),
        "tasks": task_items,
        "tradingAnalysis": {
            "title": "交易分析",
            "body": "回放页会把交易分析拆成“人话结论 + 策略解释 + 量化证据”三层。",
            "chips": [],
        },
        "holdings": _table(
            ["代码", "名称", "数量", "成本", "现价", "浮盈亏"],
            [
                {
                    "id": _txt(item.get("stock_code"), str(i)),
                    "cells": [
                        _txt(item.get("stock_code")),
                        _txt(item.get("stock_name")),
                        _txt(item.get("quantity"), "0"),
                        _num(item.get("avg_price")),
                        _num(item.get("latest_price")),
                        _pct(item.get("unrealized_pnl")),
                    ],
                    "code": _txt(item.get("stock_code")),
                    "name": _txt(item.get("stock_name")),
                }
                for i, item in enumerate(db.get_sim_run_positions(rid))
            ],
            "暂无持仓",
        ),
        "trades": _table(["时间", "信号ID", "代码", "动作", "数量", "价格"], trade_rows, "暂无交易记录"),
        "signals": _table(["信号ID", "时间", "代码", "动作", "策略", "执行结果"], signal_rows, "暂无信号"),
        "curve": [
            {"label": _txt(item.get("created_at"), str(i)), "value": float(item.get("total_equity") or 0)}
            for i, item in enumerate(db.get_sim_run_snapshots(rid))
        ],
    }


def _safe_json_load(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _profile_text(value: Any, default: str = "--") -> str:
    if isinstance(value, dict):
        return _txt(value.get("key") or value.get("label") or value.get("name") or value.get("value"), default)
    return _txt(value, default)


def _to_vote_row(item: Any, default_signal: str = "") -> dict[str, str]:
    if not isinstance(item, dict):
        return {"factor": _txt(item), "signal": default_signal, "score": "", "reason": ""}
    return {
        "factor": _txt(item.get("factor") or item.get("component") or item.get("name") or item.get("title")),
        "signal": _txt(item.get("signal") or item.get("vote") or item.get("decision"), default_signal),
        "score": _txt(item.get("score") or item.get("confidence")),
        "reason": _txt(item.get("reason") or item.get("note") or item.get("detail")),
    }


def _extract_technical_indicators(*, tech_votes: list[dict[str, Any]], reasoning: str) -> list[dict[str, str]]:
    patterns = [
        ("现价", r"现价\s*(-?\d+(?:\.\d+)?)"),
        ("成本", r"成本\s*(-?\d+(?:\.\d+)?)"),
        ("MA5", r"MA5\s*(-?\d+(?:\.\d+)?)"),
        ("MA10", r"MA10\s*(-?\d+(?:\.\d+)?)"),
        ("MA20", r"MA20\s*(-?\d+(?:\.\d+)?)"),
        ("MA60", r"MA60\s*(-?\d+(?:\.\d+)?)"),
        ("MACD", r"MACD\s*(-?\d+(?:\.\d+)?)"),
        ("RSI12", r"RSI12\s*(-?\d+(?:\.\d+)?)"),
        ("量比", r"量比\s*(-?\d+(?:\.\d+)?)"),
        ("浮盈亏", r"浮盈亏\s*(-?\d+(?:\.\d+)?)%"),
    ]
    indicator_map: dict[str, dict[str, str]] = {}

    def _add_indicator(name: str, value: str, source: str, note: str = "") -> None:
        normalized = _txt(name)
        if not normalized or normalized in indicator_map:
            return
        indicator_map[normalized] = {
            "name": normalized,
            "value": _txt(value),
            "source": source,
            "note": _txt(note),
        }

    for vote in tech_votes:
        if not isinstance(vote, dict):
            continue
        factor = _txt(vote.get("factor") or vote.get("name"))
        score_text = _txt(vote.get("score"))
        reason = _txt(vote.get("reason"))
        if factor and score_text:
            _add_indicator(f"{factor}打分", score_text, "tech_vote", reason)
        if reason:
            for metric, pattern in patterns:
                matched = re.search(pattern, reason)
                if matched:
                    value = _txt(matched.group(1))
                    if metric == "浮盈亏":
                        value = f"{value}%"
                    _add_indicator(metric, value, "tech_vote_reason", reason)

    text = _txt(reasoning)
    if text:
        for metric, pattern in patterns:
            matched = re.search(pattern, text)
            if matched:
                value = _txt(matched.group(1))
                if metric == "浮盈亏":
                    value = f"{value}%"
                _add_indicator(metric, value, "reasoning")

    return list(indicator_map.values())


def _detect_provider(api_base_url: str) -> str:
    base = api_base_url.lower()
    if "openrouter.ai" in base:
        return "openrouter"
    if "openai.com" in base:
        return "openai"
    return "openai-compatible"


def _build_runtime_context(
    context: UIApiContext,
    *,
    source: str,
    strategy_profile: dict[str, Any],
    replay_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = context.config_manager.read_env()
    scheduler_status = context.scheduler().get_status()

    model_name = _txt(config.get("DEFAULT_MODEL_NAME"), "--")
    api_base_url = _txt(config.get("AI_API_BASE_URL"), "--")
    provider = _detect_provider(api_base_url)

    if source == "replay":
        market = _txt((replay_run or {}).get("market"), _txt(scheduler_status.get("market"), "CN"))
        timeframe = _profile_text((replay_run or {}).get("timeframe"), _profile_text(strategy_profile.get("analysis_timeframe"), _txt(scheduler_status.get("analysis_timeframe"), "30m")))
        strategy_mode = _profile_text((replay_run or {}).get("selected_strategy_mode") or (replay_run or {}).get("strategy_mode"), _profile_text(strategy_profile.get("strategy_mode"), _txt(scheduler_status.get("strategy_mode"), "auto")))
    else:
        market = _txt(scheduler_status.get("market"), "CN")
        timeframe = _profile_text(strategy_profile.get("analysis_timeframe"), _txt(scheduler_status.get("analysis_timeframe"), "30m"))
        strategy_mode = _profile_text(strategy_profile.get("strategy_mode"), _txt(scheduler_status.get("strategy_mode"), "auto"))

    return {
        "model": model_name,
        "provider": provider,
        "apiBaseUrl": api_base_url,
        "market": market,
        "timeframe": timeframe,
        "strategyMode": strategy_mode,
        "autoExecute": bool(scheduler_status.get("auto_execute")),
        "intervalMinutes": _txt(scheduler_status.get("interval_minutes"), "--"),
        "lastRunAt": _txt(scheduler_status.get("last_run_at"), "--"),
        "source": source,
    }


def _vote_line(item: dict[str, Any]) -> str:
    factor = _txt(item.get("factor") or item.get("component") or item.get("name") or item.get("title"), "因子")
    signal = _txt(item.get("signal") or item.get("vote") or item.get("decision"), "--")
    score = _txt(item.get("score") or item.get("confidence"), "--")
    reason = _txt(item.get("reason") or item.get("note") or item.get("detail"), "--")
    return f"{factor}: {signal} (score={score}) · {reason}"


def _vote_sort_key(item: dict[str, Any]) -> float:
    return abs(_float(item.get("score"), 0.0) or 0.0)


def _humanize_signal(signal: Any) -> str:
    normalized = _txt(signal, "--").upper()
    mapping = {
        "BUY": "看多（买入）",
        "SELL": "看空（卖出）",
        "HOLD": "中性（持有）",
        "CONTEXT": "环境信号",
    }
    return mapping.get(normalized, _txt(signal, "--"))


def _derive_keep_position_pct(action: Any, position_size_pct: Any) -> str:
    ratio = _float(position_size_pct)
    action_upper = _txt(action, "--").upper()
    if action_upper == "HOLD":
        return "维持当前仓位（不变）"
    if ratio is None:
        return "--"
    ratio = max(0.0, min(100.0, float(ratio)))
    if action_upper == "SELL":
        keep = max(0.0, 100.0 - ratio)
    elif action_upper == "BUY":
        keep = ratio
    else:
        return "--"
    text = f"{keep:.2f}"
    return text.rstrip("0").rstrip(".")


def _dual_track_basis_lines(decision: dict[str, Any], effective_thresholds: dict[str, Any]) -> list[str]:
    tech_signal = _txt(decision.get("techSignal"), "--")
    context_signal = _txt(decision.get("contextSignal"), "--")
    decision_type = _txt(decision.get("decisionType"), "--")
    resonance_type = _txt(decision.get("resonanceType"), "--")
    rule_hit = _txt(decision.get("ruleHit"), "--")
    final_action = _txt(decision.get("finalAction") or decision.get("action"), "--")
    position_size_pct = _txt(decision.get("positionSizePct"), "--")
    keep_position_pct = _derive_keep_position_pct(final_action, position_size_pct)
    tech_score = _txt(decision.get("techScore"), "--")
    context_score = _txt(decision.get("contextScore"), "--")

    buy_threshold = _txt(effective_thresholds.get("buy_threshold"), "--")
    sell_threshold = _txt(effective_thresholds.get("sell_threshold"), "--")
    max_position_ratio = _txt(effective_thresholds.get("max_position_ratio"), "--")
    allow_pyramiding_raw = _txt(effective_thresholds.get("allow_pyramiding")).strip().lower()
    allow_pyramiding = "允许" if allow_pyramiding_raw in {"1", "true", "yes", "y", "on"} else "不允许"
    confirmation = _txt(effective_thresholds.get("confirmation"), "--")

    merge_reason_map = {
        "sell_divergence": "技术轨给出看空，但环境轨未同向看空，系统按“风险优先”的背离规则处理，优先保护资金。",
        "buy_divergence": "技术轨给出看多，但环境轨未同向看多，系统按“确认优先”的背离规则处理，避免盲目追涨。",
        "resonance_full": "技术轨与环境轨同向且强度高，形成强共振，允许更高执行力度。",
        "resonance_heavy": "技术轨与环境轨同向，形成偏强共振，执行力度高于常规。",
        "resonance_moderate": "技术轨与环境轨同向但强度中等，按中等共振规则执行。",
        "resonance_standard": "技术轨与环境轨方向一致但强度一般，按标准共振执行。",
        "neutral_hold": "双轨没有形成明确同向信号，系统保持中性观望。",
    }
    merge_reason = merge_reason_map.get(rule_hit) or merge_reason_map.get(decision_type) or "系统先判断双轨是否同向，再按共振/背离规则确定最终动作和仓位。"
    position_semantics = "目标买入仓位" if _txt(final_action).upper() == "BUY" else ("建议卖出比例" if _txt(final_action).upper() == "SELL" else "建议仓位")
    if keep_position_pct == "--":
        keep_segment = ""
    elif keep_position_pct.endswith("%") or "不变" in keep_position_pct:
        keep_segment = f"，建议保持仓位 {keep_position_pct}"
    else:
        keep_segment = f"，建议保持仓位 {keep_position_pct}%"

    return [
        "双轨决策=技术轨 + 环境轨。技术轨反映价格/指标信号，环境轨反映市场状态与风险约束，二者先独立打分再合并。",
        f"技术轨结论: {_humanize_signal(tech_signal)}，技术分 {tech_score}（阈值: 买入>= {buy_threshold}，卖出<= {sell_threshold}）。",
        f"环境轨结论: {_humanize_signal(context_signal)}，环境分 {context_score}（环境分越高，越支持进攻；越低，越偏防守）。",
        f"合并判定: 决策类型 {decision_type}，共振类型 {resonance_type}，规则命中 {rule_hit}。{merge_reason}",
        f"执行结果: 最终动作为 {_humanize_signal(final_action)}，{position_semantics} {position_size_pct}%{keep_segment}（上限比例 {max_position_ratio}，{allow_pyramiding}加仓，确认条件: {confirmation}）。",
    ]


def _build_explanation_payload(
    *,
    decision: dict[str, Any],
    analysis_text: str,
    reasoning_text: str,
    tech_votes_raw: list[dict[str, Any]],
    context_votes_raw: list[dict[str, Any]],
    effective_thresholds: dict[str, Any],
) -> dict[str, Any]:
    top_tech = sorted([item for item in tech_votes_raw if isinstance(item, dict)], key=_vote_sort_key, reverse=True)[:5]
    top_context = sorted([item for item in context_votes_raw if isinstance(item, dict)], key=_vote_sort_key, reverse=True)[:5]
    threshold_lines = [f"{_txt(k)}={_txt(v)}" for k, v in effective_thresholds.items() if _txt(k)]
    context_score_total = 0.0
    context_breakdown: list[str] = []
    for item in context_votes_raw:
        if not isinstance(item, dict):
            continue
        name = _txt(item.get("component") or item.get("factor") or item.get("name"), "component")
        score_value = _float(item.get("score"), 0.0) or 0.0
        context_score_total += score_value
        context_breakdown.append(f"{name}={score_value:+.4f}")

    summary_lines = [
        f"本次决策为 {decision.get('action', '--')}，决策类型 {decision.get('decisionType', '--')}，状态 {decision.get('status', '--')}。",
        f"技术信号 {decision.get('techSignal', '--')}，环境信号 {decision.get('contextSignal', '--')}，共振类型 {decision.get('resonanceType', '--')}，规则命中 {decision.get('ruleHit', '--')}。",
        f"置信度 {decision.get('confidence', '--')}，技术分 {decision.get('techScore', '--')}，环境分 {decision.get('contextScore', '--')}，建议仓位 {decision.get('positionSizePct', '--')}%。",
    ]

    if threshold_lines:
        summary_lines.append("阈值参考: " + " | ".join(threshold_lines[:8]))

    return {
        "summary": "\n".join(summary_lines),
        "contextScoreExplain": {
            "formula": "环境分 = 来源先验 + 趋势 + 价格结构 + 动量 + 风险平衡 + 流动性 + 时段，并截断到 [-1, 1]。",
            "confidenceFormula": "环境置信度 = clamp(0.56 + abs(趋势+结构+动量+时段)*0.45 + abs(流动性)*0.2, 0.45, 0.92)。",
            "componentBreakdown": context_breakdown,
            "componentSum": round(context_score_total, 4),
            "finalScore": _txt(decision.get("contextScore"), "0"),
        },
        "basis": [
            f"决策点: {decision.get('checkpointAt', '--')}",
            f"时间粒度: {decision.get('analysisTimeframe', '--')}，策略模式: {decision.get('strategyMode', '--')}",
            f"市场状态: {decision.get('marketRegime', '--')}，基本面质量: {decision.get('fundamentalQuality', '--')}",
            f"风险风格: {decision.get('riskStyle', '--')}（auto={decision.get('autoInferredRiskStyle', '--')}）",
            *_dual_track_basis_lines(decision, effective_thresholds),
            f"最终理由: {decision.get('finalReason', '--')}",
        ],
        "techEvidence": [_vote_line(item) for item in top_tech],
        "contextEvidence": [_vote_line(item) for item in top_context],
        "thresholdEvidence": threshold_lines,
        "original": {
            "analysis": analysis_text,
            "reasoning": reasoning_text,
        },
    }


def _build_vote_overview(
    *,
    tech_votes_raw: list[dict[str, Any]],
    context_votes_raw: list[dict[str, Any]],
) -> dict[str, Any]:
    def _extract_weight(item: dict[str, Any]) -> float:
        for key in ("weight", "vote_weight", "factor_weight", "w"):
            value = _float(item.get(key))
            if value is not None:
                return value
        return 1.0

    def _extract_contribution(item: dict[str, Any], score: float, weight: float) -> float:
        for key in ("weighted_score", "weightedScore", "contribution", "vote_score"):
            value = _float(item.get(key))
            if value is not None:
                return value
        return score * weight

    rows: list[dict[str, str]] = []
    tech_sum = 0.0
    context_sum = 0.0
    tech_count = 0
    context_count = 0

    for track, raw_votes in (("technical", tech_votes_raw), ("context", context_votes_raw)):
        for index, item in enumerate(raw_votes):
            vote_row = _to_vote_row(item, default_signal="CONTEXT" if track == "context" else "")
            if isinstance(item, dict):
                voter = _txt(
                    item.get("agent")
                    or item.get("analyst")
                    or item.get("factor")
                    or item.get("component")
                    or item.get("name")
                    or item.get("title"),
                    vote_row.get("factor") or f"{track}-voter-{index + 1}",
                )
                signal = _txt(item.get("signal") or item.get("vote") or item.get("decision"), vote_row.get("signal") or "--")
                score_value = _float(item.get("score"), _float(item.get("confidence"), 0.0)) or 0.0
                weight_value = _extract_weight(item)
                contribution_value = _extract_contribution(item, score_value, weight_value)
                reason = _txt(item.get("reason") or item.get("note") or item.get("detail"), vote_row.get("reason") or "--")
                calculation = _txt(
                    item.get("calculation") or item.get("formula"),
                    f"单票贡献 = score({score_value:+.4f}) x weight({weight_value:.4f}) = {contribution_value:+.4f}",
                )
            else:
                voter = _txt(vote_row.get("factor"), f"{track}-voter-{index + 1}")
                signal = _txt(vote_row.get("signal"), "--")
                score_value = _float(vote_row.get("score"), 0.0) or 0.0
                weight_value = 1.0
                contribution_value = score_value
                reason = _txt(vote_row.get("reason"), "--")
                calculation = f"单票贡献 = score({score_value:+.4f}) x weight(1.0000) = {contribution_value:+.4f}"

            if track == "technical":
                tech_sum += contribution_value
                tech_count += 1
            else:
                context_sum += contribution_value
                context_count += 1

            rows.append(
                {
                    "track": track,
                    "voter": voter,
                    "signal": signal,
                    "score": f"{score_value:+.4f}",
                    "weight": f"{weight_value:.4f}",
                    "contribution": f"{contribution_value:+.4f}",
                    "reason": reason,
                    "calculation": calculation,
                }
            )

    tech_clamped = max(-1.0, min(1.0, tech_sum))
    context_clamped = max(-1.0, min(1.0, context_sum))

    return {
        "voterCount": len(rows),
        "technicalVoterCount": tech_count,
        "contextVoterCount": context_count,
        "formula": "单票贡献 = score x weight；分轨得分 = clamp(Σ单票贡献, -1, 1)。",
        "technicalAggregation": f"技术轨汇总: Σ贡献={tech_sum:+.4f}，截断后={tech_clamped:+.4f}。",
        "contextAggregation": f"环境轨汇总: Σ贡献={context_sum:+.4f}，截断后={context_clamped:+.4f}。",
        "rows": rows,
    }


def _extract_vote_list(explainability: dict[str, Any], keys: tuple[str, ...]) -> list[Any]:
    for key in keys:
        value = explainability.get(key)
        if isinstance(value, list):
            return value
    votes_obj = explainability.get("votes")
    if isinstance(votes_obj, dict):
        for key in keys:
            value = votes_obj.get(key)
            if isinstance(value, list):
                return value
    return []


def _parse_metric_float(value: Any) -> float | None:
    text = _txt(value)
    if not text:
        return None
    matched = re.search(r"-?\d+(?:\.\d+)?", text)
    if not matched:
        return None
    try:
        return float(matched.group(0))
    except (TypeError, ValueError):
        return None


def _indicator_derivation(
    *,
    name: str,
    value: Any,
    source: str,
    note: str,
    metric_values: dict[str, float],
) -> str:
    metric_name = _txt(name)
    metric_upper = metric_name.upper()
    metric_value = _parse_metric_float(value)
    current_price = metric_values.get("现价")
    ma20 = metric_values.get("MA20")
    k_value = metric_values.get("K值")
    d_value = metric_values.get("D值")

    def _trend_vs_ma(ma_name: str, ma_value: float | None) -> str:
        if current_price is None or ma_value is None:
            return f"{ma_name} 是对应周期均线，用于判断该周期趋势方向与支撑/压力。"
        if current_price > ma_value:
            return f"当前价高于 {ma_name}，该周期趋势偏强，回踩 {ma_name} 常作为支撑位观察。"
        if current_price < ma_value:
            return f"当前价低于 {ma_name}，该周期趋势偏弱，{ma_name} 更可能形成上方压力。"
        return f"当前价接近 {ma_name}，多空在该周期均衡，需结合成交量确认方向。"

    if metric_name.endswith("打分"):
        if metric_value is None:
            return "该项为单因子投票分，正值偏多、负值偏空，绝对值越大影响越大。"
        if metric_value > 0:
            return f"该因子投票分为正({metric_value:+.4f})，对最终买入方向提供增量支持。"
        if metric_value < 0:
            return f"该因子投票分为负({metric_value:+.4f})，对最终卖出/谨慎方向提供增量支持。"
        return "该因子投票分接近 0，对最终决策影响中性。"

    if metric_name == "现价":
        if current_price is None or ma20 is None:
            return "现价是决策时点的成交参考价，用于与均线和阈值比较。"
        if current_price > ma20:
            return f"现价高于 MA20（{ma20:.2f}），中期趋势仍偏强。"
        if current_price < ma20:
            return f"现价低于 MA20（{ma20:.2f}），中期趋势转弱，需防回撤扩大。"
        return f"现价与 MA20（{ma20:.2f}）接近，中期方向尚不明确。"

    if metric_name == "成本":
        if current_price is None or metric_value is None:
            return "成本用于衡量当前仓位盈亏与风控空间。"
        pnl = (current_price - metric_value) / metric_value * 100 if metric_value else 0.0
        if pnl >= 0:
            return f"按当前价估算浮盈约 {pnl:.2f}%，可结合止盈阈值评估是否继续持有。"
        return f"按当前价估算浮亏约 {abs(pnl):.2f}%，需优先关注止损纪律。"

    if metric_upper in {"MA5", "MA10", "MA20", "MA60"}:
        return _trend_vs_ma(metric_upper, metric_value)

    if metric_upper in {"RSI", "RSI12"}:
        if metric_value is None:
            return "RSI 反映价格动量强弱，常用 30/70 识别超卖/超买。"
        if metric_value >= 70:
            return f"RSI={metric_value:.2f} 处于偏高区，短线可能过热，追高性价比下降。"
        if metric_value <= 30:
            return f"RSI={metric_value:.2f} 处于偏低区，短线超卖，需观察是否出现止跌信号。"
        return f"RSI={metric_value:.2f} 位于中性区间，动量未到极端。"

    if metric_upper == "MACD":
        if metric_value is None:
            return "MACD 衡量趋势动量，正值偏多、负值偏空。"
        if metric_value > 0:
            return f"MACD={metric_value:.4f} 为正，动量结构偏多。"
        if metric_value < 0:
            return f"MACD={metric_value:.4f} 为负，动量结构偏空。"
        return "MACD 接近 0，趋势动量处于切换边缘。"

    if metric_name == "信号线":
        return "信号线用于和 MACD 做交叉判断，MACD 上穿信号线通常视为动量改善。"

    if metric_name == "布林上轨":
        if current_price is None or metric_value is None:
            return "布林上轨代表近期波动上边界，接近时通常意味着波动与回撤风险加大。"
        if current_price >= metric_value:
            return "现价触及/接近布林上轨，短线容易出现震荡或回落。"
        return "现价低于布林上轨，仍有上行空间但需关注量能是否匹配。"

    if metric_name == "布林下轨":
        if current_price is None or metric_value is None:
            return "布林下轨代表近期波动下边界，接近时需观察是否出现止跌信号。"
        if current_price <= metric_value:
            return "现价触及/接近布林下轨，短线可能超跌，需结合成交量确认反弹有效性。"
        return "现价高于布林下轨，价格仍处正常波动带内。"

    if metric_name == "K值":
        if metric_value is None:
            return "K 值是 KDJ 的快线，对短周期波动较敏感。"
        if d_value is None:
            return f"K 值为 {metric_value:.2f}，用于观察短线动量强弱。"
        if metric_value > d_value:
            return f"K({metric_value:.2f}) 高于 D({d_value:.2f})，短线动量偏强。"
        if metric_value < d_value:
            return f"K({metric_value:.2f}) 低于 D({d_value:.2f})，短线动量偏弱。"
        return f"K 与 D 均约 {metric_value:.2f}，短线方向暂不明显。"

    if metric_name == "D值":
        if metric_value is None:
            return "D 值是 KDJ 的慢线，用于平滑短线噪音。"
        if k_value is None:
            return f"D 值为 {metric_value:.2f}，可配合 K 值判断拐点。"
        if k_value > metric_value:
            return f"K({k_value:.2f}) 上于 D({metric_value:.2f})，短线结构偏多。"
        if k_value < metric_value:
            return f"K({k_value:.2f}) 下于 D({metric_value:.2f})，短线结构偏空。"
        return "K 与 D 重合，短线方向等待进一步确认。"

    if metric_name == "量比":
        if metric_value is None:
            return "量比反映当前成交活跃度，相对 1 越高说明放量越明显。"
        if metric_value >= 1.5:
            return f"量比={metric_value:.2f}，成交明显放大，信号有效性通常更高。"
        if metric_value <= 0.8:
            return f"量比={metric_value:.2f}，成交偏弱，趋势延续性需要谨慎评估。"
        return f"量比={metric_value:.2f}，成交活跃度处于常态区间。"

    if metric_name == "浮盈亏":
        if metric_value is None:
            return "浮盈亏用于评估持仓安全垫与止盈止损空间。"
        if metric_value >= 0:
            return f"当前浮盈 {metric_value:.2f}%，可结合回撤容忍度动态止盈。"
        return f"当前浮亏 {abs(metric_value):.2f}%，应优先遵守止损规则。"

    if note:
        return f"该指标来自决策时的原始说明：{note}"
    if source == "tech_vote":
        return "该指标来自技术投票子模型的直接打分输出。"
    if source == "tech_vote_reason":
        return "该指标来自技术投票理由中的数值抽取，用于还原投票依据。"
    if source == "reasoning":
        return "该指标来自决策文本中的显式数值，已结构化用于复盘。"
    return "该指标用于补充决策依据。"


def _build_parameter_details(
    *,
    decision: dict[str, Any],
    runtime_context: dict[str, Any],
    technical_indicators: list[dict[str, str]],
    effective_thresholds: dict[str, Any],
    tech_votes_raw: list[dict[str, Any]],
    context_votes_raw: list[dict[str, Any]],
) -> list[dict[str, str]]:
    def _item(name: str, value: Any, source: str, derivation: str) -> dict[str, str]:
        return {
            "name": _txt(name),
            "value": _txt(value, "--"),
            "source": _txt(source),
            "derivation": _txt(derivation),
        }

    tech_vote_sum = sum((_float(item.get("score"), 0.0) or 0.0) for item in tech_votes_raw if isinstance(item, dict))
    tech_vote_clamped = max(-1.0, min(1.0, tech_vote_sum))
    context_vote_sum = sum((_float(item.get("score"), 0.0) or 0.0) for item in context_votes_raw if isinstance(item, dict))
    context_vote_clamped = max(-1.0, min(1.0, context_vote_sum))

    rows: list[dict[str, str]] = [
        _item("动作", decision.get("action"), "DualTrackResolver.resolve", "由技术信号、环境信号与规则命中共同决定最终 BUY/SELL/HOLD。"),
        _item("决策类型", decision.get("decisionType"), "DualTrackResolver.resolve", "根据共振/背离/否决路径设置，如 dual_track_resonance、dual_track_divergence、dual_track_hold。"),
        _item("技术信号", decision.get("techSignal"), "KernelStrategyRuntime._select_tech_action", "tech_score >= buy_threshold => BUY；<= sell_threshold => SELL；否则 HOLD。"),
        _item("环境信号", decision.get("contextSignal"), "KernelStrategyRuntime._select_context_signal", "context_score >= 0.3 => BUY；<= -0.3 => SELL；否则 HOLD。"),
        _item("技术分", decision.get("techScore"), "KernelStrategyRuntime._calculate_candidate_tech_votes / _calculate_position_tech_votes", f"技术投票分值求和后截断到 [-1,1]。当前投票和={tech_vote_sum:.4f}，截断后={tech_vote_clamped:.4f}。"),
        _item("环境分", decision.get("contextScore"), "MarketRegimeContextProvider.score_context", f"来源先验+趋势+结构+动量+风险平衡+流动性+时段求和后截断到 [-1,1]。当前组件和={context_vote_sum:.4f}，截断后={context_vote_clamped:.4f}。"),
        _item("置信度", decision.get("confidence"), "KernelStrategyRuntime._select_tech_confidence", "base_confidence + |tech_score|*tech_weight + max(context_score,0)*context_weight + 风格加成，之后夹在[min_confidence,max_confidence]。"),
        _item(
            "仓位建议(%)",
            decision.get("positionSizePct"),
            "DualTrackResolver._calculate_position_rule",
            "BUY 时表示目标买入仓位比例；SELL 时表示建议卖出比例（100% 即清仓可卖仓位）；HOLD 时通常为 0。由技术分与环境分命中共振/背离规则后得到。",
        ),
        _item(
            "建议保持仓位",
            _derive_keep_position_pct(decision.get("action"), decision.get("positionSizePct")),
            "DualTrackResolver._calculate_position_rule",
            "BUY 时等于目标买入仓位；SELL 时 = 100% - 建议卖出比例；HOLD 时表示维持当前仓位不变。",
        ),
        _item("规则命中", decision.get("ruleHit"), "DualTrackResolver._calculate_position_rule", "按 resonance_full/heavy/moderate/standard/divergence 等规则判定。"),
        _item("共振类型", decision.get("resonanceType"), "DualTrackResolver.resolve", "由仓位比例和背离状态映射 full/heavy/moderate/light 等类型。"),
        _item("市场", runtime_context.get("market"), "调度配置/回放任务", "实时模式取 scheduler.market；回放模式取 sim_runs.market。"),
        _item("分析粒度", runtime_context.get("timeframe"), "调度配置/回放任务/策略配置", "实时模式优先取策略分析粒度，其次 scheduler.analysis_timeframe；回放模式取 sim_runs.timeframe。"),
        _item("策略模式", runtime_context.get("strategyMode"), "调度配置/回放任务/策略配置", "实时模式优先取策略模式，其次 scheduler.strategy_mode；回放模式取 sim_runs.selected_strategy_mode。"),
    ]

    for key, value in effective_thresholds.items():
        threshold_key = _txt(key)
        if not threshold_key:
            continue
        rows.append(
            _item(
                f"阈值.{threshold_key}",
                value,
                "KernelStrategyRuntime._resolve_thresholds",
                "由风险风格参数与分析粒度参数融合得到 effective_thresholds。",
            )
        )

    metric_values = {
        _txt(item.get("name")): _parse_metric_float(item.get("value"))
        for item in technical_indicators
        if _txt(item.get("name"))
    }
    for indicator in technical_indicators:
        name = _txt(indicator.get("name"))
        if not name:
            continue
        source = _txt(indicator.get("source"), "行情快照")
        note = _txt(indicator.get("note"))
        rows.append(
            _item(
                f"指标.{name}",
                indicator.get("value"),
                source,
                _indicator_derivation(
                    name=name,
                    value=indicator.get("value"),
                    source=source,
                    note=note,
                    metric_values=metric_values,
                ),
            )
        )

    return rows


def _build_signal_detail_payload(
    context: UIApiContext,
    signal: dict[str, Any],
    *,
    source: str,
    replay_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    strategy_profile = _safe_json_load(signal.get("strategy_profile"))
    explainability = _safe_json_load(strategy_profile.get("explainability"))
    dual_track = _safe_json_load(explainability.get("dual_track"))
    tech_votes_raw = _extract_vote_list(explainability, ("tech_votes", "technical_votes", "techVotes", "tech"))
    context_votes_raw = _extract_vote_list(explainability, ("context_votes", "market_votes", "contextVotes", "context"))
    tech_votes = [_to_vote_row(item) for item in tech_votes_raw]
    context_votes = [_to_vote_row(item, default_signal="CONTEXT") for item in context_votes_raw]

    analysis_text = _txt(
        strategy_profile.get("analysis")
        or strategy_profile.get("analysis_summary")
        or strategy_profile.get("decision_reason")
        or dual_track.get("final_reason")
        or signal.get("reasoning"),
        "暂无分析数据",
    )
    reasoning_text = _txt(signal.get("reasoning"), analysis_text)

    decision = {
        "id": _txt(signal.get("id")),
        "source": source,
        "stockCode": _txt(signal.get("stock_code")),
        "stockName": _txt(signal.get("stock_name")),
        "action": _txt(signal.get("action"), "HOLD").upper(),
        "status": _txt(signal.get("signal_status") or signal.get("status") or signal.get("execution_note"), "observed"),
        "decisionType": _txt(signal.get("decision_type") or dual_track.get("decision_type"), "auto"),
        "confidence": _txt(signal.get("confidence"), "0"),
        "positionSizePct": _txt(signal.get("position_size_pct"), "0"),
        "techScore": _txt(signal.get("tech_score"), "0"),
        "contextScore": _txt(signal.get("context_score"), "0"),
        "checkpointAt": _txt(signal.get("checkpoint_at") or signal.get("updated_at") or signal.get("created_at"), "--"),
        "createdAt": _txt(signal.get("created_at"), "--"),
        "analysisTimeframe": _profile_text(strategy_profile.get("analysis_timeframe"), "--"),
        "strategyMode": _profile_text(strategy_profile.get("strategy_mode"), "--"),
        "marketRegime": _txt(strategy_profile.get("market_regime"), "--"),
        "fundamentalQuality": _txt(strategy_profile.get("fundamental_quality"), "--"),
        "riskStyle": _txt(_safe_json_load(strategy_profile.get("risk_style")).get("label") or strategy_profile.get("risk_style"), "--"),
        "autoInferredRiskStyle": _txt(strategy_profile.get("auto_inferred_risk_style"), "--"),
        "techSignal": _txt(dual_track.get("tech_signal"), "--"),
        "contextSignal": _txt(dual_track.get("context_signal"), "--"),
        "resonanceType": _txt(dual_track.get("resonance_type"), "--"),
        "ruleHit": _txt(dual_track.get("rule_hit"), "--"),
        "finalAction": _txt(dual_track.get("final_action") or signal.get("action"), "HOLD").upper(),
        "finalReason": _txt(dual_track.get("final_reason") or reasoning_text, "--"),
        "positionRatio": _txt(dual_track.get("position_ratio"), _txt(signal.get("position_size_pct"), "0")),
    }

    technical_indicators = _extract_technical_indicators(tech_votes=tech_votes_raw, reasoning=reasoning_text)
    effective_thresholds = _safe_json_load(strategy_profile.get("effective_thresholds"))
    runtime_context = _build_runtime_context(
        context,
        source=source,
        strategy_profile=strategy_profile,
        replay_run=replay_run,
    )
    explanation = _build_explanation_payload(
        decision=decision,
        analysis_text=analysis_text,
        reasoning_text=reasoning_text,
        tech_votes_raw=tech_votes_raw,
        context_votes_raw=context_votes_raw,
        effective_thresholds=effective_thresholds,
    )
    vote_overview = _build_vote_overview(
        tech_votes_raw=tech_votes_raw,
        context_votes_raw=context_votes_raw,
    )
    parameter_details = _build_parameter_details(
        decision=decision,
        runtime_context=runtime_context,
        technical_indicators=technical_indicators,
        effective_thresholds=effective_thresholds,
        tech_votes_raw=tech_votes_raw,
        context_votes_raw=context_votes_raw,
    )

    return {
        "updatedAt": _now(),
        "analysis": analysis_text,
        "reasoning": reasoning_text,
        "runtimeContext": runtime_context,
        "explanation": explanation,
        "voteOverview": vote_overview,
        "parameterDetails": parameter_details,
        "decision": decision,
        "techVotes": tech_votes,
        "contextVotes": context_votes,
        "technicalIndicators": technical_indicators,
        "effectiveThresholds": [{"name": _txt(k), "value": _txt(v)} for k, v in effective_thresholds.items() if _txt(k)],
        "strategyProfile": strategy_profile,
    }


def _find_signal_detail(context: UIApiContext, signal_id: str, *, source: str = "auto") -> dict[str, Any]:
    db = context.quant_db()
    normalized_source = _txt(source, "auto").lower()
    sid_int = _int(signal_id)
    if sid_int is None:
        raise HTTPException(status_code=400, detail=f"Invalid signal id: {signal_id}")

    if normalized_source in {"auto", "live"}:
        live_signal = next((item for item in db.get_signals(limit=5000) if _int(item.get("id")) == sid_int), None)
        if live_signal:
            return _build_signal_detail_payload(context, live_signal, source="live")

    if normalized_source in {"auto", "replay"}:
        run_rows = db.get_sim_runs(limit=30)
        for run in run_rows:
            run_id = _int(run.get("id"))
            if run_id is None:
                continue
            replay_signal = next((item for item in db.get_sim_run_signals(run_id) if _int(item.get("id")) == sid_int), None)
            if replay_signal:
                return _build_signal_detail_payload(context, replay_signal, source="replay", replay_run=run)

    raise HTTPException(status_code=404, detail=f"Signal not found: {signal_id}")


def _live_signal_table(context: UIApiContext, limit: int = 200) -> dict[str, Any]:
    db = context.quant_db()
    safe_limit = max(1, min(limit, 500))
    rows: list[dict[str, Any]] = []
    for i, item in enumerate(db.get_signals(limit=safe_limit)):
        signal_id = _txt(item.get("id"), str(i))
        rows.append(
            {
                "id": signal_id,
                "cells": [
                    f"#{signal_id}",
                    _txt(item.get("updated_at") or item.get("created_at"), "--"),
                    _txt(item.get("stock_code")),
                    _txt(item.get("action"), "HOLD").upper(),
                    _txt(item.get("decision_type"), "auto"),
                    _txt(item.get("status"), "observed"),
                ],
                "actions": [{"label": "详情", "icon": "🔎", "tone": "accent", "action": "show-signal-detail"}],
                "code": _txt(item.get("stock_code")),
                "name": _txt(item.get("stock_name")),
            }
        )
    return {
        "updatedAt": _now(),
        "table": _table(["信号ID", "时间", "代码", "动作", "策略", "状态"], rows, "暂无信号"),
    }


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

    @app.get("/api/v1/quant/signals/{signal_id}")
    def get_signal_detail(signal_id: str, source: str = "auto") -> dict[str, Any]:
        return _find_signal_detail(api_context, signal_id, source=source)

    @app.get("/api/v1/quant/live-sim/signals")
    def get_live_sim_signals(limit: int = 200) -> dict[str, Any]:
        return _live_signal_table(api_context, limit=limit)

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

