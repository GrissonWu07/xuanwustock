from __future__ import annotations

from app.gateway.deps import *
from app.gateway.constants import REPLAY_TABLE_PAGE_SIZE
from app.gateway.context import UIApiContext
from app.gateway.portfolio import _candidate_rows
from app.gateway.replay_capital_pool import build_live_sim_capital_pool
from app.gateway.scheduler_config import _fee_rate_pct_text, _normalize_dynamic_lookback, _normalize_dynamic_strength, _scheduler_update_kwargs
from app.gateway.signal_table import build_signal_summary_row, build_signal_summary_table
from app.gateway.table_query import _normalize_replay_table_page, _normalize_replay_table_page_size, _replay_actions_for_filter, _replay_table_pagination
from app.gateway.trades import (
    _trade_commission_fee,
    _trade_cost_summary_metrics,
    _trade_execution_detail,
    _trade_fee_total,
    _trade_gross_amount,
    _trade_kind,
    _trade_net_amount,
    _trade_realized_pnl_pct,
    _trade_sell_tax_fee,
    _trade_slot_units,
)

def _snapshot_live_sim(context: UIApiContext, table_query: dict[str, Any] | None = None) -> dict[str, Any]:
    db = context.quant_db()
    scheduler = context.scheduler().get_status()
    account = db.get_account_summary()
    trade_cost_summary = db.get_trade_cost_summary()
    page_size = _normalize_replay_table_page_size((table_query or {}).get("pageSize"), default=20)
    page = _normalize_replay_table_page((table_query or {}).get("page"))
    search = _txt((table_query or {}).get("search"))
    candidate_total = context.candidate_pool().count_candidates(status="active", search=search)
    candidate_pagination = _replay_table_pagination(page, page_size, candidate_total)
    candidate_page_rows = _candidate_rows(
        context,
        status="active",
        include_actions=True,
        limit=page_size,
        offset=(candidate_pagination["page"] - 1) * page_size,
        search=search,
    )
    candidate_table = _table(["股票代码", "股票名称", "来源", "最新价格"], candidate_page_rows, "暂无候选股票")
    candidate_table["pagination"] = candidate_pagination
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
            "capitalSlotEnabled": bool(scheduler.get("capital_slot_enabled", True)),
            "capitalPoolMinCash": _txt(scheduler.get("capital_pool_min_cash"), "20000"),
            "capitalPoolMaxCash": _txt(scheduler.get("capital_pool_max_cash"), "1000000"),
            "capitalSlotMinCash": _txt(scheduler.get("capital_slot_min_cash"), "20000"),
            "capitalMaxSlots": _txt(scheduler.get("capital_max_slots"), "25"),
            "capitalMinBuySlotFraction": _txt(scheduler.get("capital_min_buy_slot_fraction"), "0.25"),
            "capitalFullBuyEdge": _txt(scheduler.get("capital_full_buy_edge"), "0.25"),
            "capitalConfidenceWeight": _txt(scheduler.get("capital_confidence_weight"), "0.35"),
            "capitalHighPriceThreshold": _txt(scheduler.get("capital_high_price_threshold"), "100"),
            "capitalHighPriceMaxSlotUnits": _txt(scheduler.get("capital_high_price_max_slot_units"), "2"),
            "capitalSellCashReusePolicy": _txt(scheduler.get("capital_sell_cash_reuse_policy"), "next_batch"),
        },
        "status": {
            "running": "运行中" if scheduler.get("running") else "已停止",
            "lastRun": _txt(scheduler.get("last_run_at"), "--"),
            "nextRun": _txt(scheduler.get("next_run"), "--"),
            "candidateCount": _txt(context.candidate_pool().count_candidates(status="active"), "0"),
        },
        "metrics": [
            _metric("总权益", account.get("total_equity", 0)),
            _metric("当前持仓", account.get("position_count", 0)),
            _metric("持仓市值", account.get("market_value", 0)),
            _metric("现金值", account.get("available_cash")),
            _metric("总费用", _num(trade_cost_summary.get("fee_total"))),
            _metric("已实现盈亏", _num(account.get("realized_pnl"))),
            _metric("浮动盈亏", _num(account.get("unrealized_pnl"))),
            _metric("交易笔数", _txt(account.get("trade_count"), "0")),
            _metric("收益率", _pct(account.get("total_return_pct"))),
        ],
        "capitalSlots": _table(
            ["Slot", "预算", "可用", "占用", "待结算"],
            [
                {
                    "id": _txt(item.get("slot_index")),
                    "cells": [
                        _txt(item.get("slot_index")),
                        _num(item.get("budget_cash")),
                        _num(item.get("available_cash")),
                        _num(item.get("occupied_cash")),
                        _num(item.get("settling_cash")),
                    ],
                }
                for item in db.get_capital_slots()
            ],
            "暂无资金槽",
        ),
        "capitalPool": build_live_sim_capital_pool(db),
        "candidatePool": candidate_table,
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
        "trades": _live_trade_table(context, table_query),
        "tradeCostSummary": _trade_cost_summary_metrics(trade_cost_summary),
        "curve": [
            {"label": _txt(item.get("created_at"), str(i)), "value": float(item.get("total_equity") or 0)}
            for i, item in enumerate(db.get_account_snapshots(limit=20))
        ],
    }
