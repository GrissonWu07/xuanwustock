from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from app.async_task_base import AsyncTaskManagerBase
from app.gateway_common import (
    RESEARCH_MODULE_MAX_PARALLEL,
    code_from_payload as _code_from_payload,
    insight as _insight,
    int_value as _int,
    looks_like_stock_code as _looks_like_stock_code,
    metric as _metric,
    normalize_codes as _normalize_codes,
    now as _now,
    num as _num,
    payload_dict as _payload_dict,
    table as _table,
    txt as _txt,
)
from app.i18n import t
from app.research_watchlist_integration import add_research_stock_to_watchlist, add_research_stocks_to_watchlist
from app.sector_strategy_engine import SectorStrategyEngine
from app.selector_result_store import delete_latest_result, load_latest_result, save_latest_result
from app.stock_refresh_scheduler import load_stock_runtime_entries
from app.ui_table_cache_db import UITableCacheDB
from app.watchlist_selector_integration import normalize_stock_code

SectorStrategyDataFetcher = None
LonghubangEngine = None
NewsFlowEngine = None
MacroAnalysisEngine = None
MacroCycleEngine = None


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


def _research_rows(context: Any) -> list[dict[str, Any]]:
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
                "cells": [
                    code,
                    _txt(item.get("name") or item.get("stock_name") or code),
                    _txt(item.get("source") or item.get("source_module") or item.get("来源模块") or t("Research")),
                    _txt(item.get("reason") or item.get("body") or item.get("后续动作") or ""),
                ],
                "actions": [{"label": t("Add to watchlist"), "icon": "⭐", "tone": "accent", "action": "item-watchlist"}],
                "code": code,
                "name": _txt(item.get("name") or item.get("stock_name") or code),
                "source": _txt(item.get("source") or item.get("source_module") or item.get("来源模块") or t("Research")),
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
                "cells": [code, name, _txt(item.get("name") or t("Research module")), _txt(item.get("note") or item.get("output") or "")],
                "actions": [{"label": t("Add to watchlist"), "icon": "⭐", "tone": "accent", "action": "item-watchlist"}],
                "code": code,
                "name": name,
                "source": _txt(item.get("name") or t("Research module")),
                "latestPrice": "0.00",
                "reason": _txt(item.get("note") or item.get("output") or ""),
            }
        )
    runtime_entries = load_stock_runtime_entries(base_dir=context.selector_result_dir)
    if runtime_entries:
        for row in rows:
            runtime = runtime_entries.get(normalize_stock_code(row.get("code")))
            if not isinstance(runtime, dict):
                continue
            runtime_name = _txt(runtime.get("stock_name"))
            runtime_price = runtime.get("latest_price")
            runtime_sector = _txt(runtime.get("sector"))
            if runtime_name:
                row["name"] = runtime_name
                if len(row.get("cells", [])) > 1:
                    row["cells"][1] = runtime_name
            if runtime_price not in (None, ""):
                row["latestPrice"] = _num(runtime_price)
            if runtime_sector:
                row["industry"] = runtime_sector
    return rows


def _research_stock_row(stock: dict[str, Any], source: str, context: Any) -> dict[str, Any] | None:
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
        "actions": [{"label": t("Add to watchlist"), "icon": "⭐", "tone": "accent", "action": "item-watchlist"}],
        "code": code,
        "name": name,
        "source": source,
        "latestPrice": latest_price,
        "reason": reason,
    }


def _research_stock_rows(stocks: Any, source: str, context: Any) -> list[dict[str, Any]]:
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
    return [_insight(name, _txt(text), tone)]


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
        "sector": {"sector", "strategy", "sector_strategy", "sector"},
        "longhubang": {"longhubang", "dragon_tiger", "dragontiger"},
        "news": {"news", "news-flow", "news_flow"},
        "macro": {"macro", "macro_analysis"},
        "cycle": {"cycle", "macro_cycle"},
    }

    selected: list[str] = []
    for key, synonyms in aliases.items():
        if any(value in synonyms for value in values):
            selected.append(key)

    return selected or ["sector", "longhubang", "news", "macro", "cycle"]


