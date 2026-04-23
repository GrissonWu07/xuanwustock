from __future__ import annotations

from contextlib import asynccontextmanager
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
from app import stock_analysis_service
from app.gateway_common import (
    code_from_payload as _code_from_payload,
    first_non_empty as _first_non_empty,
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
    action_discover_reset as _action_discover_reset,
    action_discover_run_strategy as _gateway_discover_run_strategy,
    discover_task_manager,
    snapshot_discover as _snapshot_discover,
)
import app.gateway_discover as _gateway_discover_module
from app.gateway_research import (
    action_research_batch as _action_research_batch,
    action_research_item as _action_research_item,
    action_research_reset as _action_research_reset,
    action_research_run_module as _gateway_research_run_module,
    research_task_manager,
    snapshot_research as _snapshot_research,
)
import app.gateway_research as _gateway_research_module
from app.gateway_workbench import (
    action_workbench_add_watchlist as _action_workbench_add_watchlist,
    action_workbench_analysis as _action_workbench_analysis,
    action_workbench_analysis_batch as _action_workbench_analysis_batch,
    action_workbench_batch_portfolio as _action_workbench_batch_portfolio,
    action_workbench_batch_quant as _action_workbench_batch_quant,
    action_workbench_delete as _action_workbench_delete,
    action_workbench_refresh as _action_workbench_refresh,
    build_workbench_snapshot as _gateway_build_workbench_snapshot,
    snapshot_workbench as _gateway_snapshot_workbench,
)
from app.main_force_batch_db import MainForceBatchDatabase
from app.monitor_db import monitor_db
from app.portfolio_db import portfolio_db
from app.portfolio_rebalance_tasks import portfolio_rebalance_task_manager
from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.db import (
    DEFAULT_AI_DYNAMIC_LOOKBACK,
    DEFAULT_AI_DYNAMIC_STRENGTH,
    DEFAULT_AI_DYNAMIC_STRATEGY,
    DEFAULT_COMMISSION_RATE,
    DEFAULT_SELL_TAX_RATE,
    QuantSimDB,
)
from app.quant_sim.engine import QuantSimEngine
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.replay_service import QuantSimReplayService
from app.quant_sim.scheduler import get_quant_sim_scheduler
from app.runtime_paths import DATA_DIR, LOGS_DIR, default_db_path
from app.selector_result_store import DEFAULT_SELECTOR_RESULT_DIR
from app.stock_refresh_scheduler import (
    get_unified_stock_refresh_scheduler,
    load_stock_runtime_entries,
)
from app.watchlist_selector_integration import normalize_stock_code
from app.monitor_db import StockMonitorDatabase
from app.watchlist_service import WatchlistService
from app.workbench_analysis_payloads import (
    analysis_config as _workbench_analysis_config,
    analysis_options as _workbench_analysis_options,
    build_workbench_analysis_payload as _build_workbench_analysis_payload,
)
from app.workbench_analysis_tasks import analysis_task_manager

SERVICE_NAME = "xuanwu-api"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
UI_DIST_DIR = PROJECT_ROOT / "ui" / "dist"


async def _json(request: Request) -> Any:
    try:
        return await request.json()
    except Exception:
        return {}


MainForceStockSelector = _gateway_discover_module.MainForceStockSelector
LowPriceBullSelector = _gateway_discover_module.LowPriceBullSelector
SmallCapSelector = _gateway_discover_module.SmallCapSelector
ProfitGrowthSelector = _gateway_discover_module.ProfitGrowthSelector
ValueStockSelector = _gateway_discover_module.ValueStockSelector
SectorStrategyDataFetcher = _gateway_research_module.SectorStrategyDataFetcher
SectorStrategyEngine = _gateway_research_module.SectorStrategyEngine
LonghubangEngine = _gateway_research_module.LonghubangEngine
NewsFlowEngine = _gateway_research_module.NewsFlowEngine
MacroAnalysisEngine = _gateway_research_module.MacroAnalysisEngine
MacroCycleEngine = _gateway_research_module.MacroCycleEngine


def _action_discover_run_strategy(context: "UIApiContext", payload: Any) -> dict[str, Any]:
    _gateway_discover_module.MainForceStockSelector = globals().get("MainForceStockSelector")
    _gateway_discover_module.LowPriceBullSelector = globals().get("LowPriceBullSelector")
    _gateway_discover_module.SmallCapSelector = globals().get("SmallCapSelector")
    _gateway_discover_module.ProfitGrowthSelector = globals().get("ProfitGrowthSelector")
    _gateway_discover_module.ValueStockSelector = globals().get("ValueStockSelector")
    return _gateway_discover_run_strategy(context, payload)


def _action_research_run_module(context: "UIApiContext", payload: Any) -> dict[str, Any]:
    _gateway_research_module.SectorStrategyDataFetcher = globals().get("SectorStrategyDataFetcher")
    _gateway_research_module.SectorStrategyEngine = globals().get("SectorStrategyEngine")
    _gateway_research_module.LonghubangEngine = globals().get("LonghubangEngine")
    _gateway_research_module.NewsFlowEngine = globals().get("NewsFlowEngine")
    _gateway_research_module.MacroAnalysisEngine = globals().get("MacroAnalysisEngine")
    _gateway_research_module.MacroCycleEngine = globals().get("MacroCycleEngine")
    return _gateway_research_run_module(context, payload)





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


def _indicator_alias_value(indicators: dict[str, Any], aliases: list[str]) -> Any:
    for alias in aliases:
        if alias in indicators:
            return indicators.get(alias)
    lowered = {str(key).lower(): value for key, value in indicators.items()}
    for alias in aliases:
        alias_key = str(alias).lower()
        if alias_key in lowered:
            return lowered.get(alias_key)
    return None


def _build_portfolio_indicator_cards(
    indicators: dict[str, Any] | None,
    explanations: dict[str, dict[str, str]] | None,
) -> list[dict[str, Any]]:
    indicators = indicators if isinstance(indicators, dict) else {}
    explanations = explanations if isinstance(explanations, dict) else {}
    specs = [
        ("Price", ["price", "close", "Close"], "Latest traded price."),
        ("Volume", ["volume", "Volume"], "Latest traded volume."),
        ("Volume MA5", ["volume_ma5", "Volume_MA5"], "5-period average volume."),
        ("MA5", ["ma5", "MA5"], "5-day moving average."),
        ("MA10", ["ma10", "MA10"], "10-day moving average."),
        ("MA20", ["ma20", "MA20"], "20-day moving average."),
        ("MA60", ["ma60", "MA60"], "60-day moving average."),
        ("RSI", ["rsi", "RSI"], "Relative strength index."),
        ("MACD", ["macd", "MACD"], "Trend momentum indicator."),
        ("Signal line", ["macd_signal", "MACD_signal"], "MACD signal line."),
        ("Bollinger upper", ["bb_upper", "BB_upper"], "Upper volatility band."),
        ("Bollinger middle", ["bb_middle", "BB_middle"], "Middle volatility band."),
        ("Bollinger lower", ["bb_lower", "BB_lower"], "Lower volatility band."),
        ("K value", ["k_value", "K"], "KDJ fast line."),
        ("D value", ["d_value", "D"], "KDJ slow line."),
        ("Volume ratio", ["volume_ratio", "Volume_ratio", "量比"], "Relative activity vs average volume."),
    ]
    cards: list[dict[str, Any]] = []
    for label, aliases, default_hint in specs:
        value = _indicator_alias_value(indicators, aliases)
        detail = explanations.get(label) if isinstance(explanations.get(label), dict) else None
        hint = _txt(detail.get("summary"), default_hint) if detail else default_hint
        cards.append(
            {
                "label": label,
                "value": _num(value) if isinstance(value, (int, float)) else _txt(value, "--"),
                "hint": hint,
            }
        )
    return cards


def _build_portfolio_kline(stock_data: Any) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    if stock_data is None or not hasattr(stock_data, "tail"):
        return points
    def _row_number(row: Any, aliases: list[str]) -> float | None:
        if not hasattr(row, "get"):
            return None
        for alias in aliases:
            value = row.get(alias)
            if value in (None, ""):
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None
    try:
        tail = stock_data.tail(160)
        for index, row in tail.iterrows():
            close_number = _row_number(row, ["Close", "收盘", "close"])
            if close_number is None:
                continue
            open_number = _row_number(row, ["Open", "开盘", "open"])
            high_number = _row_number(row, ["High", "最高", "high"])
            low_number = _row_number(row, ["Low", "最低", "low"])
            volume_number = _row_number(row, ["Volume", "成交量", "volume", "vol"])
            if open_number is None:
                open_number = close_number
            if high_number is None:
                high_number = max(open_number, close_number)
            if low_number is None:
                low_number = min(open_number, close_number)
            label = _txt(index)
            if hasattr(index, "strftime"):
                try:
                    label = index.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    label = _txt(index)
            item: dict[str, Any] = {
                "label": label,
                "value": close_number,
                "open": open_number,
                "high": high_number,
                "low": low_number,
                "close": close_number,
            }
            if volume_number is not None:
                item["volume"] = volume_number
            points.append(item)
    except Exception:
        return []
    return points


def _portfolio_technical_snapshot(symbol: str, cycle: str = "1y") -> dict[str, Any]:
    if not symbol:
        return {"symbol": "", "stockName": "", "sector": "", "kline": [], "indicators": []}
    stock_info, stock_data, indicators = stock_analysis_service.get_stock_data(symbol, cycle)
    info = stock_info if isinstance(stock_info, dict) else {}
    indicator_map = indicators if isinstance(indicators, dict) else {}
    indicator_explanations = stock_analysis_service.build_indicator_explanations(
        indicator_map,
        current_price=info.get("current_price"),
    )
    return {
        "symbol": symbol,
        "stockName": _txt(info.get("name"), symbol),
        "sector": _txt(info.get("sector") or info.get("industry") or info.get("board") or info.get("所属行业")),
        "kline": _build_portfolio_kline(stock_data),
        "indicators": _build_portfolio_indicator_cards(indicator_map, indicator_explanations),
    }


def _portfolio_pending_signal_rows(context: "UIApiContext", symbol: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, item in enumerate(context.quant_db().get_pending_signals()):
        code = normalize_stock_code(item.get("stock_code"))
        if symbol and code != symbol:
            continue
        rows.append(
            {
                "id": _txt(item.get("id"), f"pending-{i}"),
                "cells": [
                    _txt(item.get("created_at") or item.get("updated_at"), "--"),
                    code,
                    _txt(item.get("action"), "HOLD").upper(),
                    _txt(item.get("strategy_mode") or item.get("decision_type"), "--"),
                    _txt(item.get("status"), "pending"),
                    _txt(item.get("reasoning") or item.get("execution_note"), "--"),
                ],
                "code": code,
                "name": _txt(item.get("stock_name"), code),
            }
        )
    return rows


def _payload_codes(payload: Any) -> list[str]:
    body = _payload_dict(payload)
    values = body.get("symbols") if isinstance(body.get("symbols"), list) else []
    if not values:
        raw_codes = body.get("codes")
        if isinstance(raw_codes, list):
            values = raw_codes
        elif isinstance(raw_codes, str):
            values = re.split(r"[\s,;，；]+", raw_codes)
    normalized = [normalize_stock_code(_txt(code)) for code in values if _txt(code)]
    return [code for code in normalized if code]


def _load_market_focus_news(context: "UIApiContext", limit: int = 8) -> list[dict[str, Any]]:
    try:
        from app.sector_strategy_db import SectorStrategyDatabase

        db = SectorStrategyDatabase(default_db_path("sector_strategy.db", data_dir=context.data_dir))
        payload = db.get_latest_news_data(within_hours=24)
        content = payload.get("data_content") if isinstance(payload, dict) else []
        items: list[dict[str, Any]] = []
        for idx, item in enumerate(content[:limit]):
            if not isinstance(item, dict):
                continue
            title = _txt(item.get("title"), f"市场新闻 {idx + 1}")
            body = _txt(item.get("content")) or _txt(item.get("summary"))
            if len(body) > 180:
                body = f"{body[:180]}..."
            items.append(
                {
                    "title": title,
                    "body": body or "暂无摘要",
                    "source": _txt(item.get("source"), "market"),
                    "time": _txt(item.get("news_date"), "--"),
                    "url": _txt(item.get("url")),
                }
            )
        return items
    except Exception:
        return []


def _build_portfolio_adjustment_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "action": "保持",
            "targetExposurePct": "0%",
            "summary": "当前无持仓，建议先控制仓位并等待有效信号。",
            "bullishCount": 0,
            "neutralCount": 0,
            "bearishCount": 0,
            "score": 0.0,
            "reasons": ["暂无持仓股票数据"],
        }

    bullish = 0
    bearish = 0
    neutral = 0
    weighted_score = 0.0
    total_weight = 0.0
    reasons: list[str] = []
    for item in rows:
        rating = _txt(item.get("rating"), "").upper()
        quantity = _float(item.get("quantity")) or 0.0
        price = _float(item.get("current_price")) or _float(item.get("cost_price")) or 0.0
        weight = max(quantity * price, 1.0)
        confidence = min(max((_float(item.get("confidence")) or 5.0) / 10.0, 0.0), 1.0)

        vote = 0.0
        if ("买" in rating) or ("BUY" in rating):
            bullish += 1
            vote = 1.0
        elif ("卖" in rating) or ("SELL" in rating):
            bearish += 1
            vote = -1.0
        else:
            neutral += 1
            vote = 0.0

        weighted_score += vote * confidence * weight
        total_weight += weight

    normalized_score = weighted_score / total_weight if total_weight > 0 else 0.0
    if normalized_score >= 0.35:
        action = "加仓"
        target_exposure = "70%"
    elif normalized_score <= -0.35:
        action = "降仓"
        target_exposure = "35%"
    else:
        action = "保持"
        target_exposure = "50%"

    reasons.append(f"看多 {bullish} / 中性 {neutral} / 看空 {bearish}")
    reasons.append(f"综合得分 {normalized_score:+.2f}（按仓位和置信度加权）")
    summary = f"组合仓位建议：{action}，建议目标仓位约 {target_exposure}。"
    return {
        "action": action,
        "targetExposurePct": target_exposure,
        "summary": summary,
        "bullishCount": bullish,
        "neutralCount": neutral,
        "bearishCount": bearish,
        "score": round(normalized_score, 4),
        "reasons": reasons,
    }


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
    workbench_analysis_cache: dict[str, Any] | None = None
    workbench_analysis_job_cache: dict[str, Any] | None = None

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

    def set_workbench_analysis(self, payload: dict[str, Any] | None) -> None:
        self.workbench_analysis_cache = dict(payload) if isinstance(payload, dict) else None

    def get_workbench_analysis(self) -> dict[str, Any] | None:
        return dict(self.workbench_analysis_cache) if isinstance(self.workbench_analysis_cache, dict) else None

    def set_workbench_analysis_job(self, payload: dict[str, Any] | None) -> None:
        self.workbench_analysis_job_cache = dict(payload) if isinstance(payload, dict) else None

    def get_workbench_analysis_job(self) -> dict[str, Any] | None:
        return dict(self.workbench_analysis_job_cache) if isinstance(self.workbench_analysis_job_cache, dict) else None


