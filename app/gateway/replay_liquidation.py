from __future__ import annotations

import json
from typing import Any

from app.gateway.deps import _float, _num, _pct, _txt
from app.quant_sim.db import QuantSimDB


def build_terminal_liquidation(
    db: QuantSimDB,
    run: dict[str, Any],
    latest_snapshot: dict[str, Any] | None,
    *,
    commission_rate: float,
    sell_tax_rate: float,
) -> dict[str, Any]:
    run_id = int(_float(run.get("id"), 0.0) or 0)
    initial_cash = _float(run.get("initial_cash"), 0.0) or 0.0
    final_cash = _float((latest_snapshot or {}).get("available_cash"), 0.0) or 0.0
    final_equity = _float((latest_snapshot or {}).get("total_equity"), None)
    if final_equity is None:
        final_equity = _float(run.get("final_equity"), initial_cash) or initial_cash
    checkpoint_at = _txt((latest_snapshot or {}).get("created_at") or run.get("latest_checkpoint_at") or run.get("end_datetime"), "--")

    items: list[dict[str, Any]] = []
    totals = {
        "position_count": 0,
        "quantity": 0,
        "gross_amount": 0.0,
        "commission_fee": 0.0,
        "sell_tax_fee": 0.0,
        "fee_total": 0.0,
        "net_amount": 0.0,
        "realized_pnl": 0.0,
    }
    if not run_id:
        return {"items": items, "summary": {**totals, "liquidation_cash": final_cash, "liquidation_total_pnl": final_cash - initial_cash}}

    for position in db.get_sim_run_positions(run_id):
        quantity = int(_float(position.get("quantity"), 0.0) or 0.0)
        if quantity <= 0:
            continue
        latest_price = _float(position.get("latest_price"), None)
        if latest_price is None or latest_price <= 0:
            market_value = _float(position.get("market_value"), 0.0) or 0.0
            latest_price = market_value / quantity if quantity > 0 else 0.0
        if latest_price <= 0:
            continue
        avg_price = _float(position.get("avg_price"), 0.0) or 0.0
        cost_basis = round(avg_price * quantity, 4)
        gross_amount = round(latest_price * quantity, 4)
        commission_fee = round(gross_amount * max(float(commission_rate or 0.0), 0.0), 4)
        sell_tax_fee = round(gross_amount * max(float(sell_tax_rate or 0.0), 0.0), 4)
        fee_total = round(commission_fee + sell_tax_fee, 4)
        net_amount = round(gross_amount - fee_total, 4)
        realized_pnl = round(net_amount - cost_basis, 4)
        metadata = {
            "side": "SELL",
            "terminal_liquidation": True,
            "cost_basis": cost_basis,
            "gross_amount": gross_amount,
            "commission_fee": commission_fee,
            "sell_tax_fee": sell_tax_fee,
            "fee_total": fee_total,
            "net_amount": net_amount,
        }
        items.append(
            {
                "id": f"terminal-{_txt(position.get('stock_code'))}",
                "signal_id": None,
                "stock_code": _txt(position.get("stock_code")),
                "stock_name": _txt(position.get("stock_name")),
                "action": "SELL",
                "price": round(latest_price, 4),
                "quantity": quantity,
                "amount": net_amount,
                "gross_amount": gross_amount,
                "commission_fee": commission_fee,
                "sell_tax_fee": sell_tax_fee,
                "fee_total": fee_total,
                "net_amount": net_amount,
                "realized_pnl": realized_pnl,
                "trade_metadata_json": json.dumps(metadata, ensure_ascii=False),
                "executed_at": checkpoint_at,
                "created_at": checkpoint_at,
            }
        )
        totals["position_count"] += 1
        totals["quantity"] += quantity
        totals["gross_amount"] = round(totals["gross_amount"] + gross_amount, 4)
        totals["commission_fee"] = round(totals["commission_fee"] + commission_fee, 4)
        totals["sell_tax_fee"] = round(totals["sell_tax_fee"] + sell_tax_fee, 4)
        totals["fee_total"] = round(totals["fee_total"] + fee_total, 4)
        totals["net_amount"] = round(totals["net_amount"] + net_amount, 4)
        totals["realized_pnl"] = round(totals["realized_pnl"] + realized_pnl, 4)

    liquidation_cash = round(final_cash + totals["net_amount"], 4)
    liquidation_total_pnl = round(liquidation_cash - initial_cash, 4)
    liquidation_return_pct = (liquidation_total_pnl / initial_cash * 100) if initial_cash > 0 else 0.0
    return {
        "items": items,
        "summary": {
            **totals,
            "final_equity_before_liquidation": round(float(final_equity or 0.0), 4),
            "final_cash_before_liquidation": round(final_cash, 4),
            "liquidation_cash": liquidation_cash,
            "liquidation_total_pnl": liquidation_total_pnl,
            "liquidation_return_pct": liquidation_return_pct,
        },
    }


def terminal_liquidation_metrics(liquidation: dict[str, Any] | None) -> list[dict[str, str]]:
    summary = liquidation.get("summary") if isinstance(liquidation, dict) else {}
    if not isinstance(summary, dict) or int(_float(summary.get("position_count"), 0.0) or 0.0) <= 0:
        return []
    return [
        {"label": "期末持仓数", "value": _txt(summary.get("position_count"), "0")},
        {"label": "期末清算毛额", "value": _num(summary.get("gross_amount"))},
        {"label": "期末清算费用", "value": _num(summary.get("fee_total"))},
        {"label": "期末清算盈亏", "value": _num(summary.get("realized_pnl"))},
        {"label": "清算后现金", "value": _num(summary.get("liquidation_cash"))},
        {"label": "清算后总盈亏", "value": _num(summary.get("liquidation_total_pnl"))},
        {"label": "清算后收益率", "value": _pct(summary.get("liquidation_return_pct"))},
    ]