def _resolve_research_top_n(context: Any) -> int:
    default_top_n = 10
    config_manager = getattr(context, "config_manager", None)
    if config_manager is None:
        return default_top_n
    try:
        config = config_manager.read_env()
    except Exception:
        return default_top_n
    configured = _int(config.get("RESEARCH_TOP_N"), default_top_n) if isinstance(config, dict) else default_top_n
    return max(1, min(configured or default_top_n, 200))


def _run_research_module_sector(context: Any) -> dict[str, Any]:
    fetcher = _research_cls("SectorStrategyDataFetcher")()
    data = fetcher.get_cached_data_with_fallback()
    if not data.get("success"):
        note = _txt(data.get("cache_warning") or data.get("message") or data.get("error") or t("Failed to fetch sector data"))
        return {
            "name": t("Sector strategy"),
            "note": note,
            "output": t("Data fetch failed"),
            "rows": [],
            "marketView": [_insight(t("Sector strategy"), note, "warning")],
        }

    result = SectorStrategyEngine().run_comprehensive_analysis(data)
    final_predictions = result.get("final_predictions", {}) if isinstance(result, dict) else {}
    bullish = final_predictions.get("long_short", {}).get("bullish", []) if isinstance(final_predictions, dict) else []
    bearish = final_predictions.get("long_short", {}).get("bearish", []) if isinstance(final_predictions, dict) else []
    chief_text = result.get("agents_analysis", {}).get("chief", {}).get("analysis", "") if isinstance(result, dict) else ""
    note = _txt(
        result.get("comprehensive_report") or final_predictions.get("summary") or chief_text or t("Sector strategy completed"),
    )
    output = t("Bullish {bullish} / Bearish {bearish}", bullish=len(bullish), bearish=len(bearish))
    market_view = _research_market_views_from_module(t("Sector strategy"), note, "neutral")
    return {
        "name": t("Sector strategy"),
        "note": note,
        "output": output,
        "rows": [],
        "marketView": market_view,
    }


def _run_research_module_longhubang(context: Any) -> dict[str, Any]:
    result = _research_cls("LonghubangEngine")().run_comprehensive_analysis(days=1)
    stocks = _research_stock_rows(result.get("recommended_stocks", []), t("Dragon tiger list"), context)
    chief_text = result.get("agents_analysis", {}).get("chief", {}).get("analysis", "") if isinstance(result, dict) else ""
    note = _txt(chief_text or result.get("final_report", {}).get("summary", "") or t("Dragon tiger analysis completed"))
    output = t("Stock output: {count}", count=len(stocks)) if stocks else _txt(note, t("Analysis completed"))
    return {
        "name": t("Dragon tiger list"),
        "note": note,
        "output": output,
        "rows": stocks,
        "marketView": _research_market_views_from_module(t("Dragon tiger list"), note, "neutral"),
    }


def _run_research_module_news(context: Any) -> dict[str, Any]:
    result = _research_cls("NewsFlowEngine")().run_full_analysis(include_ai=True)
    ai_analysis = result.get("ai_analysis", {}) if isinstance(result, dict) else {}
    stock_recommend = ai_analysis.get("stock_recommend", {}) if isinstance(ai_analysis, dict) else {}
    stocks = _research_stock_rows(stock_recommend.get("recommended_stocks", []), t("News flow"), context)
    advice = ai_analysis.get("investment_advice", {}) if isinstance(ai_analysis, dict) else {}
    note = _txt(
        advice.get("summary")
        or advice.get("advice")
        or result.get("trading_signals", {}).get("operation_advice")
        or t("News flow analysis completed"),
    )
    market_view: list[dict[str, Any]] = []
    if advice.get("advice"):
        market_view.append(_insight(t("News flow"), _txt(advice.get("summary") or advice.get("advice")), "accent"))
    if result.get("trading_signals", {}).get("operation_advice"):
        market_view.append(_insight(t("Trading signal"), _txt(result.get("trading_signals", {}).get("operation_advice")), "warning"))
    output = t("Stock output: {count}", count=len(stocks)) if stocks else _txt(note, t("Analysis completed"))
    return {
        "name": t("News flow"),
        "note": note,
        "output": output,
        "rows": stocks,
        "marketView": market_view,
    }


