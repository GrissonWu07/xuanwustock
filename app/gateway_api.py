from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import re
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config_manager import ConfigManager, config_manager
from app.database import StockAnalysisDatabase
from app import stock_analysis_service
from app.main_force_batch_db import MainForceBatchDatabase
from app.monitor_db import monitor_db
from app.portfolio_db import portfolio_db
from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.db import QuantSimDB
from app.quant_sim.engine import QuantSimEngine
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.replay_service import QuantSimReplayService
from app.quant_sim.scheduler import get_quant_sim_scheduler
from app.research_watchlist_integration import add_research_stock_to_watchlist, add_research_stocks_to_watchlist
from app.runtime_paths import DATA_DIR, LOGS_DIR, default_db_path
from app.selector_result_store import DEFAULT_SELECTOR_RESULT_DIR, load_latest_result, save_latest_result
from app.selector_ui_state import (
    load_main_force_state,
    load_simple_selector_state,
    save_main_force_state,
    save_simple_selector_state,
)
from app.sector_strategy_engine import SectorStrategyEngine
from app.watchlist_integration import add_watchlist_rows_to_quant_pool
from app.watchlist_selector_integration import add_stock_to_watchlist, normalize_stock_code
from app.monitor_db import StockMonitorDatabase
from app.watchlist_service import WatchlistService

SERVICE_NAME = "xuanwu-api"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
UI_DIST_DIR = PROJECT_ROOT / "ui" / "dist"

MainForceStockSelector = None
LowPriceBullSelector = None
SmallCapSelector = None
ProfitGrowthSelector = None
ValueStockSelector = None
SectorStrategyDataFetcher = None
LonghubangEngine = None
NewsFlowEngine = None
MacroAnalysisEngine = None
MacroCycleEngine = None


def _selector_cls(name: str):
    global MainForceStockSelector, LowPriceBullSelector, SmallCapSelector, ProfitGrowthSelector, ValueStockSelector
    mapping = {
        "MainForceStockSelector": ("app.main_force_selector", "MainForceStockSelector"),
        "LowPriceBullSelector": ("app.low_price_bull_selector", "LowPriceBullSelector"),
        "SmallCapSelector": ("app.small_cap_selector", "SmallCapSelector"),
        "ProfitGrowthSelector": ("app.profit_growth_selector", "ProfitGrowthSelector"),
        "ValueStockSelector": ("app.value_stock_selector", "ValueStockSelector"),
    }
    current = globals()[name]
    if current is None:
        module_name, attr_name = mapping[name]
        module = __import__(module_name, fromlist=[attr_name])
        globals()[name] = getattr(module, attr_name)
    return globals()[name]


def _research_cls(name: str):
    global SectorStrategyDataFetcher, LonghubangEngine, NewsFlowEngine, MacroAnalysisEngine, MacroCycleEngine
    mapping = {
        "SectorStrategyDataFetcher": ("app.sector_strategy_data", "SectorStrategyDataFetcher"),
        "LonghubangEngine": ("app.longhubang_engine", "LonghubangEngine"),
        "NewsFlowEngine": ("app.news_flow_engine", "NewsFlowEngine"),
        "MacroAnalysisEngine": ("app.macro_analysis_engine", "MacroAnalysisEngine"),
        "MacroCycleEngine": ("app.macro_cycle_engine", "MacroCycleEngine"),
    }
    current = globals()[name]
    if current is None:
        module_name, attr_name = mapping[name]
        module = __import__(module_name, fromlist=[attr_name])
        globals()[name] = getattr(module, attr_name)
    return globals()[name]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _p(value: str | Path) -> Path:
    return value if isinstance(value, Path) else Path(value)