def _live_signal_table(
    context: UIApiContext,
    *,
    page: int = 1,
    page_size: int = REPLAY_TABLE_PAGE_SIZE,
    action: str = "ALL",
    stock: str = "",
) -> dict[str, Any]:
    db = context.quant_db()
    safe_page_size = _normalize_replay_table_page_size(page_size)
    actions = _replay_actions_for_filter(action)
    total = db.count_signals(actions=actions, stock_keyword=stock)
    pagination = _replay_table_pagination(page, safe_page_size, total)
    rows: list[dict[str, Any]] = []
    for i, item in enumerate(
        db.get_signals(
            limit=safe_page_size,
            offset=(pagination["page"] - 1) * safe_page_size,
            actions=actions,
            stock_keyword=stock,
        )
    ):
        rows.append(build_signal_summary_row(item, i, time_key="updated_at", status_key="status"))
    return {
        "updatedAt": _now(),
        "table": {
            **build_signal_summary_table(rows),
            "pagination": pagination,
        },
    }


def _live_trade_table(context: UIApiContext, table_query: dict[str, Any] | None = None) -> dict[str, Any]:
    db = context.quant_db()
    query = table_query or {}
    page_size = _normalize_replay_table_page_size(query.get("page_size") or query.get("pageSize"))
    page = _normalize_replay_table_page(query.get("trade_page") or query.get("page"))
    actions = _replay_actions_for_filter(query.get("trade_action") or query.get("action"))
    stock_keyword = _txt(query.get("trade_stock") or query.get("stock"))
    total = db.count_trade_history(actions=actions, stock_keyword=stock_keyword)
    pagination = _replay_table_pagination(page, page_size, total)
    rows = [
        {
            "id": _txt(item.get("id"), str(i)),
            "cells": [
                _txt(item.get("executed_at") or item.get("created_at"), "--"),
                _txt(item.get("stock_code")),
                _txt(item.get("action")),
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
                _trade_slot_units(item),
                _trade_execution_detail(item),
                _txt(item.get("note") or "自动执行"),
            ],
            "code": _txt(item.get("stock_code")),
            "name": _txt(item.get("stock_name")),
        }
        for i, item in enumerate(
            db.get_trade_history(
                limit=page_size,
                offset=(pagination["page"] - 1) * page_size,
                actions=actions,
                stock_keyword=stock_keyword,
            )
        )
    ]
    table = _table(
        ["时间", "代码", "动作", "类型", "数量", "价格", "成交毛额", "手续费", "印花税", "总费用", "现金影响", "盈亏", "盈亏率", "Slot用量", "执行明细", "备注"],
        rows,
        "暂无交易记录",
    )
    table["pagination"] = pagination
    return table


def _configure_live_initial_cash_if_present(context: UIApiContext, payload: Any) -> None:
    body = _payload_dict(payload)
    if "initialCash" not in body and "initial_cash" not in body:
        return
    initial_cash = _float(body.get("initialCash") if "initialCash" in body else body.get("initial_cash"))
    if initial_cash is None or initial_cash <= 0:
        raise ValueError("initialCash must be positive")
    context.portfolio().configure_account(initial_cash=float(initial_cash))


def _action_live_sim_save(context: UIApiContext, payload: Any) -> dict[str, Any]:
    _configure_live_initial_cash_if_present(context, payload)
    updates = _scheduler_update_kwargs(payload)
    if updates:
        context.scheduler().update_config(**updates)
    return _snapshot_live_sim(context)


def _action_live_sim_start(context: UIApiContext, payload: Any) -> dict[str, Any]:
    scheduler = context.scheduler()
    _configure_live_initial_cash_if_present(context, payload)
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
    engine = QuantSimEngine(
        db_file=context.quant_sim_db_file,
        watchlist_db_file=context.watchlist_db_file,
        watchlist_service=context.watchlist(),
        stock_analysis_db_file=context.stock_analysis_db_file,
    )
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
