from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_profit_gap_attributions_from_runs(
    db: Any,
    *,
    historical_run_id: int,
    drill_run_id: int,
) -> list[dict[str, Any]]:
    """Build and persist stock-level attribution rows from two replay-domain runs."""
    rows = build_profit_gap_attributions(
        historical=build_run_stock_summaries(db, int(historical_run_id)),
        drill=build_run_stock_summaries(db, int(drill_run_id)),
    )
    db.replace_profit_gap_attributions(int(historical_run_id), int(drill_run_id), rows)
    return rows


def build_run_stock_summaries(db: Any, run_id: int) -> list[dict[str, Any]]:
    """Summarize run trades, positions, and signal diagnostics at stock level."""
    by_code: dict[str, dict[str, Any]] = {}
    trades = sorted(
        db.get_sim_run_trades(int(run_id)),
        key=lambda item: (
            str(item.get("executed_at") or item.get("created_at") or ""),
            int(item.get("id") or 0),
        ),
    )
    for trade in trades:
        code = str(trade.get("stock_code") or "").strip()
        if not code:
            continue
        item = _summary_item(by_code, code, trade.get("stock_name"))
        action = str(trade.get("action") or "").upper()
        if action == "BUY":
            item["buy_amount"] += _trade_amount(trade)
            if not item.get("first_buy_at"):
                item["first_buy_at"] = trade.get("executed_at") or trade.get("created_at")
                item["first_buy_price"] = _nullable_float(trade.get("price"))
        elif action == "SELL":
            item["sell_count"] += 1
            item["total_pnl"] += _float(trade.get("realized_pnl"))
    for position in db.get_sim_run_positions(int(run_id)):
        code = str(position.get("stock_code") or "").strip()
        if not code:
            continue
        item = _summary_item(by_code, code, position.get("stock_name"))
        item["total_pnl"] += _float(position.get("unrealized_pnl"))
    _attach_signal_evidence(db, int(run_id), by_code)
    return [
        {
            **item,
            "total_pnl": round(float(item.get("total_pnl") or 0.0), 4),
            "buy_amount": round(float(item.get("buy_amount") or 0.0), 4),
        }
        for item in by_code.values()
    ]


