from __future__ import annotations

from app.gateway.deps import *
from app.gateway.trades import _run_metadata, _trade_metadata, _trade_net_amount


def _safe_int(value: Any, default: int = 0) -> int:
    parsed = _float(value, None)
    if parsed is None:
        return default
    return int(parsed)


def _sort_trade_chronologically(item: dict[str, Any]) -> tuple[str, int]:
    return (_txt(item.get("executed_at") or item.get("created_at")), _safe_int(item.get("id")))


def _capital_slot_allocations(metadata: dict[str, Any], fallback_slot: int, fallback_cash: float) -> list[dict[str, Any]]:
    raw_allocations = metadata.get("slot_allocations")
    allocations: list[dict[str, Any]] = []
    if isinstance(raw_allocations, list):
        for raw in raw_allocations:
            if not isinstance(raw, dict):
                continue
            slot_index = _safe_int(raw.get("slot_index"))
            if slot_index <= 0:
                continue
            allocated_cash = _float(raw.get("allocated_cash"), None)
            if allocated_cash is None or allocated_cash <= 0:
                allocated_cash = fallback_cash / max(len(raw_allocations), 1)
            allocations.append(
                {
                    "slot_index": slot_index,
                    "allocated_cash": round(float(allocated_cash), 4),
                    "slot_units": _float(raw.get("slot_units"), None),
                }
            )
    if not allocations and fallback_cash > 0:
        allocations.append({"slot_index": max(fallback_slot, 1), "allocated_cash": round(fallback_cash, 4), "slot_units": 1.0})
    return allocations


def _consume_open_lot(open_lots: dict[str, dict[str, Any]], lot_id: str, quantity: int) -> int:
    if not lot_id or lot_id not in open_lots or quantity <= 0:
        return quantity
    remaining_quantity = max(_safe_int(open_lots[lot_id].get("remaining_quantity")), 0)
    consumed = min(remaining_quantity, quantity)
    open_lots[lot_id]["remaining_quantity"] = remaining_quantity - consumed
    if open_lots[lot_id]["remaining_quantity"] <= 0:
        open_lots.pop(lot_id, None)
    return quantity - consumed


def _consume_open_lot_fifo(open_lots: dict[str, dict[str, Any]], stock_code: str, quantity: int) -> None:
    remaining = quantity
    for lot_id, lot in list(open_lots.items()):
        if remaining <= 0:
            break
        if _txt(lot.get("stock_code")) != stock_code:
            continue
        remaining = _consume_open_lot(open_lots, lot_id, remaining)