_WORKBENCH_DEFAULT_ANALYSTS = ["technical", "fundamental", "fund_flow", "risk"]
_WORKBENCH_MARKDOWN_NOISE = [
    "以下是基于",
    "核心结论先看",
    "我会重点围绕",
    "如果你愿意",
    "先说明",
    "会议纪要",
    "模拟对话",
    "会议主持人",
    "投资决策团队",
]
_WORKBENCH_MODEL_FAILURE_TOKENS = [
    "api调用失败",
    "authentication fails",
    "auth fail",
    "governor",
    "鉴权",
]


def _normalize_workbench_selected(selected: Any) -> list[str]:
    if isinstance(selected, list):
        values = [str(item).strip() for item in selected if str(item).strip()]
        if values:
            return values
    return list(_WORKBENCH_DEFAULT_ANALYSTS)


def _analysis_options(selected: list[str] | None = None) -> list[dict[str, Any]]:
    return _workbench_analysis_options(_normalize_workbench_selected(selected))


def _clean_workbench_text(value: Any, *, limit: int = 0) -> str:
    text = _txt(value)
    if not text:
        return ""
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = text.replace("***", " ").replace("**", " ").replace("__", " ").replace("`", " ")
    text = text.replace("---", " ").replace("|", " ")
    for noise in _WORKBENCH_MARKDOWN_NOISE:
        text = text.replace(noise, " ")
    text = re.sub(r"\s+", " ", text).strip()
    if limit > 0 and len(text) > limit:
        text = f"{text[:limit].rstrip()}…"
    return text


def _contains_workbench_model_failure(*values: Any) -> bool:
    merged = " ".join(_txt(item).lower() for item in values if _txt(item))
    if not merged:
        return False
    return any(token in merged for token in _WORKBENCH_MODEL_FAILURE_TOKENS)


def _record_is_more_complete(record: dict[str, Any]) -> tuple[int, int]:
    indicators = record.get("indicators") if isinstance(record.get("indicators"), dict) else {}
    historical = record.get("historical_data") if isinstance(record.get("historical_data"), list) else []
    agents = record.get("agents_results") if isinstance(record.get("agents_results"), dict) else {}
    final_decision = record.get("final_decision") if isinstance(record.get("final_decision"), dict) else {}
    score = 0
    if indicators:
        score += 4
    if historical:
        score += 4
    score += min(len(agents), 4)
    if _txt(final_decision.get("operation_advice") or final_decision.get("decision_text") or final_decision.get("rating")):
        score += 2
    return score, _int(record.get("id"), 0) or 0


def _pick_best_cached_record(context: UIApiContext, symbol: str) -> dict[str, Any] | None:
    records = context.stock_analysis_db().get_recent_records_by_symbol(symbol, limit=10)
    if not records:
        return None
    ranked = sorted(records, key=_record_is_more_complete, reverse=True)
    return ranked[0] if ranked else None


def _history_points_from_dataframe(stock_data: Any) -> list[dict[str, Any]]:
    if stock_data is None or not hasattr(stock_data, "iterrows"):
        return []
    points: list[dict[str, Any]] = []
    try:
        for index, row in stock_data.tail(180).iterrows():
            close_value = row.get("Close") if hasattr(row, "get") else None
            if close_value in (None, "") and hasattr(row, "get"):
                close_value = row.get("收盘")
            if close_value in (None, ""):
                continue
            label = _txt(index)
            if hasattr(index, "strftime"):
                try:
                    label = index.strftime("%Y-%m-%d")
                except Exception:
                    label = _txt(index)
            points.append({"date": label, "close": float(close_value)})
    except Exception:
        return []
    return points


