from __future__ import annotations

from app.gateway.deps import *
from app.gateway.context import UIApiContext
from app.gateway.scheduler_config import _enabled_strategy_profile_id, _fee_rate_pct_text, _latest_replay_defaults, _normalize_dynamic_lookback, _normalize_dynamic_strength, _normalize_fee_rate, _payload_fee_rate
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
    _trade_slot_units,
)
from app.gateway.replay_capital_pool import build_his_replay_capital_pool
from app.gateway.replay_liquidation import build_terminal_liquidation, terminal_liquidation_metrics


def _build_his_replay_ranked_trade_row(item: dict[str, Any], index: int) -> dict[str, Any]:
    metadata = _trade_metadata(item)
    signal_id = _txt(item.get("signal_id"))
    return {
        "id": _txt(item.get("id"), str(index)),
        "cells": [
            _txt(item.get("executed_at") or item.get("created_at"), "--"),
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


def _build_his_replay_task_items(
    db: QuantSimDB,
    runs: list[dict[str, Any]],
    *,
    include_positions: bool = True,
) -> list[dict[str, Any]]:
    task_items: list[dict[str, Any]] = []
    for item in runs[:10]:
        run_id = int(item.get("id") or 0)
        trade_count = db.count_sim_run_trades(run_id) if run_id else int(_float(item.get("trade_count"), 0.0) or 0.0)
        latest_snapshot = db.get_latest_sim_run_snapshot(run_id) if run_id else None
        trade_quality = db.get_sim_run_trade_quality(run_id) if run_id else {}
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
        status_text = _txt(item.get("status"), "completed")
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
            "latestCheckpointAt": _txt(item.get("latest_checkpoint_at"), "--"),
            "startAt": _txt(item.get("start_datetime"), "--"),
            "endAt": _txt(item.get("end_datetime"), "--"),
            "range": f"{_txt(item.get('start_datetime'), '--')} -> {_txt(item.get('end_datetime'), 'now')}",
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
            "winningSellCount": winning_sell_count,
            "losingSellCount": losing_sell_count,
            "avgWin": _num(avg_win, 0, default="--"),
            "avgLoss": _num(avg_loss, 0, default="--"),
            "payoffRatio": _num(payoff_ratio, 2, default="--"),
            "strategyProfileId": _txt(item.get("selected_strategy_profile_id")),
            "strategyProfileName": _txt(item.get("selected_strategy_profile_name")),
            "strategyProfileVersionId": _txt(item.get("selected_strategy_profile_version_id")),
        }

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

        task_items.append(task)
    return task_items


def _build_his_replay_trade_table(db: QuantSimDB, run_id: int, table_query: dict[str, Any] | None = None) -> dict[str, Any]:
    query = table_query or {}
    page_size = _normalize_replay_table_page_size(query.get("page_size"))
    page = _normalize_replay_table_page(query.get("trade_page"))
    actions = _replay_actions_for_filter(query.get("trade_action"))
    stock_keyword = _txt(query.get("trade_stock"))
    total = db.count_sim_run_trades(run_id, actions=actions, stock_keyword=stock_keyword)
    pagination = _replay_table_pagination(page, page_size, total)
    rows = [
        {
            "id": _txt(item.get("id"), str(i)),
            "cells": [
                _txt(item.get("executed_at") or item.get("created_at"), "--"),
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
                _trade_slot_units(item),
                _trade_execution_detail(item),
            ],
            "code": _txt(item.get("stock_code")),
            "name": _txt(item.get("stock_name")),
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
        ["时间", "信号ID", "代码", "动作", "类型", "数量", "价格", "成交毛额", "手续费", "印花税", "总费用", "现金影响", "盈亏", "盈亏率", "Slot用量", "执行明细"],
        rows,
        "暂无交易记录",
    )
    table["pagination"] = pagination
    return table


def _build_his_replay_signal_table(db: QuantSimDB, run_id: int, table_query: dict[str, Any] | None = None) -> dict[str, Any]:
    query = table_query or {}
    page_size = _normalize_replay_table_page_size(query.get("page_size"))
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
            include_strategy_profile=False,
        )
    ):
        signal_id = _txt(item.get("id"), str(i))
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
                    _txt(item.get("decision_type"), "自动"),
                    _txt(item.get("signal_status") or item.get("execution_note"), "待处理"),
                ],
                "actions": [{"label": "详情", "icon": "🔎", "tone": "accent", "action": "show-signal-detail"}],
                "analysis": _txt(item.get("reasoning"), "暂无分析数据"),
                "votes": "暂无投票数据",
                "decisionType": _txt(item.get("decision_type"), "自动"),
                "signalStatus": _txt(item.get("signal_status") or item.get("execution_note"), "待处理"),
                "confidence": _txt(item.get("confidence"), "0"),
                "techScore": _txt(item.get("tech_score"), "0"),
                "contextScore": _txt(item.get("context_score"), "0"),
                "checkpointAt": checkpoint_at,
                "code": _txt(item.get("stock_code")),
                "name": _txt(item.get("stock_name")),
            }
        )
    table = _table(["信号ID", "时间", "代码", "动作", "策略", "执行结果"], signal_rows, "暂无信号")
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


def _his_replay_database_busy(exc: BaseException) -> HTTPException:
    return HTTPException(status_code=503, detail="历史回放正在写入数据库，请稍后刷新。")