def build_profit_gap_attributions(
    *,
    historical: list[dict[str, Any]],
    drill: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build stock-level attribution rows for historical replay vs live quant drill."""
    hist_by_code = {str(row.get("stock_code") or ""): row for row in historical if row.get("stock_code")}
    drill_by_code = {str(row.get("stock_code") or ""): row for row in drill if row.get("stock_code")}
    output: list[dict[str, Any]] = []
    for code in sorted(set(hist_by_code) | set(drill_by_code)):
        hist = hist_by_code.get(code) or {}
        cur = drill_by_code.get(code) or {}
        labels = _labels(hist, cur)
        hist_pnl = _float(hist.get("total_pnl"))
        drill_pnl = _float(cur.get("total_pnl"))
        output.append(
            {
                "stock_code": code,
                "stock_name": cur.get("stock_name") or hist.get("stock_name") or code,
                "historical_total_pnl": hist_pnl,
                "drill_total_pnl": drill_pnl,
                "pnl_gap": round(hist_pnl - drill_pnl, 4),
                "historical_first_buy_at": hist.get("first_buy_at"),
                "drill_first_buy_at": cur.get("first_buy_at"),
                "historical_first_buy_price": _nullable_float(hist.get("first_buy_price")),
                "drill_first_buy_price": _nullable_float(cur.get("first_buy_price")),
                "historical_buy_amount": _float(hist.get("buy_amount")),
                "drill_buy_amount": _float(cur.get("buy_amount")),
                "attribution_labels": labels,
                "primary_reason": _primary_reason(labels),
                "evidence_json": {
                    "buy_tiers": cur.get("buy_tiers") or [],
                    "lifecycle_gate_modes": cur.get("lifecycle_gate_modes") or [],
                    "blocked_reasons": cur.get("blocked_reasons") or [],
                    "cap_reasons": cur.get("cap_reasons") or [],
                    "diagnostic_labels": cur.get("diagnostic_labels") or [],
                },
            }
        )
    output.sort(key=lambda row: row["pnl_gap"], reverse=True)
    return output


def _labels(hist: dict[str, Any], drill: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    hist_has_buy = bool(hist.get("first_buy_at"))
    drill_has_buy = bool(drill.get("first_buy_at"))
    hist_pnl = _float(hist.get("total_pnl"))
    drill_pnl = _float(drill.get("total_pnl"))
    drill_diagnostics = set(drill.get("diagnostic_labels") or [])
    if hist_has_buy and drill_has_buy:
        if _entry_matches(hist, drill) and _float(drill.get("buy_amount")) < _float(hist.get("buy_amount")) * 0.6:
            labels.append("size_too_small")
        if _entry_late(hist, drill) and hist_pnl > 0:
            labels.append("entry_too_late")
        if drill_pnl < hist_pnl and "repeat_probe_loss" in drill_diagnostics:
            labels.append("repeat_probe_loss")
    if drill_has_buy and not hist_has_buy and drill_pnl < 0:
        labels.append("bad_extra_buy")
    if "sell_blocked_or_late" in drill_diagnostics:
        labels.append("sell_blocked_or_late")
    if drill_pnl > hist_pnl:
        labels.append("drill_better")
    return labels or ["unclassified"]


def _entry_matches(hist: dict[str, Any], drill: dict[str, Any]) -> bool:
    hist_at = _parse_dt(hist.get("first_buy_at"))
    drill_at = _parse_dt(drill.get("first_buy_at"))
    if hist_at is None or drill_at is None:
        return False
    hist_price = _float(hist.get("first_buy_price"))
    drill_price = _float(drill.get("first_buy_price"))
    ref_price = max(hist_price, 0.01)
    return abs((drill_at - hist_at).total_seconds()) <= 60 * 60 * 24 and abs(hist_price - drill_price) / ref_price <= 0.02


def _entry_late(hist: dict[str, Any], drill: dict[str, Any]) -> bool:
    hist_at = _parse_dt(hist.get("first_buy_at"))
    drill_at = _parse_dt(drill.get("first_buy_at"))
    if hist_at is None or drill_at is None:
        return False
    days_late = (drill_at - hist_at).total_seconds() >= 60 * 60 * 24 * 3
    price_higher = _float(drill.get("first_buy_price")) > _float(hist.get("first_buy_price")) * 1.08
    return days_late or price_higher


def _primary_reason(labels: list[str]) -> str:
    mapping = {
        "size_too_small": "entry matched but drill sizing was materially lower",
        "entry_too_late": "drill entered materially later than historical replay",
        "bad_extra_buy": "drill bought a losing stock that historical replay did not buy",
        "repeat_probe_loss": "recovery probe repeated after prior failure",
        "sell_blocked_or_late": "sell signal was blocked or delayed",
        "drill_better": "drill outperformed historical replay on this stock",
    }
    return mapping.get(labels[0], "no dominant attribution label")


def _summary_item(by_code: dict[str, dict[str, Any]], code: str, stock_name: Any = None) -> dict[str, Any]:
    item = by_code.setdefault(
        code,
        {
            "stock_code": code,
            "stock_name": str(stock_name or code),
            "total_pnl": 0.0,
            "first_buy_at": None,
            "first_buy_price": None,
            "buy_amount": 0.0,
            "sell_count": 0,
            "buy_tiers": [],
            "lifecycle_gate_modes": [],
            "blocked_reasons": [],
            "cap_reasons": [],
            "diagnostic_labels": [],
        },
    )
    if stock_name and (not item.get("stock_name") or item.get("stock_name") == code):
        item["stock_name"] = str(stock_name)
    return item


def _attach_signal_evidence(db: Any, run_id: int, by_code: dict[str, dict[str, Any]]) -> None:
    try:
        signals = db.get_sim_run_signals(run_id, include_strategy_profile=True)
    except TypeError:
        signals = db.get_sim_run_signals(run_id)
    for signal in signals:
        code = str(signal.get("stock_code") or "").strip()
        if not code:
            continue
        item = _summary_item(by_code, code, signal.get("stock_name"))
        profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
        guard = profile.get("portfolio_execution_guard") if isinstance(profile.get("portfolio_execution_guard"), dict) else {}
        gate = profile.get("lifecycle_gate") if isinstance(profile.get("lifecycle_gate"), dict) else {}
        sizing = profile.get("execution_sizing_plan") if isinstance(profile.get("execution_sizing_plan"), dict) else {}
        diagnostics = signal.get("execution_diagnostics") if isinstance(signal.get("execution_diagnostics"), dict) else {}
        _append_unique(item["buy_tiers"], guard.get("buy_tier"))
        _append_unique(item["lifecycle_gate_modes"], gate.get("mode") or sizing.get("lifecycle_gate_mode"))
        _append_unique(item["blocked_reasons"], signal.get("blocked_reason") or diagnostics.get("blocked_reason"))
        _append_unique(item["cap_reasons"], signal.get("cap_reason") or sizing.get("primary_cap_reason"))
        if _float(diagnostics.get("recent_probe_loss_count")) > 0 or _float(diagnostics.get("probe_attempt_count")) > 1:
            _append_unique(item["diagnostic_labels"], "repeat_probe_loss")
        action = str(signal.get("action") or "").upper()
        status = str(signal.get("status") or "").lower()
        blocked_reason = str(signal.get("blocked_reason") or diagnostics.get("blocked_reason") or "")
        if action == "SELL" and (status == "ignored" or blocked_reason):
            _append_unique(item["diagnostic_labels"], "sell_blocked_or_late")


def _append_unique(values: list[Any], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in values:
        values.append(text)


def _trade_amount(trade: dict[str, Any]) -> float:
    for key in ("net_amount", "gross_amount", "amount"):
        value = _float(trade.get(key))
        if value:
            return abs(value)
    return abs(_float(trade.get("price")) * _float(trade.get("quantity")))


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _nullable_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return _float(value)


def _float(value: Any) -> float:
    try:
        return round(float(value or 0.0), 4)
    except (TypeError, ValueError):
        return 0.0