def _run_research_module_macro(context: Any) -> dict[str, Any]:
    result = _research_cls("MacroAnalysisEngine")().run_full_analysis(progress_callback=None)
    stocks = _research_stock_rows(result.get("candidate_stocks", []), t("Macro analysis"), context)
    chief = result.get("agents_analysis", {}).get("chief", {}) if isinstance(result, dict) else {}
    sector_view = result.get("sector_view", {}) if isinstance(result, dict) else {}
    note = _txt(
        chief.get("analysis") or sector_view.get("market_view") or t("Macro analysis completed"),
    )
    market_view: list[dict[str, Any]] = []
    if chief.get("analysis"):
        market_view.append(_insight(t("Macro analysis"), _txt(chief.get("analysis")), "neutral"))
    if sector_view.get("market_view"):
        market_view.append(_insight(t("Sector mapping"), _txt(sector_view.get("market_view")), "accent"))
    output = t("Stock output: {count}", count=len(stocks)) if stocks else _txt(note, t("Analysis completed"))
    return {
        "name": t("Macro analysis"),
        "note": note,
        "output": output,
        "rows": stocks,
        "marketView": market_view,
    }


def _run_research_module_cycle(context: Any) -> dict[str, Any]:
    result = _research_cls("MacroCycleEngine")().run_full_analysis(progress_callback=None)
    chief = result.get("agents_analysis", {}).get("chief", {}) if isinstance(result, dict) else {}
    note = _txt(
        chief.get("analysis") or result.get("formatted_data") or t("Macro cycle analysis completed"),
    )
    market_view: list[dict[str, Any]] = []
    if chief.get("analysis"):
        market_view.append(_insight(t("Macro cycle"), _txt(chief.get("analysis")), "neutral"))
    return {
        "name": t("Macro cycle"),
        "note": note,
        "output": _txt(note, t("Analysis completed")),
        "rows": [],
        "marketView": market_view,
    }