def _normalize_workbench_payload(
    *,
    payload: dict[str, Any],
    indicators: dict[str, Any],
    discussion_result: Any,
    final_decision: dict[str, Any],
    agents_results: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(payload)
    indicator_explanations = stock_analysis_service.build_indicator_explanations(
        indicators if isinstance(indicators, dict) else {},
        current_price=None,
    )
    indicator_summary = _txt(
        stock_analysis_service.build_indicator_summary(indicator_explanations),
        "关键指标显示当前趋势信号仍在，建议结合仓位控制继续跟踪。",
    )
    discussion_summary = _txt(discussion_result.get("summary")) if isinstance(discussion_result, dict) else ""
    summary_text = _clean_workbench_text(discussion_summary or _txt(discussion_result), limit=110)
    if not summary_text:
        summary_text = _clean_workbench_text(indicator_summary, limit=110)

    analyst_views: list[dict[str, Any]] = []
    analyst_names: list[str] = []
    model_failure = _contains_workbench_model_failure(summary_text, _txt(final_decision), _txt(discussion_result))
    for _, agent_result in (agents_results or {}).items():
        if not isinstance(agent_result, dict):
            continue
        agent_name = _txt(agent_result.get("agent_name"), "分析师")
        analyst_names.append(agent_name)
        body = _clean_workbench_text(
            _txt(agent_result.get("summary") or agent_result.get("analysis") or agent_result.get("decision_text") or agent_result.get("result")),
            limit=170,
        )
        if _contains_workbench_model_failure(body):
            model_failure = True
        if not body:
            continue
        analyst_views.append({"title": agent_name, "body": body})

    rating = _txt(_first_non_empty(final_decision, ["rating", "decision", "verdict"]))
    position_size = _txt(final_decision.get("position_size"))
    target_price = _txt(final_decision.get("target_price"))
    operation_advice = _clean_workbench_text(
        _txt(final_decision.get("operation_advice") or final_decision.get("decision_text") or final_decision.get("reasoning")),
        limit=170,
    )

    decision_parts: list[str] = []
    if rating:
        decision_parts.append(f"当前评级：{rating}")
    if position_size:
        decision_parts.append(f"建议仓位：{position_size}")
    if target_price:
        decision_parts.append(f"目标价：{target_price}")
    decision_text = "；".join(decision_parts)
    if operation_advice:
        decision_text = f"{decision_text}。{operation_advice}" if decision_text else operation_advice
    if not decision_text and analyst_views:
        view_hint = "；".join(item.get("body", "") for item in analyst_views[:2] if _txt(item.get("body")))
        decision_text = _clean_workbench_text(view_hint, limit=170)
    if not decision_text:
        decision_text = summary_text or _clean_workbench_text(indicator_summary, limit=170)
    if decision_text and ("建议" not in decision_text and "更适合" not in decision_text):
        decision_text = f"建议继续观察，{decision_text}"
    if not decision_text:
        decision_text = "综合决策暂不可用，请先查看分析师观点与关键指标。"

    insights: list[dict[str, Any]] = []
    risk_warning = _clean_workbench_text(_txt(final_decision.get("risk_warning")), limit=120)
    if model_failure:
        model_state = "模型调用暂不可用（疑似鉴权或额度异常），已自动降级为指标与历史结论。"
        analyst_hint = "、".join(analyst_names) if analyst_names else "当前分析师"
        normalized["summaryBody"] = _clean_workbench_text(indicator_summary, limit=110)
        normalized["decision"] = _clean_workbench_text(indicator_summary, limit=170) or "综合决策暂不可用，请先查看关键指标。"
        normalized["finalDecisionText"] = normalized["decision"]
        normalized["analystViews"] = []
        insights.append(_insight("模型状态", model_state, "warning"))
        insights.append(_insight("分析师观点", f"{analyst_hint}观点暂不可用，建议稍后重试。", "neutral"))
        insights.append(_insight("操作建议", normalized["decision"], "accent"))
    else:
        merged_summary = summary_text
        if decision_text and _clean_workbench_text(decision_text, limit=80) not in merged_summary:
            merged_summary = _clean_workbench_text(f"{decision_text} {summary_text}", limit=110)
        normalized["summaryBody"] = merged_summary
        normalized["decision"] = _clean_workbench_text(decision_text, limit=170)
        normalized["finalDecisionText"] = normalized["decision"]
        normalized["analystViews"] = analyst_views
        insights.append(_insight("操作建议", normalized["decision"], "accent"))
        if risk_warning:
            insights.append(_insight("风险提示", risk_warning, "warning"))
    normalized["insights"] = insights
    return normalized


def _run_single_workbench_analysis(
    context: UIApiContext,
    job_id: str,
    *,
    code: str,
    selected: list[str] | None,
    cycle: str,
    mode: str,
) -> dict[str, Any]:
    symbol = normalize_stock_code(code)
    if not symbol:
        raise HTTPException(status_code=400, detail="Missing stock code")

    selected_values = _normalize_workbench_selected(selected)
    analyze_config = _workbench_analysis_config(selected_values)
    try:
        result = stock_analysis_service.analyze_single_stock_for_batch(
            symbol,
            cycle,
            enabled_analysts_config=analyze_config,
            selected_model=None,
            progress_callback=None,
        )
    except Exception as exc:
        result = {"success": False, "error": str(exc), "symbol": symbol}

    if not isinstance(result, dict) or not result.get("success"):
        hydrated_name = _hydrate_cached_workbench_analysis(
            context,
            code=symbol,
            selected=selected_values,
            cycle=cycle,
            mode=mode,
        )
        if not hydrated_name:
            fallback = {
                "symbol": symbol,
                "stockName": symbol,
                "analysts": _analysis_options(selected_values),
                "mode": mode,
                "cycle": cycle,
                "inputHint": "例如 600519 / 300390 / AAPL",
                "summaryTitle": f"{symbol} 分析摘要",
                "summaryBody": "分析未返回有效结果，请稍后重试。",
                "generatedAt": _now(),
                "indicators": [],
                "decision": "综合决策暂不可用，请先查看关键指标与分析师观点。",
                "finalDecisionText": "综合决策暂不可用，请先查看关键指标与分析师观点。",
                "insights": [
                    _insight("模型状态", "模型调用暂不可用（疑似鉴权或额度异常），请检查配置后重试。", "warning"),
                ],
                "analystViews": [],
                "curve": [],
            }
            context.set_workbench_analysis(fallback)
        failure_message = _txt(result.get("error"), "分析失败")
        if hydrated_name:
            failure_message = f"{failure_message}；已保留上一次成功分析。"
        context.set_workbench_analysis_job(
            {
                "id": job_id,
                "status": "failed",
                "title": "刷新失败（已回退到最近有效结果）",
                "message": failure_message,
                "stage": "failed",
                "progress": 100,
                "symbol": symbol,
                "startedAt": _now(),
                "updatedAt": _now(),
            }
        )
        return context.get_workbench_analysis() or {}

    stock_info = result.get("stock_info") if isinstance(result.get("stock_info"), dict) else {}
    stock_name = _txt(stock_info.get("name"), symbol)
    indicators = result.get("indicators") if isinstance(result.get("indicators"), dict) else {}
    discussion_result = result.get("discussion_result")
    final_decision = result.get("final_decision") if isinstance(result.get("final_decision"), dict) else {}
    agents_results = result.get("agents_results") if isinstance(result.get("agents_results"), dict) else {}
    historical_data = result.get("historical_data") if isinstance(result.get("historical_data"), list) else []

    try:
        context.stock_analysis_db().save_analysis(
            symbol=symbol,
            stock_name=stock_name,
            period=cycle,
            stock_info=stock_info,
            agents_results=agents_results,
            discussion_result=discussion_result,
            final_decision=final_decision,
            indicators=indicators,
            historical_data=historical_data,
        )
    except Exception:
        pass

    payload = _build_workbench_analysis_payload(
        code=symbol,
        stock_name=stock_name,
        selected=selected_values,
        mode=mode,
        cycle=cycle,
        generated_at=_txt(result.get("generated_at"), _now()),
        stock_info=stock_info,
        indicators=indicators,
        discussion_result=discussion_result,
        final_decision=final_decision,
        agents_results=agents_results,
        historical_data=historical_data,
    )
    payload = _normalize_workbench_payload(
        payload=payload,
        indicators=indicators,
        discussion_result=discussion_result,
        final_decision=final_decision,
        agents_results=agents_results,
    )
    context.set_workbench_analysis(payload)
    context.set_workbench_analysis_job(
        {
            "id": job_id,
            "status": "completed",
            "title": "分析已完成",
            "message": f"{symbol} 分析完成",
            "stage": "completed",
            "progress": 100,
            "symbol": symbol,
            "startedAt": _now(),
            "updatedAt": _now(),
        }
    )
    return payload


def _hydrate_cached_workbench_analysis(
    context: UIApiContext,
    *,
    code: str,
    selected: list[str] | None,
    cycle: str,
    mode: str,
) -> str:
    symbol = normalize_stock_code(code)
    if not symbol:
        return ""
    record = _pick_best_cached_record(context, symbol)
    if not record:
        return ""
    stock_info = record.get("stock_info") if isinstance(record.get("stock_info"), dict) else {}
    indicators = record.get("indicators") if isinstance(record.get("indicators"), dict) else {}
    historical_data = record.get("historical_data") if isinstance(record.get("historical_data"), list) else []
    if not indicators or not historical_data:
        try:
            rt_stock_info, rt_data, rt_indicators = stock_analysis_service.get_stock_data(symbol, cycle)
            if isinstance(rt_stock_info, dict):
                stock_info = rt_stock_info
            if isinstance(rt_indicators, dict) and rt_indicators:
                indicators = rt_indicators
            if not historical_data:
                historical_data = _history_points_from_dataframe(rt_data)
        except Exception:
            pass
    stock_name = _txt(record.get("stock_name"), _txt(stock_info.get("name"), symbol))
    payload = _build_workbench_analysis_payload(
        code=symbol,
        stock_name=stock_name,
        selected=_normalize_workbench_selected(selected),
        mode=mode,
        cycle=cycle,
        generated_at=_txt(record.get("analysis_date") or record.get("created_at"), _now()),
        stock_info=stock_info,
        indicators=indicators,
        discussion_result=record.get("discussion_result"),
        final_decision=record.get("final_decision") if isinstance(record.get("final_decision"), dict) else {},
        agents_results=record.get("agents_results") if isinstance(record.get("agents_results"), dict) else {},
        historical_data=historical_data,
    )
    payload = _normalize_workbench_payload(
        payload=payload,
        indicators=indicators,
        discussion_result=record.get("discussion_result"),
        final_decision=record.get("final_decision") if isinstance(record.get("final_decision"), dict) else {},
        agents_results=record.get("agents_results") if isinstance(record.get("agents_results"), dict) else {},
    )
    payload["summaryBody"] = payload.get("summaryBody", "").replace("最近一次有效分析时间", "").strip()
    context.set_workbench_analysis(payload)
    return stock_name


def _workbench_analysis_needs_refresh(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    summary_body = _txt(payload.get("summaryBody"))
    if "最近一次有效分析时间" in summary_body:
        return True
    indicators = payload.get("indicators") if isinstance(payload.get("indicators"), list) else []
    if any(_txt(item.get("value")) in {"暂无数据", "暂无判断"} for item in indicators if isinstance(item, dict)):
        return True
    curve = payload.get("curve") if isinstance(payload.get("curve"), list) else []
    return len(curve) == 0


def _snapshot_workbench(context: UIApiContext) -> dict[str, Any]:
    analysis = context.get_workbench_analysis()
    analysis_job = context.get_workbench_analysis_job()
    if analysis and _workbench_analysis_needs_refresh(analysis):
        _hydrate_cached_workbench_analysis(
            context,
            code=_txt(analysis.get("symbol")),
            selected=[item.get("value") for item in analysis.get("analysts", []) if isinstance(item, dict) and item.get("selected")] if isinstance(analysis.get("analysts"), list) else None,
            cycle=_txt(analysis.get("cycle"), "1y"),
            mode=_txt(analysis.get("mode"), "单个分析"),
        )
        analysis = context.get_workbench_analysis()
    if isinstance(analysis_job, dict) and _txt(analysis_job.get("status")) in {"running", "queued"} and isinstance(analysis, dict):
        normalized_job = {
            **analysis_job,
            "status": "completed",
            "title": "分析已完成",
            "message": _txt(analysis_job.get("message"), "分析结果已可查看"),
            "stage": "completed",
            "progress": 100,
            "updatedAt": _now(),
        }
        context.set_workbench_analysis_job(normalized_job)
        analysis_job = normalized_job
    if isinstance(analysis, dict) or isinstance(analysis_job, dict):
        return _gateway_build_workbench_snapshot(context, analysis=analysis, analysis_job=analysis_job)
    return _gateway_snapshot_workbench(context)




def _snapshot_portfolio(
    context: UIApiContext,
    *,
    selected_symbol: str | None = None,
    indicator_overrides: dict[str, dict[str, Any]] | None = None,
    analysis_job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manager = context.portfolio_manager()
    latest_rows = manager.get_all_latest_analysis()
    summary = context.portfolio().get_account_summary()
    runtime_entries = load_stock_runtime_entries(base_dir=context.selector_result_dir)

    rows: list[dict[str, Any]] = []
    latest_by_symbol: dict[str, dict[str, Any]] = {}
    for item in latest_rows:
        code = normalize_stock_code(item.get("code") or item.get("symbol"))
        if not code:
            continue
        runtime = runtime_entries.get(code) if isinstance(runtime_entries, dict) else None
        item_payload = dict(item)
        runtime_name = _txt(runtime.get("stock_name")) if isinstance(runtime, dict) else ""
        runtime_sector = _txt(runtime.get("sector")) if isinstance(runtime, dict) else ""
        runtime_price = _float(runtime.get("latest_price")) if isinstance(runtime, dict) else None
        if runtime_name:
            item_payload["name"] = runtime_name
            item_payload["stock_name"] = runtime_name
        if runtime_sector:
            item_payload["sector"] = runtime_sector
            item_payload["industry"] = runtime_sector
        if runtime_price is not None:
            item_payload["current_price"] = runtime_price

        latest_by_symbol[code] = item_payload
        name = _txt(item_payload.get("name") or item_payload.get("stock_name"), code)
        sector = _txt(item_payload.get("sector") or item_payload.get("industry") or item_payload.get("board") or item_payload.get("所属行业"), "-")
        quantity = _int(item_payload.get("quantity"), 0) or 0
        cost_price = _float(item_payload.get("cost_price"))
        current_price = _float(item_payload.get("current_price"))
        pnl_pct = None
        if current_price is not None and cost_price not in (None, 0):
            pnl_pct = ((current_price - cost_price) / cost_price) * 100
        confidence = _float(item_payload.get("confidence"))
        score = min(max(confidence * 10.0, 0.0), 100.0) if confidence is not None else None
        rows.append(
            {
                "id": code,
                "cells": [
                    code,
                    name,
                    sector,
                    _txt(quantity),
                    _num(cost_price),
                    _num((item_payload.get("take_profit") if item_payload.get("take_profit") is not None else item_payload.get("analysis_take_profit")), default="--"),
                    _num((item_payload.get("stop_loss") if item_payload.get("stop_loss") is not None else item_payload.get("analysis_stop_loss")), default="--"),
                    _num(current_price),
                    _pct(pnl_pct),
                    _num(score, digits=0, default="--"),
                ],
                "actions": [{"label": "详情", "icon": "🔎", "tone": "accent", "action": "view-detail"}],
                "code": code,
                "name": name,
                "industry": sector,
            }
        )

    selected = normalize_stock_code(selected_symbol)
    if not selected and rows:
        selected = _txt(rows[0].get("code"))
    selected_item = latest_by_symbol.get(selected) if selected else None

    technical = {}
    if selected:
        if indicator_overrides and isinstance(indicator_overrides.get(selected), dict):
            technical = indicator_overrides[selected]
        else:
            technical = _portfolio_technical_snapshot(selected, cycle="1y")

    history = None
    if selected_item:
        stock_id = _int(selected_item.get("id"))
        if stock_id is not None:
            history = manager.get_latest_analysis(stock_id)

    detail = {
        "symbol": selected,
        "stockName": _txt(
            technical.get("stockName"),
            _txt(selected_item.get("name") if selected_item else "", selected),
        ),
        "sector": _txt(
            selected_item.get("sector") if selected_item else technical.get("sector"),
            _txt(technical.get("sector"), "-"),
        ),
        "kline": technical.get("kline") if isinstance(technical.get("kline"), list) else [],
        "indicators": technical.get("indicators") if isinstance(technical.get("indicators"), list) else [],
        "pendingSignals": _table(
            ["时间", "代码", "动作", "策略", "状态", "依据"],
            _portfolio_pending_signal_rows(context, selected) if selected else [],
            "暂无待执行信号",
        ),
        "decision": {
            "rating": _txt(
                (selected_item or {}).get("rating"),
                "持有",
            ),
            "summary": _txt((history or {}).get("summary"), "可点击“实时分析”获取最新结论。"),
            "updatedAt": _txt((selected_item or {}).get("analysis_time"), "--"),
        },
        "positionForm": {
            "quantity": _txt((selected_item or {}).get("quantity"), "0"),
            "costPrice": _num((selected_item or {}).get("cost_price")),
            "takeProfit": _num((selected_item or {}).get("take_profit") if (selected_item or {}).get("take_profit") is not None else (selected_item or {}).get("analysis_take_profit")),
            "stopLoss": _num((selected_item or {}).get("stop_loss") if (selected_item or {}).get("stop_loss") is not None else (selected_item or {}).get("analysis_stop_loss")),
            "note": _txt((selected_item or {}).get("note")),
        },
    }
    portfolio_decision = _build_portfolio_adjustment_summary(latest_rows if isinstance(latest_rows, list) else [])
    market_news = _load_market_focus_news(context, limit=8)

    return {
        "updatedAt": _now(),
        "metrics": [
            _metric("当前持仓", len(rows)),
            _metric("组合收益", _pct(summary.get("total_return_pct"))),
            _metric("最大回撤", _pct(summary.get("max_drawdown_pct"))),
            _metric("可用现金", _num(summary.get("available_cash"))),
        ],
        "holdings": _table(["代码", "名称", "板块", "持仓数量", "成本", "止盈价", "止损价", "现价", "浮盈亏", "分数"], rows, "暂无持仓"),
        "selectedSymbol": selected,
        "detail": detail,
        "attribution": [],
        "curve": detail["kline"],
        "actions": ["实时分析仓位", "刷新技术指标", "更新持仓信息"],
        "portfolioDecision": portfolio_decision,
        "marketNews": market_news,
        "portfolioAnalysisJob": portfolio_rebalance_task_manager.job_view(
            analysis_job or portfolio_rebalance_task_manager.latest_task(),
            txt=_txt,
            int_fn=_int,
        ),
    }


def _snapshot_live_sim(context: UIApiContext) -> dict[str, Any]:
    db = context.quant_db()
    scheduler = context.scheduler().get_status()
    account = db.get_account_summary()
    strategy_profiles = [
        {
            "id": _txt(item.get("id")),
            "name": _txt(item.get("name") or item.get("id")),
            "enabled": bool(item.get("enabled", True)),
            "isDefault": bool(item.get("is_default", False)),
        }
        for item in db.list_strategy_profiles(include_disabled=False)
    ]
    return {
        "updatedAt": _now(),
        "config": {
            "interval": f"{scheduler.get('interval_minutes', 0)} 分钟",
            "timeframe": _txt(scheduler.get("analysis_timeframe"), "30m"),
            "strategyMode": _txt(scheduler.get("strategy_mode"), "auto"),
            "strategyProfileId": _txt(scheduler.get("strategy_profile_id")),
            "aiDynamicStrategy": _txt(scheduler.get("ai_dynamic_strategy"), DEFAULT_AI_DYNAMIC_STRATEGY),
            "aiDynamicStrength": _txt(scheduler.get("ai_dynamic_strength"), f"{DEFAULT_AI_DYNAMIC_STRENGTH:.2f}"),
            "aiDynamicLookback": _txt(scheduler.get("ai_dynamic_lookback"), str(DEFAULT_AI_DYNAMIC_LOOKBACK)),
            "strategyProfiles": strategy_profiles,
            "autoExecute": "开启" if scheduler.get("auto_execute") else "关闭",
            "market": _txt(scheduler.get("market"), "CN"),
            "initialCapital": _txt(account.get("initial_cash"), "0"),
            "commissionRatePct": _fee_rate_pct_text(scheduler.get("commission_rate"), DEFAULT_COMMISSION_RATE),
            "sellTaxRatePct": _fee_rate_pct_text(scheduler.get("sell_tax_rate"), DEFAULT_SELL_TAX_RATE),
        },
        "status": {
            "running": "运行中" if scheduler.get("running") else "已停止",
            "lastRun": _txt(scheduler.get("last_run_at"), "--"),
            "nextRun": _txt(scheduler.get("next_run"), "--"),
            "candidateCount": _txt(len(context.candidate_pool().list_candidates(status="active")), "0"),
        },
        "metrics": [
            _metric("账户结果", account.get("total_equity", 0)),
            _metric("当前持仓", account.get("position_count", 0)),
            _metric("总收益率", _pct(account.get("total_return_pct"))),
            _metric("可用现金", account.get("available_cash")),
        ],
        "candidatePool": _table(
            ["股票代码", "股票名称", "来源", "最新价格"],
            _candidate_rows(context, status="active", include_actions=True),
            "暂无候选股票",
        ),
        "pendingSignals": [
            _insight(
                _txt(item.get("stock_name") or item.get("stock_code") or "待执行信号"),
                _txt(item.get("reasoning") or item.get("execution_note") or "待处理"),
                "warning" if _txt(item.get("action")) in {"BUY", "SELL"} else "neutral",
            )
            for item in db.get_pending_signals()
        ],
        "executionCenter": {
            "title": "执行中心",
            "body": "待执行信号会放在最上方，重点解释为什么成交、为什么跳过。",
            "chips": ["待执行", "信号列表", "详情"],
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
                        _pct(item.get("unrealized_pnl_pct")),
                    ],
                    "code": _txt(item.get("stock_code")),
                    "name": _txt(item.get("stock_name")),
                    "actions": [{"label": "删除", "icon": "🗑", "tone": "danger", "action": "delete-position"}],
                }
                for i, item in enumerate(db.get_positions())
            ],
            "暂无持仓",
        ),
        "trades": _table(
            ["时间", "代码", "动作", "数量", "价格", "备注"],
            [
                {
                    "id": _txt(item.get("id"), str(i)),
                    "cells": [
                        _txt(item.get("executed_at") or item.get("created_at"), "--"),
                        _txt(item.get("stock_code")),
                        _txt(item.get("action")),
                        _txt(item.get("quantity"), "0"),
                        _num(item.get("price")),
                        _txt(item.get("note") or "自动执行"),
                    ],
                    "code": _txt(item.get("stock_code")),
                    "name": _txt(item.get("stock_name")),
                }
                for i, item in enumerate(db.get_trade_history(limit=50))
            ],
            "暂无交易记录",
        ),
        "curve": [
            {"label": _txt(item.get("created_at"), str(i)), "value": float(item.get("total_equity") or 0)}
            for i, item in enumerate(db.get_account_snapshots(limit=20))
        ],
    }


