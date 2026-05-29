from __future__ import annotations

from datetime import datetime
from pathlib import Path
import math
import time
from types import SimpleNamespace
from typing import Any, Callable

from fastapi import HTTPException
import pandas as pd

from app.discover.ai_stock_scanner import AIStockScanner, AIStockScannerConfig
from app.discover.ai_strategy import run_ai_scanner_strategy
from app.discover.candidate_artifact import (
    hydrate_discovery_candidate_rows,
    load_discovery_candidate_artifact,
    mark_rows_stale_unprepared,
    renormalize_hydrated_discovery_rows,
    save_discovery_candidate_artifact,
    technical_summary_from_rows,
)
from app.discover.lifecycle_scoring import normalize_discovery_lifecycle_row
from app.discover.row_filters import filter_rows_by_strategy as _filter_rows_by_strategy
from app.discover.row_filters import strategy_filter_value as _strategy_filter_value
from app.async_task_base import AsyncTaskManagerBase
from app.gateway.common import (
    code_from_payload as _code_from_payload,
    first_non_empty as _first_non_empty,
    int_value as _int,
    metric as _metric,
    normalize_codes as _normalize_codes,
    now as _now,
    num as _num,
    payload_dict as _payload_dict,
    table as _table,
    txt as _txt,
)
from app.gateway.quant_universe_entry import enrich_lifecycle_entry_rows, ingest_lifecycle_entry_rows
from app.gateway.page_market_artifact_projection import apply_live_artifact_projection_to_rows
from app.i18n import t
from app.quant_sim.time_utils import format_system_time, parse_system_datetime
from app.selector_ui_state import (
    load_main_force_state,
    load_simple_selector_state,
    save_main_force_state,
    save_simple_selector_state,
)
from app.stock_refresh_scheduler import get_unified_stock_refresh_scheduler, load_stock_runtime_entries
from app.ui_table_cache_db import UITableCacheDB
from app.watchlist_selector_integration import add_stock_to_watchlist, normalize_stock_code

MainForceStockSelector = None
LowPriceBullSelector = None
SmallCapSelector = None
ProfitGrowthSelector = None
ValueStockSelector = None


def _discover_strategy_defs() -> list[tuple[str, str, str]]:
    return [
        ("main_force", t("Main force selection"), t("Main fund flow + financial filter + AI pick")),
        ("low_price_bull", t("Low price momentum"), t("Low-price high-elasticity candidates")),
        ("small_cap", t("Small cap"), t("Small but active growth candidates")),
        ("profit_growth", t("Profit growth"), t("Earnings growth trend screening")),
        ("value_stock", t("Value"), t("Valuation re-rating direction")),
        ("ai_scanner", t("AI stock selection"), t("AI scanner sector-theme selection")),
    ]


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


def _query_value(table_query: dict[str, Any] | None, key: str, default: Any = None) -> Any:
    return table_query.get(key, default) if isinstance(table_query, dict) else default


def _table_cache(context: Any) -> UITableCacheDB:
    runtime = getattr(context, "db_runtime", None)
    data_dir = getattr(context, "data_dir", None)
    if runtime is not None:
        return UITableCacheDB(db_runtime=runtime)
    return UITableCacheDB(Path(data_dir) / "xuanwu_stock.db") if data_dir else UITableCacheDB()