def _run_research_modules(
    context: Any,
    payload: dict[str, Any] | None = None,
    progress_callback: Callable[[str, str, int | None], None] | None = None,
) -> dict[str, Any]:
    body = payload if isinstance(payload, dict) else {}
    default_top_n = _resolve_research_top_n(context)
    top_n = max(1, min(_int(body.get("topN"), default_top_n) or default_top_n, 200))
    selected_modules = set(_normalize_research_module_selection(body))
    module_runners: list[tuple[str, Callable[[Any], dict[str, Any]]]] = [
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
    total_modules = max(len(selected_runners), 1)
    completed_modules = 0

    module_results_cache: dict[str, dict[str, Any]] = {}
    module_errors: dict[str, BaseException] = {}

    def worker(module_key: str, runner: Callable[[Any], dict[str, Any]]) -> None:
        try:
            module_results_cache[module_key] = runner(context)
        except BaseException as exc:
            module_errors[module_key] = exc

    for offset in range(0, len(selected_runners), RESEARCH_MODULE_MAX_PARALLEL):
        chunk = selected_runners[offset : offset + RESEARCH_MODULE_MAX_PARALLEL]
        chunk_threads: dict[str, threading.Thread] = {}
        chunk_started_at: dict[str, float] = {}

        for module_key, runner in chunk:
            if progress_callback:
                progress_callback("run-module", t("Module {module} started", module=module_key), None)
            thread = threading.Thread(target=worker, args=(module_key, runner), name=f"research-module-{module_key}")
            thread.daemon = True
            thread.start()
            chunk_threads[module_key] = thread
            chunk_started_at[module_key] = time.monotonic()

        last_heartbeat = 0.0
        while True:
            running_modules: list[str] = []
            for module_key, _ in chunk:
                thread = chunk_threads[module_key]
                thread.join(timeout=0.5)
                if thread.is_alive():
                    running_modules.append(module_key)

            if not running_modules:
                break

            now_tick = time.monotonic()
            if progress_callback and now_tick - last_heartbeat >= 8.0:
                running_text = ", ".join(
                    f"{name}({int(max(0.0, now_tick - chunk_started_at.get(name, now_tick)))}s)"
                    for name in running_modules
                )
                progress_callback(
                    "run-module",
                    t("Running modules: {modules}", modules=running_text),
                    min(94, 10 + int((completed_modules / total_modules) * 80)),
                )
                last_heartbeat = now_tick

        for module_key, _ in chunk:
            progress_message: str
            if module_key in module_errors:
                failures.append(f"{module_key}: {module_errors[module_key]}")
                module_results.append(
                    {
                        "name": module_key,
                        "note": _txt(str(module_errors[module_key]), t("Analysis failed")),
                        "output": t("Analysis failed"),
                    }
                )
                progress_message = t("Module {module} failed: {reason}", module=module_key, reason=str(module_errors[module_key]))
            else:
                result = module_results_cache.get(module_key)
                if not isinstance(result, dict):
                    failures.append(t("{module}: empty result or invalid format", module=module_key))
                    module_results.append(
                        {
                            "name": module_key,
                            "note": t("Module result is empty"),
                            "output": t("Analysis failed"),
                        }
                    )
                    progress_message = t("Module {module} returned empty result", module=module_key)
                    completed_modules += 1
                    if progress_callback:
                        progress_callback(
                            "run-module",
                            progress_message,
                            min(95, 10 + int((completed_modules / total_modules) * 80)),
                        )
                    continue
                try:
                    module_rows = result.get("rows") if isinstance(result.get("rows"), list) else []
                    limited_rows = module_rows[:top_n]
                    module_results.append(
                        {
                            "name": _txt(result.get("name"), module_key),
                            "note": _txt(result.get("note") or result.get("output") or t("Analysis completed")),
                            "output": _txt(result.get("output") or t("Analysis completed")),
                        }
                    )
                    stock_rows.extend(limited_rows)
                    market_view.extend(result.get("marketView") or [])
                    progress_message = t("Module {module} completed", module=module_key)
                except Exception as exc:
                    failures.append(f"{module_key}: {exc}")
                    module_results.append(
                        {
                            "name": module_key,
                            "note": _txt(str(exc), t("Analysis failed")),
                            "output": t("Analysis failed"),
                        }
                    )
                    progress_message = t("Module {module} failed: {reason}", module=module_key, reason=str(exc))

            completed_modules += 1
            if progress_callback:
                progress_callback(
                    "run-module",
                    progress_message,
                    min(95, 10 + int((completed_modules / total_modules) * 80)),
                )

    summary_title = t("Research updated") if not failures else t("Research partially completed")
    summary_body = (
        t(
            "{module_count} research modules refreshed, with {stock_count} stock outputs; modules without stocks keep analysis conclusions only.",
            module_count=len(module_results),
            stock_count=len(stock_rows),
        )
    )
    if failures:
        summary_body = t("{base} Failed modules: {items}.", base=summary_body, items="; ".join(failures))

    payload_result = {
        "updatedAt": _now(),
        "modules": module_results,
        "marketView": market_view,
        "outputTable": _table([t("Code"), t("Name"), t("Source module"), t("Next action")], stock_rows, t("No stock output")),
        "summary": {"title": summary_title, "body": summary_body},
    }
    save_latest_result(context.research_result_key, payload_result, base_dir=context.selector_result_dir)
    return payload_result


def _append_research_task_log(
    task_id: str,
    *,
    stage: str,
    message: str,
    progress: int | None = None,
    status: str = "running",
) -> None:
    existing = research_task_manager.get_task(task_id) or {}
    logs = existing.get("logs") if isinstance(existing.get("logs"), list) else []
    merged_logs = [*logs, {"time": _now(), "stage": stage, "message": _txt(message)}]
    merged_logs = merged_logs[-80:]
    research_task_manager.update_task(
        task_id,
        now=_now,
        status=status,
        stage=stage,
        progress=progress if progress is not None else _int(existing.get("progress"), 0) or 0,
        message=_txt(message),
        logs=merged_logs,
    )


def _run_research_task(context: Any, task_id: str, payload: dict[str, Any]) -> None:
    try:
        if getattr(context, "config_manager", None):
            context.config_manager.reload_config()
    except Exception:
        # 配置热加载失败时保持任务继续，避免影响非模型模块。
        pass
    selected = _normalize_research_module_selection(payload)
    research_task_manager.update_task(
        task_id,
        now=_now,
        status="running",
        stage="run-module",
        progress=5,
        started_at=_now(),
        message=t("Running research modules. Total: {count}.", count=len(selected)),
    )
    _append_research_task_log(
        task_id,
        stage="run-module",
        message=t("Running research modules. Total: {count}.", count=len(selected)),
        progress=5,
    )
    try:
        result = _run_research_modules(
            context,
            payload,
            progress_callback=lambda stage, message, progress: _append_research_task_log(
                task_id,
                stage=stage,
                message=message,
                progress=progress,
                status="running",
            ),
        )
        output_rows = ((result.get("outputTable") or {}).get("rows") or []) if isinstance(result, dict) else []
        final_message = t("Research task completed. Stock outputs: {count}.", count=len(output_rows))
        _append_research_task_log(
            task_id,
            stage="completed",
            message=final_message,
            progress=100,
            status="completed",
        )
        research_task_manager.update_task(
            task_id,
            now=_now,
            status="completed",
            stage="completed",
            progress=100,
            message=final_message,
            finished_at=_now(),
            result={
                "moduleCount": len(selected),
                "outputCount": len(output_rows),
                "updatedAt": _now(),
            },
        )
    except Exception as exc:
        fail_message = t("Research task failed: {reason}", reason=exc)
        _append_research_task_log(
            task_id,
            stage="failed",
            message=fail_message,
            progress=100,
            status="failed",
        )
        research_task_manager.update_task(
            task_id,
            now=_now,
            status="failed",
            stage="failed",
            progress=100,
            message=fail_message,
            finished_at=_now(),
            errors=[{"message": str(exc)}],
        )


class ResearchTaskManager(AsyncTaskManagerBase):
    def __init__(self, *, limit: int = 200) -> None:
        super().__init__(task_prefix="research", title=t("Research task"), limit=limit)


research_task_manager = ResearchTaskManager()


def _query_value(table_query: dict[str, Any] | None, key: str, default: Any = None) -> Any:
    return table_query.get(key, default) if isinstance(table_query, dict) else default


def _table_cache(context: Any) -> UITableCacheDB:
    data_dir = getattr(context, "data_dir", None)
    return UITableCacheDB(Path(data_dir) / "ui_table_cache.db") if data_dir else UITableCacheDB()


def _db_page_table_rows(
    context: Any,
    table_key: str,
    rows: list[dict[str, Any]],
    table_query: dict[str, Any] | None,
    *,
    default_page_size: int = 20,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    search = _txt(_query_value(table_query, "search"))
    try:
        page_size = max(1, min(int(_query_value(table_query, "pageSize", default_page_size)), 100))
    except (TypeError, ValueError):
        page_size = default_page_size
    try:
        page = max(1, int(_query_value(table_query, "page", 1)))
    except (TypeError, ValueError):
        page = 1
    cache = _table_cache(context)
    cache.replace_rows(table_key, rows)
    total = cache.count_rows(table_key, search=search)
    total_pages = max(1, (total + page_size - 1) // page_size)
    safe_page = min(page, total_pages)
    page_rows = cache.get_rows_page(table_key, search=search, limit=page_size, offset=(safe_page - 1) * page_size)
    return page_rows, {"page": safe_page, "pageSize": page_size, "totalRows": total, "totalPages": total_pages}




def _snapshot_research(context: Any, *, task_job: dict[str, Any] | None = None, table_query: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = load_latest_result(context.research_result_key, base_dir=context.selector_result_dir) or {}
    modules = payload.get("modules") if isinstance(payload.get("modules"), list) else [
        {"name": t("Sector strategy"), "note": t("Hot direction and sector rotation judgment"), "output": t("Market view")},
        {"name": t("Dragon tiger list"), "note": t("Seat behavior and abnormal volatility"), "output": t("Market view")},
        {"name": t("News flow"), "note": t("News heat and sentiment pulse"), "output": t("Market view")},
        {"name": t("Macro analysis"), "note": t("Growth, liquidity, and risk preference"), "output": t("Market view")},
        {"name": t("Macro cycle"), "note": t("Cycle stage and asset preference"), "output": t("Market view")},
    ]
    market_view = payload.get("marketView") if isinstance(payload.get("marketView"), list) else [
        _insight(t("Market view"), t("Broad sentiment remains choppy and risk appetite has not returned to trend mode."), "warning"),
        _insight(t("Style rotation"), t("Consumer and high-dividend are defensive; high-beta tech still needs stronger flow confirmation.")),
    ]
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {
        "title": t("Research"),
        "body": t("Research defaults to market judgment first; watchlist actions appear only when modules output explicit stocks."),
    }
    latest_task = task_job or research_task_manager.latest_task()
    output_rows = _research_rows(context)
    page_rows, pagination = _db_page_table_rows(context, "research.outputs", output_rows, table_query)
    payload = {
        "updatedAt": _now(),
        "modules": [
            {
                "name": _txt(item.get("name"), t("Module {index}", index=i + 1)),
                "note": _txt(item.get("note") or item.get("body")),
                "output": _txt(item.get("output") or item.get("status")),
            }
            for i, item in enumerate(modules)
            if isinstance(item, dict)
        ],
        "marketView": market_view,
        "outputTable": _table([t("Code"), t("Name"), t("Source module"), t("Next action")], page_rows, t("No stock output")),
        "summary": {"title": _txt(summary.get("title") or t("Research")), "body": _txt(summary.get("body") or t("Research defaults to market judgment first."))},
        "taskJob": research_task_manager.job_view(latest_task, txt=_txt, int_fn=_int),
    }
    payload["outputTable"]["pagination"] = pagination
    return payload


def _action_research_item(context: Any, payload: dict[str, Any]) -> dict[str, Any]:
    code = _code_from_payload(payload)
    if not code:
        raise HTTPException(status_code=400, detail="Missing stock code")
    row = next((item for item in _research_rows(context) if item["code"] == code), None)
    if not row:
        raise HTTPException(status_code=404, detail=f"Research row not found: {code}")
    add_research_stock_to_watchlist(row, source=row.get("source") or t("Research"), db_file=context.watchlist_db_file)
    return _snapshot_research(context)


def _action_research_batch(context: Any, payload: dict[str, Any]) -> dict[str, Any]:
    selected_codes = _normalize_codes(payload)
    rows = [item for item in _research_rows(context) if item["code"] in selected_codes or not selected_codes]
    if rows:
        add_research_stocks_to_watchlist(rows, source=t("Research"), db_file=context.watchlist_db_file)
    return _snapshot_research(context)


def _action_research_run_module(context: Any, payload: dict[str, Any]) -> dict[str, Any]:
    body = _payload_dict(payload)
    selected = _normalize_research_module_selection(body)
    queued_message = t("Task submitted. {count} research modules will run.", count=len(selected))
    task_id = research_task_manager.create_task(
        now=_now,
        symbol="research",
        message=queued_message,
        stage="queued",
        progress=0,
        selected=selected,
        payload=body,
        results=[],
        errors=[],
        logs=[{"time": _now(), "stage": "queued", "message": queued_message}],
    )
    research_task_manager.start_background(
        task_id=task_id,
        target=_run_research_task,
        args=(context, task_id, body),
        name_prefix="research-task",
    )
    wait_ms = max(0, _int(body.get("waitMs"), 600) or 600)
    if wait_ms > 0:
        deadline = time.monotonic() + (wait_ms / 1000.0)
        while time.monotonic() < deadline:
            task = research_task_manager.get_task(task_id)
            if not task or task.get("status") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.02)
    snapshot = _snapshot_research(context, task_job=research_task_manager.get_task(task_id))
    snapshot["taskId"] = task_id
    return snapshot


def _action_research_reset(context: Any, payload: Any) -> dict[str, Any]:
    _ = payload
    delete_latest_result(context.research_result_key, base_dir=context.selector_result_dir)
    return _snapshot_research(context)


snapshot_research = _snapshot_research
action_research_item = _action_research_item
action_research_batch = _action_research_batch
action_research_run_module = _action_research_run_module
action_research_reset = _action_research_reset

__all__ = [
    "action_research_batch",
    "action_research_item",
    "action_research_reset",
    "action_research_run_module",
    "research_task_manager",
    "snapshot_research",
]