def _snapshot_his_replay(context: UIApiContext) -> dict[str, Any]:
    db = context.quant_db()
    scheduler_status = context.scheduler().get_status()
    strategy_profiles = [
        {
            "id": _txt(item.get("id")),
            "name": _txt(item.get("name") or item.get("id")),
            "enabled": bool(item.get("enabled", True)),
            "isDefault": bool(item.get("is_default", False)),
        }
        for item in db.list_strategy_profiles(include_disabled=False)
    ]
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
                "strategyProfileId": _txt(scheduler_status.get("strategy_profile_id")),
                "aiDynamicStrategy": _txt(scheduler_status.get("ai_dynamic_strategy"), DEFAULT_AI_DYNAMIC_STRATEGY),
                "aiDynamicStrength": _txt(scheduler_status.get("ai_dynamic_strength"), f"{DEFAULT_AI_DYNAMIC_STRENGTH:.2f}"),
                "aiDynamicLookback": _txt(scheduler_status.get("ai_dynamic_lookback"), str(DEFAULT_AI_DYNAMIC_LOOKBACK)),
                "strategyProfiles": strategy_profiles,
                "commissionRatePct": _fee_rate_pct_text(scheduler_status.get("commission_rate"), DEFAULT_COMMISSION_RATE),
                "sellTaxRatePct": _fee_rate_pct_text(scheduler_status.get("sell_tax_rate"), DEFAULT_SELL_TAX_RATE),
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
                "strategyProfileId": _txt(item.get("selected_strategy_profile_id")),
                "strategyProfileName": _txt(item.get("selected_strategy_profile_name")),
                "strategyProfileVersionId": _txt(item.get("selected_strategy_profile_version_id")),
                "holdings": position_rows,
            }
        )

    run_metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    replay_commission_rate = _normalize_fee_rate(
        run_metadata.get("commission_rate"),
        _normalize_fee_rate(scheduler_status.get("commission_rate"), DEFAULT_COMMISSION_RATE),
    )
    replay_sell_tax_rate = _normalize_fee_rate(
        run_metadata.get("sell_tax_rate"),
        _normalize_fee_rate(scheduler_status.get("sell_tax_rate"), DEFAULT_SELL_TAX_RATE),
    )
    replay_ai_dynamic_strategy = _txt(
        run_metadata.get("ai_dynamic_strategy"),
        _txt(scheduler_status.get("ai_dynamic_strategy"), DEFAULT_AI_DYNAMIC_STRATEGY),
    )
    replay_ai_dynamic_strength = _txt(
        run_metadata.get("ai_dynamic_strength"),
        _txt(scheduler_status.get("ai_dynamic_strength"), f"{DEFAULT_AI_DYNAMIC_STRENGTH:.2f}"),
    )
    replay_ai_dynamic_lookback = _txt(
        run_metadata.get("ai_dynamic_lookback"),
        _txt(scheduler_status.get("ai_dynamic_lookback"), str(DEFAULT_AI_DYNAMIC_LOOKBACK)),
    )

    return {
        "updatedAt": _now(),
        "config": {
            "mode": _txt(run.get("mode"), "historical_range"),
            "range": f"{_txt(run.get('start_datetime'), '--')} -> {_txt(run.get('end_datetime'), 'now')}",
            "timeframe": _txt(run.get("timeframe"), "30m"),
            "market": _txt(run.get("market"), "CN"),
            "strategyMode": _txt(run.get("selected_strategy_mode") or run.get("strategy_mode"), "auto"),
            "strategyProfileId": _txt(run.get("selected_strategy_profile_id"), _txt(scheduler_status.get("strategy_profile_id"))),
            "aiDynamicStrategy": replay_ai_dynamic_strategy,
            "aiDynamicStrength": replay_ai_dynamic_strength,
            "aiDynamicLookback": replay_ai_dynamic_lookback,
            "strategyProfiles": strategy_profiles,
            "commissionRatePct": _fee_rate_pct_text(replay_commission_rate, DEFAULT_COMMISSION_RATE),
            "sellTaxRatePct": _fee_rate_pct_text(replay_sell_tax_rate, DEFAULT_SELL_TAX_RATE),
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


def _profile_summary_text(value: Any, default: str = "--") -> str:
    if not isinstance(value, dict):
        return _txt(value, default)
    label = _txt(
        value.get("label")
        or value.get("标签")
        or value.get("tag")
        or value.get("name")
        or value.get("key")
        or value.get("value")
    )
    score = _txt(value.get("score") or value.get("信号分"))
    reason = _txt(value.get("reason") or value.get("说明") or value.get("detail"))
    segments: list[str] = []
    if label:
        segments.append(label)
    if score:
        segments.append(f"score={score}")
    if reason:
        segments.append(reason)
    if not segments:
        return default
    return " | ".join(segments)


def _normalize_profile_label(profile_id: str, profile_name: str) -> str:
    name = _txt(profile_name)
    if name and name != "--":
        return name
    pid = _txt(profile_id)
    if not pid or pid == "--":
        return "--"
    pid = re.sub(r"_v\d+(?:\.\d+)?$", "", pid, flags=re.IGNORECASE)
    return pid


def _to_vote_row(item: Any, default_signal: str = "") -> dict[str, str]:
    if not isinstance(item, dict):
        return {"factor": _txt(item), "signal": default_signal, "score": "", "reason": ""}
    return {
        "factor": _txt(item.get("factor") or item.get("component") or item.get("name") or item.get("title")),
        "signal": _txt(item.get("signal") or item.get("vote") or item.get("decision"), default_signal),
        "score": _txt(item.get("score") or item.get("confidence")),
        "reason": _txt(item.get("reason") or item.get("note") or item.get("detail")),
    }


def _extract_technical_indicators(
    *,
    tech_votes: list[dict[str, Any]],
    context_votes: list[dict[str, Any]],
    reasoning: str,
    analysis_text: str = "",
    strategy_profile: dict[str, Any] | None = None,
    technical_breakdown: dict[str, Any] | None = None,
    context_breakdown: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    if isinstance(technical_breakdown, dict):
        indicators: list[dict[str, str]] = []
        track_info = technical_breakdown.get("track") if isinstance(technical_breakdown.get("track"), dict) else {}
        indicators.append(
            {
                "name": "technical.track.score",
                "value": _txt(track_info.get("score"), "0"),
                "source": "technical_breakdown.track",
                "note": "技术轨总分（TrackScore）",
            }
        )
        indicators.append(
            {
                "name": "technical.track.confidence",
                "value": _txt(track_info.get("confidence"), "0"),
                "source": "technical_breakdown.track",
                "note": "技术轨置信度（TrackConfidence）",
            }
        )

        group_rows = technical_breakdown.get("groups")
        if isinstance(group_rows, list):
            for item in group_rows:
                if not isinstance(item, dict):
                    continue
                gid = _txt(item.get("id"), "group")
                indicators.append(
                    {
                        "name": f"technical.group.{gid}",
                        "value": _txt(item.get("score"), "0"),
                        "source": "technical_breakdown.groups",
                        "note": f"coverage={_txt(item.get('coverage'), '--')}; weight_norm={_txt(item.get('weight_norm_in_track'), '--')}; track_contribution={_txt(item.get('track_contribution'), '--')}",
                    }
                )

        dim_rows = technical_breakdown.get("dimensions")
        if isinstance(dim_rows, list):
            for item in dim_rows:
                if not isinstance(item, dict):
                    continue
                dim_id = _txt(item.get("id"), "dimension")
                indicators.append(
                    {
                        "name": dim_id,
                        "value": _txt(item.get("score"), "0"),
                        "source": "technical_breakdown.dimensions",
                        "note": f"group={_txt(item.get('group'), '--')}; weight_raw={_txt(item.get('weight_raw'), '--')}; w_norm={_txt(item.get('weight_norm_in_group'), '--')}; group_contribution={_txt(item.get('group_contribution'), '--')}; track_contribution={_txt(item.get('track_contribution'), '--')}; reason={_txt(item.get('reason'), '--')}",
                    }
                )

        if isinstance(context_breakdown, dict):
            ctx_track = context_breakdown.get("track") if isinstance(context_breakdown.get("track"), dict) else {}
            indicators.append(
                {
                    "name": "context.track.score",
                    "value": _txt(ctx_track.get("score"), "0"),
                    "source": "context_breakdown.track",
                    "note": "环境轨总分（TrackScore）",
                }
            )
            indicators.append(
                {
                    "name": "context.track.confidence",
                    "value": _txt(ctx_track.get("confidence"), "0"),
                    "source": "context_breakdown.track",
                    "note": "环境轨置信度（TrackConfidence）",
                }
            )

        return indicators

    patterns = [
        ("现价", r"现价\s*(-?\d+(?:\.\d+)?)"),
        ("现价", r"价格\s*(-?\d+(?:\.\d+)?)"),
        ("成本", r"成本\s*(-?\d+(?:\.\d+)?)"),
        ("MA5", r"MA5\s*(-?\d+(?:\.\d+)?)"),
        ("MA10", r"MA10\s*(-?\d+(?:\.\d+)?)"),
        ("MA20", r"MA20\s*(-?\d+(?:\.\d+)?)"),
        ("MA60", r"MA60\s*(-?\d+(?:\.\d+)?)"),
        ("MACD", r"MACD\s*(-?\d+(?:\.\d+)?)"),
        ("RSI12", r"RSI12\s*(-?\d+(?:\.\d+)?)"),
        ("量比", r"量比\s*(-?\d+(?:\.\d+)?)"),
        ("成交量", r"成交量\s*[:：]?\s*([-\d,.]+(?:亿|万)?(?:手|股)?)"),
        ("5日均量", r"(?:5日均量|五日均量|VOL5|Volume_MA5)\s*[:：]?\s*([-\d,.]+(?:亿|万)?(?:手|股)?)"),
        ("换手率", r"换手率\s*[:：]?\s*(-?\d+(?:\.\d+)?)%?"),
        ("成交额", r"成交额\s*[:：]?\s*([-\d,.]+(?:亿|万)?(?:元)?)"),
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

    def _scan_text(text: str, source: str, note: str = "") -> None:
        content = _txt(text)
        if not content:
            return
        for metric, pattern in patterns:
            matched = re.search(pattern, content)
            if not matched:
                continue
            value = _txt(matched.group(1))
            if metric in {"浮盈亏", "换手率"} and value and not value.endswith("%"):
                value = f"{value}%"
            _add_indicator(metric, value, source, note or content)

    for vote in tech_votes:
        if not isinstance(vote, dict):
            continue
        factor = _txt(vote.get("factor") or vote.get("name"))
        score_text = _txt(vote.get("score"))
        reason = _txt(vote.get("reason"))
        if factor and score_text:
            _add_indicator(f"{factor}打分", score_text, "tech_vote", reason)
        _scan_text(reason, "tech_vote_reason", reason)

    for vote in context_votes:
        if not isinstance(vote, dict):
            continue
        component = _txt(vote.get("component") or vote.get("factor") or vote.get("name"))
        score_text = _txt(vote.get("score"))
        reason = _txt(vote.get("reason") or vote.get("note") or vote.get("detail"))
        if component.lower() in {"liquidity", "volume", "volume_flow"} and score_text:
            _add_indicator("流动性打分", score_text, "context_vote", reason)
        _scan_text(reason, "context_vote_reason", reason)

    _scan_text(_txt(reasoning), "reasoning")
    _scan_text(_txt(analysis_text), "analysis")

    profile = strategy_profile if isinstance(strategy_profile, dict) else {}
    market_regime = profile.get("market_regime")
    if isinstance(market_regime, dict):
        _scan_text(_txt(market_regime.get("reason")), "strategy_profile")
    for key in ("risk_style", "auto_inferred_risk_style", "analysis_timeframe"):
        item = profile.get(key)
        if isinstance(item, dict):
            _scan_text(_txt(item.get("reason")), "strategy_profile")

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
    explainability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    explain_obj = explainability if isinstance(explainability, dict) else {}
    if not _is_structured_explainability(explain_obj):
        raise HTTPException(status_code=422, detail="Signal explanation requires structured explainability payload")

    technical_breakdown = _safe_json_load(explain_obj.get("technical_breakdown"))
    context_breakdown = _safe_json_load(explain_obj.get("context_breakdown"))
    fusion_breakdown = _safe_json_load(explain_obj.get("fusion_breakdown"))
    decision_path = explain_obj.get("decision_path") if isinstance(explain_obj.get("decision_path"), list) else []
    vetoes = explain_obj.get("vetoes") if isinstance(explain_obj.get("vetoes"), list) else []

    tech_track = _safe_json_load(technical_breakdown.get("track"))
    context_track = _safe_json_load(context_breakdown.get("track"))
    tech_groups = technical_breakdown.get("groups") if isinstance(technical_breakdown.get("groups"), list) else []
    context_groups = context_breakdown.get("groups") if isinstance(context_breakdown.get("groups"), list) else []
    tech_dims = technical_breakdown.get("dimensions") if isinstance(technical_breakdown.get("dimensions"), list) else []
    context_dims = context_breakdown.get("dimensions") if isinstance(context_breakdown.get("dimensions"), list) else []

    mode = _txt(fusion_breakdown.get("mode"), _txt(decision.get("strategyMode"), "--"))
    weighted_threshold_action = _txt(fusion_breakdown.get("weighted_threshold_action"), "--")
    weighted_action_raw = _txt(fusion_breakdown.get("weighted_action_raw"), "--")
    core_rule_action = _txt(fusion_breakdown.get("core_rule_action"), "--")
    final_action = _txt(fusion_breakdown.get("final_action"), _txt(decision.get("finalAction"), "--"))
    gate_fail_reasons = fusion_breakdown.get("weighted_gate_fail_reasons") if isinstance(
        fusion_breakdown.get("weighted_gate_fail_reasons"), list
    ) else []

    tech_score = _txt(fusion_breakdown.get("tech_score"), _txt(tech_track.get("score"), _txt(decision.get("techScore"), "0")))
    context_score = _txt(
        fusion_breakdown.get("context_score"),
        _txt(context_track.get("score"), _txt(decision.get("contextScore"), "0")),
    )
    fusion_score = _txt(fusion_breakdown.get("fusion_score"), "--")
    tech_conf = _txt(fusion_breakdown.get("tech_confidence"), _txt(tech_track.get("confidence"), "--"))
    context_conf = _txt(fusion_breakdown.get("context_confidence"), _txt(context_track.get("confidence"), "--"))
    fusion_conf = _txt(fusion_breakdown.get("fusion_confidence"), _txt(decision.get("confidence"), "--"))
    divergence = _txt(fusion_breakdown.get("divergence"), "--")
    divergence_penalty = _txt(fusion_breakdown.get("divergence_penalty"), "--")
    sign_conflict = _txt(fusion_breakdown.get("sign_conflict"), "--")

    tech_weight_raw = _txt(fusion_breakdown.get("tech_weight_raw"), "--")
    tech_weight_norm = _txt(fusion_breakdown.get("tech_weight_norm"), "--")
    context_weight_raw = _txt(fusion_breakdown.get("context_weight_raw"), "--")
    context_weight_norm = _txt(fusion_breakdown.get("context_weight_norm"), "--")

    tech_group_lines: list[str] = []
    for group in tech_groups:
        if not isinstance(group, dict):
            continue
        tech_group_lines.append(
            "技术组 "
            + _txt(group.get("id"), "--")
            + f": score={_txt(group.get('score'), '--')}, coverage={_txt(group.get('coverage'), '--')}, "
            + f"weight_raw={_txt(group.get('weight_raw'), '--')}, weight_norm={_txt(group.get('weight_norm_in_track'), '--')}, "
            + f"track_contribution={_txt(group.get('track_contribution'), '--')}"
        )

    context_group_lines: list[str] = []
    for group in context_groups:
        if not isinstance(group, dict):
            continue
        context_group_lines.append(
            "环境组 "
            + _txt(group.get("id"), "--")
            + f": score={_txt(group.get('score'), '--')}, coverage={_txt(group.get('coverage'), '--')}, "
            + f"weight_raw={_txt(group.get('weight_raw'), '--')}, weight_norm={_txt(group.get('weight_norm_in_track'), '--')}, "
            + f"track_contribution={_txt(group.get('track_contribution'), '--')}"
        )

    top_tech_dims = sorted(
        [item for item in tech_dims if isinstance(item, dict)],
        key=lambda item: abs(_float(item.get("track_contribution"), _float(item.get("group_contribution"), _float(item.get("score"), 0.0))) or 0.0),
        reverse=True,
    )[:6]
    top_context_dims = sorted(
        [item for item in context_dims if isinstance(item, dict)],
        key=lambda item: abs(_float(item.get("track_contribution"), _float(item.get("group_contribution"), _float(item.get("score"), 0.0))) or 0.0),
        reverse=True,
    )[:6]

    tech_evidence = [
        "技术维度 "
        + _txt(item.get("id"), "--")
        + f"（组={_txt(item.get('group'), '--')}）: score={_txt(item.get('score'), '--')}, "
        + f"group_contribution={_txt(item.get('group_contribution'), '--')}, track_contribution={_txt(item.get('track_contribution'), '--')} · "
        + _txt(item.get("reason"), "--")
        for item in top_tech_dims
    ]
    context_evidence = [
        "环境维度 "
        + _txt(item.get("id"), "--")
        + f"（组={_txt(item.get('group'), '--')}）: score={_txt(item.get('score'), '--')}, "
        + f"group_contribution={_txt(item.get('group_contribution'), '--')}, track_contribution={_txt(item.get('track_contribution'), '--')} · "
        + _txt(item.get("reason"), "--")
        for item in top_context_dims
    ]

    threshold_lines = [f"{_txt(k)}={_txt(v)}" for k, v in effective_thresholds.items() if _txt(k)]
    decision_path_lines = []
    for item in decision_path:
        if not isinstance(item, dict):
            continue
        decision_path_lines.append(
            _txt(item.get("step"), "--")
            + f": matched={_txt(item.get('matched'), '--')}"
            + f", detail={_txt(item.get('detail'), '--')}"
        )
    veto_lines = []
    for item in vetoes:
        if not isinstance(item, dict):
            continue
        veto_lines.append(
            _txt(item.get("id"), "veto")
            + f": action={_txt(item.get('action'), '--')}, reason={_txt(item.get('reason'), '--')}, priority={_txt(item.get('priority'), '--')}"
        )

    summary_lines = [
        f"本次信号采用结构化双轨算法，模式 {mode}。最终动作 {final_action}，融合分 {fusion_score}，融合置信度 {fusion_conf}。",
        f"策略模板：配置={_txt(decision.get('configuredProfile'), '--')}，应用={_txt(decision.get('appliedProfile'), '--')}，AI动态={_txt(decision.get('aiDynamicStrategy'), '--')}。"
        + (
            "（本次发生模板切换）"
            if _txt(decision.get("aiProfileSwitched"), "").lower() in {"1", "true", "yes", "是"}
            else ""
        ),
        f"技术轨 score/confidence={tech_score}/{tech_conf}；环境轨 score/confidence={context_score}/{context_conf}。",
        f"动作链路：core_rule={core_rule_action} -> weighted_threshold={weighted_threshold_action} -> weighted_gate={weighted_action_raw} -> final={final_action}。",
    ]
    if gate_fail_reasons:
        summary_lines.append("加权门控未通过原因: " + " | ".join(_txt(item, "--") for item in gate_fail_reasons))
    if veto_lines:
        summary_lines.append("否决命中: " + " | ".join(veto_lines))

    basis = [
        f"决策点: {_txt(decision.get('checkpointAt'), '--')}",
        f"轨道权重: 技术轨 raw={tech_weight_raw}, norm={tech_weight_norm}; 环境轨 raw={context_weight_raw}, norm={context_weight_norm}",
        f"融合参数: divergence={divergence}, divergence_penalty={divergence_penalty}, sign_conflict={sign_conflict}",
        f"阈值: buy={_txt(fusion_breakdown.get('buy_threshold_eff'), '--')} (base={_txt(fusion_breakdown.get('buy_threshold_base'), '--')}), "
        + f"sell={_txt(fusion_breakdown.get('sell_threshold_eff'), '--')} (base={_txt(fusion_breakdown.get('sell_threshold_base'), '--')}), "
        + f"sell_precedence_gate={_txt(fusion_breakdown.get('sell_precedence_gate'), '--')}, mode={_txt(fusion_breakdown.get('threshold_mode'), '--')}",
        *tech_group_lines,
        *context_group_lines,
        *decision_path_lines,
        *veto_lines,
        f"最终理由: {_txt(decision.get('finalReason') or reasoning_text, '--')}",
    ]

    context_component_breakdown = [
        f"{_txt(item.get('id'), '--')}: track_contribution={_txt(item.get('track_contribution'), '--')} · {_txt(item.get('reason'), '--')}"
        for item in top_context_dims
    ]
    context_component_sum = 0.0
    for group in context_groups:
        if not isinstance(group, dict):
            continue
        context_component_sum += _float(group.get("track_contribution"), 0.0) or 0.0

    return {
        "summary": "\n".join(summary_lines),
        "contextScoreExplain": {
            "formula": "环境轨分值 = Σ(组权重归一化 × 组分值)，组分值=Σ(组内维度归一化权重 × 维度分)，并截断到 [-1, 1]。",
            "confidenceFormula": "环境轨置信度 = Σ(组权重 × 组覆盖率)/Σ组权重；融合置信度 = base_confidence × (1 - divergence_penalty)。",
            "componentBreakdown": context_component_breakdown,
            "componentSum": round(context_component_sum, 6),
            "finalScore": _txt(context_score, _txt(decision.get("contextScore"), "0")),
        },
        "basis": basis,
        "techEvidence": tech_evidence,
        "contextEvidence": context_evidence,
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
    explainability: dict[str, Any] | None = None,
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

    explain_obj = explainability if isinstance(explainability, dict) else {}
    if _is_structured_explainability(explain_obj):
        technical_breakdown = _safe_json_load(explain_obj.get("technical_breakdown"))
        context_breakdown = _safe_json_load(explain_obj.get("context_breakdown"))
        tech_track = _safe_json_load(technical_breakdown.get("track"))
        context_track = _safe_json_load(context_breakdown.get("track"))
        tech_group_lines = []
        for item in technical_breakdown.get("groups") if isinstance(technical_breakdown.get("groups"), list) else []:
            if not isinstance(item, dict):
                continue
            tech_group_lines.append(
                f"{_txt(item.get('id'), '--')}: score={_txt(item.get('score'), '--')}, "
                f"weight_norm={_txt(item.get('weight_norm_in_track'), '--')}, track_contribution={_txt(item.get('track_contribution'), '--')}"
            )
        context_group_lines = []
        for item in context_breakdown.get("groups") if isinstance(context_breakdown.get("groups"), list) else []:
            if not isinstance(item, dict):
                continue
            context_group_lines.append(
                f"{_txt(item.get('id'), '--')}: score={_txt(item.get('score'), '--')}, "
                f"weight_norm={_txt(item.get('weight_norm_in_track'), '--')}, track_contribution={_txt(item.get('track_contribution'), '--')}"
            )
        return {
            "voterCount": len(rows),
            "technicalVoterCount": tech_count,
            "contextVoterCount": context_count,
            "formula": "结构化聚合：组内维度归一化 -> 轨内组权重归一化 -> 双轨融合；表格贡献分优先展示 track_contribution。",
            "technicalAggregation": (
                f"技术轨 score={_txt(tech_track.get('score'), '--')}, confidence={_txt(tech_track.get('confidence'), '--')}"
                + (f"；组明细: {' | '.join(tech_group_lines)}" if tech_group_lines else "")
            ),
            "contextAggregation": (
                f"环境轨 score={_txt(context_track.get('score'), '--')}, confidence={_txt(context_track.get('confidence'), '--')}"
                + (f"；组明细: {' | '.join(context_group_lines)}" if context_group_lines else "")
            ),
            "rows": rows,
        }

    raise HTTPException(status_code=422, detail="Vote overview requires structured explainability payload")


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

    if metric_name == "成交量":
        avg_volume = metric_values.get("5日均量")
        if metric_value is None:
            return "成交量是当前周期真实成交规模，用于验证价格信号是否有资金参与。"
        if avg_volume is None or avg_volume == 0:
            return "成交量用于验证价格动作的资金参与强度，需配合均量或量比判断。"
        ratio = metric_value / avg_volume
        if ratio >= 1.5:
            return f"成交量约为5日均量的 {ratio:.2f} 倍，属于放量，信号可信度更高。"
        if ratio <= 0.8:
            return f"成交量约为5日均量的 {ratio:.2f} 倍，属于缩量，趋势延续需谨慎。"
        return f"成交量约为5日均量的 {ratio:.2f} 倍，量能处于常态区间。"

    if metric_name in {"5日均量", "五日均量", "VOL5"}:
        return "5日均量用于给当前成交量提供基准，判断是放量突破还是缩量震荡。"

    if metric_name == "换手率":
        if metric_value is None:
            return "换手率用于衡量筹码交换强度和交易拥挤程度。"
        if metric_value >= 8:
            return f"换手率={metric_value:.2f}% 偏高，资金博弈激烈，波动风险同步升高。"
        if metric_value <= 1:
            return f"换手率={metric_value:.2f}% 偏低，流动性一般，趋势推进通常较慢。"
        return f"换手率={metric_value:.2f}% 处于常态区间。"

    if metric_name == "成交额":
        if metric_value is None:
            return "成交额用于衡量资金绝对规模，常与成交量、换手率联动观察。"
        if metric_value > 0:
            return f"成交额={_txt(value)}，可与历史均值对比判断资金是否持续流入。"
        return "成交额接近 0，说明资金参与度较低。"

    if metric_name == "流动性打分":
        if metric_value is None:
            return "流动性打分来自环境轨，对成交活跃度与可交易性进行量化。"
        if metric_value > 0:
            return f"流动性打分为正({metric_value:+.4f})，说明成交环境支持信号执行。"
        if metric_value < 0:
            return f"流动性打分为负({metric_value:+.4f})，说明成交环境偏弱，执行应更保守。"
        return "流动性打分为中性，对决策影响有限。"

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
    explainability: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    def _item(name: str, value: Any, source: str, derivation: str) -> dict[str, str]:
        return {
            "name": _txt(name),
            "value": _txt(value, "--"),
            "source": _txt(source),
            "derivation": _txt(derivation),
        }

    explain_obj = explainability if isinstance(explainability, dict) else {}
    if _is_structured_explainability(explain_obj):
        technical_breakdown = _safe_json_load(explain_obj.get("technical_breakdown"))
        context_breakdown = _safe_json_load(explain_obj.get("context_breakdown"))
        fusion_breakdown = _safe_json_load(explain_obj.get("fusion_breakdown"))
        decision_path = explain_obj.get("decision_path") if isinstance(explain_obj.get("decision_path"), list) else []
        vetoes = explain_obj.get("vetoes") if isinstance(explain_obj.get("vetoes"), list) else []

        tech_track = _safe_json_load(technical_breakdown.get("track"))
        context_track = _safe_json_load(context_breakdown.get("track"))

        rows: list[dict[str, str]] = [
            _item("动作", decision.get("action"), "fusion_breakdown.final_action", "最终动作来自结构化融合层输出（含 veto/门控/规则合并）。"),
            _item("决策类型", decision.get("decisionType"), "signal.decision_type", "决策类型来自信号记录，用于区分融合路径与执行语义。"),
            _item("核心规则动作", fusion_breakdown.get("core_rule_action"), "fusion_breakdown.core_rule_action", "仅规则引擎输出，不含 veto。"),
            _item("加权阈值动作", fusion_breakdown.get("weighted_threshold_action"), "fusion_breakdown.weighted_threshold_action", "仅由融合分与阈值比较得到的动作。"),
            _item("加权门控后动作", fusion_breakdown.get("weighted_action_raw"), "fusion_breakdown.weighted_action_raw", "在阈值动作基础上应用置信度与分轨门控后的动作。"),
            _item("技术信号", decision.get("techSignal"), "technical_breakdown.track.score", "技术轨信号由技术轨 TrackScore 符号映射：>0 BUY，<0 SELL，=0 HOLD。"),
            _item("环境信号", decision.get("contextSignal"), "context_breakdown.track.score", "环境轨信号由环境轨 TrackScore 符号映射：>0 BUY，<0 SELL，=0 HOLD。"),
            _item("技术分", decision.get("techScore"), "technical_breakdown.track.score", "技术轨分值=Σ(组权重归一化 × 组分值)，组分值=Σ(组内维度归一化权重 × 维度分)。"),
            _item("环境分", decision.get("contextScore"), "context_breakdown.track.score", "环境轨分值=Σ(组权重归一化 × 组分值)，组分值=Σ(组内维度归一化权重 × 维度分)。"),
            _item("技术轨置信度", tech_track.get("confidence"), "technical_breakdown.track.confidence", "技术轨置信度=Σ(组权重 × 组覆盖率)/Σ组权重。"),
            _item("环境轨置信度", context_track.get("confidence"), "context_breakdown.track.confidence", "环境轨置信度=Σ(组权重 × 组覆盖率)/Σ组权重。"),
            _item("融合分", fusion_breakdown.get("fusion_score"), "fusion_breakdown.fusion_score", "融合分=技术轨归一化权重×技术轨分 + 环境轨归一化权重×环境轨分。"),
            _item(
                "融合置信度",
                fusion_breakdown.get("fusion_confidence"),
                "fusion_breakdown.fusion_confidence",
                "融合置信度=base_confidence × (1 - divergence_penalty)，用于 BUY 门控和动作稳定性控制。",
            ),
            _item("仓位建议(%)", decision.get("positionSizePct"), "signal.position_size_pct", "仓位建议由融合动作与风险约束共同决定。"),
            _item(
                "建议保持仓位",
                _derive_keep_position_pct(decision.get("action"), decision.get("positionSizePct")),
                "signal.position_size_pct",
                "BUY 时等于目标买入仓位；SELL 时 = 100% - 建议卖出比例；HOLD 时保持不变。",
            ),
            _item("规则命中", decision.get("ruleHit"), "dual_track.rule_hit", "规则命中来自双轨规则融合结果。"),
            _item("共振类型", decision.get("resonanceType"), "dual_track.resonance_type", "共振类型用于说明双轨是否同向及其强弱。"),
            _item("市场", runtime_context.get("market"), "调度配置/回放任务", "实时模式取 scheduler.market；回放模式取 sim_runs.market。"),
            _item("配置模板", decision.get("configuredProfile"), "sim_scheduler_config.strategy_profile_id", "当前调度配置中的策略模板。"),
            _item("应用模板", decision.get("appliedProfile"), "strategy_profile.selected_strategy_profile", "该条信号实际使用的策略模板（信号快照）。"),
            _item("AI动态策略", decision.get("aiDynamicStrategy"), "sim_scheduler_config.ai_dynamic_strategy", "AI 动态策略开关状态，控制是否允许按市场切换模板/权重。"),
            _item("AI动态强度", decision.get("aiDynamicStrength"), "sim_scheduler_config.ai_dynamic_strength", "AI 动态调整强度（0~1，越大调整越激进）。"),
            _item("AI回看窗口(小时)", decision.get("aiDynamicLookback"), "sim_scheduler_config.ai_dynamic_lookback", "AI 评估市场状态时使用的回看窗口。"),
            _item("AI是否切换模板", decision.get("aiProfileSwitched"), "strategy_profile.selected_strategy_profile", "配置模板与应用模板不一致时为“是”，表示本次触发了动态切换。"),
            _item("分析粒度", runtime_context.get("timeframe"), "调度配置/回放任务/策略配置", "实时模式优先策略粒度，其次 scheduler.analysis_timeframe；回放模式取 sim_runs.timeframe。"),
            _item("策略模式", runtime_context.get("strategyMode"), "调度配置/回放任务/策略配置", "实时模式优先策略模式，其次 scheduler.strategy_mode；回放模式取 sim_runs.selected_strategy_mode。"),
            _item("双轨模式", fusion_breakdown.get("mode"), "fusion_breakdown.mode", "融合模式支持 rule_only / weighted_only / hybrid。"),
            _item("技术轨权重(raw)", fusion_breakdown.get("tech_weight_raw"), "fusion_breakdown.tech_weight_raw", "技术轨原始权重，融合前参数。"),
            _item("环境轨权重(raw)", fusion_breakdown.get("context_weight_raw"), "fusion_breakdown.context_weight_raw", "环境轨原始权重，融合前参数。"),
            _item("技术轨权重(norm)", fusion_breakdown.get("tech_weight_norm"), "fusion_breakdown.tech_weight_norm", "技术轨融合归一化权重。"),
            _item("环境轨权重(norm)", fusion_breakdown.get("context_weight_norm"), "fusion_breakdown.context_weight_norm", "环境轨融合归一化权重。"),
            _item("方向背离度", fusion_breakdown.get("divergence"), "fusion_breakdown.divergence", "双轨分值差异度，用于冲突惩罚计算。"),
            _item("背离惩罚", fusion_breakdown.get("divergence_penalty"), "fusion_breakdown.divergence_penalty", "融合置信度惩罚项，越大代表轨道冲突越强。"),
            _item("方向冲突标记", fusion_breakdown.get("sign_conflict"), "fusion_breakdown.sign_conflict", "技术轨与环境轨符号是否冲突（0/1）。"),
            _item("veto 来源模式", fusion_breakdown.get("veto_source_mode"), "fusion_breakdown.veto_source_mode", "标记 veto 判定来源（如 legacy/new）。"),
        ]

        buy_base = _float(fusion_breakdown.get("buy_threshold_base"))
        buy_eff = _float(fusion_breakdown.get("buy_threshold_eff"))
        if buy_base is not None and buy_eff is not None:
            rows.append(
                _item(
                    "BUY阈值调整",
                    f"{buy_base:.4f} -> {buy_eff:.4f} (Δ{buy_eff - buy_base:+.4f})",
                    "fusion_breakdown.buy_threshold_base/buy_threshold_eff",
                    "显示 BUY 阈值从基础值到生效值的变化（含 AI/波动率策略影响）。",
                )
            )

        sell_base = _float(fusion_breakdown.get("sell_threshold_base"))
        sell_eff = _float(fusion_breakdown.get("sell_threshold_eff"))
        if sell_base is not None and sell_eff is not None:
            rows.append(
                _item(
                    "SELL阈值调整",
                    f"{sell_base:.4f} -> {sell_eff:.4f} (Δ{sell_eff - sell_base:+.4f})",
                    "fusion_breakdown.sell_threshold_base/sell_threshold_eff",
                    "显示 SELL 阈值从基础值到生效值的变化（含 AI/波动率策略影响）。",
                )
            )

        gate_reasons = fusion_breakdown.get("weighted_gate_fail_reasons")
        if isinstance(gate_reasons, list):
            rows.append(
                _item(
                    "加权门控失败原因",
                    " | ".join(_txt(item, "--") for item in gate_reasons) if gate_reasons else "无",
                    "fusion_breakdown.weighted_gate_fail_reasons",
                    "记录 weighted_action_raw 未能通过门控时的失败原因列表。",
                )
            )

        for index, item in enumerate(decision_path):
            if not isinstance(item, dict):
                continue
            step = _txt(item.get("step"), f"step_{index + 1}")
            rows.append(
                _item(
                    f"决策路径.{index + 1}.{step}",
                    _txt(item.get("matched"), "--"),
                    "decision_path",
                    _txt(item.get("detail"), "--"),
                )
            )

        if vetoes:
            for index, item in enumerate(vetoes):
                if not isinstance(item, dict):
                    continue
                rows.append(
                    _item(
                        f"否决.{index + 1}",
                        _txt(item.get("action"), "--"),
                        "vetoes",
                        f"id={_txt(item.get('id'), '--')}; priority={_txt(item.get('priority'), '--')}; reason={_txt(item.get('reason'), '--')}",
                    )
                )
        else:
            rows.append(_item("否决命中", "无", "vetoes", "本次未命中 veto，动作由规则与加权门控链路决定。"))
    else:
        tech_vote_sum = sum((_float(item.get("score"), 0.0) or 0.0) for item in tech_votes_raw if isinstance(item, dict))
        tech_vote_clamped = max(-1.0, min(1.0, tech_vote_sum))
        context_vote_sum = sum((_float(item.get("score"), 0.0) or 0.0) for item in context_votes_raw if isinstance(item, dict))
        context_vote_clamped = max(-1.0, min(1.0, context_vote_sum))

        rows = [
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


def _parse_signal_time(raw: Any) -> datetime | None:
    text = _txt(raw).strip()
    if not text or text == "--":
        return None
    normalized = text.replace("T", " ").replace("Z", "")
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
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
                "decisionTime": _txt(item.get("decision_time"), "--"),
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
                "tradeTime": _txt(item.get("trade_time"), "--"),
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
        "decisionTime": _txt(selected.get("decision_time"), "--"),
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


def _build_signal_detail_payload(
    context: UIApiContext,
    signal: dict[str, Any],
    *,
    source: str,
    replay_run: dict[str, Any] | None = None,
    fetch_realtime_snapshot: bool = False,
) -> dict[str, Any]:
    strategy_profile = _safe_json_load(signal.get("strategy_profile"))
    selected_strategy_profile = _safe_json_load(strategy_profile.get("selected_strategy_profile"))
    explainability = _safe_json_load(strategy_profile.get("explainability"))
    technical_breakdown = _safe_json_load(explainability.get("technical_breakdown"))
    context_breakdown = _safe_json_load(explainability.get("context_breakdown"))
    fusion_breakdown = _safe_json_load(explainability.get("fusion_breakdown"))
    is_structured = _is_structured_explainability(explainability)
    if not is_structured:
        raise HTTPException(
            status_code=422,
            detail=(
                "Signal detail requires structured explainability schema; "
                f"signal_id={_txt(signal.get('id'), '--')}"
            ),
        )
    dual_track = _safe_json_load(explainability.get("dual_track"))
    tech_votes_raw = _build_structured_vote_rows(technical_breakdown, track="technical")
    context_votes_raw = _build_structured_vote_rows(context_breakdown, track="context")
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

    scheduler_cfg = context.quant_db().get_scheduler_config()
    configured_profile_id = _txt(scheduler_cfg.get("strategy_profile_id"), "--")
    configured_profile_name = "--"
    if configured_profile_id and configured_profile_id != "--":
        configured_profile = context.quant_db().get_strategy_profile(configured_profile_id) or {}
        configured_profile_name = _txt(configured_profile.get("name"), configured_profile_id)

    applied_profile_id = _txt(selected_strategy_profile.get("id"), "")
    applied_profile_name = _txt(selected_strategy_profile.get("name"), "")
    applied_profile_version = _txt(selected_strategy_profile.get("version"), "")
    if not applied_profile_id:
        applied_profile_id = configured_profile_id
    if not applied_profile_name:
        applied_profile_name = configured_profile_name
    ai_profile_switched = bool(
        configured_profile_id
        and configured_profile_id != "--"
        and applied_profile_id
        and applied_profile_id != "--"
        and applied_profile_id != configured_profile_id
    )
    ai_dynamic_strategy = _txt(scheduler_cfg.get("ai_dynamic_strategy"), "off")
    ai_dynamic_strength = _txt(scheduler_cfg.get("ai_dynamic_strength"), "--")
    ai_dynamic_lookback = _txt(scheduler_cfg.get("ai_dynamic_lookback"), "--")
    configured_profile_label = _normalize_profile_label(configured_profile_id, configured_profile_name)
    applied_profile_label = _normalize_profile_label(applied_profile_id, applied_profile_name)
    applied_profile_version_text = (
        f"版本 {applied_profile_version}"
        if applied_profile_version and applied_profile_version != "--"
        else ""
    )

    tech_track = _safe_json_load(technical_breakdown.get("track"))
    context_track = _safe_json_load(context_breakdown.get("track"))
    tech_score_value = _txt(
        fusion_breakdown.get("tech_score"),
        _txt(tech_track.get("score"), _txt(signal.get("tech_score"), "0")),
    )
    context_score_value = _txt(
        fusion_breakdown.get("context_score"),
        _txt(context_track.get("score"), _txt(signal.get("context_score"), "0")),
    )
    confidence_value = _txt(fusion_breakdown.get("fusion_confidence"), _txt(signal.get("confidence"), "0"))
    tech_signal_value = _score_to_signal(_float(tech_score_value, 0.0) or 0.0)
    context_signal_value = _score_to_signal(_float(context_score_value, 0.0) or 0.0)
    final_action_value = _txt(fusion_breakdown.get("final_action") or dual_track.get("final_action") or signal.get("action"), "HOLD").upper()

    decision = {
        "id": _txt(signal.get("id")),
        "source": source,
        "stockCode": _txt(signal.get("stock_code")),
        "stockName": _txt(signal.get("stock_name")),
        "action": final_action_value,
        "status": _txt(signal.get("signal_status") or signal.get("status") or signal.get("execution_note"), "observed"),
        "decisionType": _txt(signal.get("decision_type") or fusion_breakdown.get("mode"), "auto"),
        "confidence": confidence_value,
        "positionSizePct": _txt(signal.get("position_size_pct"), "0"),
        "techScore": tech_score_value,
        "contextScore": context_score_value,
        "checkpointAt": _txt(signal.get("checkpoint_at") or signal.get("updated_at") or signal.get("created_at"), "--"),
        "createdAt": _txt(signal.get("created_at"), "--"),
        "analysisTimeframe": _profile_text(strategy_profile.get("analysis_timeframe"), "--"),
        "strategyMode": _profile_text(strategy_profile.get("strategy_mode"), "--"),
        "marketRegime": _profile_summary_text(strategy_profile.get("market_regime"), "--"),
        "fundamentalQuality": _profile_summary_text(strategy_profile.get("fundamental_quality"), "--"),
        "riskStyle": _profile_summary_text(strategy_profile.get("risk_style"), "--"),
        "autoInferredRiskStyle": _profile_summary_text(strategy_profile.get("auto_inferred_risk_style"), "--"),
        "techSignal": tech_signal_value,
        "contextSignal": context_signal_value,
        "resonanceType": _txt(dual_track.get("resonance_type"), "--"),
        "ruleHit": _txt(dual_track.get("rule_hit"), _txt(fusion_breakdown.get("mode"), "--")),
        "finalAction": final_action_value,
        "finalReason": _txt(dual_track.get("final_reason") or reasoning_text, "--"),
        "positionRatio": _txt(dual_track.get("position_ratio"), _txt(signal.get("position_size_pct"), "0")),
        "configuredProfile": configured_profile_label,
        "appliedProfile": (
            f"{applied_profile_label} {applied_profile_version_text}".strip()
            if applied_profile_label and applied_profile_label != "--"
            else "--"
        ),
        "aiDynamicStrategy": ai_dynamic_strategy,
        "aiDynamicStrength": ai_dynamic_strength,
        "aiDynamicLookback": ai_dynamic_lookback,
        "aiProfileSwitched": "是" if ai_profile_switched else "否",
    }

    technical_indicators = _extract_technical_indicators(
        tech_votes=tech_votes_raw,
        context_votes=context_votes_raw,
        reasoning=reasoning_text,
        analysis_text=analysis_text,
        strategy_profile=strategy_profile,
        technical_breakdown=technical_breakdown,
        context_breakdown=context_breakdown,
    )
    effective_thresholds = _safe_json_load(strategy_profile.get("effective_thresholds"))
    if _txt(fusion_breakdown.get("buy_threshold_eff")):
        effective_thresholds["buy_threshold"] = fusion_breakdown.get("buy_threshold_eff")
    if _txt(fusion_breakdown.get("sell_threshold_eff")):
        effective_thresholds["sell_threshold"] = fusion_breakdown.get("sell_threshold_eff")
    for key in (
        "buy_threshold_base",
        "buy_threshold_eff",
        "sell_threshold_base",
        "sell_threshold_eff",
        "sell_precedence_gate",
        "threshold_mode",
        "volatility_regime_score",
        "tech_weight_raw",
        "tech_weight_norm",
        "context_weight_raw",
        "context_weight_norm",
        "fusion_score",
        "fusion_confidence",
        "fusion_confidence_base",
        "divergence",
        "divergence_penalty",
        "sign_conflict",
        "mode",
        "veto_source_mode",
    ):
        if _txt(fusion_breakdown.get(key)):
            effective_thresholds[key] = fusion_breakdown.get(key)
    gate_fail_reasons = fusion_breakdown.get("weighted_gate_fail_reasons")
    if isinstance(gate_fail_reasons, list):
        effective_thresholds["weighted_gate_fail_reasons"] = " | ".join(_txt(item, "--") for item in gate_fail_reasons) if gate_fail_reasons else "无"

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
        explainability=explainability,
    )
    vote_overview = _build_vote_overview(
        tech_votes_raw=tech_votes_raw,
        context_votes_raw=context_votes_raw,
        explainability=explainability,
    )
    parameter_details = _build_parameter_details(
        decision=decision,
        runtime_context=runtime_context,
        technical_indicators=technical_indicators,
        effective_thresholds=effective_thresholds,
        tech_votes_raw=tech_votes_raw,
        context_votes_raw=context_votes_raw,
        explainability=explainability,
    )

    ai_monitor = _build_signal_ai_monitor_payload(
        context=context,
        signal=signal,
        checkpoint_at=decision.get("checkpointAt"),
        fetch_realtime_snapshot=fetch_realtime_snapshot,
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
        "aiMonitor": ai_monitor,
        "strategyProfile": strategy_profile,
    }


def _find_signal_detail(
    context: UIApiContext,
    signal_id: str,
    *,
    source: str = "auto",
    fetch_realtime_snapshot: bool = False,
) -> dict[str, Any]:
    db = context.quant_db()
    normalized_source = _txt(source, "auto").lower()
    sid_int = _int(signal_id)
    if sid_int is None:
        raise HTTPException(status_code=400, detail=f"Invalid signal id: {signal_id}")

    if normalized_source in {"auto", "live"}:
        live_signal = db.get_signal(sid_int)
        if live_signal:
            return _build_signal_detail_payload(
                context,
                live_signal,
                source="live",
                fetch_realtime_snapshot=fetch_realtime_snapshot,
            )

    if normalized_source in {"auto", "replay"}:
        replay_signal = db.get_sim_run_signal(sid_int)
        if replay_signal:
            run_id = _int(replay_signal.get("run_id"))
            replay_run = db.get_sim_run(run_id) if run_id is not None else None
            return _build_signal_detail_payload(
                context,
                replay_signal,
                source="replay",
                replay_run=replay_run,
                fetch_realtime_snapshot=fetch_realtime_snapshot,
            )

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
                "updatedAt": _txt(row.get("updated_at")),
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
        "paths": [
            str(context.data_dir / "watchlist.db"),
            str(context.quant_sim_db_file),
            str(context.portfolio_db_file),
            str(context.monitor_db_file),
            str(context.smart_monitor_db_file),
            str(context.stock_analysis_db_file),
            str(context.main_force_batch_db_file),
            str(context.selector_result_dir),
            str(LOGS_DIR),
        ],
    }


def _score_to_signal(score: Any, *, epsilon: float = 1e-6) -> str:
    value = _float(score, 0.0) or 0.0
    if value > epsilon:
        return "BUY"
    if value < -epsilon:
        return "SELL"
    return "HOLD"


def _is_structured_explainability(explainability: dict[str, Any]) -> bool:
    technical_breakdown = explainability.get("technical_breakdown")
    context_breakdown = explainability.get("context_breakdown")
    fusion_breakdown = explainability.get("fusion_breakdown")
    return isinstance(technical_breakdown, dict) and isinstance(context_breakdown, dict) and isinstance(fusion_breakdown, dict)


def _build_structured_vote_rows(track_breakdown: dict[str, Any], *, track: str) -> list[dict[str, Any]]:
    rows = track_breakdown.get("dimensions")
    if not isinstance(rows, list):
        return []
    output: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        dim_id = _txt(row.get("id"), f"{track}_dim_{index + 1}")
        dim_group = _txt(row.get("group"))
        score_value = _float(row.get("score"), 0.0) or 0.0
        weight_raw = _float(row.get("weight_raw"), 1.0)
        if weight_raw is None:
            weight_raw = 1.0
        weight_norm_group = _float(row.get("weight_norm_in_group"))
        group_contribution = _float(row.get("group_contribution"))
        track_contribution = _float(row.get("track_contribution"))
        contribution_value = (
            track_contribution
            if track_contribution is not None
            else (
                group_contribution
                if group_contribution is not None
                else score_value
            )
        )
        reason = _txt(row.get("reason"), "--")
        calc_parts = [
            f"score={score_value:+.4f}",
            f"weight_raw={float(weight_raw):.4f}",
        ]
        if weight_norm_group is not None:
            calc_parts.append(f"w_norm_group={float(weight_norm_group):.4f}")
        if group_contribution is not None:
            calc_parts.append(f"group_contrib={float(group_contribution):+.4f}")
        if track_contribution is not None:
            calc_parts.append(f"track_contrib={float(track_contribution):+.4f}")
        calculation = "；".join(calc_parts)
        output.append(
            {
                "factor": dim_id,
                "component": dim_id if track == "context" else "",
                "name": dim_id,
                "group": dim_group,
                "signal": _score_to_signal(score_value),
                "score": round(score_value, 6),
                "weight": round(float(weight_raw), 6),
                "vote_weight": round(float(weight_norm_group), 6) if weight_norm_group is not None else "",
                "contribution": round(contribution_value, 6),
                "reason": f"group={dim_group}; {reason}" if dim_group else reason,
                "calculation": calculation,
            }
        )
    return output


def _action_settings_save(context: UIApiContext, payload: dict[str, Any]) -> dict[str, Any]:
    body = _payload_dict(payload)
    env_payload = body.get("env") if isinstance(body.get("env"), dict) else {}
    if not env_payload:
        env_payload = {
            str(key): value
            for key, value in body.items()
            if str(key) not in {"strategyProfileId", "strategy_profile_id", "env"}
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
    return _snapshot_settings(context)
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


def _latest_replay_defaults(context: UIApiContext) -> dict[str, Any]:
    scheduler_cfg = context.quant_db().get_scheduler_config()
    default_commission_rate = _normalize_fee_rate(scheduler_cfg.get("commission_rate"), DEFAULT_COMMISSION_RATE)
    default_sell_tax_rate = _normalize_fee_rate(scheduler_cfg.get("sell_tax_rate"), DEFAULT_SELL_TAX_RATE)
    default_strategy_profile_id = _txt(scheduler_cfg.get("strategy_profile_id")).strip() or context.quant_db().get_default_strategy_profile_id()
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
            "commission_rate": _normalize_fee_rate(metadata.get("commission_rate"), default_commission_rate),
            "sell_tax_rate": _normalize_fee_rate(metadata.get("sell_tax_rate"), default_sell_tax_rate),
            "strategy_profile_id": _txt(latest.get("selected_strategy_profile_id"), default_strategy_profile_id),
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
    }
    if commission_present:
        mapping["commission_rate"] = commission_rate
    if sell_tax_present:
        mapping["sell_tax_rate"] = sell_tax_rate
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
    analysis_timeframe = _txt(scheduler_state.get("analysis_timeframe"), "1d")
    strategy_mode = _txt(scheduler_state.get("strategy_mode"), "auto")
    strategy_profile_id = _txt(scheduler_state.get("strategy_profile_id")).strip() or None
    ai_dynamic_strategy = _txt(scheduler_state.get("ai_dynamic_strategy"), DEFAULT_AI_DYNAMIC_STRATEGY)
    ai_dynamic_strength = _normalize_dynamic_strength(scheduler_state.get("ai_dynamic_strength"), DEFAULT_AI_DYNAMIC_STRENGTH)
    ai_dynamic_lookback = _normalize_dynamic_lookback(scheduler_state.get("ai_dynamic_lookback"), DEFAULT_AI_DYNAMIC_LOOKBACK)
    try:
        engine.analyze_candidate(
            candidate,
            analysis_timeframe=analysis_timeframe,
            strategy_mode=strategy_mode,
            strategy_profile_id=strategy_profile_id,
            ai_dynamic_strategy=ai_dynamic_strategy,
            ai_dynamic_strength=ai_dynamic_strength,
            ai_dynamic_lookback=ai_dynamic_lookback,
        )
    except TypeError as exc:
        message = str(exc)
        if "strategy_profile_id" in message:
            engine.analyze_candidate(
                candidate,
                analysis_timeframe=analysis_timeframe,
                strategy_mode=strategy_mode,
            )
        else:
            raise
    return _snapshot_live_sim(context)


def _action_live_sim_delete_candidate(context: UIApiContext, payload: Any) -> dict[str, Any]:
    code = _code_from_payload(payload)
    if not code:
        raise HTTPException(status_code=400, detail="Missing candidate code")
    context.candidate_pool().delete_candidate(code)
    context.watchlist().mark_in_quant_pool(code, False)
    return _snapshot_live_sim(context)


def _action_live_sim_delete_position(context: UIApiContext, payload: Any) -> dict[str, Any]:
    code = _code_from_payload(payload)
    if not code:
        raise HTTPException(status_code=400, detail="Missing position code")
    removed = context.quant_db().delete_position(code)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Position not found: {code}")
    return _snapshot_live_sim(context)


def _action_live_sim_bulk_quant(context: UIApiContext, payload: Any) -> dict[str, Any]:
    context.scheduler().run_once(run_reason="ui_manual_run")
    return _snapshot_live_sim(context)


def _action_his_replay_start(context: UIApiContext, payload: Any) -> dict[str, Any]:
    defaults = _latest_replay_defaults(context)
    body = _payload_dict(payload)
    _, commission_rate = _payload_fee_rate(
        body,
        pct_key="commissionRatePct",
        camel_key="commissionRate",
        snake_key="commission_rate",
        default=float(defaults["commission_rate"]),
    )
    _, sell_tax_rate = _payload_fee_rate(
        body,
        pct_key="sellTaxRatePct",
        camel_key="sellTaxRate",
        snake_key="sell_tax_rate",
        default=float(defaults["sell_tax_rate"]),
    )
    context.replay_service().enqueue_historical_range(
        start_datetime=body.get("startDateTime") or body.get("start_datetime") or defaults["start_datetime"],
        end_datetime=body.get("endDateTime") or body.get("end_datetime") or defaults["end_datetime"],
        timeframe=body.get("timeframe") or defaults["timeframe"],
        market=body.get("market") or defaults["market"],
        strategy_mode=body.get("strategyMode") or body.get("strategy_mode") or defaults["strategy_mode"],
        strategy_profile_id=body.get("strategyProfileId") or body.get("strategy_profile_id") or defaults.get("strategy_profile_id"),
        ai_dynamic_strategy=body.get("aiDynamicStrategy") or body.get("ai_dynamic_strategy") or defaults.get("ai_dynamic_strategy"),
        ai_dynamic_strength=_normalize_dynamic_strength(
            body.get("aiDynamicStrength") if "aiDynamicStrength" in body else body.get("ai_dynamic_strength"),
            _normalize_dynamic_strength(defaults.get("ai_dynamic_strength"), DEFAULT_AI_DYNAMIC_STRENGTH),
        ),
        ai_dynamic_lookback=_normalize_dynamic_lookback(
            body.get("aiDynamicLookback") if "aiDynamicLookback" in body else body.get("ai_dynamic_lookback"),
            _normalize_dynamic_lookback(defaults.get("ai_dynamic_lookback"), DEFAULT_AI_DYNAMIC_LOOKBACK),
        )
        or DEFAULT_AI_DYNAMIC_LOOKBACK,
        commission_rate=commission_rate,
        sell_tax_rate=sell_tax_rate,
    )
    return _snapshot_his_replay(context)


def _action_his_replay_continue(context: UIApiContext, payload: Any) -> dict[str, Any]:
    defaults = _latest_replay_defaults(context)
    body = _payload_dict(payload)
    _, commission_rate = _payload_fee_rate(
        body,
        pct_key="commissionRatePct",
        camel_key="commissionRate",
        snake_key="commission_rate",
        default=float(defaults["commission_rate"]),
    )
    _, sell_tax_rate = _payload_fee_rate(
        body,
        pct_key="sellTaxRatePct",
        camel_key="sellTaxRate",
        snake_key="sell_tax_rate",
        default=float(defaults["sell_tax_rate"]),
    )
    context.replay_service().enqueue_past_to_live(
        start_datetime=body.get("startDateTime") or body.get("start_datetime") or defaults["start_datetime"],
        end_datetime=body.get("endDateTime") or body.get("end_datetime") or defaults["end_datetime"],
        timeframe=body.get("timeframe") or defaults["timeframe"],
        market=body.get("market") or defaults["market"],
        strategy_mode=body.get("strategyMode") or body.get("strategy_mode") or defaults["strategy_mode"],
        strategy_profile_id=body.get("strategyProfileId") or body.get("strategy_profile_id") or defaults.get("strategy_profile_id"),
        ai_dynamic_strategy=body.get("aiDynamicStrategy") or body.get("ai_dynamic_strategy") or defaults.get("ai_dynamic_strategy"),
        ai_dynamic_strength=_normalize_dynamic_strength(
            body.get("aiDynamicStrength") if "aiDynamicStrength" in body else body.get("ai_dynamic_strength"),
            _normalize_dynamic_strength(defaults.get("ai_dynamic_strength"), DEFAULT_AI_DYNAMIC_STRENGTH),
        ),
        ai_dynamic_lookback=_normalize_dynamic_lookback(
            body.get("aiDynamicLookback") if "aiDynamicLookback" in body else body.get("ai_dynamic_lookback"),
            _normalize_dynamic_lookback(defaults.get("ai_dynamic_lookback"), DEFAULT_AI_DYNAMIC_LOOKBACK),
        )
        or DEFAULT_AI_DYNAMIC_LOOKBACK,
        commission_rate=commission_rate,
        sell_tax_rate=sell_tax_rate,
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
        strategy_profile_id=defaults.get("strategy_profile_id"),
        ai_dynamic_strategy=defaults.get("ai_dynamic_strategy", DEFAULT_AI_DYNAMIC_STRATEGY),
        ai_dynamic_strength=_normalize_dynamic_strength(defaults.get("ai_dynamic_strength"), DEFAULT_AI_DYNAMIC_STRENGTH),
        ai_dynamic_lookback=_normalize_dynamic_lookback(defaults.get("ai_dynamic_lookback"), DEFAULT_AI_DYNAMIC_LOOKBACK),
        commission_rate=float(defaults["commission_rate"]),
        sell_tax_rate=float(defaults["sell_tax_rate"]),
    )
    return _snapshot_history(context)


def _action_portfolio_analyze(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    code = _code_from_payload(body)
    manager = context.portfolio_manager()
    if code:
        manager.analyze_single_stock(code)
        return _snapshot_portfolio(context, selected_symbol=code)

    mode = _txt(body.get("mode"), "parallel")
    max_workers = _int(body.get("maxWorkers"), 3) or 3
    period = _txt(body.get("cycle"), "1y")
    task_id = portfolio_rebalance_task_manager.create_task(
        mode=mode,
        cycle=period,
        max_workers=max_workers,
        now=_now,
    )
    portfolio_rebalance_task_manager.start_background(
        task_id=task_id,
        target=portfolio_rebalance_task_manager.run_task,
        kwargs={
            "task_id": task_id,
            "context": context,
            "now": _now,
            "txt": _txt,
        },
        name_prefix="portfolio-rebalance",
    )
    rows = manager.get_all_latest_analysis()
    default_symbol = normalize_stock_code((rows[0].get("code") or rows[0].get("symbol")) if rows else "")
    snapshot = _snapshot_portfolio(
        context,
        selected_symbol=default_symbol,
        analysis_job=portfolio_rebalance_task_manager.get_task(task_id),
    )
    snapshot["taskId"] = task_id
    return snapshot


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


def _action_portfolio_refresh_indicators(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    selected_symbol = normalize_stock_code(body.get("selectedSymbol") or body.get("selected_symbol"))
    symbols = _payload_codes(body)
    if not symbols:
        if selected_symbol:
            symbols = [selected_symbol]
        else:
            symbols = [
                normalize_stock_code(item.get("code") or item.get("symbol"))
                for item in context.portfolio_manager().get_all_latest_analysis()
                if normalize_stock_code(item.get("code") or item.get("symbol"))
            ][:50]
    overrides: dict[str, dict[str, Any]] = {}
    manager = context.portfolio_manager()
    for symbol in symbols:
        overrides[symbol] = _portfolio_technical_snapshot(symbol, cycle=_txt(body.get("cycle"), "1y"))
        sector = _txt(overrides[symbol].get("sector"))
        if sector:
            existing = manager.db.get_stock_by_code(symbol)
            if existing and _txt(existing.get("sector")) != sector:
                manager.update_stock(_int(existing.get("id"), 0) or 0, sector=sector)
    snapshot = _snapshot_portfolio(
        context,
        selected_symbol=selected_symbol or (symbols[0] if symbols else ""),
        indicator_overrides=overrides,
    )
    snapshot["indicatorRefresh"] = {
        "updatedAt": _now(),
        "scope": "indicators_only",
        "symbols": symbols,
    }
    return snapshot


def _action_portfolio_update_position(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    code = normalize_stock_code(_txt(body.get("code") or body.get("symbol")))
    if not code:
        raise HTTPException(status_code=400, detail="Missing portfolio stock code")
    manager = context.portfolio_manager()
    stock = manager.db.get_stock_by_code(code)
    if not stock:
        raise HTTPException(status_code=404, detail=f"Portfolio stock not found: {code}")
    manager.db.update_stock(
        int(stock["id"]),
        cost_price=_float(body.get("costPrice") if "costPrice" in body else body.get("cost_price")),
        quantity=_int(body.get("quantity")),
        take_profit=_float(body.get("takeProfit") if "takeProfit" in body else body.get("take_profit")),
        stop_loss=_float(body.get("stopLoss") if "stopLoss" in body else body.get("stop_loss")),
        note=_txt(body.get("note")) if "note" in body else None,
    )
    return _snapshot_portfolio(context, selected_symbol=code)


def _action_portfolio_delete_position(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    code = normalize_stock_code(_txt(body.get("code") or body.get("symbol") or _code_from_payload(body)))
    if not code:
        raise HTTPException(status_code=400, detail="Missing portfolio stock code")
    manager = context.portfolio_manager()
    stock = manager.db.get_stock_by_code(code)
    if not stock:
        raise HTTPException(status_code=404, detail=f"Portfolio stock not found: {code}")
    ok, message = manager.delete_stock(_int(stock.get("id"), 0) or 0)
    if not ok:
        raise HTTPException(status_code=500, detail=message or f"Failed to delete portfolio stock: {code}")
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


def _action_workbench_analysis_batch_compat(context: UIApiContext, payload: Any) -> dict[str, Any]:
    snapshot = _action_workbench_analysis_batch(context, payload)
    body = _payload_dict(payload)
    raw_codes = body.get("stockCodes") if isinstance(body, dict) else None
    codes = [normalize_stock_code(item) for item in (raw_codes or []) if normalize_stock_code(item)]
    count = len(codes)
    if isinstance(snapshot.get("analysis"), dict):
        analysis = dict(snapshot["analysis"])
        mode = _txt(body.get("mode"), "批量分析")
        if count > 0:
            analysis["mode"] = mode
            analysis["summaryTitle"] = f"{mode}任务已提交"
            analysis["summaryBody"] = f"已提交 {count} 只股票进入批量分析队列，结果会按股票逐条更新。"
        snapshot["analysis"] = analysis
    return snapshot


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
    ("workbench", "batch-portfolio"): _action_workbench_batch_portfolio,
    ("workbench", "analysis"): _action_workbench_analysis,
    ("workbench", "analysis-batch"): _action_workbench_analysis_batch_compat,
    ("workbench", "clear-selection"): lambda context, payload: _action_noop(context, "workbench"),
    ("workbench", "delete-watchlist"): _action_workbench_delete,
    ("discover", "run-strategy"): _action_discover_run_strategy,
    ("discover", "batch-watchlist"): _action_discover_batch,
    ("discover", "item-watchlist"): _action_discover_item,
    ("discover", "reset-list"): _action_discover_reset,
    ("research", "run-module"): _action_research_run_module,
    ("research", "batch-watchlist"): _action_research_batch,
    ("research", "item-watchlist"): _action_research_item,
    ("research", "reset-list"): _action_research_reset,
    ("portfolio", "analyze"): _action_portfolio_analyze,
    ("portfolio", "refresh-portfolio"): _action_portfolio_refresh,
    ("portfolio", "schedule-save"): _action_portfolio_schedule_save,
    ("portfolio", "schedule-start"): _action_portfolio_schedule_start,
    ("portfolio", "schedule-stop"): _action_portfolio_schedule_stop,
    ("portfolio", "refresh-indicators"): _action_portfolio_refresh_indicators,
    ("portfolio", "update-position"): _action_portfolio_update_position,
    ("portfolio", "delete-position"): _action_portfolio_delete_position,
    ("live-sim", "save"): _action_live_sim_save,
    ("live-sim", "start"): _action_live_sim_start,
    ("live-sim", "stop"): _action_live_sim_stop,
    ("live-sim", "reset"): _action_live_sim_reset,
    ("live-sim", "analyze-candidate"): _action_live_sim_analyze_candidate,
    ("live-sim", "delete-candidate"): _action_live_sim_delete_candidate,
    ("live-sim", "delete-position"): _action_live_sim_delete_position,
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


TASK_MANAGERS = [analysis_task_manager, discover_task_manager, research_task_manager, portfolio_rebalance_task_manager]


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
    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        try:
            unified_stock_refresh_scheduler = get_unified_stock_refresh_scheduler(api_context)
            unified_stock_refresh_scheduler.start()
            app.state.unified_stock_refresh_scheduler = unified_stock_refresh_scheduler
        except Exception:
            app.state.unified_stock_refresh_scheduler = None
        try:
            yield
        finally:
            scheduler = getattr(app.state, "unified_stock_refresh_scheduler", None)
            if scheduler:
                scheduler.stop()

    app = FastAPI(
        title="玄武AI智能体股票团队分析系统 Backend API",
        version="0.1.0",
        lifespan=app_lifespan,
    )
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
    def get_signal_detail(signal_id: str, source: str = "auto", refresh_market: bool = False) -> dict[str, Any]:
        return _find_signal_detail(
            api_context,
            signal_id,
            source=source,
            fetch_realtime_snapshot=bool(refresh_market),
        )

    @app.get("/api/v1/quant/live-sim/signals")
    def get_live_sim_signals(limit: int = 200) -> dict[str, Any]:
        return _live_signal_table(api_context, limit=limit)

    @app.get("/api/v1/portfolio_v2/positions/{symbol}")
    def get_portfolio_position(symbol: str) -> dict[str, Any]:
        normalized = normalize_stock_code(symbol)
        if not normalized:
            raise HTTPException(status_code=400, detail="Missing portfolio stock code")
        return _snapshot_portfolio(api_context, selected_symbol=normalized)

    @app.patch("/api/v1/portfolio_v2/positions/{symbol}")
    async def patch_portfolio_position(symbol: str, request: Request) -> dict[str, Any]:
        payload = await _json(request)
        body = _payload_dict(payload)
        body["code"] = normalize_stock_code(symbol)
        return _action_portfolio_update_position(api_context, body)

    @app.get("/api/v1/strategy-profiles")
    def list_strategy_profiles(include_disabled: bool = False) -> dict[str, Any]:
        db = api_context.quant_db()
        scheduler_cfg = db.get_scheduler_config()
        rows = db.list_strategy_profiles(include_disabled=include_disabled)
        items: list[dict[str, Any]] = []
        for row in rows:
            profile_id = _txt(row.get("id")).strip()
            latest = db.get_latest_strategy_profile_version(profile_id) if profile_id else None
            items.append(
                {
                    "id": profile_id,
                    "name": _txt(row.get("name"), profile_id),
                    "description": _txt(row.get("description")),
                    "enabled": bool(row.get("enabled", True)),
                    "isDefault": bool(row.get("is_default", False)),
                    "createdAt": _txt(row.get("created_at")),
                    "updatedAt": _txt(row.get("updated_at")),
                    "latestVersion": latest,
                }
            )
        return {
            "updatedAt": _now(),
            "selectedStrategyProfileId": _txt(scheduler_cfg.get("strategy_profile_id")),
            "profiles": items,
        }

    @app.get("/api/v1/strategy-profiles/{profile_id}")
    def get_strategy_profile(profile_id: str, versions_limit: int = 20) -> dict[str, Any]:
        db = api_context.quant_db()
        profile = db.get_strategy_profile(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail=f"Strategy profile not found: {profile_id}")
        return {
            "updatedAt": _now(),
            "profile": profile,
            "latestVersion": db.get_latest_strategy_profile_version(profile_id),
            "versions": db.list_strategy_profile_versions(profile_id, limit=versions_limit),
        }

    @app.post("/api/v1/strategy-profiles")
    async def create_strategy_profile(request: Request) -> dict[str, Any]:
        body = _payload_dict(await _json(request))
        config = body.get("config")
        if not isinstance(config, dict):
            raise HTTPException(status_code=400, detail="Missing strategy profile config")
        try:
            created = api_context.quant_db().create_strategy_profile(
                profile_id=_txt(body.get("profileId") if "profileId" in body else body.get("id")).strip() or None,
                name=_txt(body.get("name")).strip(),
                config=config,
                description=_txt(body.get("description")),
                enabled=bool(body.get("enabled", True)),
                set_default=bool(body.get("setDefault", False) or body.get("set_default", False)),
                note=_txt(body.get("note")),
            )
            return {"updatedAt": _now(), **created}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/v1/strategy-profiles/{profile_id}")
    async def update_strategy_profile(profile_id: str, request: Request) -> dict[str, Any]:
        body = _payload_dict(await _json(request))
        config = body.get("config")
        try:
            updated = api_context.quant_db().update_strategy_profile(
                profile_id,
                name=_txt(body.get("name")).strip() if "name" in body else None,
                config=config if isinstance(config, dict) else None,
                description=_txt(body.get("description")) if "description" in body else None,
                enabled=bool(body.get("enabled")) if "enabled" in body else None,
                set_default=bool(body.get("setDefault") if "setDefault" in body else body.get("set_default")) if ("setDefault" in body or "set_default" in body) else None,
                note=_txt(body.get("note")) if "note" in body else None,
            )
            return {"updatedAt": _now(), **updated}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/v1/strategy-profiles/{profile_id}/clone")
    async def clone_strategy_profile(profile_id: str, request: Request) -> dict[str, Any]:
        body = _payload_dict(await _json(request))
        clone_name = _txt(body.get("name")).strip()
        if not clone_name:
            raise HTTPException(status_code=400, detail="Clone name is required")
        try:
            cloned = api_context.quant_db().clone_strategy_profile(
                profile_id,
                name=clone_name,
                profile_id=_txt(body.get("profileId") if "profileId" in body else body.get("id")).strip() or None,
                description=_txt(body.get("description")) if "description" in body else None,
            )
            return {"updatedAt": _now(), **cloned}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/v1/strategy-profiles/{profile_id}/validate")
    async def validate_strategy_profile(profile_id: str, request: Request) -> dict[str, Any]:
        body = _payload_dict(await _json(request))
        config = body.get("config")
        db = api_context.quant_db()
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

    @app.post("/api/v1/strategy-profiles/{profile_id}/set-default")
    def set_default_strategy_profile(profile_id: str) -> dict[str, Any]:
        try:
            profile = api_context.quant_db().set_default_strategy_profile(profile_id)
            return {"updatedAt": _now(), "profile": profile}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/v1/strategy-profiles/{profile_id}")
    def delete_strategy_profile(profile_id: str) -> dict[str, Any]:
        db = api_context.quant_db()
        profile = db.get_strategy_profile(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail=f"Strategy profile not found: {profile_id}")
        if bool(profile.get("is_default", False)):
            raise HTTPException(status_code=400, detail="Default strategy profile cannot be deleted")
        try:
            updated = db.update_strategy_profile(profile_id, enabled=False, note="disabled_by_delete")
            return {"updatedAt": _now(), "ok": True, **updated}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    for path, page in {
        "/api/v1/workbench": "workbench",
        "/api/v1/discover": "discover",
        "/api/v1/research": "research",
        "/api/v1/portfolio": "portfolio",
        "/api/v1/portfolio_v2": "portfolio",
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
        ("/api/v1/workbench/actions/batch-portfolio", "workbench", "batch-portfolio"),
        ("/api/v1/workbench/actions/analysis", "workbench", "analysis"),
        ("/api/v1/workbench/actions/analysis-batch", "workbench", "analysis-batch"),
        ("/api/v1/workbench/actions/clear-selection", "workbench", "clear-selection"),
        ("/api/v1/workbench/actions/delete-watchlist", "workbench", "delete-watchlist"),
        ("/api/v1/discover/actions/item-watchlist", "discover", "item-watchlist"),
        ("/api/v1/discover/actions/batch-watchlist", "discover", "batch-watchlist"),
        ("/api/v1/discover/actions/run-strategy", "discover", "run-strategy"),
        ("/api/v1/discover/actions/reset-list", "discover", "reset-list"),
        ("/api/v1/research/actions/item-watchlist", "research", "item-watchlist"),
        ("/api/v1/research/actions/batch-watchlist", "research", "batch-watchlist"),
        ("/api/v1/research/actions/run-module", "research", "run-module"),
        ("/api/v1/research/actions/reset-list", "research", "reset-list"),
        ("/api/v1/portfolio/actions/analyze", "portfolio", "analyze"),
        ("/api/v1/portfolio/actions/refresh-portfolio", "portfolio", "refresh-portfolio"),
        ("/api/v1/portfolio/actions/schedule-save", "portfolio", "schedule-save"),
        ("/api/v1/portfolio/actions/schedule-start", "portfolio", "schedule-start"),
        ("/api/v1/portfolio/actions/schedule-stop", "portfolio", "schedule-stop"),
        ("/api/v1/portfolio/actions/refresh-indicators", "portfolio", "refresh-indicators"),
        ("/api/v1/portfolio/actions/update-position", "portfolio", "update-position"),
        ("/api/v1/portfolio/actions/delete-position", "portfolio", "delete-position"),
        ("/api/v1/portfolio_v2/actions/analyze", "portfolio", "analyze"),
        ("/api/v1/portfolio_v2/actions/refresh-portfolio", "portfolio", "refresh-portfolio"),
        ("/api/v1/portfolio_v2/actions/schedule-save", "portfolio", "schedule-save"),
        ("/api/v1/portfolio_v2/actions/schedule-start", "portfolio", "schedule-start"),
        ("/api/v1/portfolio_v2/actions/schedule-stop", "portfolio", "schedule-stop"),
        ("/api/v1/portfolio_v2/actions/refresh-indicators", "portfolio", "refresh-indicators"),
        ("/api/v1/portfolio_v2/actions/update-position", "portfolio", "update-position"),
        ("/api/v1/portfolio_v2/actions/delete-position", "portfolio", "delete-position"),
        ("/api/v1/quant/live-sim/actions/save", "live-sim", "save"),
        ("/api/v1/quant/live-sim/actions/start", "live-sim", "start"),
        ("/api/v1/quant/live-sim/actions/stop", "live-sim", "stop"),
        ("/api/v1/quant/live-sim/actions/reset", "live-sim", "reset"),
        ("/api/v1/quant/live-sim/actions/analyze-candidate", "live-sim", "analyze-candidate"),
        ("/api/v1/quant/live-sim/actions/delete-candidate", "live-sim", "delete-candidate"),
        ("/api/v1/quant/live-sim/actions/delete-position", "live-sim", "delete-position"),
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