def _reconcile_stale_his_replay_runs(db: QuantSimDB) -> None:
    from app.quant_sim.replay_runner import _is_pid_running

    for run in db.get_sim_runs(limit=20):
        status = _txt(run.get("status")).lower()
        if status not in {"queued", "running"}:
            continue
        progress_total = int(_float(run.get("progress_total"), 0.0) or 0.0)
        progress_current = int(_float(run.get("progress_current"), 0.0) or 0.0)
        if progress_total <= 0 or progress_current < progress_total:
            continue
        worker_pid = int(_float(run.get("worker_pid"), 0.0) or 0.0)
        if worker_pid > 0 and _is_pid_running(worker_pid):
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
    db = context.quant_db()
    _reconcile_stale_his_replay_runs(db)
    runs = db.get_sim_runs(limit=20)
    payload: dict[str, Any] = {
        "updatedAt": _now(),
        "tasks": _build_his_replay_task_items(db, runs, include_positions=False),
    }
    if runs:
        run_id = int(runs[0].get("id") or 0)
        payload.update(
            {
                "holdings": _table(["代码", "名称", "数量", "成本", "现价", "浮盈亏"], _build_his_replay_holdings_rows(db, run_id), "暂无持仓"),
                "trades": _build_his_replay_trade_table(db, run_id, table_query),
                "signals": _build_his_replay_signal_table(db, run_id, table_query),
                "tradeCostSummary": _trade_cost_summary_metrics(db.get_sim_run_trade_cost_summary_lightweight(run_id)),
            }
        )
    return payload


def _build_checkpoint_selector_item(item: dict[str, Any]) -> dict[str, Any]:
    checkpoint_at = _txt(item.get("checkpoint_at"), "--")
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


def _snapshot_his_replay_capital_pool(context: UIApiContext, table_query: dict[str, Any] | None = None) -> dict[str, Any]:
    db = context.quant_db()
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
    checkpoint_total = db.count_sim_run_checkpoints(run_id, keyword=checkpoint_search)
    pagination = _replay_table_pagination(requested_page, page_size, checkpoint_total)
    checkpoint_rows = db.get_sim_run_checkpoints(
        run_id,
        limit=page_size,
        offset=(pagination["page"] - 1) * page_size,
        keyword=checkpoint_search,
        order="desc",
    )

    selected_checkpoint = None
    checkpoint_at = _txt(query.get("checkpoint_at"))
    if checkpoint_at:
        selected_checkpoint = db.get_sim_run_checkpoint_at(run_id, checkpoint_at)
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
        "selectedCheckpointAt": _txt(selected_checkpoint.get("checkpoint_at")),
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
    db = context.quant_db()
    _reconcile_stale_his_replay_runs(db)
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
    candidate_page_size = _normalize_replay_table_page_size((table_query or {}).get("candidate_page_size") or (table_query or {}).get("pageSize"), default=20)
    candidate_page = _normalize_replay_table_page((table_query or {}).get("candidate_page") or (table_query or {}).get("page"))
    candidate_search = _txt((table_query or {}).get("candidate_search") or (table_query or {}).get("search"))
    candidate_total = context.candidate_pool().count_candidates(status="active", search=candidate_search)
    candidate_pagination = _replay_table_pagination(candidate_page, candidate_page_size, candidate_total)
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
        for i, item in enumerate(
            context.candidate_pool().list_candidates(
                status="active",
                limit=candidate_page_size,
                offset=(candidate_pagination["page"] - 1) * candidate_page_size,
                search=candidate_search,
            )
        )
    ]
    candidate_pool_table = _table(["股票代码", "股票名称", "最新价格"], candidate_rows, "暂无候选股票")
    candidate_pool_table["pagination"] = candidate_pagination

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
                ["时间", "信号ID", "代码", "动作", "类型", "数量", "价格", "成交毛额", "手续费", "印花税", "总费用", "现金影响", "盈亏", "盈亏率", "Slot用量", "执行明细"],
                [],
                "暂无交易记录",
            ),
            "signals": _table(["信号ID", "时间", "代码", "动作", "策略", "执行结果"], [], "暂无信号"),
            "tradeCostSummary": _trade_cost_summary_metrics({}),
            "curve": [],
        }

    rid = int(run["id"])

    signal_table = _build_his_replay_signal_table(db, rid, table_query)
    trade_table = _build_his_replay_trade_table(db, rid, table_query)
    trade_count = db.count_sim_run_trades(rid)

    task_items = _build_his_replay_task_items(db, runs, include_positions=True)

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
    latest_snapshot = db.get_latest_sim_run_snapshot(rid)
    terminal_liquidation = build_terminal_liquidation(
        db,
        run,
        latest_snapshot,
        commission_rate=replay_commission_rate,
        sell_tax_rate=replay_sell_tax_rate,
    )

    return {
        "updatedAt": _now(),
        "config": {
            "mode": _txt(run.get("mode"), "historical_range"),
            "range": f"{_txt(run.get('start_datetime'), '--')} -> {_txt(run.get('end_datetime'), 'now')}",
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
        "trades": trade_table,
        "signals": signal_table,
        "tradeCostSummary": _replay_execution_summary_metrics(
            run,
            latest_snapshot,
            db.get_sim_run_trade_cost_summary(rid),
            scheduler_status,
        )
        + terminal_liquidation_metrics(terminal_liquidation),
        "curve": [
            {"label": _txt(item.get("created_at"), str(i)), "value": float(item.get("total_equity") or 0)}
            for i, item in enumerate(db.get_sim_run_snapshots(rid))
        ],
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
