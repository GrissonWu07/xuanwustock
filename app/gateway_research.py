from __future__ import annotations

import threading
import time
from typing import Any, Callable

from fastapi import HTTPException

from app.async_task_base import AsyncTaskManagerBase
from app.gateway_common import (
    RESEARCH_MARKDOWN_TEXT_LIMIT,
    RESEARCH_MODULE_TIMEOUT_SECONDS,
    code_from_payload as _code_from_payload,
    insight as _insight,
    int_value as _int,
    looks_like_stock_code as _looks_like_stock_code,
    metric as _metric,
    normalize_codes as _normalize_codes,
    now as _now,
    num as _num,
    payload_dict as _payload_dict,
    snippet as _snippet,
    table as _table,
    txt as _txt,
)
from app.i18n import t
from app.research_watchlist_integration import add_research_stock_to_watchlist, add_research_stocks_to_watchlist
from app.sector_strategy_engine import SectorStrategyEngine
from app.selector_result_store import load_latest_result, save_latest_result
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


def _run_research_module_sector(context: Any) -> dict[str, Any]:
    fetcher = _research_cls("SectorStrategyDataFetcher")()
    data = fetcher.get_cached_data_with_fallback()
    if not data.get("success"):
        note = _snippet(
            data.get("cache_warning") or data.get("message") or data.get("error") or t("Failed to fetch sector data"),
            RESEARCH_MARKDOWN_TEXT_LIMIT,
        )
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
    note = _snippet(
        result.get("comprehensive_report") or final_predictions.get("summary") or chief_text or t("Sector strategy completed"),
        RESEARCH_MARKDOWN_TEXT_LIMIT,
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
    note = _snippet(
        chief_text or result.get("final_report", {}).get("summary", "") or t("Dragon tiger analysis completed"), RESEARCH_MARKDOWN_TEXT_LIMIT
    )
    output = t("Stock output: {count}", count=len(stocks)) if stocks else _snippet(note, 120, t("Analysis completed"))
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
    note = _snippet(
        advice.get("summary")
        or advice.get("advice")
        or result.get("trading_signals", {}).get("operation_advice")
        or t("News flow analysis completed"),
        RESEARCH_MARKDOWN_TEXT_LIMIT,
    )
    market_view: list[dict[str, Any]] = []
    if advice.get("advice"):
        market_view.append(_insight(t("News flow"), _snippet(advice.get("summary") or advice.get("advice"), RESEARCH_MARKDOWN_TEXT_LIMIT), "accent"))
    if result.get("trading_signals", {}).get("operation_advice"):
        market_view.append(_insight(t("Trading signal"), _snippet(result.get("trading_signals", {}).get("operation_advice"), RESEARCH_MARKDOWN_TEXT_LIMIT), "warning"))
    output = t("Stock output: {count}", count=len(stocks)) if stocks else _snippet(note, 120, t("Analysis completed"))
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
    note = _snippet(
        chief.get("analysis") or sector_view.get("market_view") or t("Macro analysis completed"),
        RESEARCH_MARKDOWN_TEXT_LIMIT,
    )
    market_view: list[dict[str, Any]] = []
    if chief.get("analysis"):
        market_view.append(_insight(t("Macro analysis"), _snippet(chief.get("analysis"), RESEARCH_MARKDOWN_TEXT_LIMIT), "neutral"))
    if sector_view.get("market_view"):
        market_view.append(_insight(t("Sector mapping"), _snippet(sector_view.get("market_view"), RESEARCH_MARKDOWN_TEXT_LIMIT), "accent"))
    output = t("Stock output: {count}", count=len(stocks)) if stocks else _snippet(note, 120, t("Analysis completed"))
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
    note = _snippet(
        chief.get("analysis") or result.get("formatted_data") or t("Macro cycle analysis completed"),
        RESEARCH_MARKDOWN_TEXT_LIMIT,
    )
    market_view: list[dict[str, Any]] = []
    if chief.get("analysis"):
        market_view.append(_insight(t("Macro cycle"), _snippet(chief.get("analysis"), RESEARCH_MARKDOWN_TEXT_LIMIT), "neutral"))
    return {
        "name": t("Macro cycle"),
        "note": note,
        "output": _snippet(note, 120, t("Analysis completed")),
        "rows": [],
        "marketView": market_view,
    }


def _run_research_modules(context: Any, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = payload if isinstance(payload, dict) else {}
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

    module_results_cache: dict[str, dict[str, Any]] = {}
    module_errors: dict[str, BaseException] = {}
    module_threads: dict[str, threading.Thread] = {}

    def worker(module_key: str, runner: Callable[[Any], dict[str, Any]]) -> None:
        try:
            module_results_cache[module_key] = runner(context)
        except BaseException as exc:
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
            failures.append(t("{module}: analysis timeout ({seconds}s)", module=module_key, seconds=RESEARCH_MODULE_TIMEOUT_SECONDS))
            module_results.append(
                {
                    "name": module_key,
                    "note": _snippet(
                        t("{module}: analysis timeout ({seconds}s)", module=module_key, seconds=RESEARCH_MODULE_TIMEOUT_SECONDS),
                        80,
                        t("Analysis failed"),
                    ),
                    "output": t("Analysis failed"),
                }
            )
            continue
        if module_key in module_errors:
            failures.append(f"{module_key}: {module_errors[module_key]}")
            module_results.append(
                {
                    "name": module_key,
                    "note": _snippet(str(module_errors[module_key]), 80, t("Analysis failed")),
                    "output": t("Analysis failed"),
                }
            )
            continue
        result = module_results_cache.get(module_key)
        if not isinstance(result, dict):
            failures.append(t("{module}: empty result or invalid format", module=module_key))
            module_results.append(
                {
                    "name": module_key,
                    "note": _snippet(t("Module result is empty"), 80, t("Analysis failed")),
                    "output": t("Analysis failed"),
                }
            )
            continue
        try:
            module_results.append(
                {
                    "name": _txt(result.get("name"), module_key),
                    "note": _snippet(
                        result.get("note") or result.get("output") or t("Analysis completed"),
                        RESEARCH_MARKDOWN_TEXT_LIMIT,
                    ),
                    "output": _snippet(result.get("output") or t("Analysis completed"), 24),
                }
            )
            stock_rows.extend(result.get("rows") or [])
            market_view.extend(result.get("marketView") or [])
        except Exception as exc:
            failures.append(f"{module_key}: {exc}")
            module_results.append(
                {
                    "name": module_key,
                    "note": _snippet(str(exc), 80, t("Analysis failed")),
                    "output": t("Analysis failed"),
                }
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
        summary_body = t("{base} Failed modules: {items}.", base=summary_body, items="; ".join(failures[:3]))

    payload_result = {
        "updatedAt": _now(),
        "modules": module_results,
        "marketView": market_view[:6],
        "outputTable": _table([t("Code"), t("Name"), t("Source module"), t("Next action")], stock_rows, t("No stock output")),
        "summary": {"title": summary_title, "body": summary_body},
    }
    save_latest_result(context.research_result_key, payload_result, base_dir=context.selector_result_dir)
    return payload_result


class ResearchTaskManager(AsyncTaskManagerBase):
    def __init__(self, *, limit: int = 200) -> None:
        super().__init__(task_prefix="research", title=t("Research task"), limit=limit)


research_task_manager = ResearchTaskManager()


def _run_research_task(context: Any, task_id: str, payload: dict[str, Any]) -> None:
    selected = _normalize_research_module_selection(payload)
    research_task_manager.update_task(
        task_id,
        now=_now,
        status="running",
        stage="run-module",
        progress=10,
        started_at=_now(),
        message=t("Running research modules. Total: {count}.", count=len(selected)),
    )
    try:
        result = _run_research_modules(context, payload)
        output_rows = ((result.get("outputTable") or {}).get("rows") or []) if isinstance(result, dict) else []
        research_task_manager.update_task(
            task_id,
            now=_now,
            status="completed",
            stage="completed",
            progress=100,
            message=t("Research task completed. Stock outputs: {count}.", count=len(output_rows)),
            finished_at=_now(),
            result={
                "moduleCount": len(selected),
                "outputCount": len(output_rows),
                "updatedAt": _now(),
            },
        )
    except Exception as exc:
        research_task_manager.update_task(
            task_id,
            now=_now,
            status="failed",
            stage="failed",
            progress=100,
            message=t("Research task failed: {reason}", reason=exc),
            finished_at=_now(),
            errors=[{"message": str(exc)}],
        )


def _snapshot_research(context: Any, *, task_job: dict[str, Any] | None = None) -> dict[str, Any]:
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
    return {
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
        "outputTable": _table([t("Code"), t("Name"), t("Source module"), t("Next action")], _research_rows(context), t("No stock output")),
        "summary": {"title": _txt(summary.get("title") or t("Research")), "body": _txt(summary.get("body") or t("Research defaults to market judgment first."))},
        "taskJob": research_task_manager.job_view(latest_task, txt=_txt, int_fn=_int),
    }


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
    task_id = research_task_manager.create_task(
        now=_now,
        symbol="research",
        message=t("Task submitted. {count} research modules will run.", count=len(selected)),
        stage="queued",
        progress=0,
        selected=selected,
        payload=body,
        results=[],
        errors=[],
    )
    research_task_manager.start_background(
        task_id=task_id,
        target=_run_research_task,
        args=(context, task_id, body),
        name_prefix="research-task",
    )
    snapshot = _snapshot_research(context, task_job=research_task_manager.get_task(task_id))
    snapshot["taskId"] = task_id
    return snapshot


snapshot_research = _snapshot_research
action_research_item = _action_research_item
action_research_batch = _action_research_batch
action_research_run_module = _action_research_run_module

__all__ = [
    "action_research_batch",
    "action_research_item",
    "action_research_run_module",
    "research_task_manager",
    "snapshot_research",
]