def _txt(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _dict_value(obj: Any, key: str, default: Any = None) -> Any:
    if not isinstance(obj, dict):
        return default
    return obj.get(key, default)


def _num(value: Any, digits: int = 2, default: str = "0.00") -> str:
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return default


def _pct(value: Any, digits: int = 2, default: str = "0.00%") -> str:
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        return f"{float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None or (isinstance(value, str) and not str(value).strip()):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _metric(label: str, value: Any) -> dict[str, Any]:
    return {"label": label, "value": _txt(value, "0")}


def _insight(title: str, body: str, tone: str | None = None) -> dict[str, Any]:
    item = {"title": title, "body": body}
    if tone:
        item["tone"] = tone
    return item


def _timeline(time: str, title: str, body: str) -> dict[str, str]:
    return {"time": time, "title": title, "body": body}


def _table(columns: list[str], rows: list[dict[str, Any]], empty_label: str) -> dict[str, Any]:
    return {"columns": columns, "rows": rows, "emptyLabel": empty_label}


def _snippet(value: Any, limit: int = 80, default: str = "") -> str:
    text = _txt(value, default)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip(" ,;；。.") + "…"


RESEARCH_MARKDOWN_TEXT_LIMIT = 2000
RESEARCH_MODULE_TIMEOUT_SECONDS = 90


def _looks_like_stock_code(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip().upper()
    return bool(re.fullmatch(r"\d{6}(?:\.[A-Z]{2,6})?", text))


def _payload_dict(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def _code_from_payload(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("code", "stockCode", "stock_code", "id", "symbol"):
            code = normalize_stock_code(payload.get(key))
            if code:
                return code
        return ""
    code = normalize_stock_code(payload)
    if code:
        return code
    return ""


def _normalize_codes(payload: Any) -> list[str]:
    if isinstance(payload, list):
        return [normalize_stock_code(item) for item in payload if normalize_stock_code(item)]
    if isinstance(payload, dict):
        for key in ("codes", "stockCodes", "stock_codes", "rows", "ids"):
            if key in payload:
                return _normalize_codes(payload[key])
        code = _code_from_payload(payload)
        return [code] if code else []
    if payload is None:
        return []
    code = normalize_stock_code(payload)
    return [code] if code else []


def _first_non_empty(mapping: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _discover_code(value: Any) -> str:
    code = normalize_stock_code(value)
    if not code:
        return ""
    if code.isdigit() and len(code) < 6:
        try:
            return f"{int(code):06d}"
        except (TypeError, ValueError):
            return code
    return code


def _parse_selector_timestamp(value: Any) -> datetime | None:
    text = _txt(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _discover_row_from_mapping(row: dict[str, Any], *, source: str, selected_at: str | None) -> dict[str, Any] | None:
    code = _discover_code(
        _first_non_empty(
            row,
            [
                "股票代码",
                "stock_code",
                "stockCode",
                "code",
                "symbol",
                "证券代码",
                "代码",
                "id",
            ],
        )
    )
    if not code:
        return None
    name = _txt(
        _first_non_empty(
            row,
            [
                "股票简称",
                "股票名称",
                "stock_name",
                "stockName",
                "name",
                "证券简称",
                "名称",
            ],
        ),
        code,
    )
    industry = _txt(
        _first_non_empty(
            row,
            [
                "所属同花顺行业",
                "所属行业",
                "industry",
                "行业",
                "板块",
            ],
        )
    )
    latest_price = _num(
        _first_non_empty(
            row,
            [
                "最新价",
                "股价",
                "latestPrice",
                "latest_price",
                "当前价",
                "收盘价",
                "price",
            ],
        )
    )
    market_cap = _num(
        _first_non_empty(
            row,
            [
                "总市值",
                "market_cap",
                "marketCap",
                "市值",
            ],
        )
    )
    pe = _num(
        _first_non_empty(
            row,
            [
                "市盈率",
                "pe",
                "pe_ratio",
                "PE",
            ],
        )
    )
    pb = _num(
        _first_non_empty(
            row,
            [
                "市净率",
                "pb",
                "pb_ratio",
                "PB",
            ],
        )
    )
    reason = _txt(
        _first_non_empty(
            row,
            [
                "reason",
                "理由",
                "说明",
                "备注",
                "选股理由",
                "后续动作",
                "note",
                "body",
                "summary",
                "highlights",
            ],
        )
    )
    cells = [code, name, industry, source, latest_price, market_cap, pe, pb]
    result = {
        "id": code,
        "cells": cells,
        "actions": [{"label": "加入关注池", "icon": "⭐", "tone": "accent", "action": "item-watchlist"}],
        "code": code,
        "name": name,
        "industry": industry,
        "source": source,
        "latestPrice": latest_price,
        "reason": reason,
        "selectedAt": _txt(selected_at),
    }
    return result


def _discover_rows_from_main_force(result: dict[str, Any], selected_at: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    recommendations = result.get("final_recommendations", []) if isinstance(result, dict) else []
    for item in recommendations or []:
        if not isinstance(item, dict):
            continue
        stock = item.get("stock_data", {}) if isinstance(item.get("stock_data"), dict) else {}
        row = _discover_row_from_mapping(
            {
                "股票代码": stock.get("股票代码") or item.get("code") or item.get("stock_code") or item.get("symbol"),
                "股票简称": stock.get("股票简称") or item.get("name"),
                "所属同花顺行业": stock.get("所属同花顺行业") or stock.get("所属行业") or item.get("industry"),
                "最新价": stock.get("最新价") or item.get("latestPrice") or item.get("latest_price"),
                "总市值": stock.get("总市值[20260410]") or stock.get("总市值") or item.get("market_cap"),
                "市盈率": stock.get("市盈率(pe)[20260410]") or stock.get("市盈率") or item.get("pe_ratio"),
                "市净率": stock.get("市净率(pb)[20260410]") or stock.get("市净率") or item.get("pb_ratio"),
                "reason": item.get("highlights") or item.get("reason") or ", ".join(item.get("reasons", [])),
            },
            source=_txt(item.get("source") or "主力选股"),
            selected_at=selected_at,
        )
        if row:
            rows.append(row)
    return rows


def _discover_rows_from_simple_selector(
    strategy_key: str,
    strategy_name: str,
    selected_at: str | None,
    stocks_df: Any,
) -> list[dict[str, Any]]:
    if stocks_df is None:
        return []
    try:
        if getattr(stocks_df, "empty", False):
            return []
        rows_iter = stocks_df.to_dict(orient="records")
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for item in rows_iter or []:
        if not isinstance(item, dict):
            continue
        row = _discover_row_from_mapping(item, source=strategy_name, selected_at=selected_at)
        if not row:
            continue
        row["strategyKey"] = strategy_key
        rows.append(row)
    return rows


def _discover_strategy_snapshots(context: "UIApiContext") -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    main_result, _, main_selected_at = load_main_force_state(base_dir=context.selector_result_dir)
    if main_result:
        rows = _discover_rows_from_main_force(main_result, main_selected_at)
        if rows:
            snapshots.append(
                {
                    "key": "main_force",
                    "name": "主力选股",
                    "note": "主资金流 + 财务过滤 + AI精选",
                    "selected_at": main_selected_at,
                    "rows": rows,
                }
            )

    for strategy_key, strategy_name, strategy_note in [
        ("low_price_bull", "低价擒牛", "低价高弹性标的挖掘"),
        ("small_cap", "小市值", "小而活跃的成长标的"),
        ("profit_growth", "净利增长", "盈利增长趋势筛选"),
        ("value_stock", "低估值", "估值修复方向"),
    ]:
        stocks_df, selected_at = load_simple_selector_state(strategy_key, base_dir=context.selector_result_dir)
        rows = _discover_rows_from_simple_selector(strategy_key, strategy_name, selected_at, stocks_df)
        if rows:
            snapshots.append(
                {
                    "key": strategy_key,
                    "name": strategy_name,
                    "note": strategy_note,
                    "selected_at": selected_at,
                    "rows": rows,
                }
            )
    snapshots.sort(
        key=lambda item: (
            _parse_selector_timestamp(item.get("selected_at")) or datetime.min,
            item.get("name") or "",
        ),
        reverse=True,
    )
    return snapshots


async def _json(request: Request) -> Any:
    try:
        return await request.json()
    except Exception:
        return {}


def _discover_rows(context: "UIApiContext") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for snapshot in _discover_strategy_snapshots(context):
        for row in snapshot.get("rows", []):
            row = dict(row)
            row["source"] = _txt(row.get("source") or snapshot.get("name"))
            row["strategyKey"] = _txt(snapshot.get("key"))
            row["strategyName"] = _txt(snapshot.get("name"))
            row["selectedAt"] = _txt(snapshot.get("selected_at") or row.get("selectedAt"))
            row["_selected_dt"] = _parse_selector_timestamp(row.get("selectedAt")) or datetime.min
            row["_strategy_priority"] = {
                "main_force": 5,
                "low_price_bull": 4,
                "small_cap": 3,
                "profit_growth": 2,
                "value_stock": 1,
            }.get(_txt(snapshot.get("key")), 0)
            rows.append(row)
    rows.sort(
        key=lambda item: (
            item.get("_selected_dt") or datetime.min,
            item.get("_strategy_priority") or 0,
            item.get("code") or "",
        ),
        reverse=True,
    )
    for row in rows:
        row.pop("_selected_dt", None)
        row.pop("_strategy_priority", None)
    return rows


def _research_rows(context: "UIApiContext") -> list[dict[str, Any]]:
    payload = load_latest_result(context.research_result_key, base_dir=context.selector_result_dir) or {}
    rows: list[dict[str, Any]] = []
    for item in (payload.get("outputTable") or {}).get("rows", []) or []:
        if not isinstance(item, dict):
            continue
        code = normalize_stock_code(item.get("code") or item.get("stock_code") or item.get("id"))
        if not code:
            continue
        rows.append(
            {
                "id": code,
                "cells": [code, _txt(item.get("name") or item.get("stock_name") or code), _txt(item.get("source") or item.get("source_module") or item.get("来源模块") or "研究情报"), _txt(item.get("reason") or item.get("body") or item.get("后续动作") or "")],
                "actions": [{"label": "加入关注池", "icon": "⭐", "tone": "accent", "action": "item-watchlist"}],
                "code": code,
                "name": _txt(item.get("name") or item.get("stock_name") or code),
                "source": _txt(item.get("source") or item.get("source_module") or item.get("来源模块") or "研究情报"),
                "latestPrice": _num(item.get("latestPrice") or item.get("latest_price") or item.get("最新价")),
                "reason": _txt(item.get("reason") or item.get("body") or item.get("后续动作") or ""),
            }
        )
    existing = {row["code"] for row in rows}
    for item in payload.get("modules", []) or []:
        if not isinstance(item, dict):
            continue
        raw_code = item.get("output") or item.get("code") or item.get("stock_code")
        if not _looks_like_stock_code(raw_code):
            continue
        code = normalize_stock_code(raw_code)
        if not code or code in existing:
            continue
        name = context.stock_name_resolver(code) if context.stock_name_resolver else code
        rows.append(
            {
                "id": code,
                "cells": [code, name, _txt(item.get("name") or "研究模块"), _txt(item.get("note") or item.get("output") or "")],
                "actions": [{"label": "加入关注池", "icon": "⭐", "tone": "accent", "action": "item-watchlist"}],
                "code": code,
                "name": name,
                "source": _txt(item.get("name") or "研究模块"),
                "latestPrice": "0.00",
                "reason": _txt(item.get("note") or item.get("output") or ""),
            }
        )
    return rows


def _research_stock_row(
    stock: dict[str, Any],
    source: str,
    context: "UIApiContext",
) -> dict[str, Any] | None:
    if not isinstance(stock, dict):
        return None
    code = normalize_stock_code(
        stock.get("code")
        or stock.get("stock_code")
        or stock.get("股票代码")
        or stock.get("symbol")
        or stock.get("id")
    )
    if not code:
        return None

    name = _txt(
        stock.get("name")
        or stock.get("stock_name")
        or stock.get("股票名称")
        or stock.get("股票简称")
        or stock.get("名称")
    )
    if not name and context.stock_name_resolver:
        name = context.stock_name_resolver(code)
    if not name:
        name = code

    reason = _txt(
        stock.get("reason")
        or stock.get("highlights")
        or stock.get("analysis")
        or stock.get("summary")
        or stock.get("advice")
        or stock.get("body")
        or stock.get("后续动作")
    )
    latest_price = _num(
        stock.get("latestPrice")
        or stock.get("latest_price")
        or stock.get("最新价")
        or stock.get("price")
        or stock.get("现价")
    )
    return {
        "id": code,
        "cells": [code, name, source, reason],
        "actions": [{"label": "加入关注池", "icon": "⭐", "tone": "accent", "action": "item-watchlist"}],
        "code": code,
        "name": name,
        "source": source,
        "latestPrice": latest_price,
        "reason": reason,
    }


def _research_stock_rows(
    stocks: Any,
    source: str,
    context: "UIApiContext",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(stocks, list):
        return rows
    for stock in stocks:
        row = _research_stock_row(stock, source, context)
        if row:
            rows.append(row)
    return rows


def _research_market_views_from_module(name: str, text: str, tone: str = "neutral") -> list[dict[str, Any]]:
    if not text:
        return []
    return [_insight(name, _snippet(text, RESEARCH_MARKDOWN_TEXT_LIMIT), tone)]


def _normalize_research_module_selection(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("modules") or payload.get("module") or payload.get("moduleKey")
    if raw is None or raw == "":
        return ["sector", "longhubang", "news", "macro", "cycle"]

    values: list[str]
    if isinstance(raw, list):
        values = [str(item).strip().lower() for item in raw if str(item).strip()]
    else:
        values = [str(raw).strip().lower()]

    aliases = {
        "sector": {"sector", "strategy", "智策板块", "板块", "sector_strategy"},
        "longhubang": {"longhubang", "龙虎榜", "龙虎", "dragon_tiger"},
        "news": {"news", "news-flow", "新闻", "新闻流量"},
        "macro": {"macro", "宏观", "宏观分析"},
        "cycle": {"cycle", "宏观周期", "周期"},
    }

    selected: list[str] = []
    for key, synonyms in aliases.items():
        if any(value in synonyms for value in values):
            selected.append(key)

    return selected or ["sector", "longhubang", "news", "macro", "cycle"]


def _normalize_discover_strategy_selection(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("strategies") or payload.get("strategy") or payload.get("strategyKey")
    if raw is None or raw == "":
        return ["main_force", "low_price_bull", "small_cap", "profit_growth", "value_stock"]

    values: list[str]
    if isinstance(raw, list):
        values = [str(item).strip().lower() for item in raw if str(item).strip()]
    else:
        values = [str(raw).strip().lower()]

    aliases = {
        "main_force": {"main_force", "main-force", "主力选股", "主力"},
        "low_price_bull": {"low_price_bull", "low-price-bull", "低价擒牛", "低价"},
        "small_cap": {"small_cap", "small-cap", "小市值"},
        "profit_growth": {"profit_growth", "profit-growth", "净利增长"},
        "value_stock": {"value_stock", "value-stock", "低估值"},
    }

    selected: list[str] = []
    for key, synonyms in aliases.items():
        if any(value in synonyms for value in values):
            selected.append(key)
    return selected or ["main_force", "low_price_bull", "small_cap", "profit_growth", "value_stock"]


def _run_research_module_sector(context: "UIApiContext") -> dict[str, Any]:
    fetcher = _research_cls("SectorStrategyDataFetcher")()
    data = fetcher.get_cached_data_with_fallback()
    if not data.get("success"):
        note = _snippet(
            data.get("cache_warning") or data.get("message") or data.get("error") or "板块数据获取失败",
            RESEARCH_MARKDOWN_TEXT_LIMIT,
        )
        return {
            "name": "智策板块",
            "note": note,
            "output": "数据获取失败",
            "rows": [],
            "marketView": [_insight("智策板块", note, "warning")],
        }

    result = SectorStrategyEngine().run_comprehensive_analysis(data)
    final_predictions = result.get("final_predictions", {}) if isinstance(result, dict) else {}
    bullish = final_predictions.get("long_short", {}).get("bullish", []) if isinstance(final_predictions, dict) else []
    bearish = final_predictions.get("long_short", {}).get("bearish", []) if isinstance(final_predictions, dict) else []
    chief_text = result.get("agents_analysis", {}).get("chief", {}).get("analysis", "") if isinstance(result, dict) else ""
    note = _snippet(
        result.get("comprehensive_report") or final_predictions.get("summary") or chief_text or "板块策略已完成",
        RESEARCH_MARKDOWN_TEXT_LIMIT,
    )
    output = f"看多 {len(bullish)} / 看空 {len(bearish)}"
    market_view = _research_market_views_from_module("智策板块", note, "neutral")
    return {
        "name": "智策板块",
        "note": note,
        "output": output,
        "rows": [],
        "marketView": market_view,
    }


def _run_research_module_longhubang(context: "UIApiContext") -> dict[str, Any]:
    result = _research_cls("LonghubangEngine")().run_comprehensive_analysis(days=1)
    stocks = _research_stock_rows(result.get("recommended_stocks", []), "智瞰龙虎", context)
    chief_text = result.get("agents_analysis", {}).get("chief", {}).get("analysis", "") if isinstance(result, dict) else ""
    note = _snippet(
        chief_text or result.get("final_report", {}).get("summary", "") or "龙虎榜分析已完成", RESEARCH_MARKDOWN_TEXT_LIMIT
    )
    output = f"股票输出 {len(stocks)} 只" if stocks else _snippet(note, 120, "分析完成")
    return {
        "name": "智瞰龙虎",
        "note": note,
        "output": output,
        "rows": stocks,
        "marketView": _research_market_views_from_module("智瞰龙虎", note, "neutral"),
    }


def _run_research_module_news(context: "UIApiContext") -> dict[str, Any]:
    result = _research_cls("NewsFlowEngine")().run_full_analysis(include_ai=True)
    ai_analysis = result.get("ai_analysis", {}) if isinstance(result, dict) else {}
    stock_recommend = ai_analysis.get("stock_recommend", {}) if isinstance(ai_analysis, dict) else {}
    stocks = _research_stock_rows(stock_recommend.get("recommended_stocks", []), "新闻流量", context)
    advice = ai_analysis.get("investment_advice", {}) if isinstance(ai_analysis, dict) else {}
    note = _snippet(
        advice.get("summary")
        or advice.get("advice")
        or result.get("trading_signals", {}).get("operation_advice")
        or "新闻流量分析已完成",
        RESEARCH_MARKDOWN_TEXT_LIMIT,
    )
    market_view: list[dict[str, Any]] = []
    if advice.get("advice"):
        market_view.append(_insight("新闻流量", _snippet(advice.get("summary") or advice.get("advice"), RESEARCH_MARKDOWN_TEXT_LIMIT), "accent"))
    if result.get("trading_signals", {}).get("operation_advice"):
        market_view.append(_insight("交易信号", _snippet(result.get("trading_signals", {}).get("operation_advice"), RESEARCH_MARKDOWN_TEXT_LIMIT), "warning"))
    output = f"股票输出 {len(stocks)} 只" if stocks else _snippet(note, 120, "分析完成")
    return {
        "name": "新闻流量",
        "note": note,
        "output": output,
        "rows": stocks,
        "marketView": market_view,
    }


def _run_research_module_macro(context: "UIApiContext") -> dict[str, Any]:
    result = _research_cls("MacroAnalysisEngine")().run_full_analysis(progress_callback=None)
    stocks = _research_stock_rows(result.get("candidate_stocks", []), "宏观分析", context)
    chief = result.get("agents_analysis", {}).get("chief", {}) if isinstance(result, dict) else {}
    sector_view = result.get("sector_view", {}) if isinstance(result, dict) else {}
    note = _snippet(
        chief.get("analysis") or sector_view.get("market_view") or "宏观分析已完成",
        RESEARCH_MARKDOWN_TEXT_LIMIT,
    )
    market_view: list[dict[str, Any]] = []
    if chief.get("analysis"):
        market_view.append(_insight("宏观分析", _snippet(chief.get("analysis"), RESEARCH_MARKDOWN_TEXT_LIMIT), "neutral"))
    if sector_view.get("market_view"):
        market_view.append(_insight("行业映射", _snippet(sector_view.get("market_view"), RESEARCH_MARKDOWN_TEXT_LIMIT), "accent"))
    output = f"股票输出 {len(stocks)} 只" if stocks else _snippet(note, 120, "分析完成")
    return {
        "name": "宏观分析",
        "note": note,
        "output": output,
        "rows": stocks,
        "marketView": market_view,
    }


def _run_research_module_cycle(context: "UIApiContext") -> dict[str, Any]:
    result = _research_cls("MacroCycleEngine")().run_full_analysis(progress_callback=None)
    chief = result.get("agents_analysis", {}).get("chief", {}) if isinstance(result, dict) else {}
    note = _snippet(
        chief.get("analysis") or result.get("formatted_data") or "宏观周期分析已完成",
        RESEARCH_MARKDOWN_TEXT_LIMIT,
    )
    market_view: list[dict[str, Any]] = []
    if chief.get("analysis"):
        market_view.append(_insight("宏观周期", _snippet(chief.get("analysis"), RESEARCH_MARKDOWN_TEXT_LIMIT), "neutral"))
    return {
        "name": "宏观周期",
        "note": note,
        "output": _snippet(note, 120, "分析完成"),
        "rows": [],
        "marketView": market_view,
    }


def _run_research_modules(context: "UIApiContext", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = payload if isinstance(payload, dict) else {}
    selected_modules = set(_normalize_research_module_selection(body))
    module_runners: list[tuple[str, Callable[["UIApiContext"], dict[str, Any]]]] = [
        ("sector", _run_research_module_sector),
        ("longhubang", _run_research_module_longhubang),
        ("news", _run_research_module_news),
        ("macro", _run_research_module_macro),
        ("cycle", _run_research_module_cycle),
    ]

    module_results: list[dict[str, Any]] = []
    stock_rows: list[dict[str, Any]] = []
    market_view: list[dict[str, Any]] = []
    failures: list[str] = []

    selected_runners = [(module_key, runner) for module_key, runner in module_runners if module_key in selected_modules]
    if not selected_runners:
        selected_runners = module_runners[:]

    module_results_cache: dict[str, dict[str, Any]] = {}
    module_errors: dict[str, BaseException] = {}
    module_threads: dict[str, threading.Thread] = {}

    def worker(module_key: str, runner: Callable[["UIApiContext"], dict[str, Any]]) -> None:
        try:
            module_results_cache[module_key] = runner(context)
        except BaseException as exc:  # pragma: no cover - defensive for plugin exceptions
            module_errors[module_key] = exc

    for module_key, runner in selected_runners:
        thread = threading.Thread(target=worker, args=(module_key, runner), name=f"research-module-{module_key}")
        thread.daemon = True
        thread.start()
        module_threads[module_key] = thread

    deadline = time.time() + RESEARCH_MODULE_TIMEOUT_SECONDS
    for module_key in module_threads:
        thread = module_threads[module_key]
        remaining = deadline - time.time()
        if remaining > 0:
            thread.join(timeout=remaining)

    for module_key in module_threads:
        thread = module_threads[module_key]
        if thread.is_alive():
            failures.append(f"{module_key}: {module_key} 分析超时（{RESEARCH_MODULE_TIMEOUT_SECONDS} 秒）")
            module_results.append(
                {
                    "name": module_key,
                    "note": _snippet(f"{module_key} 分析超时（{RESEARCH_MODULE_TIMEOUT_SECONDS} 秒）", 80, "分析失败"),
                    "output": "分析失败",
                }
            )
            continue
        if module_key in module_errors:
            failures.append(f"{module_key}: {module_errors[module_key]}")
            module_results.append(
                {
                    "name": module_key,
                    "note": _snippet(str(module_errors[module_key]), 80, "分析失败"),
                    "output": "分析失败",
                }
            )
            continue
        result = module_results_cache.get(module_key)
        if not isinstance(result, dict):
            failures.append(f"{module_key}: 分析返回为空或格式异常")
            module_results.append(
                {
                    "name": module_key,
                    "note": _snippet("模块结果为空", 80, "分析失败"),
                    "output": "分析失败",
                }
            )
            continue
        try:
            module_results.append(
                {
                    "name": _txt(result.get("name"), module_key),
                    "note": _snippet(
                        result.get("note") or result.get("output") or "分析已完成",
                        RESEARCH_MARKDOWN_TEXT_LIMIT,
                    ),
                    "output": _snippet(result.get("output") or "分析完成", 24),
                }
            )
            stock_rows.extend(result.get("rows") or [])
            market_view.extend(result.get("marketView") or [])
        except Exception as exc:  # pragma: no cover - defensive aggregation
            failures.append(f"{module_key}: {exc}")
            module_results.append(
                {
                    "name": module_key,
                    "note": _snippet(str(exc), 80, "分析失败"),
                    "output": "分析失败",
                }
            )

    summary_title = "研究情报已更新" if not failures else "研究情报部分完成"
    summary_body = (
        f"已刷新 {len(module_results)} 个研究模块，其中 {len(stock_rows)} 只股票有明确输出；"
        "没有股票输出的模块只保留分析结论。"
    )
    if failures:
        summary_body = f"{summary_body} 部分模块失败：{'; '.join(failures[:3])}。"

    payload_result = {
        "updatedAt": _now(),
        "modules": module_results,
        "marketView": market_view[:6],
        "outputTable": _table(["代码", "名称", "来源模块", "后续动作"], stock_rows, "暂无股票输出"),
        "summary": {"title": summary_title, "body": summary_body},
    }
    save_latest_result(context.research_result_key, payload_result, base_dir=context.selector_result_dir)
    return payload_result


def _watchlist_rows(context: "UIApiContext") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in context.watchlist().list_watches():
        code = normalize_stock_code(item.get("stock_code"))
        rows.append(
            {
                "id": code,
                "cells": [code, _txt(item.get("stock_name") or code), _num(item.get("latest_price")), _txt(item.get("source_summary") or "手工/策略"), _txt(item.get("latest_signal") or "待分析"), "已入量化" if item.get("in_quant_pool") else "未加入"],
                "actions": [
                    {"label": "分析", "icon": "🔎", "tone": "accent", "action": "analysis"},
                    {"label": "入量化", "icon": "🧪", "tone": "neutral", "action": "batch-quant"},
                    {"label": "删除", "icon": "🗑", "tone": "danger", "action": "delete-watchlist"},
                ],
                "code": code,
                "name": _txt(item.get("stock_name") or code),
                "source": _txt(item.get("source_summary") or "手工/策略"),
                "latestPrice": _num(item.get("latest_price")),
                "reason": _txt(item.get("latest_signal") or "待分析"),
            }
        )
    return rows


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


def _analysis_options(selected: list[str] | set[str] | None = None) -> list[dict[str, Any]]:
    defaults = {"technical", "fundamental", "fund_flow", "risk"}
    if selected is not None:
        defaults = {str(item) for item in selected if str(item).strip()}
    return [
        {"label": "技术分析师", "value": "technical", "selected": "technical" in defaults},
        {"label": "基本面分析师", "value": "fundamental", "selected": "fundamental" in defaults},
        {"label": "资金面分析师", "value": "fund_flow", "selected": "fund_flow" in defaults},
        {"label": "风险管理师", "value": "risk", "selected": "risk" in defaults},
        {"label": "市场情绪分析师", "value": "sentiment", "selected": "sentiment" in defaults},
        {"label": "新闻分析师", "value": "news", "selected": "news" in defaults},
    ]


def _analysis_config(selected_values: list[str] | None) -> dict[str, bool]:
    selected = {str(item) for item in selected_values or [] if str(item).strip()}
    return {
        "technical": "technical" in selected,
        "fundamental": "fundamental" in selected,
        "fund_flow": "fund_flow" in selected,
        "risk": "risk" in selected,
        "sentiment": "sentiment" in selected,
        "news": "news" in selected,
    }


def _analysis_agent_title(agent_key: str) -> str:
    mapping = {
        "technical": "技术分析师",
        "fundamental": "基本面分析师",
        "fund_flow": "资金面分析师",
        "risk_management": "风险管理师",
        "market_sentiment": "市场情绪分析师",
        "news": "新闻分析师",
        "risk": "风险管理师",
        "sentiment": "市场情绪分析师",
    }
    return mapping.get(agent_key, f"{agent_key}分析师")


def _indicator_value(indicators: dict[str, Any], aliases: list[str]) -> Any:
    for alias in aliases:
        if alias in indicators:
            return indicators.get(alias)
    lowered = {str(key).lower(): value for key, value in indicators.items()}
    for alias in aliases:
        alias_lower = str(alias).lower()
        if alias_lower in lowered:
            return lowered.get(alias_lower)
    return None


def _format_indicator_cards(indicators: dict[str, Any] | None, explanations: Any) -> list[dict[str, str]]:
    if isinstance(explanations, list):
        return [{"label": _txt(item.get("label")), "value": _txt(item.get("value"))} for item in explanations if isinstance(item, dict)]
    cards: list[dict[str, str]] = []
    indicators = indicators or {}
    explanation_map = explanations if isinstance(explanations, dict) else {}
    specs = [
        ("现价", ["price", "close", "Close"], "当前最新成交价，用于判断趋势位置与止盈止损空间。"),
        ("MA5", ["ma5", "MA5"], "5日均线，反映短线节奏。"),
        ("MA10", ["ma10", "MA10"], "10日均线，反映短中线过渡趋势。"),
        ("MA20", ["ma20", "MA20"], "20日均线，常用作中期强弱分界。"),
        ("MA60", ["ma60", "MA60"], "60日均线，反映中长期趋势方向。"),
        ("RSI", ["rsi", "RSI"], "相对强弱指标，判断是否偏热或偏冷。"),
        ("MACD", ["macd", "MACD"], "趋势动能指标，正值偏多、负值偏空。"),
        ("信号线", ["macd_signal", "MACD_signal"], "MACD信号线，用于观察动能拐点。"),
        ("布林上轨", ["bb_upper", "BB_upper"], "价格波动上沿，靠近上轨通常波动加大。"),
        ("布林下轨", ["bb_lower", "BB_lower"], "价格波动下沿，跌近下轨需结合成交量判断。"),
        ("K值", ["k_value", "K"], "KDJ快线，反映短周期价格敏感变化。"),
        ("D值", ["d_value", "D"], "KDJ慢线，和K值交叉可辅助判断转折。"),
        ("量比", ["volume_ratio", "Volume_ratio"], "当前成交活跃度，相对历史均量的强弱。"),
    ]
    for label, aliases, fallback_hint in specs:
        value = _indicator_value(indicators, aliases)
        detail = explanation_map.get(label) if isinstance(explanation_map.get(label), dict) else None
        if value is None and detail:
            value = detail.get("state") or detail.get("summary")
        hint = _txt(detail.get("summary")) if detail else fallback_hint
        cards.append(
            {
                "label": label,
                "value": _txt(_num(value, 2) if isinstance(value, (int, float)) else value, "--"),
                "hint": _txt(hint, fallback_hint),
            }
        )
    return cards


def _analysis_curve(points: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    curve: list[dict[str, Any]] = []
    for item in points or []:
        if not isinstance(item, dict):
            continue
        label = _txt(item.get("date") or item.get("日期") or item.get("datetime"))
        value = item.get("close") or item.get("收盘") or item.get("value")
        try:
            curve.append({"label": label, "value": float(value)})
        except (TypeError, ValueError):
            continue
    return curve


def _build_workbench_analysis_payload(
    *,
    code: str,
    stock_name: str,
    selected: list[str] | None,
    mode: str,
    cycle: str,
    generated_at: str,
    stock_info: dict[str, Any],
    indicators: dict[str, Any],
    discussion_result: Any,
    final_decision: dict[str, Any],
    agents_results: dict[str, Any],
    historical_data: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    indicator_explanations = stock_analysis_service.build_indicator_explanations(
        indicators,
        current_price=stock_info.get("current_price"),
    )
    summary_body = _txt(_dict_value(discussion_result, "summary")) or _txt(discussion_result)
    if not summary_body:
        summary_body = _txt(stock_analysis_service.build_indicator_summary(indicator_explanations), "分析完成。")
    summary_body = _snippet(summary_body, 1200, "分析完成。")

    analyst_views: list[dict[str, Any]] = []
    insights: list[dict[str, Any]] = []
    decision_rating = _txt(
        _first_non_empty(final_decision, ["decision", "rating", "verdict"]),
        "暂无明确结论",
    )
    operation_advice = _txt(_dict_value(final_decision, "operation_advice"))
    final_reasoning = _txt(_dict_value(final_decision, "reasoning")) or operation_advice or _txt(_dict_value(final_decision, "decision_text"))
    if final_reasoning:
        insights.append(_insight("操作建议", _snippet(final_reasoning, 500), "accent"))
    risk_warning = _txt(_dict_value(final_decision, "risk_warning"))
    if risk_warning:
        insights.append(_insight("风险提示", _snippet(risk_warning, 400), "warning"))
    decision_detail_lines = [f"- 投资评级：{decision_rating}"]
    detail_fields = [
        ("目标价位", "target_price"),
        ("进场区间", "entry_range"),
        ("止盈位置", "take_profit"),
        ("止损位置", "stop_loss"),
        ("持有周期", "holding_period"),
        ("仓位建议", "position_size"),
        ("信心度", "confidence_level"),
    ]
    for label, key in detail_fields:
        value = _txt(_dict_value(final_decision, key))
        if value:
            decision_detail_lines.append(f"- {label}：{value}")
    final_decision_text = "\n".join(decision_detail_lines)

    for key, agent_result in agents_results.items():
        if not isinstance(agent_result, dict):
            continue
        agent_text = _txt(_first_non_empty(agent_result, ["summary", "analysis", "decision_text", "result"]))
        if not agent_text:
            continue
        agent_name = _txt(agent_result.get("agent_name"), _analysis_agent_title(key))
        analyst_views.append(_insight(agent_name, _snippet(agent_text, 800)))

    return {
        "symbol": code,
        "analysts": _analysis_options(selected),
        "mode": mode,
        "cycle": cycle,
        "inputHint": "例如 600519 / 300390 / AAPL",
        "summaryTitle": f"{stock_name} 分析摘要",
        "summaryBody": summary_body,
        "generatedAt": _txt(generated_at, _now()),
        "indicators": _format_indicator_cards(indicators, indicator_explanations),
        "decision": decision_rating,
        "finalDecisionText": final_decision_text,
        "insights": insights or [_insight("当前结论", "分析完成，但当前没有更多结构化解读。")],
        "analystViews": analyst_views,
        "curve": _analysis_curve(historical_data),
    }


def _build_workbench_snapshot(
    context: UIApiContext,
    *,
    analysis: dict[str, Any] | None = None,
    activity: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    summary = context.portfolio().get_account_summary()
    watchlist = _watchlist_rows(context)
    quant_count = sum(1 for row in watchlist if row["cells"][5] == "已入量化")
    active_symbol = _txt(analysis.get("symbol")) if isinstance(analysis, dict) else _txt(watchlist[0]["code"]) if watchlist else ""
    cached_analysis = analysis
    if not cached_analysis:
        latest_record = context.stock_analysis_db().get_latest_record_by_symbol(active_symbol) if active_symbol else None
        if not latest_record:
            records = context.stock_analysis_db().get_all_records()
            latest_id = _int(records[0].get("id")) if records else None
            latest_record = context.stock_analysis_db().get_record_by_id(latest_id) if latest_id else None
        if latest_record:
            resolved_symbol = normalize_stock_code(_txt(latest_record.get("symbol"), active_symbol))
            if not active_symbol:
                active_symbol = resolved_symbol
            record_stock_info = latest_record.get("stock_info") if isinstance(latest_record.get("stock_info"), dict) else {}
            record_indicators = latest_record.get("indicators") if isinstance(latest_record.get("indicators"), dict) else {}
            record_discussion = latest_record.get("discussion_result")
            record_final_decision = latest_record.get("final_decision") if isinstance(latest_record.get("final_decision"), dict) else {}
            record_agents = latest_record.get("agents_results") if isinstance(latest_record.get("agents_results"), dict) else {}
            record_historical = latest_record.get("historical_data") if isinstance(latest_record.get("historical_data"), list) else []
            cached_analysis = _build_workbench_analysis_payload(
                code=resolved_symbol,
                stock_name=_txt(latest_record.get("stock_name"), resolved_symbol),
                selected=None,
                mode="单个分析",
                cycle=_txt(latest_record.get("period"), "1y"),
                generated_at=_txt(latest_record.get("analysis_date") or latest_record.get("created_at"), _now()),
                stock_info=record_stock_info,
                indicators=record_indicators,
                discussion_result=record_discussion,
                final_decision=record_final_decision,
                agents_results=record_agents,
                historical_data=record_historical,
            )
    return {
        "updatedAt": _now(),
        "metrics": [
            _metric("我的关注", len(watchlist)),
            _metric("我的持仓", summary.get("position_count", 0)),
            _metric("量化候选", quant_count),
            _metric("量化任务", len(context.quant_db().get_sim_runs(limit=1000))),
        ],
        "watchlist": _table(["代码", "名称", "现价", "来源", "状态", "量化状态"], watchlist, "我的关注还是空的。"),
        "watchlistMeta": {
            "selectedCount": 0,
            "quantCount": quant_count,
            "refreshHint": "报价支持手动刷新，量化调度运行时也会把最新价格和信号回写到这里。",
        },
        "analysis": cached_analysis
        or {
            "symbol": active_symbol,
            "analysts": _analysis_options(),
            "mode": "单个分析",
            "cycle": "1y",
            "inputHint": "例如 600519 / 300390 / AAPL",
            "summaryTitle": "最近分析摘要",
            "summaryBody": "先从我的关注里添加股票，再开始分析。",
            "indicators": [],
            "decision": "先看我的关注，再决定是否推进到量化候选池。",
            "insights": [
                _insight("当前风格", "工作台聚合了关注、分析和下一步动作。"),
                _insight("执行提示", "从关注池进入候选池后，量化模拟会直接读取同一份数据。"),
            ],
            "curve": [],
        },
        "nextSteps": [
            {"label": "持仓分析", "hint": "查看当前持仓、收益归因和仓位动作", "href": "/portfolio"},
            {"label": "实时监控", "hint": "看价格规则、触发记录和通知状态", "href": "/real-monitor"},
            {"label": "AI盯盘", "hint": "连续盯盘、生成信号并回看事件时间线", "href": "/ai-monitor"},
            {"label": "发现股票", "hint": "进入选股聚合页，挑出新的关注对象", "href": "/discover"},
            {"label": "研究情报", "hint": "聚合板块、龙虎榜、新闻和宏观判断", "href": "/research"},
            {"label": "量化模拟", "hint": "围绕量化候选池做实时模拟", "href": "/live-sim"},
            {"label": "历史回放", "hint": "用同一候选池回看历史表现", "href": "/his-replay"},
        ],
        "activity": activity
        or [_timeline(_now(), "工作台初始化", "当前没有量化运行记录，关注池和候选池将从这里开始。")],
    }


def _snapshot_workbench(context: UIApiContext) -> dict[str, Any]:
    return _build_workbench_snapshot(context)


def _snapshot_discover(context: UIApiContext) -> dict[str, Any]:
    snapshots = _discover_strategy_snapshots(context)
    rows = _discover_rows(context)
    latest_snapshot = snapshots[0] if snapshots else {}
    latest_row = rows[0] if rows else {}
    latest_selected_at = _txt(latest_snapshot.get("selected_at") or latest_row.get("selectedAt") or _now())
    latest_count = len(rows)
    strategy_lookup = {str(snapshot.get("key")): snapshot for snapshot in snapshots}
    strategy_defs = [
        ("main_force", "主力选股", "主资金流 + 财务过滤 + AI精选"),
        ("low_price_bull", "低价擒牛", "低价高弹性标的挖掘"),
        ("small_cap", "小市值", "小而活跃的成长标的"),
        ("profit_growth", "净利增长", "盈利增长趋势筛选"),
        ("value_stock", "低估值", "估值修复方向"),
    ]
    strategy_cards = []
    for strategy_key, strategy_name, strategy_note in strategy_defs:
        snapshot = strategy_lookup.get(strategy_key)
        snapshot_rows = snapshot.get("rows", []) if snapshot else []
        selected_at = _txt(snapshot.get("selected_at"), "--") if snapshot else "--"
        strategy_cards.append(
            {
                "name": strategy_name,
                "note": strategy_note,
                "status": f"最近推荐 {len(snapshot_rows)} 只" if snapshot_rows else "待运行",
                "highlight": _txt(selected_at if selected_at != "--" else "等待最新结果"),
                "selectedAt": selected_at,
                "count": len(snapshot_rows),
            }
        )
    return {
        "updatedAt": _now(),
        "metrics": [_metric("发现策略", 5), _metric("最近候选股票", len(rows)), _metric("加入我的关注", len(context.watchlist().list_watches())), _metric("最近一次运行", latest_selected_at)],
        "strategies": strategy_cards,
        "summary": {
            "title": _txt(
                latest_snapshot.get("name")
                or latest_row.get("strategyName")
                or "发现策略聚合结果"
            ),
            "body": _txt(
                (
                    f"已汇总 {len(snapshots)} 个发现策略的最新结果，共 {latest_count} 只候选，最近一次更新时间 {latest_selected_at}。"
                    + (
                        f" 最新策略：{_txt(latest_snapshot.get('note'))}。"
                        if _txt(latest_snapshot.get("note"))
                        else ""
                    )
                    if rows
                    else "先运行选股策略，再把真正需要跟踪的股票加入我的关注。"
                )
            ),
        },
        "candidateTable": _table(["代码", "名称", "所属行业", "来源策略", "最新价", "总市值(亿)", "市盈率", "市净率"], rows, "暂无候选股票"),
        "recommendation": {
            "title": "精选推荐",
            "body": "这部分保留模型综合筛选后的优先关注名单，支持单只或批量加入我的关注。",
            "chips": [f"⭐ 最近 {latest_count} 只候选", f"📌 {len(snapshots)} 个策略", "⭐ 加入所选关注池", "⭐ 加入单只关注池"],
        },
    }


def _snapshot_research(context: UIApiContext) -> dict[str, Any]:
    payload = load_latest_result(context.research_result_key, base_dir=context.selector_result_dir) or {}
    modules = payload.get("modules") if isinstance(payload.get("modules"), list) else [{"name": "智策板块", "note": "热点方向和板块轮动判断", "output": "市场判断"}, {"name": "智瞰龙虎", "note": "龙虎榜席位行为和异常波动", "output": "市场判断"}, {"name": "新闻流量", "note": "新闻热度和情绪脉冲", "output": "市场判断"}, {"name": "宏观分析", "note": "总量、流动性和风险偏好", "output": "市场判断"}, {"name": "宏观周期", "note": "周期阶段与资产偏好", "output": "市场判断"}]
    market_view = payload.get("marketView") if isinstance(payload.get("marketView"), list) else [_insight("市场判断", "大盘情绪偏震荡，风险偏好没有恢复到趋势市状态。", "warning"), _insight("风格轮动", "消费和高股息偏防御，科技高弹性需要更强资金确认。")]
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {"title": "研究情报", "body": "研究情报默认先给出市场判断；只有模块产出明确股票时，才出现加入我的关注动作。"}
    return {
        "updatedAt": _now(),
        "modules": [{"name": _txt(item.get("name"), f"模块{i + 1}"), "note": _txt(item.get("note") or item.get("body")), "output": _txt(item.get("output") or item.get("status"))} for i, item in enumerate(modules) if isinstance(item, dict)],
        "marketView": market_view,
        "outputTable": _table(["代码", "名称", "来源模块", "后续动作"], _research_rows(context), "暂无股票输出"),
        "summary": {"title": _txt(summary.get("title") or "研究情报"), "body": _txt(summary.get("body") or "研究情报默认先给出市场判断。")},
    }


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
    if not run:
        return {"updatedAt": _now(), "config": {"mode": "历史区间", "range": "--", "timeframe": "30m", "market": "CN", "strategyMode": "auto"}, "metrics": [_metric("回放结果", "--"), _metric("最终总权益", "--"), _metric("交易笔数", "0"), _metric("胜率", "--")], "candidatePool": _table(["股票代码", "股票名称", "最新价格"], [], "暂无候选股票"), "tasks": [], "tradingAnalysis": {"title": "交易分析", "body": "暂无回放记录。", "chips": []}, "holdings": _table(["代码", "名称", "数量", "成本", "现价", "浮盈亏"], [], "暂无持仓"), "trades": _table(["时间", "代码", "动作", "数量", "价格", "备注"], [], "暂无交易记录"), "signals": _table(["时间", "代码", "动作", "策略", "执行结果"], [], "暂无信号"), "curve": []}
    rid = int(run["id"])
    return {"updatedAt": _now(), "config": {"mode": _txt(run.get("mode"), "historical_range"), "range": f"{_txt(run.get('start_datetime'), '--')} -> {_txt(run.get('end_datetime'), 'now')}", "timeframe": _txt(run.get("timeframe"), "30m"), "market": _txt(run.get("market"), "CN"), "strategyMode": _txt(run.get("selected_strategy_mode") or run.get("strategy_mode"), "auto")}, "metrics": [_metric("回放结果", _pct(run.get("total_return_pct"))), _metric("最终总权益", _num(run.get("final_equity"), 0)), _metric("交易笔数", _txt(run.get("trade_count"), "0")), _metric("胜率", _pct(run.get("win_rate")))], "candidatePool": _table(["股票代码", "股票名称", "最新价格"], [{"id": _txt(item.get("stock_code"), str(i)), "cells": [_txt(item.get("stock_code")), _txt(item.get("stock_name")), _num(item.get("latest_price"))], "code": _txt(item.get("stock_code")), "name": _txt(item.get("stock_name")), "latestPrice": _num(item.get("latest_price"))} for i, item in enumerate(context.candidate_pool().list_candidates(status="active"))], "暂无候选股票"), "tasks": [{"id": f"#{item.get('id')}", "status": _txt(item.get("status"), "completed"), "range": f"{_txt(item.get('start_datetime'), '--')} -> {_txt(item.get('end_datetime'), 'now')}", "note": _txt(item.get("status_message") or f"{item.get('checkpoint_count', 0)} 个检查点")} for item in runs[:10]], "tradingAnalysis": {"title": "交易分析", "body": "回放页会把交易分析拆成“人话结论 + 策略解释 + 量化证据”三层。", "chips": [_txt(f"已实现盈亏 {run.get('realized_pnl', 0)}"), _txt(f"最终总权益 {run.get('final_equity', 0)}"), _txt(f"交易笔数 {run.get('trade_count', 0)}")]}, "holdings": _table(["代码", "名称", "数量", "成本", "现价", "浮盈亏"], [{"id": _txt(item.get("stock_code"), str(i)), "cells": [_txt(item.get("stock_code")), _txt(item.get("stock_name")), _txt(item.get("quantity"), "0"), _num(item.get("avg_price")), _num(item.get("latest_price")), _pct(item.get("unrealized_pnl"))], "code": _txt(item.get("stock_code")), "name": _txt(item.get("stock_name"))} for i, item in enumerate(db.get_sim_run_positions(rid))], "暂无持仓"), "trades": _table(["时间", "代码", "动作", "数量", "价格", "备注"], [{"id": _txt(item.get("id"), str(i)), "cells": [_txt(item.get("executed_at") or item.get("created_at"), "--"), _txt(item.get("stock_code")), _txt(item.get("action")), _txt(item.get("quantity"), "0"), _num(item.get("price")), _txt(item.get("note") or "自动执行")]} for i, item in enumerate(db.get_sim_run_trades(rid))], "暂无交易记录"), "signals": _table(["时间", "代码", "动作", "策略", "执行结果"], [{"id": _txt(item.get("id"), str(i)), "cells": [_txt(item.get("created_at") or item.get("checkpoint_at"), "--"), _txt(item.get("stock_code")), _txt(item.get("action")), _txt(item.get("decision_type") or "自动"), _txt(item.get("signal_status") or item.get("execution_note") or "待处理")], "actions": [{"label": "详情", "icon": "🔎"}]} for i, item in enumerate(db.get_sim_run_signals(rid))], "暂无信号"), "curve": [{"label": _txt(item.get("created_at"), str(i)), "value": float(item.get("total_equity") or 0)} for i, item in enumerate(db.get_sim_run_snapshots(rid))]}


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


def _action_discover_item(context: UIApiContext, payload: dict[str, Any]) -> dict[str, Any]:
    code = _code_from_payload(payload)
    if not code:
        raise HTTPException(status_code=400, detail="Missing stock code")
    row = next((item for item in _discover_rows(context) if item["code"] == code), None)
    if not row:
        raise HTTPException(status_code=404, detail=f"Discover row not found: {code}")
    add_stock_to_watchlist(code, row["name"], row.get("source") or "主力选股", latest_price=float(row.get("latestPrice") or 0) if row.get("latestPrice") else None, notes=row.get("reason"), metadata={"industry": row.get("industry")}, db_file=context.watchlist_db_file)
    return _snapshot_discover(context)


def _action_research_item(context: UIApiContext, payload: dict[str, Any]) -> dict[str, Any]:
    code = _code_from_payload(payload)
    if not code:
        raise HTTPException(status_code=400, detail="Missing stock code")
    row = next((item for item in _research_rows(context) if item["code"] == code), None)
    if not row:
        raise HTTPException(status_code=404, detail=f"Research row not found: {code}")
    add_research_stock_to_watchlist(row, source=row.get("source") or "研究情报", db_file=context.watchlist_db_file)
    return _snapshot_research(context)


def _action_research_batch(context: UIApiContext, payload: dict[str, Any]) -> dict[str, Any]:
    rows = [item for item in _research_rows(context) if item["code"] in _normalize_codes(payload) or not _normalize_codes(payload)]
    if rows:
        add_research_stocks_to_watchlist(rows, source="研究情报", db_file=context.watchlist_db_file)
    return _snapshot_research(context)


def _action_research_run_module(context: UIApiContext, payload: dict[str, Any]) -> dict[str, Any]:
    _run_research_modules(context, payload)
    return _snapshot_research(context)


def _action_discover_batch(context: UIApiContext, payload: dict[str, Any]) -> dict[str, Any]:
    codes = _normalize_codes(payload)
    rows = [item for item in _discover_rows(context) if item["code"] in codes or not codes]
    for row in rows:
        add_stock_to_watchlist(
            row["code"],
            row["name"],
            row.get("source") or "主力选股",
            latest_price=float(row.get("latestPrice") or 0) if row.get("latestPrice") else None,
            notes=row.get("reason"),
            metadata={"industry": row.get("industry")},
            db_file=context.watchlist_db_file,
        )
    return _snapshot_discover(context)


def _build_main_force_discover_result(stocks_df: Any, top_n: int) -> dict[str, Any]:
    try:
        rows = stocks_df.to_dict(orient="records")
    except Exception:
        rows = []

    recommendations: list[dict[str, Any]] = []
    for item in rows[:top_n]:
        if not isinstance(item, dict):
            continue
        code = normalize_stock_code(
            item.get("股票代码") or item.get("stock_code") or item.get("code") or item.get("symbol")
        )
        if not code:
            continue
        recommendations.append(
            {
                "symbol": code,
                "code": code,
                "name": _txt(item.get("股票简称") or item.get("股票名称") or item.get("name") or code, code),
                "source": "主力选股",
                "highlights": _txt(item.get("理由") or item.get("说明") or item.get("备注") or "主力资金流与筛选条件命中"),
                "stock_data": dict(item),
            }
        )

    return {
        "success": True,
        "total_stocks": len(rows),
        "filtered_stocks": len(rows),
        "final_recommendations": recommendations,
        "error": None,
    }


def _run_discover_strategies(context: UIApiContext, payload: dict[str, Any]) -> None:
    selected = set(_normalize_discover_strategy_selection(payload))
    selected_at = _now()
    top_n = max(_int(payload.get("topN"), 5) or 5, 1)

    if "main_force" in selected:
        try:
            success, stocks_df, _ = _selector_cls("MainForceStockSelector")().get_main_force_stocks(
                days_ago=_int(payload.get("daysAgo"), 90) or 90
            )
            if success and stocks_df is not None and not getattr(stocks_df, "empty", False):
                analyzer = SimpleNamespace(
                    raw_stocks=stocks_df,
                    fund_flow_analysis=None,
                    industry_analysis=None,
                    fundamental_analysis=None,
                )
                save_main_force_state(
                    result=_build_main_force_discover_result(stocks_df, top_n),
                    analyzer=analyzer,
                    selected_at=selected_at,
                    base_dir=context.selector_result_dir,
                )
        except Exception:
            pass

    simple_strategies: list[tuple[str, Callable[[], tuple[bool, Any, str]]]] = [
        ("low_price_bull", lambda: _selector_cls("LowPriceBullSelector")().get_low_price_stocks(top_n=top_n)),
        ("small_cap", lambda: _selector_cls("SmallCapSelector")().get_small_cap_stocks(top_n=top_n)),
        ("profit_growth", lambda: _selector_cls("ProfitGrowthSelector")().get_profit_growth_stocks(top_n=top_n)),
        ("value_stock", lambda: _selector_cls("ValueStockSelector")().get_value_stocks(top_n=max(top_n, 10))),
    ]
    for strategy_key, runner in simple_strategies:
        if strategy_key not in selected:
            continue
        try:
            success, stocks_df, _ = runner()
            if success and stocks_df is not None:
                save_simple_selector_state(
                    strategy_key=strategy_key,
                    stocks_df=stocks_df,
                    selected_at=selected_at,
                    base_dir=context.selector_result_dir,
                )
        except Exception:
            continue


def _action_discover_run_strategy(context: UIApiContext, payload: Any) -> dict[str, Any]:
    _run_discover_strategies(context, _payload_dict(payload))
    return _snapshot_discover(context)


def _action_workbench_batch_quant(context: UIApiContext, payload: dict[str, Any]) -> dict[str, Any]:
    codes = _normalize_codes(payload) or [row["code"] for row in _watchlist_rows(context)]
    add_watchlist_rows_to_quant_pool(codes, watchlist_service=context.watchlist(), candidate_service=context.candidate_pool(), db_file=context.quant_sim_db_file)
    return _snapshot_workbench(context)


def _action_workbench_add_watchlist(context: UIApiContext, payload: dict[str, Any]) -> dict[str, Any]:
    code = _code_from_payload(payload)
    if not code:
        raise HTTPException(status_code=400, detail="Missing stock code")
    context.watchlist().add_manual_stock(code)
    return _snapshot_workbench(context)


def _action_workbench_refresh(context: UIApiContext, payload: dict[str, Any]) -> dict[str, Any]:
    context.watchlist().refresh_quotes(_normalize_codes(payload) or None)
    return _snapshot_workbench(context)


def _action_workbench_delete(context: UIApiContext, payload: dict[str, Any]) -> dict[str, Any]:
    code = _code_from_payload(payload)
    if code:
        context.watchlist().delete_stock(code)
    return _snapshot_workbench(context)


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


def _action_workbench_analysis(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    code = _code_from_payload(body)
    if not code:
        raise HTTPException(status_code=400, detail="Missing stock code")
    selected = body.get("analysts")
    if not isinstance(selected, list):
        selected = []
    cycle = _txt(body.get("cycle"), "1y")
    mode = _txt(body.get("mode"), "单个分析")
    result = stock_analysis_service.analyze_single_stock_for_batch(
        code,
        cycle,
        enabled_analysts_config=_analysis_config(selected),
        selected_model=None,
    )
    if not result or not result.get("success"):
        raise HTTPException(status_code=502, detail=f"分析失败: {code}")

    stock_info = result.get("stock_info") if isinstance(result.get("stock_info"), dict) else {}
    stock_name = _txt(stock_info.get("name"), code)
    indicators = result.get("indicators") if isinstance(result.get("indicators"), dict) else {}
    discussion_result = result.get("discussion_result")
    final_decision = _dict_value(result, "final_decision", {})
    agents_results = result.get("agents_results") if isinstance(result.get("agents_results"), dict) else {}
    historical_data = result.get("historical_data") if isinstance(result.get("historical_data"), list) else []

    context.stock_analysis_db().save_analysis(
        symbol=code,
        stock_name=stock_name,
        period=cycle,
        stock_info=stock_info,
        agents_results=agents_results,
        discussion_result=discussion_result,
        final_decision=final_decision,
        indicators=indicators,
        historical_data=historical_data,
    )

    analysis = _build_workbench_analysis_payload(
        code=code,
        stock_name=stock_name,
        selected=selected,
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
    return _build_workbench_snapshot(
        context,
        analysis=analysis,
        activity=[_timeline(_now(), f"{stock_name} 分析完成", _snippet(_txt(_dict_value(discussion_result, "summary")) or _txt(discussion_result), 160, "分析完成。"))],
    )


def _action_workbench_analysis_batch(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    codes = _normalize_codes(body.get("stockCodes") if isinstance(body, dict) else payload)
    if not codes:
        raise HTTPException(status_code=400, detail="Missing stock codes")
    selected = body.get("analysts")
    if not isinstance(selected, list):
        selected = []
    cycle = _txt(body.get("cycle"), "1y")
    mode = _txt(body.get("mode"), "批量分析")
    insights: list[dict[str, Any]] = []
    curve: list[dict[str, Any]] = []
    for code in codes[:5]:
        result = stock_analysis_service.analyze_single_stock_for_batch(
            code,
            cycle,
            enabled_analysts_config=_analysis_config(selected),
            selected_model=None,
        )
        if not result or not result.get("success"):
            continue
        stock_info_batch = result.get("stock_info") if isinstance(result.get("stock_info"), dict) else {}
        stock_name = _txt(stock_info_batch.get("name"), code)
        final_decision = _dict_value(result, "final_decision", {})
        decision = _txt(_first_non_empty(final_decision, ["decision", "rating", "verdict"]), "暂无结论")
        reasoning = _txt(_first_non_empty(final_decision, ["reasoning", "operation_advice", "decision_text"]))
        if not reasoning:
            discussion_result = result.get("discussion_result")
            reasoning = _txt(_dict_value(discussion_result, "summary")) or _txt(discussion_result, "已完成批量分析。")
        insights.append(_insight(stock_name, f"{decision} · {reasoning}"))
        if not curve:
            curve = _analysis_curve(result.get("historical_data"))
    count_label = str(len(codes))
    analysis = {
        "symbol": ",".join(codes),
        "analysts": _analysis_options(selected),
        "mode": mode,
        "cycle": cycle,
        "inputHint": "例如 600519 / 300390 / AAPL",
        "summaryTitle": f"批量分析摘要 · {count_label} 只股票",
        "summaryBody": f"本次批量分析覆盖 {count_label} 只股票，结果会统一汇总到工作台中继续推进。",
        "indicators": [],
        "decision": "优先查看每只股票的结论摘要，再决定是否推进到量化候选池。",
        "insights": insights or [_insight("批量分析", "当前没有可展示的批量分析结果。")],
        "curve": curve,
    }
    return _build_workbench_snapshot(
        context,
        analysis=analysis,
        activity=[_timeline(_now(), "批量分析完成", f"本次共处理 {count_label} 只股票。")],
    )


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

