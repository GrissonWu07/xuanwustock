from __future__ import annotations

from datetime import datetime
import threading
from typing import Any

from fastapi import HTTPException

from app import stock_analysis_service
from app.i18n import t
from app.watchlist_integration import add_watchlist_rows_to_quant_pool
from app.watchlist_selector_integration import normalize_stock_code
from app.workbench_analysis_payloads import (
    analysis_config as _analysis_config,
    analysis_options as _analysis_options,
    build_workbench_analysis_payload as _build_workbench_analysis_payload,
)
from app.workbench_analysis_tasks import analysis_task_manager


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def _query_value(table_query: dict[str, Any] | None, key: str, default: Any = None) -> Any:
    return table_query.get(key, default) if isinstance(table_query, dict) else default


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


def _parse_datetime(value: Any) -> datetime | None:
    text = _txt(value)
    if not text:
        return None
    for candidate in (text, text.replace("T", " ")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            pass
    for fmt, length in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(text[:length], fmt)
        except ValueError:
            pass
    return None


def _short_time(value: Any) -> str:
    parsed = _parse_datetime(value)
    if not parsed:
        return _txt(value, "--")
    return parsed.strftime("%m-%d %H:%M")


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


def _watchlist_quote_label(item: dict[str, Any], metadata: dict[str, Any]) -> str:
    latest_price = _float(item.get("latest_price"))
    price_text = "--" if latest_price is None or latest_price <= 0 else f"{latest_price:.2f}"
    change_pct = None
    for key in ("change_pct", "pct_chg", "涨跌幅", "changePercent"):
        if key in metadata and metadata.get(key) not in (None, ""):
            change_pct = _float(metadata.get(key))
            break
    if change_pct is None:
        return price_text
    return f"{price_text} {change_pct:+.2f}%"


def _watchlist_data_status(item: dict[str, Any], metadata: dict[str, Any], sector: str) -> str:
    latest_price = _float(item.get("latest_price"))
    stock_code = normalize_stock_code(item.get("stock_code"))
    stock_name = _txt(item.get("stock_name"))
    if latest_price is None or latest_price <= 0:
        return t("Quote missing")
    if not stock_name or stock_name.upper() in {stock_code, "N/A", "UNKNOWN"}:
        return t("Name pending")
    if not sector or sector in {"-", "N/A", "未知"}:
        return t("Sector pending")
    if metadata.get("data_error") or metadata.get("refresh_error"):
        return t("Data needs refresh")
    return t("Data OK")


def _watchlist_signal_label(item: dict[str, Any]) -> str:
    signal = _txt(item.get("latest_signal")).upper()
    return signal if signal else t("No signal")


def _analysis_status(record: dict[str, Any] | None) -> tuple[str, str]:
    if not isinstance(record, dict) or not record:
        return t("Needs analysis"), "warning"
    decision = record.get("final_decision") if isinstance(record.get("final_decision"), dict) else {}
    rating = _txt(decision.get("rating") or decision.get("action") or record.get("rating"), t("Analyzed"))
    parsed = _parse_datetime(record.get("analysis_date") or record.get("created_at"))
    if not parsed:
        return f"{t('Analyzed')} · {rating}", "neutral"
    today = datetime.now().date()
    age_days = (today - parsed.date()).days
    if age_days <= 0:
        return f"{t('Today analyzed')} · {rating}", "success"
    return f"{t('Stale analysis')} {age_days}{t('Days suffix')} · {rating}", "warning"


def _workflow_badges(
    *,
    in_quant_pool: bool,
    has_position: bool,
    data_status: str,
    analysis_tone: str,
) -> list[str]:
    badges: list[str] = []
    if has_position:
        badges.append(t("Holding"))
    if in_quant_pool:
        badges.append(t("Quant pool"))
    if analysis_tone == "warning":
        badges.append(t("Analysis pending"))
    if data_status != t("Data OK"):
        badges.append(data_status)
    if not badges:
        badges.append(t("Watch only"))
    return badges


def _analyze_stock_with_context(context: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return stock_analysis_service.analyze_single_stock_for_batch(
            *args,
            analysis_db=context.stock_analysis_db(),
            **kwargs,
        )
    except TypeError as exc:
        if "analysis_db" not in str(exc):
            raise
        return stock_analysis_service.analyze_single_stock_for_batch(*args, **kwargs)


WORKBENCH_WATCHLIST_PAGE_SIZE = 20


def _table_page_query(
    table_query: dict[str, Any] | None,
    *,
    default_page_size: int = WORKBENCH_WATCHLIST_PAGE_SIZE,
    max_page_size: int = WORKBENCH_WATCHLIST_PAGE_SIZE,
) -> tuple[str, int, int]:
    search = _txt(_query_value(table_query, "search"))
    try:
        page_size = max(1, min(int(_query_value(table_query, "pageSize", default_page_size)), max_page_size))
    except (TypeError, ValueError):
        page_size = default_page_size
    try:
        page = max(1, int(_query_value(table_query, "page", 1)))
    except (TypeError, ValueError):
        page = 1
    return search, page, page_size


def _pagination(page: int, page_size: int, total: int) -> dict[str, int]:
    total_pages = max(1, (max(0, int(total)) + page_size - 1) // page_size)
    safe_page = min(max(1, page), total_pages)
    return {"page": safe_page, "pageSize": page_size, "totalRows": max(0, int(total)), "totalPages": total_pages}


def watchlist_rows_from_items(
    items: list[dict[str, Any]],
    *,
    latest_analysis_by_code: dict[str, dict[str, Any]] | None = None,
    position_codes: set[str] | None = None,
) -> list[dict[str, Any]]:
    latest_analysis_by_code = latest_analysis_by_code or {}
    position_codes = position_codes or set()
    rows: list[dict[str, Any]] = []
    for item in items:
        code = normalize_stock_code(item.get("stock_code"))
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        sector = _txt(metadata.get("industry") or metadata.get("sector"), "-")
        quote_label = _watchlist_quote_label(item, metadata)
        data_status = _watchlist_data_status(item, metadata, sector)
        analysis_status, analysis_tone = _analysis_status(latest_analysis_by_code.get(code))
        signal_status = _watchlist_signal_label(item)
        latest_price_value = _float(item.get("latest_price"))
        workflow_badges = _workflow_badges(
            in_quant_pool=bool(item.get("in_quant_pool")),
            has_position=code in position_codes,
            data_status=data_status,
            analysis_tone=analysis_tone,
        )
        updated_at = _short_time(item.get("updated_at"))
        rows.append(
            {
                "id": code,
                "cells": [
                    code,
                    _txt(item.get("stock_name") or code),
                    quote_label,
                    sector,
                    analysis_status,
                    signal_status,
                    " · ".join(workflow_badges),
                    updated_at,
                ],
                "actions": [],
                "code": code,
                "name": _txt(item.get("stock_name") or code),
                "source": "",
                "industry": sector,
                "latestPrice": "--" if latest_price_value is None or latest_price_value <= 0 else _num(latest_price_value, default="--"),
                "reason": analysis_status,
                "quoteText": quote_label,
                "analysisStatus": analysis_status,
                "analysisTone": analysis_tone,
                "signalStatus": signal_status,
                "workflowBadges": workflow_badges,
                "dataStatus": data_status,
                "updatedAt": updated_at,
            }
        )
    return rows


def watchlist_rows(context: Any) -> list[dict[str, Any]]:
    return watchlist_rows_from_items(context.watchlist().list_watches())


def build_workbench_snapshot(
    context: Any,
    *,
    analysis: dict[str, Any] | None = None,
    analysis_job: dict[str, Any] | None = None,
    activity: list[dict[str, str]] | None = None,
    table_query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = context.portfolio().get_account_summary()
    search, requested_page, page_size = _table_page_query(table_query)
    total_watchlist = context.watchlist().count_watches()
    filtered_total = context.watchlist().count_watches(search=search)
    watchlist_pagination = _pagination(requested_page, page_size, filtered_total)
    page_items = context.watchlist().list_watches_page(
        search=search,
        limit=page_size,
        offset=(watchlist_pagination["page"] - 1) * page_size,
    )
    page_codes = [normalize_stock_code(item.get("stock_code")) for item in page_items if normalize_stock_code(item.get("stock_code"))]
    stock_analysis_db = context.stock_analysis_db()
    latest_analysis_by_code: dict[str, dict[str, Any]] = stock_analysis_db.get_latest_records_by_symbols(page_codes)
    try:
        position_codes = {
            normalize_stock_code(position.get("stock_code") or position.get("code"))
            for position in context.portfolio().list_positions()
            if normalize_stock_code(position.get("stock_code") or position.get("code"))
        }
    except Exception:
        position_codes = set()
    watchlist = watchlist_rows_from_items(
        page_items,
        latest_analysis_by_code=latest_analysis_by_code,
        position_codes=position_codes,
    )
    quant_count = context.watchlist().count_watches(in_quant_pool=True)

    def _analysis_from_record(latest_record: dict[str, Any], fallback_symbol: str = "") -> dict[str, Any]:
        resolved_symbol = normalize_stock_code(_txt(latest_record.get("symbol"), fallback_symbol))
        record_stock_info = latest_record.get("stock_info") if isinstance(latest_record.get("stock_info"), dict) else {}
        record_indicators = latest_record.get("indicators") if isinstance(latest_record.get("indicators"), dict) else {}
        record_discussion = latest_record.get("discussion_result")
        record_final_decision = latest_record.get("final_decision") if isinstance(latest_record.get("final_decision"), dict) else {}
        record_agents = latest_record.get("agents_results") if isinstance(latest_record.get("agents_results"), dict) else {}
        record_historical = latest_record.get("historical_data") if isinstance(latest_record.get("historical_data"), list) else []
        return _build_workbench_analysis_payload(
            code=resolved_symbol,
            stock_name=_txt(latest_record.get("stock_name"), resolved_symbol),
            selected=None,
            mode=t("Single analysis"),
            cycle=_txt(latest_record.get("period"), "1y"),
            generated_at=_txt(latest_record.get("analysis_date") or latest_record.get("created_at"), _now()),
            stock_info=record_stock_info,
            indicators=record_indicators,
            discussion_result=record_discussion,
            final_decision=record_final_decision,
            agents_results=record_agents,
            historical_data=record_historical,
        )

    active_symbol = _txt(analysis.get("symbol")) if isinstance(analysis, dict) else _txt(watchlist[0]["code"]) if watchlist else ""
    latest_task = analysis_job or analysis_task_manager.latest_task()
    task_results = latest_task.get("results") if isinstance(latest_task, dict) and isinstance(latest_task.get("results"), list) else []
    cached_analysis = analysis
    if not cached_analysis and task_results:
        last_result = next((item for item in reversed(task_results) if isinstance(item, dict)), None)
        if isinstance(last_result, dict):
            cached_analysis = last_result
            active_symbol = _txt(last_result.get("symbol"), active_symbol)
    if not cached_analysis:
        latest_record = context.stock_analysis_db().get_latest_record_by_symbol(active_symbol) if active_symbol else None
        if not latest_record:
            records = context.stock_analysis_db().get_records_page(limit=1)
            latest_id = _int(records[0].get("id")) if records else None
            latest_record = context.stock_analysis_db().get_record_by_id(latest_id) if latest_id else None
        if latest_record:
            resolved_symbol = normalize_stock_code(_txt(latest_record.get("symbol"), active_symbol))
            if not active_symbol:
                active_symbol = resolved_symbol
            cached_analysis = _analysis_from_record(latest_record, resolved_symbol)
    base_analysis = cached_analysis or {
        "symbol": active_symbol,
        "analysts": _analysis_options(),
        "mode": t("Single analysis"),
        "cycle": "1y",
        "inputHint": t("Example: 600519 / 300390 / AAPL"),
        "summaryTitle": t("Latest analysis summary"),
        "summaryBody": t("Add symbols to watchlist first, then start analysis."),
        "indicators": [],
        "decision": t("Review watchlist first, then decide whether to push to quant candidates."),
        "insights": [
            _insight(t("Current mode"), t("Workbench aggregates watchlist, analysis, and next actions.")),
            _insight(t("Execution note"), t("Once moved into candidate pool, quant simulation reads the same dataset.")),
        ],
        "curve": [],
    }
    if task_results:
        analysis_results = [item for item in task_results if isinstance(item, dict)]
    else:
        analysis_results = list(base_analysis.get("results")) if isinstance(base_analysis.get("results"), list) else []
    if isinstance(latest_task, dict):
        task_codes = [normalize_stock_code(code) for code in latest_task.get("codes") or [] if _txt(code)]
        deduped_codes: list[str] = []
        for code in task_codes:
            if code and code not in deduped_codes:
                deduped_codes.append(code)
        if not analysis_results:
            for code in deduped_codes:
                latest_record = context.stock_analysis_db().get_latest_record_by_symbol(code)
                if latest_record:
                    analysis_results.append(_analysis_from_record(latest_record, code))
        result_symbols = {normalize_stock_code(item.get("symbol")) for item in analysis_results if isinstance(item, dict)}
        selected = [str(item) for item in latest_task.get("selected") or [] if _txt(item)]
        mode = _txt(latest_task.get("mode"), _txt(base_analysis.get("mode"), t("Batch analysis")))
        cycle = _txt(latest_task.get("cycle"), _txt(base_analysis.get("cycle"), "1y"))
        running_symbol = normalize_stock_code(latest_task.get("symbol"))
        failed_by_symbol = {
            normalize_stock_code(item.get("symbol")): _txt(item.get("message"), t("Analysis failed"))
            for item in latest_task.get("errors") or []
            if isinstance(item, dict) and normalize_stock_code(item.get("symbol"))
        }
        for code in deduped_codes:
            if code in result_symbols:
                continue
            state = t("Failed") if code in failed_by_symbol else t("In progress") if code == running_symbol else t("Queued")
            message = (
                failed_by_symbol[code]
                if code in failed_by_symbol
                else f"{code} 已提交到本次批量分析任务，当前状态：{state}，正在排队等待或执行中。真实分析由后台任务逐只执行，完成后会自动替换为完整结论。"
            )
            analysis_results.append(
                {
                    "symbol": code,
                    "stockName": code,
                    "analysts": _analysis_options(selected),
                    "mode": mode,
                    "cycle": cycle,
                    "inputHint": t("Example: 600519 / 300390 / AAPL"),
                    "summaryTitle": f"{code} {'分析中' if code not in failed_by_symbol else '分析失败'}",
                    "summaryBody": message,
                    "generatedAt": _txt(latest_task.get("updated_at") or latest_task.get("updatedAt"), _now()),
                    "indicators": [],
                    "decision": t("Waiting for analysis result"),
                    "finalDecisionText": t("Waiting for analysis result"),
                    "insights": [_insight(t("Task status"), message, "accent" if code not in failed_by_symbol else "danger")],
                    "analystViews": [],
                    "curve": [],
                }
            )
    if not analysis_results and _txt(base_analysis.get("generatedAt")):
        analysis_results = [{key: value for key, value in base_analysis.items() if key != "results"}]
    analysis_payload = {**base_analysis, "results": analysis_results}
    return {
        "updatedAt": _now(),
        "metrics": [
            _metric(t("My watchlist"), total_watchlist),
            _metric(t("My positions"), summary.get("position_count", 0)),
            _metric(t("Quant candidates"), quant_count),
            _metric(t("Quant jobs"), len(context.quant_db().get_sim_runs(limit=1000))),
        ],
        "watchlist": {
            **_table(
                [t("Code"), t("Name"), t("Quote"), t("Sector"), t("Analysis"), t("Signal"), t("Workflow"), t("Updated")],
                watchlist,
                t("Watchlist is empty."),
            ),
            "pagination": watchlist_pagination,
        },
        "watchlistMeta": {
            "selectedCount": 0,
            "quantCount": quant_count,
            "refreshHint": t("Watchlist refresh updates name, price, and sector in batch. Quant scheduler also writes latest prices and signals here."),
        },
        "analysis": analysis_payload,
        "analysisJob": analysis_task_manager.job_view(latest_task, txt=_txt, int_fn=_int),
        "nextSteps": [
            {"label": t("Portfolio"), "hint": t("View holdings, attribution, and position actions"), "href": "/portfolio"},
            {"label": t("Real-time monitor"), "hint": t("Check price rules, triggers, and notifications"), "href": "/real-monitor"},
            {"label": t("Discover"), "hint": t("Enter stock discovery and pick new watch targets"), "href": "/discover"},
            {"label": t("Research"), "hint": t("Aggregate sectors, dragon-tiger list, news, and macro"), "href": "/research"},
            {"label": t("Quant simulation"), "hint": t("Run live simulation based on quant candidate pool"), "href": "/live-sim"},
            {"label": t("Historical replay"), "hint": t("Replay historical performance with same candidate pool"), "href": "/his-replay"},
        ],
        "activity": activity or [_timeline(_now(), t("Workbench initialized"), t("No quant run records yet. Watchlist and candidates will start from here."))],
    }


def snapshot_workbench(context: Any, *, table_query: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_workbench_snapshot(context, table_query=table_query)


def _submit_workbench_analysis_task(
    context: Any,
    *,
    codes: list[str],
    selected: list[str],
    cycle: str,
    mode: str,
    activity_title: str,
) -> dict[str, Any]:
    normalized_codes = [normalize_stock_code(code) for code in codes if _txt(code)]
    task_id = analysis_task_manager.create_task(
        codes=normalized_codes,
        selected=selected,
        cycle=cycle,
        mode=mode,
        now=_now,
    )
    thread = threading.Thread(
        target=analysis_task_manager.run_task,
        kwargs={
            "task_id": task_id,
            "context": context,
            "normalize_code": normalize_stock_code,
            "analysis_config_builder": _analysis_config,
            "build_payload": _build_workbench_analysis_payload,
            "analyze_stock": lambda *args, **kwargs: _analyze_stock_with_context(context, *args, **kwargs),
            "now": _now,
            "txt": _txt,
            "dict_value": _dict_value,
        },
        name=f"workbench-analysis-{task_id}",
        daemon=True,
    )
    thread.start()
    detail = (
        t("{symbol} added to analysis queue, task id: {task_id}", symbol=normalized_codes[0], task_id=task_id)
        if len(normalized_codes) == 1
        else t("{count} symbols added to analysis queue, task id: {task_id}", count=len(normalized_codes), task_id=task_id)
    )
    snapshot = build_workbench_snapshot(
        context,
        analysis_job=analysis_task_manager.get_task(task_id),
        activity=[_timeline(_now(), activity_title, detail)],
    )
    snapshot["taskId"] = task_id
    if isinstance(snapshot.get("analysis"), dict):
        snapshot["analysis"] = {
            **snapshot["analysis"],
            "symbol": normalized_codes[0] if len(normalized_codes) == 1 else ",".join(normalized_codes),
            "mode": mode,
            "cycle": cycle,
            "analysts": _analysis_options(selected),
        }
    return snapshot


def action_workbench_batch_quant(context: Any, payload: dict[str, Any]) -> dict[str, Any]:
    codes = _normalize_codes(payload) or [row["code"] for row in watchlist_rows(context)]
    add_watchlist_rows_to_quant_pool(codes, watchlist_service=context.watchlist(), candidate_service=context.candidate_pool(), db_file=context.quant_sim_db_file)
    return snapshot_workbench(context)


def action_workbench_batch_portfolio(context: Any, payload: dict[str, Any]) -> dict[str, Any]:
    body = _payload_dict(payload)
    codes = _normalize_codes(body) or [row["code"] for row in watchlist_rows(context)]
    if not codes:
        raise HTTPException(status_code=400, detail=t("Missing stock codes"))
    input_cost = None
    input_quantity = 100
    try:
        raw_cost = body.get("costPrice") if isinstance(body, dict) else None
        if raw_cost not in (None, ""):
            input_cost = float(raw_cost)
    except (TypeError, ValueError):
        input_cost = None
    try:
        raw_quantity = body.get("quantity") if isinstance(body, dict) else None
        if raw_quantity not in (None, ""):
            input_quantity = max(100, int(float(raw_quantity)))
    except (TypeError, ValueError):
        input_quantity = 100

    watch_map: dict[str, dict[str, Any]] = {}
    for item in context.watchlist().list_watches():
        watch_code = normalize_stock_code(item.get("stock_code"))
        if watch_code:
            watch_map[watch_code] = item

    manager = context.portfolio_manager()
    added = 0
    updated = 0
    skipped = 0
    failed = 0

    for code in codes:
        watch_item = watch_map.get(code, {})
        metadata = watch_item.get("metadata") if isinstance(watch_item.get("metadata"), dict) else {}
        sector = _txt(metadata.get("industry") or metadata.get("sector"), "")
        name = _txt((watch_item or {}).get("stock_name"), code)
        latest_price_raw = (watch_item or {}).get("latest_price")
        try:
            latest_price = float(latest_price_raw) if latest_price_raw is not None else None
        except (TypeError, ValueError):
            latest_price = None
        target_cost = input_cost if input_cost is not None else latest_price
        target_quantity = input_quantity if input_quantity is not None else 100

        existing = manager.db.get_stock_by_code(code)
        if existing:
            update_fields: dict[str, Any] = {}
            if target_cost is not None:
                update_fields["cost_price"] = target_cost
            if target_quantity is not None:
                update_fields["quantity"] = target_quantity
            if sector:
                update_fields["sector"] = sector
            if name:
                update_fields["name"] = name
            if update_fields:
                ok, _ = manager.update_stock(_int(existing.get("id"), 0) or 0, **update_fields)
                if ok:
                    updated += 1
                else:
                    failed += 1
            else:
                skipped += 1
            continue

        success, message, _ = manager.add_stock(
            code=code,
            name=name,
            sector=sector,
            cost_price=target_cost,
            quantity=target_quantity,
            note="",
            auto_monitor=True,
        )
        if success:
            added += 1
            continue
        normalized_message = _txt(message).lower()
        if "已存在" in _txt(message) or "exist" in normalized_message:
            skipped += 1
        else:
            failed += 1

    detail = t(
        "Holdings registration completed: added {added}, updated {updated}, skipped {skipped}, failed {failed}.",
        added=added,
        updated=updated,
        skipped=skipped,
        failed=failed,
    )
    return build_workbench_snapshot(
        context,
        activity=[_timeline(_now(), t("Holdings registration"), detail)],
    )


def action_workbench_add_watchlist(context: Any, payload: dict[str, Any]) -> dict[str, Any]:
    code = _code_from_payload(payload)
    if not code:
        raise HTTPException(status_code=400, detail="Missing stock code")
    try:
        context.watchlist().add_manual_stock(code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_txt(exc, t("Invalid stock code"))) from exc
    return snapshot_workbench(context)


def action_workbench_refresh(context: Any, payload: dict[str, Any]) -> dict[str, Any]:
    body = _payload_dict(payload)
    explicit_codes = isinstance(body, dict) and "codes" in body
    codes = _normalize_codes(body.get("codes")) if explicit_codes else _normalize_codes(body)
    full_refresh = bool(body.get("fullRefresh")) if isinstance(body, dict) else False
    context.watchlist().refresh_quotes(codes if explicit_codes else (codes or None), full_refresh=full_refresh)
    return snapshot_workbench(context)


def action_workbench_delete(context: Any, payload: dict[str, Any]) -> dict[str, Any]:
    codes = _normalize_codes(payload)
    for code in codes:
        context.watchlist().delete_stock(code)
    return snapshot_workbench(context)


def action_workbench_analysis(context: Any, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    code = _code_from_payload(body)
    if not code:
        raise HTTPException(status_code=400, detail="Missing stock code")
    selected = body.get("analysts")
    if not isinstance(selected, list):
        selected = []
    cycle = _txt(body.get("cycle"), "1y")
    mode = _txt(body.get("mode"), t("Single analysis"))
    return _submit_workbench_analysis_task(
        context,
        codes=[code],
        selected=selected,
        cycle=cycle,
        mode=mode,
        activity_title=t("Analysis task submitted"),
    )


def action_workbench_analysis_batch(context: Any, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    codes = _normalize_codes(body.get("stockCodes") if isinstance(body, dict) else payload)
    if not codes:
        raise HTTPException(status_code=400, detail="Missing stock codes")
    selected = body.get("analysts")
    if not isinstance(selected, list):
        selected = []
    cycle = _txt(body.get("cycle"), "1y")
    mode = _txt(body.get("mode"), t("Batch analysis"))
    return _submit_workbench_analysis_task(
        context,
        codes=codes,
        selected=selected,
        cycle=cycle,
        mode=mode,
        activity_title=t("Batch analysis task submitted"),
    )


__all__ = [
    "action_workbench_add_watchlist",
    "action_workbench_analysis",
    "action_workbench_analysis_batch",
    "action_workbench_batch_portfolio",
    "action_workbench_batch_quant",
    "action_workbench_delete",
    "action_workbench_refresh",
    "build_workbench_snapshot",
    "snapshot_workbench",
    "watchlist_rows",
]
