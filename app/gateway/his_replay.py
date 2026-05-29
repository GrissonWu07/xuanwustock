from __future__ import annotations

import sqlite3

from app.gateway.deps import *
from app.gateway.context import UIApiContext
from app.gateway.scheduler_config import _enabled_strategy_profile_id, _fee_rate_pct_text, _latest_replay_defaults, _normalize_dynamic_lookback, _normalize_dynamic_strength, _normalize_fee_rate, _payload_fee_rate
from app.gateway.signal_table import build_signal_summary_row, build_signal_summary_table
from app.gateway.table_query import _normalize_replay_table_page, _normalize_replay_table_page_size, _replay_actions_for_filter, _replay_table_pagination
from app.gateway.trades import (
    _replay_execution_summary_metrics,
    _trade_commission_fee,
    _trade_cost_summary_metrics,
    _trade_execution_detail,
    _trade_fee_total,
    _trade_gross_amount,
    _trade_kind,
    _trade_metadata,
    _trade_net_amount,
    _trade_realized_pnl_pct,
    _trade_sell_tax_fee,
    build_trade_provenance,
)
from app.gateway.replay_capital_pool import build_his_replay_capital_pool
from app.gateway.replay_liquidation import build_terminal_liquidation, terminal_liquidation_metrics


def _build_his_replay_ranked_trade_row(item: dict[str, Any], index: int) -> dict[str, Any]:
    metadata = _trade_metadata(item)
    signal_id = _txt(item.get("signal_id"))
    return {
        "id": _txt(item.get("id"), str(index)),
        "cells": [
            _system_time_text(item.get("executed_at") or item.get("created_at"), "--"),
            "期末清算" if metadata.get("terminal_liquidation") else (f"#{signal_id}" if signal_id else "--"),
            _txt(item.get("stock_code")),
            _num(item.get("price")),
            _num(item.get("realized_pnl")),
            _trade_realized_pnl_pct(item),
            _trade_execution_detail(item),
        ],
        "code": _txt(item.get("stock_code")),
        "name": _txt(item.get("stock_name")),
    }