def _reconstruct_open_lots_from_trades(
    db: QuantSimDB,
    run_id: int,
    slot_count_hint: int,
    *,
    executed_to: str | None = None,
) -> dict[str, dict[str, Any]]:
    open_lots: dict[str, dict[str, Any]] = {}
    trades = sorted(db.get_sim_run_trades(run_id, executed_to=executed_to), key=_sort_trade_chronologically)
    for trade in trades:
        action = _txt(trade.get("action")).upper()
        metadata = _trade_metadata(trade)
        stock_code = _txt(trade.get("stock_code"))
        if action == "BUY":
            quantity = max(_safe_int(trade.get("quantity")), 0)
            if quantity <= 0:
                continue
            lot = metadata.get("lot") if isinstance(metadata.get("lot"), dict) else {}
            lot_id = _txt(lot.get("lot_id")) or f"{stock_code}-{_txt(trade.get('id')) or _txt(trade.get('executed_at'))}"
            if lot_id in open_lots:
                lot_id = f"{lot_id}-{_txt(trade.get('id'))}"
            remaining_quantity = max(_safe_int(lot.get("remaining_quantity"), quantity), 0)
            lot_count = _safe_int(lot.get("lot_count"))
            if lot_count <= 0:
                lot_count = max(1, (quantity + 99) // 100)
            fallback_slot = min(max(len(open_lots) + 1, 1), max(slot_count_hint, 1))
            net_amount = _trade_net_amount(trade)
            open_lots[lot_id] = {
                "lot_id": lot_id,
                "stock_code": stock_code,
                "stock_name": _txt(trade.get("stock_name"), stock_code),
                "entry_price": _float(lot.get("entry_price"), _float(trade.get("price"), 0.0)) or 0.0,
                "quantity": quantity,
                "remaining_quantity": remaining_quantity or quantity,
                "lot_count": lot_count,
                "unlock_date": _txt(lot.get("unlock_date")),
                "is_add": bool(metadata.get("is_add")),
                "allocations": _capital_slot_allocations(metadata, fallback_slot, net_amount),
            }
            continue
        if action != "SELL":
            continue
        consumed_lots = metadata.get("consumed_lots")
        if isinstance(consumed_lots, list) and consumed_lots:
            fallback_remaining = 0
            for consumed_lot in consumed_lots:
                if not isinstance(consumed_lot, dict):
                    continue
                consumed_quantity = max(_safe_int(consumed_lot.get("quantity")), 0)
                lot_id = _txt(consumed_lot.get("lot_id"))
                fallback_remaining += _consume_open_lot(open_lots, lot_id, consumed_quantity)
            if fallback_remaining > 0:
                _consume_open_lot_fifo(open_lots, stock_code, fallback_remaining)
        else:
            _consume_open_lot_fifo(open_lots, stock_code, max(_safe_int(trade.get("quantity")), 0))
    return open_lots


def _position_fallback_open_lots(
    positions: list[dict[str, Any]],
    existing_codes: set[str],
    slot_count: int,
) -> dict[str, dict[str, Any]]:
    fallback_lots: dict[str, dict[str, Any]] = {}
    slot_count = max(slot_count, 1)
    for index, position in enumerate(positions):
        stock_code = _txt(position.get("stock_code"))
        if not stock_code or stock_code in existing_codes:
            continue
        quantity = max(_safe_int(position.get("quantity")), 0)
        if quantity <= 0:
            continue
        slot_index = (index % slot_count) + 1
        avg_price = _float(position.get("avg_price"), 0.0) or 0.0
        allocated_cash = round(avg_price * quantity, 4)
        fallback_lots[f"{stock_code}-position"] = {
            "lot_id": f"{stock_code}-position",
            "stock_code": stock_code,
            "stock_name": _txt(position.get("stock_name"), stock_code),
            "entry_price": avg_price,
            "quantity": quantity,
            "remaining_quantity": quantity,
            "lot_count": max(1, (quantity + 99) // 100),
            "unlock_date": "",
            "is_add": False,
            "allocations": [{"slot_index": slot_index, "allocated_cash": allocated_cash, "slot_units": 1.0}],
        }
    return fallback_lots


def _build_slot_lot_groups(
    open_lots: dict[str, dict[str, Any]],
    positions_by_code: dict[str, dict[str, Any]],
) -> dict[tuple[int, str], dict[str, Any]]:
    groups: dict[tuple[int, str], dict[str, Any]] = {}
    for lot in open_lots.values():
        quantity = max(_safe_int(lot.get("remaining_quantity")), 0)
        if quantity <= 0:
            continue
        allocations = lot.get("allocations") if isinstance(lot.get("allocations"), list) else []
        total_allocated = sum(_float(item.get("allocated_cash"), 0.0) or 0.0 for item in allocations if isinstance(item, dict))
        if total_allocated <= 0:
            total_allocated = max((_float(lot.get("entry_price"), 0.0) or 0.0) * quantity, 1.0)
        for allocation in allocations or [{"slot_index": 1, "allocated_cash": total_allocated}]:
            if not isinstance(allocation, dict):
                continue
            slot_index = max(_safe_int(allocation.get("slot_index"), 1), 1)
            allocated_cash = _float(allocation.get("allocated_cash"), 0.0) or 0.0
            ratio = allocated_cash / total_allocated if total_allocated > 0 else 1.0
            group_quantity = max(1, int(round(quantity * ratio))) if quantity > 0 else 0
            group_lot_count = max(1, int(round(max(_safe_int(lot.get("lot_count")), 1) * ratio)))
            stock_code = _txt(lot.get("stock_code"))
            position = positions_by_code.get(stock_code, {})
            position_quantity = max(_safe_int(position.get("quantity")), 0)
            latest_price = _float(position.get("latest_price"), None)
            if latest_price is None or latest_price <= 0:
                latest_price = _float(lot.get("entry_price"), 0.0) or 0.0
            locked_total = max(_safe_int(position.get("locked_quantity")), 0)
            sellable_total = max(_safe_int(position.get("sellable_quantity")), 0)
            if position_quantity > 0:
                locked_quantity = int(round(group_quantity * locked_total / position_quantity))
                sellable_quantity = int(round(group_quantity * sellable_total / position_quantity))
            else:
                locked_quantity = 0
                sellable_quantity = group_quantity
            key = (slot_index, stock_code)
            group = groups.setdefault(
                key,
                {
                    "slot_index": slot_index,
                    "stock_code": stock_code,
                    "stock_name": _txt(position.get("stock_name") or lot.get("stock_name"), stock_code),
                    "lot_ids": [],
                    "lot_count": 0,
                    "quantity": 0,
                    "sellable_quantity": 0,
                    "locked_quantity": 0,
                    "allocated_cash": 0.0,
                    "market_value": 0.0,
                    "entry_prices": [],
                    "is_add": False,
                },
            )
            group["lot_ids"].append(_txt(lot.get("lot_id")))
            group["lot_count"] += group_lot_count
            group["quantity"] += group_quantity
            group["sellable_quantity"] += sellable_quantity
            group["locked_quantity"] += locked_quantity
            group["allocated_cash"] = round(float(group["allocated_cash"]) + allocated_cash, 4)
            group["market_value"] = round(float(group["market_value"]) + latest_price * group_quantity, 4)
            group["entry_prices"].append(_float(lot.get("entry_price"), 0.0) or 0.0)
            group["is_add"] = bool(group["is_add"] or lot.get("is_add"))
    return groups


def _capital_lot_card(group: dict[str, Any]) -> dict[str, Any]:
    prices = [float(price) for price in group.get("entry_prices", []) if float(price or 0) > 0]
    cost_band = "--"
    if prices:
        low = min(prices)
        high = max(prices)
        cost_band = _num(low) if abs(high - low) < 0.0001 else f"{_num(low)}-{_num(high)}"
    locked_quantity = max(_safe_int(group.get("locked_quantity")), 0)
    sellable_quantity = max(_safe_int(group.get("sellable_quantity")), 0)
    if locked_quantity > 0 and sellable_quantity > 0:
        status = "mixed"
    elif locked_quantity > 0:
        status = "locked"
    else:
        status = "available"
    lot_ids = [_txt(item) for item in group.get("lot_ids", []) if _txt(item)]
    return {
        "id": f"{_txt(group.get('stock_code'))}-{_txt(group.get('slot_index'))}",
        "stockCode": _txt(group.get("stock_code")),
        "stockName": _txt(group.get("stock_name")),
        "lotCount": max(_safe_int(group.get("lot_count")), 0),
        "quantity": max(_safe_int(group.get("quantity")), 0),
        "sellableQuantity": sellable_quantity,
        "lockedQuantity": locked_quantity,
        "allocatedCash": _num(group.get("allocated_cash")),
        "marketValue": _num(group.get("market_value")),
        "costBand": cost_band,
        "status": status,
        "isAdd": bool(group.get("is_add")),
        "isStack": max(_safe_int(group.get("lot_count")), 0) > 1 or len(lot_ids) > 1,
        "lotIds": lot_ids[:8],
        "hiddenLotCount": max(len(lot_ids) - 8, 0),
    }


def build_his_replay_capital_pool(
    db: QuantSimDB,
    run: dict[str, Any],
    latest_snapshot: dict[str, Any] | None,
    *,
    checkpoint: dict[str, Any] | None = None,
    include_position_fallback: bool = True,
) -> dict[str, Any]:
    run_id = _safe_int(run.get("id"))
    metadata = _run_metadata(run)
    is_checkpoint_view = bool(checkpoint)
    slot_summary = metadata.get("final_slot_summary") if not is_checkpoint_view and isinstance(metadata.get("final_slot_summary"), dict) else {}
    initial_cash = _float(run.get("initial_cash"), 0.0) or 0.0
    source_snapshot = checkpoint or latest_snapshot or {}
    total_equity = _float(source_snapshot.get("total_equity"), None)
    if total_equity is None:
        total_equity = _float(run.get("final_equity"), initial_cash) or initial_cash
    cash_value = _float(source_snapshot.get("available_cash"), None)
    if cash_value is None:
        cash_value = _float(slot_summary.get("available_cash"), 0.0) or 0.0
    market_value = _float(source_snapshot.get("market_value"), 0.0) or 0.0
    checkpoint_metadata = checkpoint.get("metadata") if isinstance((checkpoint or {}).get("metadata"), dict) else {}
    realized_pnl = _float(source_snapshot.get("realized_pnl"), _float(checkpoint_metadata.get("realized_pnl"), 0.0)) or 0.0
    unrealized_pnl = _float(source_snapshot.get("unrealized_pnl"), _float(checkpoint_metadata.get("unrealized_pnl"), 0.0)) or 0.0
    plan = calculate_slot_plan(float(total_equity or 0.0), normalize_capital_slot_config(metadata))
    slot_count = _safe_int(slot_summary.get("slot_count"), _safe_int(plan.get("slot_count")))
    slot_budget = _float(slot_summary.get("slot_budget"), _float(plan.get("slot_budget"), 0.0)) or 0.0
    positions = [] if is_checkpoint_view else (db.get_sim_run_positions(run_id) if run_id else [])
    positions_by_code = {_txt(position.get("stock_code")): position for position in positions if _txt(position.get("stock_code"))}
    open_lots = _reconstruct_open_lots_from_trades(
        db,
        run_id,
        slot_count,
        executed_to=_txt(checkpoint.get("checkpoint_at")) if checkpoint else None,
    ) if run_id else {}
    if include_position_fallback:
        existing_codes = {_txt(lot.get("stock_code")) for lot in open_lots.values()}
        open_lots.update(_position_fallback_open_lots(positions, existing_codes, slot_count))
    groups = _build_slot_lot_groups(open_lots, positions_by_code)
    max_group_slot = max((slot_index for slot_index, _ in groups.keys()), default=0)
    slot_count = max(slot_count, max_group_slot)
    if slot_count <= 0 and float(total_equity or 0.0) > 0:
        slot_count = _safe_int(plan.get("slot_count"))
        slot_budget = _float(plan.get("slot_budget"), 0.0) or 0.0

    occupied_by_slot: dict[int, float] = {}
    lots_by_slot: dict[int, list[dict[str, Any]]] = {}
    for (slot_index, _stock_code), group in groups.items():
        lot_card = _capital_lot_card(group)
        lots_by_slot.setdefault(slot_index, []).append(lot_card)
        occupied_by_slot[slot_index] = round(occupied_by_slot.get(slot_index, 0.0) + (_float(group.get("allocated_cash"), 0.0) or 0.0), 4)

    total_settling_cash = _float(slot_summary.get("settling_cash"), _float(checkpoint_metadata.get("settling_cash"), 0.0)) or 0.0
    slots: list[dict[str, Any]] = []
    for index in range(1, max(slot_count, 0) + 1):
        lots = sorted(lots_by_slot.get(index, []), key=lambda item: (-_safe_int(item.get("lotCount")), _txt(item.get("stockCode"))))
        occupied_cash = occupied_by_slot.get(index, 0.0)
        slot_available_cash = max(slot_budget - occupied_cash, 0.0) if slot_budget > 0 else 0.0
        usage_pct = round(min(max((occupied_cash / slot_budget * 100) if slot_budget > 0 else 0.0, 0.0), 100.0), 1)
        status = "occupied" if occupied_cash > 0.01 or lots else "free"
        slots.append(
            {
                "id": f"slot-{index}",
                "index": index,
                "title": f"Slot {index:02d}",
                "status": status,
                "budgetCash": _num(slot_budget),
                "availableCash": _num(slot_available_cash),
                "occupiedCash": _num(occupied_cash),
                "settlingCash": _num(0.0),
                "usagePct": usage_pct,
                "lots": lots,
                "hiddenLotGroups": max(len(lots) - 3, 0),
            }
        )

    occupied_cash_total = round(sum(occupied_by_slot.values()), 4)
    available_slot_cash = round(sum(_float(slot.get("availableCash"), 0.0) or 0.0 for slot in slots), 4)
    selected_slot = next((slot for slot in slots if slot["status"] == "occupied"), slots[0] if slots else None)
    progress_total = max(_safe_int(run.get("progress_total")), 0)
    progress_current = max(_safe_int(run.get("progress_current")), 0)
    progress = int(round(progress_current / progress_total * 100)) if progress_total > 0 else (100 if _txt(run.get("status")) in {"completed", "failed", "cancelled"} else 0)
    return {
        "task": {
            "runId": _txt(run_id),
            "status": _txt(run.get("status"), "completed"),
            "progress": max(0, min(progress, 100)),
            "checkpoint": _txt((checkpoint or {}).get("checkpoint_at") or run.get("latest_checkpoint_at"), "--"),
            "timeframe": _txt(run.get("timeframe"), "30m"),
            "range": f"{_txt(run.get('start_datetime'), '--')} -> {_txt(run.get('end_datetime'), 'now')}",
            "strategy": _txt(run.get("selected_strategy_profile_name") or run.get("selected_strategy_profile_id") or run.get("selected_strategy_mode"), "--"),
        },
        "pool": {
            "initialCash": _num(initial_cash),
            "cashValue": _num(cash_value),
            "marketValue": _num(market_value),
            "totalEquity": _num(total_equity),
            "realizedPnl": _num(realized_pnl),
            "unrealizedPnl": _num(unrealized_pnl),
            "slotCount": slot_count,
            "slotBudget": _num(slot_budget),
            "availableCash": _num(available_slot_cash),
            "occupiedCash": _num(occupied_cash_total),
            "settlingCash": _num(total_settling_cash),
            "poolReady": bool(plan.get("pool_ready") or slot_count > 0),
        },
        "slots": slots,
        "selectedSlotIndex": selected_slot.get("index") if selected_slot else None,
        "taskMetrics": [
            _metric("任务", f"#{_txt(run_id)}"),
            _metric("状态", _txt(run.get("status"), "--")),
            _metric("检查点", _txt((checkpoint or {}).get("checkpoint_at") or run.get("latest_checkpoint_at"), "--")),
            _metric("成交", _txt(run.get("trade_count"), "0")),
        ],
        "notes": [
            "资金池按选中检查点之前的成交流水重建；未选择检查点时展示回放最终快照。",
            "Slot 表示单次买入资金上限；Lot 表示具体买入批次，卖出仍按lot/T+1规则执行。",
        ],
    }