def _db_page_table_rows(
    context: Any,
    table_key: str,
    rows: list[dict[str, Any]],
    table_query: dict[str, Any] | None,
    *,
    default_page_size: int = 6,
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


def _parse_selector_timestamp(value: Any) -> datetime | None:
    text = _txt(value)
    if not text:
        return None
    try:
        return parse_system_datetime(text)
    except (TypeError, ValueError):
        return None


def _system_time(value: Any, default: str = "--") -> str:
    return format_system_time(value, default=default)


def _num_or_dash(value: Any, digits: int = 2) -> str:
    try:
        if value is None:
            return "--"
        if isinstance(value, str) and not value.strip():
            return "--"
        number = float(value)
        if not math.isfinite(number):
            return "--"
        return f"{number:.{digits}f}"
    except (TypeError, ValueError):
        return "--"


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        text = str(value).strip().replace(",", "")
        if not text or text in {"-", "--", "N/A", "NA", "nan", "None"}:
            return None
        number = float(text)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _market_cap_100m_or_dash(value: Any) -> str:
    number = _float_or_none(value)
    if number is None:
        return "--"
    if abs(number) >= 10_000_000:
        number = number / 100_000_000
    return f"{number:.2f}"


def _first_metric_value(row: dict[str, Any], aliases: list[str], key_needles: list[tuple[str, ...]]) -> Any:
    value = _first_non_empty(row, aliases)
    if value not in (None, ""):
        return value
    for key, candidate in row.items():
        if candidate in (None, ""):
            continue
        normalized_key = str(key).strip().lower().replace(" ", "")
        if not normalized_key:
            continue
        for needles in key_needles:
            if all(needle.lower() in normalized_key for needle in needles):
                return candidate
    return None


def _discover_row_from_mapping(row: dict[str, Any], *, source: str, selected_at: str | None, strategy_key: str = "", rank: int = 1, total: int = 1) -> dict[str, Any] | None:
    lifecycle_row = normalize_discovery_lifecycle_row(row, strategy_key=strategy_key or source, strategy_name=source, rank=rank, total=total)
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
    latest_price = _num_or_dash(
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
    market_cap = _market_cap_100m_or_dash(
        _first_metric_value(
            row,
            ["总市值", "market_cap", "marketCap", "total_market_value", "total_market_cap", "市值"],
            [("总市值",), ("market", "cap")],
        )
    )
    pe = _num_or_dash(
        _first_metric_value(
            row,
            ["市盈率", "市盈率TTM", "pe", "pe_ratio", "pe_ttm", "PE", "PE(TTM)"],
            [("市盈率",)],
        )
    )
    pb = _num_or_dash(
        _first_metric_value(
            row,
            ["市净率", "pb", "pb_ratio", "PB"],
            [("市净率",)],
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
        "actions": [{"label": t("Add to watchlist"), "icon": "⭐", "tone": "accent", "action": "item-watchlist"}],
        "code": code,
        "name": name,
        "industry": industry,
        "source": source,
        "latestPrice": latest_price,
        "marketCap": market_cap,
        "peRatio": pe,
        "pbRatio": pb,
        "score": lifecycle_row.get("score"),
        "source_score": lifecycle_row.get("source_score"),
        "confidence": lifecycle_row.get("confidence"),
        "candidate_confidence": lifecycle_row.get("candidate_confidence"),
        "trend": lifecycle_row.get("trend"),
        "ma5": _first_non_empty(row, ["ma5", "MA5"]),
        "ma10": _first_non_empty(row, ["ma10", "MA10"]),
        "ma20": _first_non_empty(row, ["ma20", "MA20"]),
        "ma20_slope": _first_non_empty(row, ["ma20_slope", "MA20_slope", "ma20Slope"]),
        "ma60": _first_non_empty(row, ["ma60", "MA60"]),
        "amount": _first_non_empty(row, ["amount", "turnover", "成交额"]),
        "volume_ratio": _first_non_empty(row, ["volume_ratio", "量比"]),
        "rsi": _first_non_empty(row, ["rsi", "rsi12", "RSI"]),
        "macd": _first_non_empty(row, ["macd", "MACD"]),
        "technical_confirmation_count": lifecycle_row.get("technical_confirmation_count"),
        "lifecycle_score_diagnostics": lifecycle_row.get("lifecycle_score_diagnostics"),
        "reason": reason,
        "selectedAt": _system_time(selected_at, ""),
    }
    for key in (
        "technical_snapshot_ready",
        "technical_snapshot_status",
        "technical_snapshot_missing_fields",
        "technical_snapshot_timeframe",
        "technical_snapshot_provider",
        "technical_snapshot_prepared_at",
        "technical_snapshot_row_count",
        "technical_snapshot_indicator_version",
    ):
        if key in row:
            result[key] = row.get(key)
    snapshot_at = _first_non_empty(row, ["technical_snapshot_at", "snapshot_at", "datetime"])
    if snapshot_at not in (None, ""):
        result["technical_snapshot_at"] = _system_time(snapshot_at, str(snapshot_at))
    for key in ("scanner_score", "theme_score", "technical_score", "technical_reasons", "sector_score", "rank_score", "price_change_score"):
        if lifecycle_row.get(key) not in (None, ""):
            result[key] = lifecycle_row.get(key)
    return result


def _discover_rows_from_main_force(result: dict[str, Any], selected_at: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    recommendations = result.get("final_recommendations", []) if isinstance(result, dict) else []
    total = len(recommendations or [])
    for rank, item in enumerate(recommendations or [], start=1):
        if not isinstance(item, dict):
            continue
        stock = item.get("stock_data", {}) if isinstance(item.get("stock_data"), dict) else {}
        source_row = dict(stock)
        source_row.update(
            {
                "股票代码": stock.get("股票代码") or item.get("code") or item.get("stock_code") or item.get("symbol"),
                "股票简称": stock.get("股票简称") or item.get("name"),
                "所属同花顺行业": stock.get("所属同花顺行业") or stock.get("所属行业") or item.get("industry"),
                "最新价": stock.get("最新价") or item.get("latestPrice") or item.get("latest_price"),
                "reason": item.get("highlights") or item.get("reason") or ", ".join(item.get("reasons", [])),
            }
        )
        row = _discover_row_from_mapping(source_row, source=_txt(item.get("source") or t("Main force selection")), selected_at=selected_at, strategy_key="main_force", rank=rank, total=total)
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
    total = len(rows_iter or [])
    for rank, item in enumerate(rows_iter or [], start=1):
        if not isinstance(item, dict):
            continue
        row = _discover_row_from_mapping(item, source=strategy_name, selected_at=selected_at, strategy_key=strategy_key, rank=rank, total=total)
        if not row:
            continue
        row["strategyKey"] = strategy_key
        rows.append(row)
    return rows


def _run_ai_scanner_strategy(context: Any, payload: dict[str, Any], *, top_n: int) -> pd.DataFrame:
    return run_ai_scanner_strategy(payload, top_n=top_n, scanner_cls=AIStockScanner, config_cls=AIStockScannerConfig)


def _discover_strategy_snapshots(context: Any) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    main_result, _, main_selected_at = load_main_force_state(base_dir=context.selector_result_dir)
    if main_result:
        rows = _discover_rows_from_main_force(main_result, main_selected_at)
        if rows:
            snapshots.append(
                {
                    "key": "main_force",
                    "name": t("Main force selection"),
                    "note": t("Main fund flow + financial filter + AI pick"),
                    "selected_at": main_selected_at,
                    "rows": rows,
                }
            )

    for strategy_key, strategy_name, strategy_note in _discover_strategy_defs():
        if strategy_key == "main_force":
            continue
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


def _raw_discover_rows(context: Any, strategy_keys: set[str] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for snapshot in _discover_strategy_snapshots(context):
        if strategy_keys and _txt(snapshot.get("key")) not in strategy_keys:
            continue
        for row in snapshot.get("rows", []):
            row = dict(row)
            row["source"] = _txt(row.get("source") or snapshot.get("name"))
            row["strategyKey"] = _txt(snapshot.get("key"))
            row["strategyName"] = _txt(snapshot.get("name"))
            selected_at_raw = snapshot.get("selected_at") or row.get("selectedAt")
            row["selectedAt"] = _system_time(selected_at_raw, "")
            row["_selected_dt"] = _parse_selector_timestamp(selected_at_raw) or datetime.min
            strategy_key = _txt(snapshot.get("key"))
            row["_strategy_priority"] = {
                "ai_scanner": 6,
                "main_force": 5,
                "low_price_bull": 4,
                "small_cap": 3,
                "profit_growth": 2,
                "value_stock": 1,
            }.get(strategy_key, 0)
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


def _hydrated_discovery_rows(context: Any) -> list[dict[str, Any]]:
    artifact = load_discovery_candidate_artifact(base_dir=context.selector_result_dir)
    artifact_rows = artifact.get("rows") if isinstance(artifact, dict) else None
    runtime_entries = load_stock_runtime_entries(base_dir=context.selector_result_dir)
    if isinstance(artifact_rows, list) and artifact_rows:
        rows = hydrate_discovery_candidate_rows(
            artifact_rows,
            runtime_entries,
            run_id=_txt(artifact.get("runId")),
            artifact_status="current",
        )
        normalized = renormalize_hydrated_discovery_rows(rows)
        db_file = getattr(context, "quant_sim_db_file", None)
        if db_file is None:
            return normalized
        return apply_live_artifact_projection_to_rows(
            db_file=db_file,
            rows=normalized,
            runtime_entries=runtime_entries,
            price_cell_index=4,
            industry_cell_index=2,
        )
    return renormalize_hydrated_discovery_rows(mark_rows_stale_unprepared(_raw_discover_rows(context)))


def _discover_rows(context: Any) -> list[dict[str, Any]]:
    rows = _hydrated_discovery_rows(context)
    runtime_entries = load_stock_runtime_entries(base_dir=context.selector_result_dir)
    db_file = getattr(context, "quant_sim_db_file", None)
    if db_file is None:
        return rows
    projected = apply_live_artifact_projection_to_rows(
        db_file=db_file,
        rows=rows,
        runtime_entries=runtime_entries,
        price_cell_index=4,
        industry_cell_index=2,
    )
    return enrich_lifecycle_entry_rows(context, projected)

def _optional_float(value: Any) -> float | None:
    return _float_or_none(value)


def _add_discover_row_to_watchlist(context: Any, row: dict[str, Any]) -> None:
    metadata: dict[str, Any] = {
        "industry": row.get("industry"),
        "sector": row.get("industry"),
        "discover_source": row.get("strategyName") or row.get("source"),
        "source_strategy": row.get("strategyKey") or row.get("source"),
        "discovered_at": row.get("selectedAt"),
    }
    for metadata_key, row_key in (
        ("market_cap", "marketCap"),
        ("pe_ratio", "peRatio"),
        ("pb_ratio", "pbRatio"),
    ):
        value = _optional_float(row.get(row_key))
        if value is not None:
            metadata[metadata_key] = value
    add_stock_to_watchlist(
        row["code"],
        row["name"],
        row.get("source") or t("Main force selection"),
        latest_price=_optional_float(row.get("latestPrice")),
        notes=row.get("reason"),
        metadata=metadata,
        db_file=context.quant_sim_db_file,
    )


def _normalize_discover_strategy_selection(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("strategies") or payload.get("strategy") or payload.get("strategyKey")
    if raw is None or raw == "":
        return ["main_force", "low_price_bull", "small_cap", "profit_growth", "value_stock", "ai_scanner"]

    values: list[str]
    if isinstance(raw, list):
        values = [str(item).strip().lower() for item in raw if str(item).strip()]
    else:
        values = [str(raw).strip().lower()]

    aliases = {
        "main_force": {"main_force", "main-force", "main_force_selection", "mainforce"},
        "low_price_bull": {"low_price_bull", "low-price-bull", "low_price_momentum", "lowprice"},
        "small_cap": {"small_cap", "small-cap", "small_cap"},
        "profit_growth": {"profit_growth", "profit-growth", "profit_growth"},
        "value_stock": {"value_stock", "value-stock", "value"},
        "ai_scanner": {"ai_scanner", "ai-scanner", "ai_scanner_selection", "ai_selector", "ai_stock_selection"},
    }

    selected: list[str] = []
    for key, synonyms in aliases.items():
        if any(value in synonyms for value in values):
            selected.append(key)
    return selected or ["main_force", "low_price_bull", "small_cap", "profit_growth", "value_stock", "ai_scanner"]


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
                "source": t("Main force selection"),
                "highlights": _txt(item.get("理由") or item.get("说明") or item.get("备注") or t("Main fund flow and screening rules matched")),
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


def _resolve_default_top_n(context: Any) -> int:
    default_top_n = 10
    config_manager = getattr(context, "config_manager", None)
    if config_manager is None:
        return default_top_n
    try:
        config = config_manager.read_env()
    except Exception:
        return default_top_n
    configured = _int(config.get("DISCOVER_TOP_N"), default_top_n) if isinstance(config, dict) else default_top_n
    return max(1, min(configured or default_top_n, 200))


def _run_discover_strategies(context: Any, payload: dict[str, Any]) -> dict[str, Any]:
    selected = set(_normalize_discover_strategy_selection(payload))
    selected_at = _now()
    default_top_n = _resolve_default_top_n(context)
    top_n = max(1, min(_int(payload.get("topN"), default_top_n) or default_top_n, 200))
    ai_top_n = max(1, min(_int(payload.get("aiTopN"), top_n) or top_n, 200))
    completed: list[str] = []
    failed: list[dict[str, str]] = []

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
                completed.append("main_force")
            else:
                failed.append({"strategy": "main_force", "reason": t("No valid result returned")})
        except Exception as exc:
            failed.append({"strategy": "main_force", "reason": str(exc) or t("Strategy execution failed")})

    if "ai_scanner" in selected:
        try:
            scanner_df = _run_ai_scanner_strategy(context, payload, top_n=ai_top_n)
            if scanner_df is not None and not getattr(scanner_df, "empty", False):
                save_simple_selector_state(
                    strategy_key="ai_scanner",
                    stocks_df=scanner_df,
                    selected_at=selected_at,
                    base_dir=context.selector_result_dir,
                )
                completed.append("ai_scanner")
            else:
                failed.append({"strategy": "ai_scanner", "reason": t("No valid result returned")})
        except Exception as exc:
            failed.append({"strategy": "ai_scanner", "reason": str(exc) or t("Strategy execution failed")})

    simple_strategies: list[tuple[str, Callable[[], tuple[bool, Any, str]]]] = [
        ("low_price_bull", lambda: _selector_cls("LowPriceBullSelector")().get_low_price_stocks(top_n=top_n)),
        ("small_cap", lambda: _selector_cls("SmallCapSelector")().get_small_cap_stocks(top_n=top_n)),
        ("profit_growth", lambda: _selector_cls("ProfitGrowthSelector")().get_profit_growth_stocks(top_n=top_n)),
        ("value_stock", lambda: _selector_cls("ValueStockSelector")().get_value_stocks(top_n=top_n)),
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
                completed.append(strategy_key)
            else:
                failed.append({"strategy": strategy_key, "reason": t("No valid result returned")})
        except Exception as exc:
            failed.append({"strategy": strategy_key, "reason": str(exc) or t("Strategy execution failed")})

    return {"completed": completed, "failed": failed, "selected_at": selected_at}


def _run_discovery_refresh(context: Any) -> dict[str, Any]:
    try:
        scheduler = get_unified_stock_refresh_scheduler(context)
        return scheduler.run_once(context=context, run_reason="discover")
    except Exception as exc:
        return {
            "reason": "discover",
            "updated": 0,
            "failed": 1,
            "totalCodes": 0,
            "error": str(exc) or type(exc).__name__,
            "updatedAt": _now(),
        }


class DiscoverTaskManager(AsyncTaskManagerBase):
    def __init__(self, *, limit: int = 200) -> None:
        super().__init__(task_prefix="discover", title=t("Stock discovery task"), limit=limit)


discover_task_manager = DiscoverTaskManager()


def _run_discover_task(context: Any, task_id: str, payload: dict[str, Any]) -> None:
    selected = _normalize_discover_strategy_selection(payload)
    discover_task_manager.update_task(
        task_id,
        now=_now,
        status="running",
        stage="run-strategy",
        progress=10,
        started_at=_now(),
        message=t("Running discovery strategies. Total: {count}.", count=len(selected)),
    )
    try:
        run_result = _run_discover_strategies(context, payload)
        completed_keys = {_txt(item) for item in run_result.get("completed", []) if _txt(item)}
        raw_rows = _raw_discover_rows(context, completed_keys)
        selected_at = _txt(run_result.get("selected_at"), _now()) if isinstance(run_result, dict) else _now()
        save_discovery_candidate_artifact(
            raw_rows,
            run_id=task_id,
            selected_at=selected_at,
            base_dir=context.selector_result_dir,
        )
        refresh_summary = _run_discovery_refresh(context)
        rows = _hydrated_discovery_rows(context)
        snapshot_summary = technical_summary_from_rows(rows)
        save_discovery_candidate_artifact(
            raw_rows,
            run_id=task_id,
            selected_at=selected_at,
            summary=snapshot_summary,
            refresh_summary=refresh_summary,
            base_dir=context.selector_result_dir,
        )
        ingest_summary = ingest_lifecycle_entry_rows(context, rows, source_type="discover")
        failed_items = run_result.get("failed") if isinstance(run_result, dict) and isinstance(run_result.get("failed"), list) else []
        completed_items = run_result.get("completed") if isinstance(run_result, dict) and isinstance(run_result.get("completed"), list) else []
        message = t("Discovery task completed. Current candidates: {count}.", count=len(rows))
        status = "completed"
        if failed_items:
            failed_names = ", ".join(str(item.get("strategy")) for item in failed_items if isinstance(item, dict) and item.get("strategy"))
            if not completed_items:
                status = "failed"
                message = t("Discovery task failed. Failed strategies: {strategies}.", strategies=failed_names or t("unknown"))
            else:
                message = t(
                    "{base} Failed strategies: {strategies}.",
                    base=message,
                    strategies=failed_names or t("unknown"),
                )
        discover_task_manager.update_task(
            task_id,
            now=_now,
            status=status,
            stage=status,
            progress=100,
            message=message,
            finished_at=_now(),
            errors=failed_items if failed_items else [],
            result={
                "candidateCount": len(rows),
                "updatedAt": _now(),
                "completedStrategies": completed_items,
                "failedStrategies": failed_items,
                "technicalSnapshotPreparation": snapshot_summary,
                "stockRefresh": refresh_summary,
                "quantAutoEntry": ingest_summary,
            },
        )
    except Exception as exc:
        discover_task_manager.update_task(
            task_id,
            now=_now,
            status="failed",
            stage="failed",
            progress=100,
            message=t("Discovery task failed: {reason}", reason=exc),
            finished_at=_now(),
            errors=[{"message": str(exc)}],
        )


def _snapshot_discover(context: Any, *, task_job: dict[str, Any] | None = None, table_query: dict[str, Any] | None = None) -> dict[str, Any]:
    snapshots = _discover_strategy_snapshots(context)
    rows = _discover_rows(context)
    strategy_filter = _strategy_filter_value(table_query)
    filtered_rows = _filter_rows_by_strategy(rows, strategy_filter)
    discover_table_query = dict(table_query or {})
    if not discover_table_query.get("_page_size_explicit"):
        discover_table_query["pageSize"] = 10
    page_rows, pagination = _db_page_table_rows(
        context,
        "discover.candidates",
        filtered_rows,
        discover_table_query,
        default_page_size=10,
    )
    latest_snapshot = snapshots[0] if snapshots else {}
    latest_row = rows[0] if rows else {}
    latest_selected_at = _system_time(latest_snapshot.get("selected_at") or latest_row.get("selectedAt") or _now())
    latest_count = len(rows)
    top_names = "、".join(_txt(row.get("name")) for row in rows[:3] if _txt(row.get("name")))
    strategy_lookup = {str(snapshot.get("key")): snapshot for snapshot in snapshots}
    strategy_defs = _discover_strategy_defs()
    strategy_cards = []
    for strategy_key, strategy_name, strategy_note in strategy_defs:
        snapshot = strategy_lookup.get(strategy_key)
        snapshot_rows = snapshot.get("rows", []) if snapshot else []
        selected_at = _system_time(snapshot.get("selected_at"), "--") if snapshot else "--"
        strategy_cards.append(
            {
                "key": strategy_key,
                "name": strategy_name,
                "note": strategy_note,
                "status": t("Latest picks: {count}", count=len(snapshot_rows)) if snapshot_rows else t("Pending run"),
                "highlight": _txt(selected_at if selected_at != "--" else t("Waiting for latest result")),
                "selectedAt": selected_at,
                "count": len(snapshot_rows),
            }
        )
    recommendation_body = t("This section keeps priority targets after model aggregation, with single/batch add to watchlist.")
    if top_names:
        recommendation_body = _txt(
            t(
                "This section keeps priority targets after model aggregation, with single/batch add to watchlist."
            )
            + " "
            + t("Priority candidates: {names}.", names=top_names)
        )
    recommendation_chips = [
        t("⭐ Latest {count} candidates", count=latest_count),
        t("📌 {count} strategies", count=len(snapshots)),
        t("⭐ Add selected to watchlist"),
        t("⭐ Add single to watchlist"),
    ]
    strategy_name_chips = [f"📌 {_txt(snapshot.get('name'))}" for snapshot in snapshots[:3] if _txt(snapshot.get("name"))]
    for chip in strategy_name_chips:
        if chip not in recommendation_chips:
            recommendation_chips.append(chip)
    latest_task = task_job or discover_task_manager.latest_task()
    payload = {
        "updatedAt": _now(),
        "metrics": [
            _metric(t("Discovery strategies"), len(strategy_defs)),
            _metric(t("Latest candidates"), len(rows)),
            _metric(t("Added to watchlist"), len(context.watchlist().list_watches())),
            _metric(t("Last run"), latest_selected_at),
        ],
        "strategies": strategy_cards,
        "summary": {
            "title": _txt(
                latest_snapshot.get("name")
                or latest_row.get("strategyName")
                or t("Discovery strategy aggregate")
            ),
            "body": _txt(
                (
                    t(
                        "Aggregated latest results from {strategy_count} discovery strategies, {candidate_count} candidates in total, latest update at {updated_at}.",
                        strategy_count=len(snapshots),
                        candidate_count=latest_count,
                        updated_at=latest_selected_at,
                    )
                    + (
                        t(" Latest strategy: {note}.", note=_txt(latest_snapshot.get("note")))
                        if _txt(latest_snapshot.get("note"))
                        else ""
                    )
                    if rows
                    else t("Run a selection strategy first, then add real targets into watchlist.")
                )
            ),
        },
        "candidateTable": _table(
            [
                t("Code"),
                t("Name"),
                t("Industry"),
                t("Source strategy"),
                t("Latest price"),
                t("Market cap (100M)"),
                t("P/E"),
                t("P/B"),
            ],
            page_rows,
            t("No candidate stocks"),
        ),
        "recommendation": {
            "title": t("Top recommendations"),
            "body": recommendation_body,
            "chips": recommendation_chips,
        },
        "taskJob": discover_task_manager.job_view(latest_task, txt=_txt, int_fn=_int),
    }
    payload["candidateTable"]["pagination"] = pagination
    payload["candidateTable"]["activeStrategyKey"] = strategy_filter or "all"
    return payload


def _action_discover_item(context: Any, payload: dict[str, Any]) -> dict[str, Any]:
    code = _code_from_payload(payload)
    if not code:
        raise HTTPException(status_code=400, detail="Missing stock code")
    row = next((item for item in _discover_rows(context) if item["code"] == code), None)
    if not row:
        raise HTTPException(status_code=404, detail=f"Discover row not found: {code}")
    _add_discover_row_to_watchlist(context, row)
    return _snapshot_discover(context)


def _action_discover_batch(context: Any, payload: dict[str, Any]) -> dict[str, Any]:
    codes = _normalize_codes(payload)
    rows = [item for item in _discover_rows(context) if item["code"] in codes or not codes]
    for row in rows:
        _add_discover_row_to_watchlist(context, row)
    return _snapshot_discover(context)


def _action_discover_run_strategy(context: Any, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    selected = _normalize_discover_strategy_selection(body)
    task_id = discover_task_manager.create_task(
        now=_now,
        symbol="discover",
        message=t("Task submitted. {count} discovery strategies will run.", count=len(selected)),
        stage="queued",
        progress=0,
        selected=selected,
        payload=body,
        results=[],
        errors=[],
    )
    discover_task_manager.start_background(
        task_id=task_id,
        target=_run_discover_task,
        args=(context, task_id, body),
        name_prefix="discover-task",
    )
    wait_ms = max(0, _int(body.get("waitMs"), 600) or 600)
    if wait_ms > 0:
        deadline = time.monotonic() + (wait_ms / 1000.0)
        while time.monotonic() < deadline:
            task = discover_task_manager.get_task(task_id)
            if not task or task.get("status") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.02)
    snapshot = _snapshot_discover(context, task_job=discover_task_manager.get_task(task_id))
    snapshot["taskId"] = task_id
    return snapshot

def _action_discover_reset(context: Any, payload: Any) -> dict[str, Any]:
    _ = payload
    base_dir = Path(context.selector_result_dir)
    for strategy_key in ["main_force", "low_price_bull", "small_cap", "profit_growth", "value_stock", "ai_scanner"]:
        file_path = base_dir / f"{strategy_key}.json"
        if file_path.exists():
            file_path.unlink()
    return _snapshot_discover(context)

snapshot_discover = _snapshot_discover
action_discover_item = _action_discover_item
action_discover_batch = _action_discover_batch
action_discover_run_strategy = _action_discover_run_strategy
action_discover_reset = _action_discover_reset
__all__ = [
    "action_discover_batch",
    "action_discover_item",
    "action_discover_reset",
    "action_discover_run_strategy",
    "discover_task_manager",
    "snapshot_discover",
]
