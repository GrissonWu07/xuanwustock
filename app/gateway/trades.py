from __future__ import annotations

from app.gateway.deps import *
from app.gateway.context import UIApiContext
from app.gateway.table_query import _normalize_replay_table_page, _normalize_replay_table_page_size, _replay_actions_for_filter, _replay_table_pagination

def _trade_gross_amount(item: dict[str, Any]) -> float:
    gross = _float(item.get("gross_amount"), None)
    if gross is not None and gross > 0:
        return gross
    return round((_float(item.get("price"), 0.0) or 0.0) * (_float(item.get("quantity"), 0.0) or 0.0), 4)


def _trade_fee_total(item: dict[str, Any]) -> float:
    fee_total = _float(item.get("fee_total"), None)
    if fee_total is not None and fee_total > 0:
        return fee_total
    return round((_float(item.get("commission_fee"), 0.0) or 0.0) + (_float(item.get("sell_tax_fee"), 0.0) or 0.0), 4)


def _trade_net_amount(item: dict[str, Any]) -> float:
    net_amount = _float(item.get("net_amount"), None)
    if net_amount is not None and net_amount > 0:
        return net_amount
    amount = _float(item.get("amount"), None)
    if amount is not None and amount > 0:
        return amount
    gross = _trade_gross_amount(item)
    fee_total = _trade_fee_total(item)
    return round(gross - fee_total if _txt(item.get("action")).upper() == "SELL" else gross + fee_total, 4)


def _trade_commission_fee(item: dict[str, Any]) -> float:
    return round(_float(item.get("commission_fee"), 0.0) or 0.0, 4)


def _trade_sell_tax_fee(item: dict[str, Any]) -> float:
    return round(_float(item.get("sell_tax_fee"), 0.0) or 0.0, 4)