def _build_his_replay_ranked_trade_rows(
    db: QuantSimDB,
    run_id: int,
    *,
    profitable: bool,
    limit: int,
    extra_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    items = list(db.get_sim_run_ranked_trades(run_id, profitable=profitable, limit=limit))
    for extra in extra_items or []:
        realized_pnl = _float(extra.get("realized_pnl"), 0.0) or 0.0
        if profitable and realized_pnl > 0:
            items.append(extra)
        elif not profitable and realized_pnl < 0:
            items.append(extra)
    items.sort(key=lambda item: (_float(item.get("realized_pnl"), 0.0) or 0.0), reverse=profitable)
    return [_build_his_replay_ranked_trade_row(item, index) for index, item in enumerate(items[:limit])]


def _build_his_replay_profit_loss_by_stock_rows(db: QuantSimDB, run_id: int) -> list[dict[str, Any]]:
    by_code: dict[str, dict[str, Any]] = {}
    for trade in db.get_sim_run_trades(run_id):
        code = _txt(trade.get("stock_code"))
        if not code:
            continue
        item = by_code.setdefault(
            code,
            {
                "stock_code": code,
                "stock_name": _txt(trade.get("stock_name")),
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "buy_net_amount": 0.0,
                "sell_net_amount": 0.0,
                "fee_total": 0.0,
                "trade_count": 0,
            },
        )
        if not item.get("stock_name"):
            item["stock_name"] = _txt(trade.get("stock_name"))
        action = _txt(trade.get("action")).upper()
        if action in {"BUY", "SELL"}:
            item["trade_count"] += 1
        if action == "BUY":
            item["buy_net_amount"] += _float(_trade_net_amount(trade), 0.0) or 0.0
        elif action == "SELL":
            item["sell_net_amount"] += _float(_trade_net_amount(trade), 0.0) or 0.0
        item["fee_total"] += _float(_trade_fee_total(trade), 0.0) or 0.0
        item["realized_pnl"] += _float(trade.get("realized_pnl"), 0.0) or 0.0

    for position in db.get_sim_run_positions(run_id):
        code = _txt(position.get("stock_code"))
        if not code:
            continue
        item = by_code.setdefault(
            code,
            {
                "stock_code": code,
                "stock_name": _txt(position.get("stock_name")),
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "buy_net_amount": 0.0,
                "sell_net_amount": 0.0,
                "fee_total": 0.0,
                "trade_count": 0,
            },
        )
        if not item.get("stock_name"):
            item["stock_name"] = _txt(position.get("stock_name"))
        item["unrealized_pnl"] += _float(position.get("unrealized_pnl"), 0.0) or 0.0

    items = list(by_code.values())
    items.sort(key=lambda item: abs((_float(item.get("realized_pnl"), 0.0) or 0.0) + (_float(item.get("unrealized_pnl"), 0.0) or 0.0)), reverse=True)
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        realized_pnl = _float(item.get("realized_pnl"), 0.0) or 0.0
        unrealized_pnl = _float(item.get("unrealized_pnl"), 0.0) or 0.0
        total_pnl = realized_pnl + unrealized_pnl
        rows.append(
            {
                "id": _txt(item.get("stock_code"), str(index)),
                "cells": [
                    _txt(item.get("stock_code")),
                    _txt(item.get("stock_name"), "--"),
                    _num(total_pnl),
                    _num(realized_pnl),
                    _num(unrealized_pnl),
                    _num(item.get("buy_net_amount")),
                    _num(item.get("sell_net_amount")),
                    _num(item.get("fee_total")),
                    _txt(item.get("trade_count"), "0"),
                ],
                "code": _txt(item.get("stock_code")),
                "name": _txt(item.get("stock_name")),
            }
        )
    return rows


def _replay_signal_execution_metrics(summary: dict[str, Any] | None) -> list[dict[str, Any]]:
    item = summary or {}
    return [
        _metric("交易信号", _txt(item.get("trade_signal_count"), "0")),
        _metric("BUY信号", _txt(item.get("buy_signal_count"), "0")),
        _metric("SELL信号", _txt(item.get("sell_signal_count"), "0")),
        _metric("已执行信号", _txt(item.get("executed_signal_count"), "0")),
        _metric("忽略信号", _txt(item.get("ignored_signal_count"), "0")),
        _metric("忽略BUY", _txt(item.get("ignored_buy_signal_count"), "0")),
        _metric("忽略SELL", _txt(item.get("ignored_sell_signal_count"), "0")),
        _metric("待执行信号", _txt(item.get("pending_signal_count"), "0")),
    ]


def _run_stock_scope_rows_from_metadata(metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
    item = metadata if isinstance(metadata, dict) else {}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    raw_scope = item.get("candidate_scope")
    if isinstance(raw_scope, list):
        for index, candidate in enumerate(raw_scope):
            if not isinstance(candidate, dict):
                continue
            code = _txt(candidate.get("stock_code") or candidate.get("code")).strip()
            if not code or code in seen:
                continue
            seen.add(code)
            name = _txt(candidate.get("stock_name") or candidate.get("name") or code, code).strip() or code
            rows.append(
                {
                    "id": code,
                    "cells": [code, name],
                    "code": code,
                    "name": name,
                    "source": "run_metadata",
                    "order": index,
                }
            )
    raw_codes = item.get("stock_codes")
    if isinstance(raw_codes, list):
        for index, raw_code in enumerate(raw_codes):
            code = _txt(raw_code).strip()
            if not code or code in seen:
                continue
            seen.add(code)
            rows.append(
                {
                    "id": code,
                    "cells": [code, code],
                    "code": code,
                    "name": code,
                    "source": "run_metadata",
                    "order": len(rows) + index,
                }
            )
    return rows


def _stock_scope_search_matches(row: dict[str, Any], keyword: str) -> bool:
    search = _txt(keyword).lower()
    if not search:
        return True
    values = [_txt(row.get("code")), _txt(row.get("name")), *[_txt(cell) for cell in row.get("cells", [])]]
    return any(search in value.lower() for value in values if value)


def _build_his_replay_candidate_pool_table(
    context: UIApiContext,
    run: dict[str, Any] | None,
    table_query: dict[str, Any] | None,
) -> dict[str, Any]:
    query = table_query or {}
    page_size = _normalize_replay_table_page_size(query.get("candidate_page_size") or query.get("pageSize"), default=20)
    page = _normalize_replay_table_page(query.get("candidate_page") or query.get("page"))
    search = _txt(query.get("candidate_search") or query.get("search"))
    run_metadata = run.get("metadata") if isinstance((run or {}).get("metadata"), dict) else {}
    scope_rows = _run_stock_scope_rows_from_metadata(run_metadata)

    if scope_rows:
        matched_rows = [row for row in scope_rows if _stock_scope_search_matches(row, search)]
        pagination = _replay_table_pagination(page, page_size, len(matched_rows))
        start = (pagination["page"] - 1) * page_size
        table = _table(["股票代码", "股票名称"], matched_rows[start : start + page_size], "暂无任务量化股票")
        table["pagination"] = pagination
        return table

    candidate_total = context.candidate_pool().count_candidates(status="active", search=search)
    pagination = _replay_table_pagination(page, page_size, candidate_total)
    candidate_rows = [
        {
            "id": _txt(item.get("stock_code"), str(i)),
            "cells": [
                _txt(item.get("stock_code")),
                _txt(item.get("stock_name")),
            ],
            "code": _txt(item.get("stock_code")),
            "name": _txt(item.get("stock_name")),
        }
        for i, item in enumerate(
            context.candidate_pool().list_candidates(
                status="active",
                limit=page_size,
                offset=(pagination["page"] - 1) * page_size,
                search=search,
            )
        )
    ]
    table = _table(["股票代码", "股票名称"], candidate_rows, "暂无任务量化股票")
    table["pagination"] = pagination
    return table


def _drill_table_payload(items: list[dict[str, Any]], total: int | None = None, page: int = 1, page_size: int = 20) -> dict[str, Any]:
    return {"items": items, "total": int(total if total is not None else len(items)), "page": page, "pageSize": page_size}


def _drill_distinct_stock_count(events: list[dict[str, Any]], statuses: set[str]) -> int:
    return len({_txt(event.get("stock_code")) for event in events if _txt(event.get("to_status")) in statuses and _txt(event.get("stock_code"))})


def _live_quant_drill_data_risk_items(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    data_warnings = metadata.get("data_warnings") if isinstance(metadata.get("data_warnings"), list) else []
    disabled_sources = metadata.get("disabled_candidate_sources") if isinstance(metadata.get("disabled_candidate_sources"), list) else []
    data_risk_items: list[dict[str, Any]] = []
    for warning in data_warnings:
        if isinstance(warning, dict):
            data_risk_items.append(
                {
                    "stockCode": _txt(warning.get("stock_code") or warning.get("code")),
                    "domain": _txt(warning.get("domain") or warning.get("data_domain") or "data_warning"),
                    "provider": _txt(warning.get("provider") or warning.get("source")),
                    "reason": _txt(warning.get("reason") or warning.get("message") or warning),
                }
            )
        else:
            data_risk_items.append({"stockCode": "", "domain": "data_warning", "provider": "", "reason": _txt(warning)})
    for source in disabled_sources:
        data_risk_items.append({"stockCode": "", "domain": "candidate_source", "provider": _txt(source), "reason": "source_not_historical"})
    return data_risk_items


def _build_live_quant_drill_partial_payload(metadata: dict[str, Any], data_risk_items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "runType": "live_quant_drill",
        "typeLabel": "实时量化演练",
        "title": "实时量化演练",
        "lifecycleSummary": {
            "initialQuantCount": len(metadata.get("initial_quant_universe_snapshot") or metadata.get("stock_codes") or []),
            "candidateEventCount": 0,
            "autoPromotedCount": 0,
            "autoExitedCount": 0,
            "exitOnlyCount": 0,
            "coolingCount": 0,
            "retiredCount": 0,
            "dataWarningCount": len(data_risk_items),
        },
        "lifecycleSeries": [],
        "candidateEventsTable": _drill_table_payload([], total=0, page=1, page_size=20),
        "exitEventsTable": _drill_table_payload([], total=0, page=1, page_size=20),
        "finalStatesTable": _drill_table_payload([], total=0, page=1, page_size=50),
        "dataRisksTable": _drill_table_payload(data_risk_items, total=len(data_risk_items), page=1, page_size=max(1, len(data_risk_items) or 20)),
    }


def _build_live_quant_drill_payload(db: QuantSimDB, run: dict[str, Any], run_id: int) -> dict[str, Any]:
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    data_risk_items = _live_quant_drill_data_risk_items(metadata)
    status_text = _txt(run.get("status")).lower()
    if status_text in {"queued", "running", "failed", "cancelled", "cancel_request", "cancel_requested"}:
        return _build_live_quant_drill_partial_payload(metadata, data_risk_items)

    try:
        summary_rows = db.list_sim_run_quant_summary(run_id)
        last_summary = summary_rows[-1] if summary_rows else {}
        candidate_events = db.list_sim_run_candidate_events(run_id, page_size=1)
        promoted_candidate_events = db.list_sim_run_candidate_events(run_id, status="consumed", page_size=20)
        quant_events = db.list_sim_run_quant_events(run_id, page_size=10000)
    except sqlite3.DatabaseError as exc:
        data_risk_items.append(
            {
                "stockCode": "",
                "domain": "live_quant_drill_lifecycle",
                "provider": "replay_db",
                "reason": _txt(exc),
            }
        )
        return _build_live_quant_drill_partial_payload(metadata, data_risk_items)

    quant_event_items = quant_events.get("items", [])
    exit_event_items = [
        event
        for event in quant_event_items
        if _txt(event.get("to_status")) in {"exit_only", "cooling", "retired"}
    ]
    auto_promoted_count = (
        sum(int(row.get("auto_promoted_count") or 0) for row in summary_rows)
        if summary_rows
        else sum(1 for event in quant_event_items if _txt(event.get("to_status")) == "trial")
    )
    auto_exited_count = (
        sum(int(row.get("auto_exited_count") or 0) for row in summary_rows)
        if summary_rows
        else sum(1 for event in quant_event_items if _txt(event.get("to_status")) in {"cooling", "retired"})
    )
    try:
        final_states_response = (
            db.list_sim_run_quant_states(run_id, checkpoint_at=last_summary.get("checkpoint_at"), page_size=50)
            if last_summary.get("checkpoint_at")
            else {"items": [], "total": 0, "page": 1, "pageSize": 50}
        )
    except sqlite3.DatabaseError as exc:
        data_risk_items.append(
            {
                "stockCode": "",
                "domain": "live_quant_drill_final_states",
                "provider": "replay_db",
                "reason": _txt(exc),
            }
        )
        final_states_response = {"items": [], "total": 0, "page": 1, "pageSize": 50}

    return {
        "runType": "live_quant_drill",
        "typeLabel": "实时量化演练",
        "title": "实时量化演练",
        "lifecycleSummary": {
            "initialQuantCount": len(metadata.get("initial_quant_universe_snapshot") or metadata.get("stock_codes") or []),
            "candidateEventCount": int(candidate_events.get("total") or 0),
            "autoPromotedCount": auto_promoted_count,
            "autoExitedCount": auto_exited_count,
            "exitOnlyCount": _drill_distinct_stock_count(quant_event_items, {"exit_only"}),
            "coolingCount": _drill_distinct_stock_count(quant_event_items, {"cooling"}),
            "retiredCount": _drill_distinct_stock_count(quant_event_items, {"retired"}),
            "dataWarningCount": len(data_risk_items),
        },
        "lifecycleSeries": [
            {
                "checkpointAt": _system_time_text(row.get("checkpoint_at"), "--"),
                "trialCount": int(row.get("trial_count") or 0),
                "activeCount": int(row.get("active_count") or 0),
                "exitOnlyCount": int(row.get("exit_only_count") or 0),
                "coolingCount": int(row.get("cooling_count") or 0),
                "retiredCount": int(row.get("retired_count") or 0),
            }
            for row in summary_rows
        ],
        "candidateEventsTable": _drill_table_payload(
            [
                {
                    "checkpointAt": _system_time_text(event.get("checkpoint_at"), "--"),
                    "stockCode": _txt(event.get("stock_code")),
                    "stockName": _txt(event.get("stock_name")),
                    "sourceType": _txt(event.get("source_type")),
                    "candidateScore": event.get("candidate_score"),
                    "statusChange": "candidate -> trial",
                    "reason": _txt(event.get("reason_text")),
                }
                for event in promoted_candidate_events.get("items", [])
            ],
            total=int(promoted_candidate_events.get("total") or 0),
            page=int(promoted_candidate_events.get("page") or 1),
            page_size=int(promoted_candidate_events.get("pageSize") or promoted_candidate_events.get("page_size") or 20),
        ),
        "exitEventsTable": _drill_table_payload(
            [
                {
                    "checkpointAt": _system_time_text(event.get("checkpoint_at"), "--"),
                    "stockCode": _txt(event.get("stock_code")),
                    "stockName": _txt(event.get("stock_name")),
                    "fromStatus": _txt(event.get("from_status")),
                    "toStatus": _txt(event.get("to_status")),
                    "healthScore": event.get("health_score_after"),
                    "reason": _txt(event.get("reason_code") or event.get("reason_text")),
                }
                for event in exit_event_items[:20]
            ],
            total=len(exit_event_items),
            page=1,
            page_size=20,
        ),
        "finalStatesTable": _drill_table_payload(
            [
                {
                    "stockCode": _txt(state.get("stock_code")),
                    "stockName": _txt(state.get("stock_name")),
                    "finalStatus": _txt(state.get("quant_status")),
                    "realizedPnl": state.get("realized_pnl"),
                    "liquidationPnl": state.get("liquidation_pnl"),
                    "stateChangeCount": state.get("state_change_count"),
                    "latestReason": _txt(state.get("latest_reason") or state.get("retire_reason")),
                }
                for state in final_states_response.get("items", [])
            ],
            total=int(final_states_response.get("total") or 0),
            page=int(final_states_response.get("page") or 1),
            page_size=int(final_states_response.get("pageSize") or final_states_response.get("page_size") or 50),
        ),
        "dataRisksTable": _drill_table_payload(data_risk_items, total=len(data_risk_items), page=1, page_size=max(1, len(data_risk_items) or 20)),
    }


def _build_his_replay_task_items(
    db: QuantSimDB,
    runs: list[dict[str, Any]],
    *,
    include_positions: bool = True,
    include_terminal_limit: int = 0,
    terminal_run_id: int | None = None,
    detail_run_id: int | None = None,
) -> list[dict[str, Any]]:
    task_items: list[dict[str, Any]] = []
    has_active_live_drill = any(
        (
            item.get("mode") == "live_quant_drill"
            or ((item.get("metadata") if isinstance(item.get("metadata"), dict) else {}).get("run_type") == "live_quant_drill")
        )
        and _txt(item.get("status")).lower() in {"queued", "running"}
        for item in runs[:10]
    )
    for task_index, item in enumerate(runs[:10]):
        run_id = int(item.get("id") or 0)
        run_metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        status_text = _txt(item.get("status"), "completed")
        is_live_drill = item.get("mode") == "live_quant_drill" or run_metadata.get("run_type") == "live_quant_drill"
        use_lightweight_task_metrics = bool(is_live_drill and status_text in {"queued", "running", "failed", "cancelled", "cancel_request", "cancel_requested"}) or has_active_live_drill
        if use_lightweight_task_metrics:
            trade_count = int(_float(item.get("trade_count"), 0.0) or 0.0)
            latest_snapshot = None
            trade_quality = {}
            signal_summary = {}
        else:
            trade_count = db.count_sim_run_trades(run_id) if run_id else int(_float(item.get("trade_count"), 0.0) or 0.0)
            latest_snapshot = db.get_latest_sim_run_snapshot(run_id) if run_id else None
            trade_quality = db.get_sim_run_trade_quality(run_id) if run_id else {}
            signal_summary = db.get_sim_run_signal_execution_summary(run_id) if run_id else {}
        buy_trade_count = int(_float(trade_quality.get("buy_count"), 0.0) or 0.0)
        sell_trade_count = int(_float(trade_quality.get("sell_count"), 0.0) or 0.0)
        winning_sell_count = int(_float(trade_quality.get("winning_sell_count"), 0.0) or 0.0)
        losing_sell_count = int(_float(trade_quality.get("losing_sell_count"), 0.0) or 0.0)
        winning_sell_pnl = _float(trade_quality.get("winning_sell_pnl"), 0.0) or 0.0
        losing_sell_pnl = _float(trade_quality.get("losing_sell_pnl"), 0.0) or 0.0
        avg_win = winning_sell_pnl / winning_sell_count if winning_sell_count > 0 else None
        avg_loss = losing_sell_pnl / losing_sell_count if losing_sell_count > 0 else None
        sell_win_rate = (winning_sell_count / sell_trade_count * 100) if sell_trade_count > 0 else None
        payoff_ratio = abs(avg_win / avg_loss) if avg_win is not None and avg_loss is not None and avg_loss < 0 else None
        final_equity = _first_non_empty(latest_snapshot or {}, ["total_equity"]) if latest_snapshot else None
        if final_equity is None:
            final_equity = item.get("final_equity")
        progress_total = int(_float(item.get("progress_total"), 0.0) or 0.0)
        progress_current = int(_float(item.get("progress_current"), 0.0) or 0.0)
        if progress_total > 0:
            progress_pct = max(0, min(int(round((progress_current / progress_total) * 100)), 100))
        elif status_text in {"completed", "failed", "cancelled"}:
            progress_pct = 100
        else:
            progress_pct = 0

        task = {
            "id": f"#{item.get('id')}",
            "runId": _txt(item.get("id")),
            "status": status_text,
            "stage": _txt(item.get("status_message") or f"{item.get('checkpoint_count', 0)} 个检查点"),
            "progress": progress_pct,
            "progressCurrent": progress_current,
            "progressTotal": progress_total,
            "checkpointCount": int(_float(item.get("checkpoint_count"), 0.0) or 0.0),
            "latestCheckpointAt": _system_time_text(item.get("latest_checkpoint_at"), "--"),
            "startAt": _system_time_text(item.get("start_datetime"), "--"),
            "endAt": _system_time_text(item.get("end_datetime"), "--"),
            "range": f"{_system_time_text(item.get('start_datetime'), '--')} -> {_system_time_text(item.get('end_datetime'), 'now')}",
            "mode": _txt(item.get("mode"), "historical_range"),
            "timeframe": _txt(item.get("timeframe"), "30m"),
            "market": _txt(item.get("market"), "CN"),
            "strategyMode": _txt(item.get("selected_strategy_mode") or item.get("strategy_mode"), "auto"),
            "returnPct": _pct(item.get("total_return_pct")),
            "finalEquity": _num(final_equity, 0),
            "cashValue": _num((latest_snapshot or {}).get("available_cash"), 0, default="--"),
            "marketValue": _num((latest_snapshot or {}).get("market_value"), 0, default="--"),
            "realizedPnl": _num((latest_snapshot or {}).get("realized_pnl"), 0, default="--"),
            "unrealizedPnl": _num((latest_snapshot or {}).get("unrealized_pnl"), 0, default="--"),
            "tradeCount": _txt(trade_count, "0"),
            "winRate": _pct(item.get("win_rate")),
            "sellWinRate": _pct(sell_win_rate, default="--"),
            "buyTradeCount": buy_trade_count,
            "sellTradeCount": sell_trade_count,
            "tradeSignalCount": int(_float(signal_summary.get("trade_signal_count"), 0.0) or 0.0),
            "buySignalCount": int(_float(signal_summary.get("buy_signal_count"), 0.0) or 0.0),
            "sellSignalCount": int(_float(signal_summary.get("sell_signal_count"), 0.0) or 0.0),
            "executedSignalCount": int(_float(signal_summary.get("executed_signal_count"), 0.0) or 0.0),
            "ignoredSignalCount": int(_float(signal_summary.get("ignored_signal_count"), 0.0) or 0.0),
            "ignoredBuySignalCount": int(_float(signal_summary.get("ignored_buy_signal_count"), 0.0) or 0.0),
            "ignoredSellSignalCount": int(_float(signal_summary.get("ignored_sell_signal_count"), 0.0) or 0.0),
            "pendingSignalCount": int(_float(signal_summary.get("pending_signal_count"), 0.0) or 0.0),
            "winningSellCount": winning_sell_count,
            "losingSellCount": losing_sell_count,
            "avgWin": _num(avg_win, 0, default="--"),
            "avgLoss": _num(avg_loss, 0, default="--"),
            "payoffRatio": _num(payoff_ratio, 2, default="--"),
            "strategyProfileId": _txt(item.get("selected_strategy_profile_id")),
            "strategyProfileName": _txt(item.get("selected_strategy_profile_name")),
            "strategyProfileVersionId": _txt(item.get("selected_strategy_profile_version_id")),
            "stockScope": _run_stock_scope_rows_from_metadata(item.get("metadata") if isinstance(item.get("metadata"), dict) else {}),
        }
        if is_live_drill:
            include_live_drill_details = detail_run_id is not None and run_id == int(detail_run_id) and status_text == "completed" and not has_active_live_drill
            if include_live_drill_details:
                task.update(_build_live_quant_drill_payload(db, item, run_id))
            else:
                task.update(
                    _build_live_quant_drill_partial_payload(
                        run_metadata,
                        _live_quant_drill_data_risk_items(run_metadata),
                    )
                )

        terminal_liquidation_items: list[dict[str, Any]] = []
        if include_positions:
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
            task["holdings"] = position_rows
            task["capitalPool"] = build_his_replay_capital_pool(db, item, latest_snapshot)

        include_terminal_liquidation = not use_lightweight_task_metrics and (
            task_index < include_terminal_limit or (terminal_run_id is not None and run_id == int(terminal_run_id))
        )
        if include_terminal_liquidation:
            run_metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            terminal_liquidation = build_terminal_liquidation(
                db,
                item,
                latest_snapshot,
                commission_rate=_normalize_fee_rate(run_metadata.get("commission_rate"), DEFAULT_COMMISSION_RATE),
                sell_tax_rate=_normalize_fee_rate(run_metadata.get("sell_tax_rate"), DEFAULT_SELL_TAX_RATE),
            )
            task["terminalLiquidation"] = terminal_liquidation.get("summary", {})
            terminal_liquidation_items = terminal_liquidation.get("items", [])

        if use_lightweight_task_metrics:
            task["topWinningTrades"] = []
            task["topLosingTrades"] = []
        else:
            task["topWinningTrades"] = _build_his_replay_ranked_trade_rows(
                db,
                run_id,
                profitable=True,
                limit=5,
                extra_items=terminal_liquidation_items,
            )
            task["topLosingTrades"] = _build_his_replay_ranked_trade_rows(
                db,
                run_id,
                profitable=False,
                limit=5,
                extra_items=terminal_liquidation_items,
            )
        if include_terminal_liquidation:
            task["profitLossByStock"] = _build_his_replay_profit_loss_by_stock_rows(db, run_id)

        task_items.append(task)
    return task_items


def _build_his_replay_trade_table(db: QuantSimDB, run_id: int, table_query: dict[str, Any] | None = None) -> dict[str, Any]:
    query = table_query or {}
    page_size = _normalize_replay_table_page_size(query.get("trade_page_size") or query.get("page_size"))
    page = _normalize_replay_table_page(query.get("trade_page"))
    actions = _replay_actions_for_filter(query.get("trade_action"))
    stock_keyword = _txt(query.get("trade_stock"))
    total = db.count_sim_run_trades(run_id, actions=actions, stock_keyword=stock_keyword)
    pagination = _replay_table_pagination(page, page_size, total)
    rows = [
        {
            "id": _txt(item.get("id"), str(i)),
            "cells": [
                _system_time_text(item.get("executed_at") or item.get("created_at"), "--"),
                f"#{_txt(item.get('signal_id'))}" if _txt(item.get("signal_id")) else "--",
                _txt(item.get("stock_code")),
                _txt(item.get("action"), "HOLD").upper(),
                _trade_kind(item),
                _txt(item.get("quantity"), "0"),
                _num(item.get("price")),
                _num(_trade_gross_amount(item)),
                _num(_trade_commission_fee(item)),
                _num(_trade_sell_tax_fee(item)),
                _num(_trade_fee_total(item)),
                _num(_trade_net_amount(item)),
                _num(item.get("realized_pnl")),
                _trade_realized_pnl_pct(item),
                _trade_execution_detail(item),
            ],
            "code": _txt(item.get("stock_code")),
            "name": _txt(item.get("stock_name")),
            "tradeProvenance": build_trade_provenance(item),
        }
        for i, item in enumerate(
            db.get_sim_run_trades(
                run_id,
                limit=page_size,
                offset=(pagination["page"] - 1) * page_size,
                actions=actions,
                stock_keyword=stock_keyword,
            )
        )
    ]
    table = _table(
        ["时间", "信号ID", "代码", "动作", "类型", "数量", "价格", "成交毛额", "手续费", "印花税", "总费用", "现金影响", "盈亏", "盈亏率", "执行明细"],
        rows,
        "暂无交易记录",
    )
    table["pagination"] = pagination
    return table


def _build_his_replay_signal_table(db: QuantSimDB, run_id: int, table_query: dict[str, Any] | None = None) -> dict[str, Any]:
    query = table_query or {}
    page_size = _normalize_replay_table_page_size(query.get("signal_page_size") or query.get("page_size"))
    page = _normalize_replay_table_page(query.get("signal_page"))
    actions = _replay_actions_for_filter(query.get("signal_action"))
    stock_keyword = _txt(query.get("signal_stock"))
    total = db.count_sim_run_signals(run_id, actions=actions, stock_keyword=stock_keyword)
    pagination = _replay_table_pagination(page, page_size, total)
    signal_rows: list[dict[str, Any]] = []
    for i, item in enumerate(
        db.get_sim_run_signals(
            run_id,
            limit=page_size,
            offset=(pagination["page"] - 1) * page_size,
            actions=actions,
            stock_keyword=stock_keyword,
            include_strategy_profile=True,
        )
    ):
        checkpoint_at = _system_time_text(item.get("checkpoint_at") or item.get("created_at"), "--")
        row = build_signal_summary_row(item, i, time_key="checkpoint_at", status_key="status")
        if len(row.get("cells", [])) > 1:
            row["cells"][1] = checkpoint_at
        row["checkpointAt"] = checkpoint_at
        signal_rows.append(row)
    table = build_signal_summary_table(signal_rows)
    table["pagination"] = pagination
    return table


def _build_his_replay_holdings_rows(db: QuantSimDB, run_id: int) -> list[dict[str, Any]]:
    return [
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
        for i, item in enumerate(db.get_sim_run_positions(run_id))
    ]


def _calculate_replay_equity_metrics(initial_cash: float, equity_values: list[float]) -> tuple[float, float, float]:
    final_equity = equity_values[-1] if equity_values else initial_cash
    total_return_pct = ((final_equity - initial_cash) / initial_cash * 100) if initial_cash > 0 else 0.0
    peak = initial_cash
    max_drawdown_pct = 0.0
    for value in equity_values:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown_pct = max(max_drawdown_pct, (peak - value) / peak * 100)
    return final_equity, total_return_pct, max_drawdown_pct


def _his_replay_run_has_live_worker(run: dict[str, Any]) -> bool:
    from app.quant_sim.replay_runner import _is_pid_running

    worker_pid = int(_float(run.get("worker_pid"), 0.0) or 0.0)
    return worker_pid > 0 and _is_pid_running(worker_pid)


def _finalize_cancelled_his_replay_run(
    db: QuantSimDB,
    run: dict[str, Any],
    *,
    stale_worker: bool,
) -> None:
    run_id = int(run.get("id") or 0)
    if run_id <= 0:
        return
    status = _txt(run.get("status")).lower()
    if status in {"cancelled", "completed", "failed"}:
        return

    checkpoints = db.get_sim_run_checkpoints(run_id)
    trades = db.get_sim_run_trades(run_id)
    snapshots = db.get_sim_run_snapshots(run_id)
    checkpoint_equity = [float(item.get("total_equity") or 0) for item in checkpoints if item.get("total_equity") is not None]
    snapshot_equity = [float(item.get("total_equity") or 0) for item in snapshots if item.get("total_equity") is not None]
    initial_cash = float(run.get("initial_cash") or 0)
    final_equity, total_return_pct, max_drawdown_pct = _calculate_replay_equity_metrics(initial_cash, snapshot_equity or checkpoint_equity)
    sell_trades = [trade for trade in trades if _txt(trade.get("action")).upper() == "SELL"]
    wins = [trade for trade in sell_trades if float(trade.get("realized_pnl") or 0) > 0]
    win_rate = (len(wins) / len(sell_trades) * 100) if sell_trades else 0.0

    db.finalize_sim_run(
        run_id,
        status="cancelled",
        final_equity=final_equity,
        total_return_pct=total_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        win_rate=win_rate,
        trade_count=len(trades),
        status_message="回放任务已取消，可开始新的回放任务。",
        metadata={
            "cancelled_by_user": True,
            "stale_worker_cancel": stale_worker,
            "checkpoint_count": len(checkpoints),
        },
    )
    db.append_sim_run_event(run_id, "回放任务已取消，可开始新的回放任务。", level="warning")


def _finalize_failed_his_replay_run_from_stale_worker(
    db: QuantSimDB,
    run: dict[str, Any],
) -> None:
    run_id = int(run.get("id") or 0)
    if run_id <= 0:
        return
    status = _txt(run.get("status")).lower()
    if status in {"cancelled", "completed", "failed"}:
        return

    checkpoints = db.get_sim_run_checkpoints(run_id)
    trades = db.get_sim_run_trades(run_id)
    snapshots = db.get_sim_run_snapshots(run_id)
    checkpoint_equity = [float(item.get("total_equity") or 0) for item in checkpoints if item.get("total_equity") is not None]
    snapshot_equity = [float(item.get("total_equity") or 0) for item in snapshots if item.get("total_equity") is not None]
    initial_cash = float(run.get("initial_cash") or 0)
    final_equity, total_return_pct, max_drawdown_pct = _calculate_replay_equity_metrics(initial_cash, snapshot_equity or checkpoint_equity)
    sell_trades = [trade for trade in trades if _txt(trade.get("action")).upper() == "SELL"]
    wins = [trade for trade in sell_trades if float(trade.get("realized_pnl") or 0) > 0]
    win_rate = (len(wins) / len(sell_trades) * 100) if sell_trades else 0.0
    progress_current = int(_float(run.get("progress_current"), 0.0) or 0.0)
    progress_total = int(_float(run.get("progress_total"), 0.0) or 0.0)
    latest_checkpoint = _system_time_text(run.get("latest_checkpoint_at"), "")
    detail = f"已完成 {progress_current}/{progress_total} 个检查点"
    if latest_checkpoint:
        detail = f"{detail}，最后检查点 {latest_checkpoint}"

    db.finalize_sim_run(
        run_id,
        status="failed",
        final_equity=final_equity,
        total_return_pct=total_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        win_rate=win_rate,
        trade_count=len(trades),
        status_message=f"后台回放 worker 已退出，任务未写入最终状态（{detail}）。",
        metadata={
            "stale_worker_failed": True,
            "checkpoint_count": len(checkpoints),
            "worker_pid": run.get("worker_pid"),
        },
    )
    db.append_sim_run_event(run_id, f"后台回放 worker 已退出，已标记任务失败（{detail}）。", level="error")


def _his_replay_database_busy(exc: BaseException) -> HTTPException:
    return HTTPException(status_code=503, detail="历史回放正在写入数据库，请稍后刷新。")


def _reconcile_stale_his_replay_runs(db: QuantSimDB) -> None:
    for run in db.get_sim_runs(limit=20):
        status = _txt(run.get("status")).lower()
        cancel_requested = bool(run.get("cancel_requested"))
        if status == "cancel_requested" or (status in {"queued", "running"} and cancel_requested):
            if not _his_replay_run_has_live_worker(run):
                _finalize_cancelled_his_replay_run(db, run, stale_worker=True)
            continue
        if status not in {"queued", "running"}:
            continue
        worker_pid = int(_float(run.get("worker_pid"), 0.0) or 0.0)
        progress_current = int(_float(run.get("progress_current"), 0.0) or 0.0)
        progress_total = int(_float(run.get("progress_total"), 0.0) or 0.0)
        if progress_total <= 0 or progress_current < progress_total:
            if worker_pid > 0 and not _his_replay_run_has_live_worker(run):
                _finalize_failed_his_replay_run_from_stale_worker(db, run)
                continue
            continue

        run_id = int(run.get("id") or 0)
        checkpoints = db.get_sim_run_checkpoints(run_id)
        trades = db.get_sim_run_trades(run_id)
        snapshots = db.get_sim_run_snapshots(run_id)
        checkpoint_equity = [float(item.get("total_equity") or 0) for item in checkpoints if item.get("total_equity") is not None]
        snapshot_equity = [float(item.get("total_equity") or 0) for item in snapshots if item.get("total_equity") is not None]
        equity_values = snapshot_equity or checkpoint_equity
        initial_cash = float(run.get("initial_cash") or 0)
        final_equity, total_return_pct, max_drawdown_pct = _calculate_replay_equity_metrics(initial_cash, equity_values)
        sell_trades = [trade for trade in trades if _txt(trade.get("action")).upper() == "SELL"]
        wins = [trade for trade in sell_trades if float(trade.get("realized_pnl") or 0) > 0]
        win_rate = (len(wins) / len(sell_trades) * 100) if sell_trades else 0.0
        auto_executed = sum(int(_float(item.get("auto_executed"), 0.0) or 0.0) for item in checkpoints)

        if auto_executed > 0 and not trades:
            db.finalize_sim_run(
                run_id,
                status="failed",
                final_equity=final_equity,
                total_return_pct=total_return_pct,
                max_drawdown_pct=max_drawdown_pct,
                win_rate=win_rate,
                trade_count=0,
                status_message="回放检查点已完成，但最终成交汇总未落库，请重新回放。",
                metadata={"reconciled_stale_run": True, "auto_executed": auto_executed},
            )
            db.append_sim_run_event(run_id, "回放检查点已完成，但最终成交汇总未落库，已标记为失败。", level="error")
            continue

        db.finalize_sim_run(
            run_id,
            status="completed",
            final_equity=final_equity,
            total_return_pct=total_return_pct,
            max_drawdown_pct=max_drawdown_pct,
            win_rate=win_rate,
            trade_count=len(trades),
            status_message="回放任务已完成",
            metadata={"reconciled_stale_run": True},
        )
        db.append_sim_run_event(run_id, "回放任务已完成，已自动修正任务终态。", level="success")


def _snapshot_his_replay_progress(context: UIApiContext, table_query: dict[str, Any] | None = None) -> dict[str, Any]:
    db = context.replay_db()
    _reconcile_stale_his_replay_runs(db)
    query = table_query or {}
    runs = db.get_sim_runs(limit=20)
    requested_run_id = _int(query.get("run_id"))
    selected_run = db.get_sim_run(requested_run_id) if requested_run_id is not None else None
    if selected_run is None:
        selected_run = runs[0] if runs else None
    selected_run_id = int(selected_run.get("id") or 0) if selected_run else 0
    payload: dict[str, Any] = {
        "updatedAt": _now(),
        "tasks": _build_his_replay_task_items(
            db,
            runs,
            include_positions=False,
            terminal_run_id=selected_run_id or None,
            detail_run_id=selected_run_id or None,
        ),
    }
    if selected_run_id:
        run_id = selected_run_id
        selected_metadata = selected_run.get("metadata") if isinstance(selected_run.get("metadata"), dict) else {}
        selected_is_active_live_drill = (
            selected_run.get("mode") == "live_quant_drill" or selected_metadata.get("run_type") == "live_quant_drill"
        ) and _txt(selected_run.get("status")).lower() in {"queued", "running"}
        if selected_is_active_live_drill:
            payload.update(
                {
                    "holdings": _table(["代码", "名称", "数量", "成本", "现价", "浮盈亏"], [], "任务运行中，持仓明细完成后加载"),
                    "trades": _table(
                        ["时间", "信号ID", "代码", "动作", "类型", "数量", "价格", "成交毛额", "手续费", "印花税", "总费用", "现金影响", "盈亏", "盈亏率", "执行明细"],
                        [],
                        "任务运行中，交易明细完成后加载",
                    ),
                    "signals": build_signal_summary_table([], "任务运行中，信号明细完成后加载"),
                    "tradeCostSummary": _trade_cost_summary_metrics({}) + _replay_signal_execution_metrics({}),
                }
            )
        else:
            payload.update(
                {
                    "holdings": _table(["代码", "名称", "数量", "成本", "现价", "浮盈亏"], _build_his_replay_holdings_rows(db, run_id), "暂无持仓"),
                    "trades": _build_his_replay_trade_table(db, run_id, table_query),
                    "signals": _build_his_replay_signal_table(db, run_id, table_query),
                    "tradeCostSummary": _trade_cost_summary_metrics(db.get_sim_run_trade_cost_summary_lightweight(run_id))
                    + _replay_signal_execution_metrics(db.get_sim_run_signal_execution_summary(run_id)),
                }
            )
    return payload


def _build_checkpoint_selector_item(item: dict[str, Any]) -> dict[str, Any]:
    checkpoint_at = _system_time_text(item.get("checkpoint_at"), "--")
    return {
        "id": _txt(item.get("id"), checkpoint_at),
        "checkpointAt": checkpoint_at,
        "label": checkpoint_at,
        "cashValue": _num(item.get("available_cash"), 0),
        "marketValue": _num(item.get("market_value"), 0),
        "totalEquity": _num(item.get("total_equity"), 0),
        "signalsCreated": int(_float(item.get("signals_created"), 0.0) or 0),
        "autoExecuted": int(_float(item.get("auto_executed"), 0.0) or 0),
    }


def _checkpoint_matches_system_search(item: dict[str, Any], keyword: str) -> bool:
    search = _txt(keyword).lower()
    if not search:
        return True
    values = [
        _txt(item.get("id")),
        _txt(item.get("checkpoint_at")),
        _system_time_text(item.get("checkpoint_at"), ""),
    ]
    return any(search in value.lower() for value in values if value)


def _get_checkpoint_selector_page(
    db: QuantSimDB,
    run_id: int,
    *,
    page: int,
    page_size: int,
    keyword: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if not _txt(keyword):
        total = db.count_sim_run_checkpoints(run_id)
        pagination = _replay_table_pagination(page, page_size, total)
        rows = db.get_sim_run_checkpoints(
            run_id,
            limit=page_size,
            offset=(pagination["page"] - 1) * page_size,
            order="desc",
        )
        return rows, pagination

    matched = [
        item
        for item in db.get_sim_run_checkpoints(run_id, order="desc")
        if _checkpoint_matches_system_search(item, keyword)
    ]
    pagination = _replay_table_pagination(page, page_size, len(matched))
    start = (pagination["page"] - 1) * page_size
    return matched[start : start + page_size], pagination


def _get_sim_run_checkpoint_by_system_time(db: QuantSimDB, run_id: int, checkpoint_at: str) -> dict[str, Any] | None:
    selected = db.get_sim_run_checkpoint_at(run_id, checkpoint_at)
    if selected is not None:
        return selected
    target = _system_time_text(checkpoint_at, "")
    if not target:
        return None
    for item in db.get_sim_run_checkpoints(run_id):
        if _system_time_text(item.get("checkpoint_at"), "") == target:
            return item
    return None


def _snapshot_his_replay_capital_pool(context: UIApiContext, table_query: dict[str, Any] | None = None) -> dict[str, Any]:
    db = context.replay_db()
    _reconcile_stale_his_replay_runs(db)
    query = table_query or {}
    requested_run_id = _int(query.get("run_id"))
    run = db.get_sim_run(requested_run_id) if requested_run_id is not None else None
    if run is None:
        run = next(iter(db.get_sim_runs(limit=1)), None)
    if not run:
        raise HTTPException(status_code=404, detail="未找到历史回放任务")

    run_id = int(run.get("id") or 0)
    page_size = _normalize_replay_table_page_size(query.get("checkpoint_page_size"), default=50)
    requested_page = _normalize_replay_table_page(query.get("checkpoint_page"))
    checkpoint_search = _txt(query.get("checkpoint_search"))
    checkpoint_rows, pagination = _get_checkpoint_selector_page(
        db,
        run_id,
        page=requested_page,
        page_size=page_size,
        keyword=checkpoint_search,
    )

    selected_checkpoint = None
    checkpoint_at = _txt(query.get("checkpoint_at"))
    if checkpoint_at:
        selected_checkpoint = _get_sim_run_checkpoint_by_system_time(db, run_id, checkpoint_at)
    if selected_checkpoint is None:
        selected_checkpoint = checkpoint_rows[0] if checkpoint_rows else None
    if selected_checkpoint is None:
        latest_snapshot = db.get_latest_sim_run_snapshot(run_id)
        capital_pool = build_his_replay_capital_pool(db, run, latest_snapshot)
        return {
            "updatedAt": _now(),
            "runId": _txt(run_id),
            "selectedCheckpointAt": _txt(capital_pool["task"].get("checkpoint"), "--"),
            "checkpoints": {"items": [], "pagination": pagination},
            "capitalPool": capital_pool,
        }

    return {
        "updatedAt": _now(),
        "runId": _txt(run_id),
        "selectedCheckpointAt": _system_time_text(selected_checkpoint.get("checkpoint_at"), "--"),
        "checkpoints": {
            "items": [_build_checkpoint_selector_item(item) for item in checkpoint_rows],
            "pagination": pagination,
        },
        "capitalPool": build_his_replay_capital_pool(
            db,
            run,
            selected_checkpoint,
            checkpoint=selected_checkpoint,
            include_position_fallback=False,
        ),
    }


def _snapshot_his_replay(context: UIApiContext, table_query: dict[str, Any] | None = None) -> dict[str, Any]:
    db = context.replay_db()
    _reconcile_stale_his_replay_runs(db)
    scheduler_status = context.scheduler().get_status()
    quant_db = context.quant_db()
    strategy_profiles = [
        {
            "id": _txt(item.get("id")),
            "name": _txt(item.get("name") or item.get("id")),
            "enabled": bool(item.get("enabled", True)),
            "isDefault": bool(item.get("is_default", False)),
        }
        for item in quant_db.list_strategy_profiles(include_disabled=False)
    ]
    runs = db.get_sim_runs(limit=20)
    query = table_query or {}
    requested_run_id = _int(query.get("run_id"))
    run = db.get_sim_run(requested_run_id) if requested_run_id is not None else None
    if run is None:
        run = runs[0] if runs else None
    candidate_pool_table = _build_his_replay_candidate_pool_table(context, run, table_query)

    if not run:
        return {
            "updatedAt": _now(),
            "config": {
                "mode": "历史区间",
                "range": "--",
                "timeframe": "30m",
                "market": "CN",
                "strategyMode": "auto",
                "strategyProfileId": _enabled_strategy_profile_id(context, scheduler_status.get("strategy_profile_id")),
                "aiDynamicStrategy": _txt(scheduler_status.get("ai_dynamic_strategy"), DEFAULT_AI_DYNAMIC_STRATEGY),
                "aiDynamicStrength": _txt(scheduler_status.get("ai_dynamic_strength"), f"{DEFAULT_AI_DYNAMIC_STRENGTH:.2f}"),
                "aiDynamicLookback": _txt(scheduler_status.get("ai_dynamic_lookback"), str(DEFAULT_AI_DYNAMIC_LOOKBACK)),
                "strategyProfiles": strategy_profiles,
                "initialCapital": _num(context.quant_db().get_account_summary().get("initial_cash"), 0, default="100000"),
                "commissionRatePct": _fee_rate_pct_text(scheduler_status.get("commission_rate"), DEFAULT_COMMISSION_RATE),
                "sellTaxRatePct": _fee_rate_pct_text(scheduler_status.get("sell_tax_rate"), DEFAULT_SELL_TAX_RATE),
            },
            "metrics": [
                _metric("回放结果", "--"),
                _metric("最终总权益", "--"),
                _metric("交易笔数", "0"),
                _metric("胜率", "--"),
            ],
            "candidatePool": candidate_pool_table,
            "tasks": [],
            "tradingAnalysis": {"title": "交易分析", "body": "暂无回放记录。", "chips": []},
            "holdings": _table(["代码", "名称", "数量", "成本", "现价", "浮盈亏"], [], "暂无持仓"),
            "trades": _table(
                ["时间", "信号ID", "代码", "动作", "类型", "数量", "价格", "成交毛额", "手续费", "印花税", "总费用", "现金影响", "盈亏", "盈亏率", "执行明细"],
                [],
                "暂无交易记录",
            ),
            "signals": build_signal_summary_table([], "暂无信号"),
            "tradeCostSummary": _trade_cost_summary_metrics({}),
            "curve": [],
        }

    rid = int(run["id"])
    run_metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    selected_is_active_live_drill = (
        run.get("mode") == "live_quant_drill" or run_metadata.get("run_type") == "live_quant_drill"
    ) and _txt(run.get("status")).lower() in {"queued", "running"}

    if selected_is_active_live_drill:
        signal_table = build_signal_summary_table([], "任务运行中，信号明细完成后加载")
        trade_table = _table(
            ["时间", "信号ID", "代码", "动作", "类型", "数量", "价格", "成交毛额", "手续费", "印花税", "总费用", "现金影响", "盈亏", "盈亏率", "执行明细"],
            [],
            "任务运行中，交易明细完成后加载",
        )
        trade_count = int(_float(run.get("trade_count"), 0.0) or 0.0)
    else:
        signal_table = _build_his_replay_signal_table(db, rid, table_query)
        trade_table = _build_his_replay_trade_table(db, rid, table_query)
        trade_count = db.count_sim_run_trades(rid)

    task_items = _build_his_replay_task_items(db, runs, include_positions=False, terminal_run_id=rid, detail_run_id=rid)

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
    if selected_is_active_live_drill:
        latest_snapshot = None
        terminal_liquidation = {"summary": {}, "items": []}
        holdings_table = _table(["代码", "名称", "数量", "成本", "现价", "浮盈亏"], [], "任务运行中，持仓明细完成后加载")
        trade_cost_summary = _replay_execution_summary_metrics(run, latest_snapshot, {}, scheduler_status) + _replay_signal_execution_metrics({})
        curve = []
    else:
        latest_snapshot = db.get_latest_sim_run_snapshot(rid)
        terminal_liquidation = build_terminal_liquidation(
            db,
            run,
            latest_snapshot,
            commission_rate=replay_commission_rate,
            sell_tax_rate=replay_sell_tax_rate,
        )
        holdings_table = _table(
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
        )
        trade_cost_summary = (
            _replay_execution_summary_metrics(
                run,
                latest_snapshot,
                db.get_sim_run_trade_cost_summary(rid),
                scheduler_status,
            )
            + _replay_signal_execution_metrics(db.get_sim_run_signal_execution_summary(rid))
            + terminal_liquidation_metrics(terminal_liquidation)
        )
        curve = [
            {"label": _system_time_text(item.get("created_at"), str(i)), "value": float(item.get("total_equity") or 0)}
            for i, item in enumerate(db.get_sim_run_snapshots(rid))
        ]

    return {
        "updatedAt": _now(),
        "config": {
            "mode": _txt(run.get("mode"), "historical_range"),
            "range": f"{_system_time_text(run.get('start_datetime'), '--')} -> {_system_time_text(run.get('end_datetime'), 'now')}",
            "timeframe": _txt(run.get("timeframe"), "30m"),
            "market": _txt(run.get("market"), "CN"),
            "strategyMode": _txt(run.get("selected_strategy_mode") or run.get("strategy_mode"), "auto"),
            "strategyProfileId": _enabled_strategy_profile_id(
                context,
                run.get("selected_strategy_profile_id") or scheduler_status.get("strategy_profile_id"),
            ),
            "aiDynamicStrategy": replay_ai_dynamic_strategy,
            "aiDynamicStrength": replay_ai_dynamic_strength,
            "aiDynamicLookback": replay_ai_dynamic_lookback,
            "strategyProfiles": strategy_profiles,
            "initialCapital": _num(run.get("initial_cash"), 0, default="100000"),
            "commissionRatePct": _fee_rate_pct_text(replay_commission_rate, DEFAULT_COMMISSION_RATE),
            "sellTaxRatePct": _fee_rate_pct_text(replay_sell_tax_rate, DEFAULT_SELL_TAX_RATE),
        },
        "metrics": [
            _metric("回放结果", _pct(run.get("total_return_pct"))),
            _metric("最终总权益", _num(run.get("final_equity"), 0)),
            _metric("交易笔数", _txt(trade_count, "0")),
            _metric("胜率", _pct(run.get("win_rate"))),
        ],
        "candidatePool": candidate_pool_table,
        "tasks": task_items,
        "tradingAnalysis": {
            "title": "交易分析",
            "body": "回放页会把交易分析拆成“人话结论 + 策略解释 + 量化证据”三层。",
            "chips": [],
        },
        "holdings": holdings_table,
        "trades": trade_table,
        "signals": signal_table,
        "tradeCostSummary": trade_cost_summary,
        "curve": curve,
    }
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
        initial_cash=_float(
            body.get("initialCash") if "initialCash" in body else body.get("initial_cash"),
            float(defaults.get("initial_cash") or 100000),
        ),
        strategy_mode=body.get("strategyMode") or body.get("strategy_mode") or defaults["strategy_mode"],
        strategy_profile_id=_enabled_strategy_profile_id(
            context,
            body.get("strategyProfileId") or body.get("strategy_profile_id") or defaults.get("strategy_profile_id"),
        ),
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


def _action_his_replay_cancel(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    run_id = _int(body.get("id"))
    if run_id is None:
        latest = next(iter(context.replay_db().get_sim_runs(limit=1)), None)
        run_id = _int(latest.get("id")) if latest else None
    if run_id is not None:
        db = context.replay_db()
        db.request_sim_run_cancel(run_id)
        run = db.get_sim_run(run_id)
        if run is not None and not _his_replay_run_has_live_worker(run):
            _finalize_cancelled_his_replay_run(db, run, stale_worker=True)
        else:
            db.append_sim_run_event(run_id, "已请求取消回放任务，可开始新的回放任务。", level="warning")
    return _snapshot_his_replay(context)


def _action_his_replay_delete(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    run_id = _int(body.get("id"))
    if run_id is not None:
        context.replay_db().delete_sim_run(run_id)
    return _snapshot_his_replay(context)