def _trade_metadata(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("trade_metadata") or item.get("trade_metadata_json")
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _trade_kind(item: dict[str, Any]) -> str:
    action = _txt(item.get("action")).upper()
    metadata = _trade_metadata(item)
    if action == "BUY":
        return "加仓" if metadata.get("is_add") else "建仓"
    if action == "SELL":
        if metadata.get("terminal_liquidation"):
            return "期末清算"
        return "卖出"
    return "--"


def _trade_cost_basis(item: dict[str, Any], metadata: dict[str, Any]) -> float:
    metadata_cost_basis = _float(metadata.get("cost_basis"), 0.0) or 0.0
    if metadata_cost_basis > 0:
        return round(metadata_cost_basis, 4)
    consumed_lots = metadata.get("consumed_lots")
    cost_basis = 0.0
    if isinstance(consumed_lots, list):
        for lot in consumed_lots:
            if not isinstance(lot, dict):
                continue
            quantity = _float(lot.get("quantity"), 0.0) or 0.0
            entry_price = _float(lot.get("entry_price"), 0.0) or 0.0
            cost_basis += quantity * entry_price
    if cost_basis > 0:
        return round(cost_basis, 4)
    released_slots = metadata.get("released_slot_allocations")
    if isinstance(released_slots, list):
        occupied_release = sum(_float(item.get("occupied_release"), 0.0) or 0.0 for item in released_slots if isinstance(item, dict))
        if occupied_release > 0:
            return round(occupied_release, 4)
    net_amount = _trade_net_amount(item)
    realized_pnl = _float(item.get("realized_pnl"), 0.0) or 0.0
    if net_amount > 0:
        return round(net_amount - realized_pnl, 4)
    return 0.0


def _trade_realized_pnl_pct(item: dict[str, Any]) -> str:
    if _txt(item.get("action")).upper() != "SELL":
        return "--"
    metadata = _trade_metadata(item)
    cost_basis = _trade_cost_basis(item, metadata)
    if cost_basis <= 0:
        return "--"
    realized_pnl = _float(item.get("realized_pnl"), 0.0) or 0.0
    return _pct(realized_pnl / cost_basis * 100)


def _trade_slot_units(item: dict[str, Any]) -> str:
    metadata = _trade_metadata(item)
    action = _txt(item.get("action")).upper()
    position_sizing = metadata.get("position_sizing") if isinstance(metadata.get("position_sizing"), dict) else {}
    sizing = position_sizing.get("sizing") if isinstance(position_sizing.get("sizing"), dict) else {}
    slot_units = _float(sizing.get("slot_units"), None) if isinstance(sizing, dict) else None
    if slot_units is not None and slot_units > 0:
        return f"{_num(slot_units, 2)} slot"
    if action == "BUY":
        allocations = metadata.get("slot_allocations")
        if isinstance(allocations, list) and allocations:
            return f"{len(allocations)} slot"
    if action == "SELL":
        releases = metadata.get("released_slot_allocations")
        if isinstance(releases, list) and releases:
            return f"释放 {len(releases)} slot"
    return "--"


def _trade_execution_detail(item: dict[str, Any]) -> str:
    action = _txt(item.get("action")).upper()
    quantity = int(_float(item.get("quantity"), 0.0) or 0.0)
    metadata = _trade_metadata(item)
    if action == "BUY":
        lot = metadata.get("lot") if isinstance(metadata.get("lot"), dict) else {}
        lot_count = int(_float(lot.get("lot_count") if isinstance(lot, dict) else None, 0.0) or 0.0)
        if lot_count <= 0:
            lot_count = max(1, (quantity + 99) // 100) if quantity > 0 else 0
        slot_allocations = metadata.get("slot_allocations")
        slot_parts: list[str] = []
        if isinstance(slot_allocations, list):
            for allocation in slot_allocations[:3]:
                if not isinstance(allocation, dict):
                    continue
                slot_index = _txt(allocation.get("slot_index"), "?")
                allocated_cash = _num(allocation.get("allocated_cash"))
                slot_parts.append(f"slot#{slot_index} {allocated_cash}")
            if len(slot_allocations) > 3:
                slot_parts.append(f"+{len(slot_allocations) - 3} slot")
        parts = [_trade_kind(item)]
        if lot_count > 0:
            parts.append(f"{lot_count} lot/{quantity}股")
        if isinstance(lot, dict):
            lot_id = _txt(lot.get("lot_id"))
            unlock_date = _txt(lot.get("unlock_date"))
            if lot_id:
                parts.append(f"lot {lot_id}")
            if unlock_date:
                parts.append(f"T+1 {unlock_date}")
        if slot_parts:
            parts.append(", ".join(slot_parts))
        return " · ".join(parts)
    if action == "SELL":
        if metadata.get("terminal_liquidation"):
            return (
                f"期末模拟清仓 · {quantity}股 · 毛额 {_num(_trade_gross_amount(item))} · "
                f"费用 {_num(_trade_fee_total(item))} · 到账 {_num(_trade_net_amount(item))}"
            )
        consumed_lots = metadata.get("consumed_lots")
        consumed_quantity = 0
        if isinstance(consumed_lots, list):
            for lot in consumed_lots:
                if isinstance(lot, dict):
                    consumed_quantity += int(_float(lot.get("quantity"), 0.0) or 0.0)
        if consumed_quantity <= 0:
            consumed_quantity = quantity
        consumed_count = max(1, (consumed_quantity + 99) // 100) if consumed_quantity > 0 else 0
        released_slots = metadata.get("released_slot_allocations")
        release_parts: list[str] = []
        if isinstance(released_slots, list):
            for release in released_slots[:3]:
                if not isinstance(release, dict):
                    continue
                slot_index = _txt(release.get("slot_index"), "?")
                released_cash = release.get("released_cash")
                if released_cash is None and len(released_slots) == 1:
                    released_cash = _trade_net_amount(item)
                release_parts.append(f"slot#{slot_index} {_num(released_cash)}")
            if len(released_slots) > 3:
                release_parts.append(f"+{len(released_slots) - 3} slot")
        parts = []
        if consumed_count > 0:
            parts.append(f"消耗 {consumed_count} lot/{consumed_quantity}股")
        if isinstance(consumed_lots, list):
            lot_ids = [_txt(lot.get("lot_id")) for lot in consumed_lots if isinstance(lot, dict) and _txt(lot.get("lot_id"))]
            if lot_ids:
                parts.append(f"lot {', '.join(lot_ids[:3])}{'...' if len(lot_ids) > 3 else ''}")
            unlock_dates = sorted(
                {
                    _txt(lot.get("unlock_date"))
                    for lot in consumed_lots
                    if isinstance(lot, dict) and _txt(lot.get("unlock_date"))
                }
            )
            if unlock_dates:
                parts.append(f"T+1已解锁 {unlock_dates[-1]}")
        if release_parts:
            parts.append(f"释放 {', '.join(release_parts)}")
        return " · ".join(parts) if parts else "--"
    return "--"


def _trade_cost_summary_metrics(summary: dict[str, Any] | None) -> list[dict[str, Any]]:
    item = summary or {}
    metrics = [
        _metric("交易笔数", _txt(item.get("trade_count"), "0")),
        _metric("买入笔数", _txt(item.get("buy_count"), "0")),
        _metric("卖出笔数", _txt(item.get("sell_count"), "0")),
        _metric("买入毛额", _num(item.get("buy_gross_amount"))),
        _metric("卖出毛额", _num(item.get("sell_gross_amount"))),
        _metric("买入总成本", _num(item.get("buy_net_amount"))),
        _metric("卖出到账", _num(item.get("sell_net_amount"))),
        _metric("总费用", _num(item.get("fee_total"))),
        _metric("手续费", _num(item.get("commission_fee"))),
        _metric("印花税", _num(item.get("sell_tax_fee"))),
        _metric("实现盈亏", _num(item.get("realized_pnl"))),
    ]
    if "add_count" in item:
        metrics.insert(2, _metric("加仓次数", _txt(item.get("add_count"), "0")))
    if "buy_lot_count" in item:
        metrics.extend(
            [
                _metric("买入lot", _txt(item.get("buy_lot_count"), "0")),
                _metric("卖出lot", _txt(item.get("sold_lot_count"), "0")),
                _metric("剩余lot", _txt(max(int(_float(item.get("buy_lot_count"), 0.0) or 0.0) - int(_float(item.get("sold_lot_count"), 0.0) or 0.0), 0))),
                _metric("占用slot", _txt(item.get("slot_allocation_count"), "0")),
                _metric("释放slot", _txt(item.get("slot_release_count"), "0")),
                _metric("最大占用slot", _txt(item.get("max_occupied_slot_count"), "0")),
                _metric("平均占用slot", _num(item.get("avg_occupied_slot_count"), 2)),
            ]
        )
    return metrics


def _run_metadata(item: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    metadata_json = item.get("metadata_json")
    if isinstance(metadata_json, str):
        try:
            parsed = json.loads(metadata_json)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _replay_execution_summary_metrics(
    run: dict[str, Any],
    latest_snapshot: dict[str, Any] | None,
    cost_summary: dict[str, Any],
    scheduler_status: dict[str, Any],
) -> list[dict[str, Any]]:
    metadata = _run_metadata(run)
    initial_cash = _float(run.get("initial_cash"), 0.0) or 0.0
    final_equity = _float((latest_snapshot or {}).get("total_equity"), None)
    if final_equity is None:
        final_equity = _float(run.get("final_equity"), initial_cash) or initial_cash
    final_cash = _float((latest_snapshot or {}).get("available_cash"), None)
    final_market_value = _float((latest_snapshot or {}).get("market_value"), None)
    floating_pnl = _float((latest_snapshot or {}).get("unrealized_pnl"), None)
    total_pnl = round(float(final_equity) - initial_cash, 4)
    overview = [
        _metric("初始资金", _num(initial_cash)),
        _metric("最终权益", _num(final_equity)),
        _metric("最终现金", _num(final_cash, default="--")),
        _metric("持仓市值", _num(final_market_value, default="--")),
        _metric("浮动盈亏", _num(floating_pnl, default="--")),
        _metric("总盈亏", _num(total_pnl)),
        _metric("总收益率", _pct(run.get("total_return_pct"))),
        _metric("胜率", _pct(run.get("win_rate"))),
    ]
    metrics = overview + _trade_cost_summary_metrics(cost_summary)

    capital_config = normalize_capital_slot_config(
        {
            "capital_slot_enabled": metadata.get("capital_slot_enabled", scheduler_status.get("capital_slot_enabled", True)),
            "capital_pool_min_cash": metadata.get("capital_pool_min_cash", scheduler_status.get("capital_pool_min_cash")),
            "capital_pool_max_cash": metadata.get("capital_pool_max_cash", scheduler_status.get("capital_pool_max_cash")),
            "capital_slot_min_cash": metadata.get("capital_slot_min_cash", scheduler_status.get("capital_slot_min_cash")),
            "capital_max_slots": metadata.get("capital_max_slots", scheduler_status.get("capital_max_slots")),
            "capital_min_buy_slot_fraction": metadata.get("capital_min_buy_slot_fraction", scheduler_status.get("capital_min_buy_slot_fraction")),
            "capital_full_buy_edge": metadata.get("capital_full_buy_edge", scheduler_status.get("capital_full_buy_edge")),
            "capital_confidence_weight": metadata.get("capital_confidence_weight", scheduler_status.get("capital_confidence_weight")),
            "capital_high_price_threshold": metadata.get("capital_high_price_threshold", scheduler_status.get("capital_high_price_threshold")),
            "capital_high_price_max_slot_units": metadata.get("capital_high_price_max_slot_units", scheduler_status.get("capital_high_price_max_slot_units")),
            "capital_sell_cash_reuse_policy": metadata.get("capital_sell_cash_reuse_policy", scheduler_status.get("capital_sell_cash_reuse_policy")),
        }
    )
    slot_plan = calculate_slot_plan(initial_cash, capital_config)
    final_slot_summary = metadata.get("final_slot_summary") if isinstance(metadata.get("final_slot_summary"), dict) else {}
    metrics.extend(
        [
            _metric("Slot数量", _txt(final_slot_summary.get("slot_count"), _txt(slot_plan.get("slot_count"), "0"))),
            _metric("单Slot预算", _num(final_slot_summary.get("slot_budget"), default=_num(slot_plan.get("slot_budget")))),
            _metric("最大Slot", _txt(capital_config.get("capital_max_slots"), "0")),
            _metric("高价双Slot线", _num(capital_config.get("capital_high_price_threshold"))),
            _metric("最终空闲", _num(final_slot_summary.get("available_cash"), default="--")),
            _metric("最终占用", _num(final_slot_summary.get("occupied_cash"), default=_num(cost_summary.get("final_occupied_slot_cash"), default="--"))),
            _metric("最终待结算", _num(final_slot_summary.get("settling_cash"), default="--")),
        ]
    )
    return metrics
