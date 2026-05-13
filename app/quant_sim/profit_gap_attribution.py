from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

LARGE_GAP_THRESHOLD = 500.0


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
        item["trade_path"].append(_trade_path_item(trade, action))
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
        item["unrealized_pnl"] += _float(position.get("unrealized_pnl"))
        item["position_market_value"] += _float(position.get("market_value"))
    _attach_signal_evidence(db, int(run_id), by_code)
    _attach_lifecycle_evidence(db, int(run_id), by_code)
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
        hist_pnl = _float(hist.get("total_pnl"))
        drill_pnl = _float(cur.get("total_pnl"))
        pnl_gap = round(hist_pnl - drill_pnl, 4)
        labels = _labels(hist, cur, pnl_gap)
        classification = _classify_v2(hist, cur, labels, pnl_gap)
        output.append(
            {
                "stock_code": code,
                "stock_name": cur.get("stock_name") or hist.get("stock_name") or code,
                "historical_total_pnl": hist_pnl,
                "drill_total_pnl": drill_pnl,
                "pnl_gap": pnl_gap,
                "historical_first_buy_at": hist.get("first_buy_at"),
                "drill_first_buy_at": cur.get("first_buy_at"),
                "historical_first_buy_price": _nullable_float(hist.get("first_buy_price")),
                "drill_first_buy_price": _nullable_float(cur.get("first_buy_price")),
                "historical_buy_amount": _float(hist.get("buy_amount")),
                "drill_buy_amount": _float(cur.get("buy_amount")),
                "attribution_labels": labels,
                "primary_label": classification["primary_label"],
                "sub_reason": classification["sub_reason"],
                "severity": classification["severity"],
                "actionable": classification["actionable"],
                "recommended_action": classification["recommended_action"],
                "primary_reason": _primary_reason(labels),
                "evidence_json": {
                    "buy_tiers": cur.get("buy_tiers") or [],
                    "lifecycle_gate_modes": cur.get("lifecycle_gate_modes") or [],
                    "blocked_reasons": cur.get("blocked_reasons") or [],
                    "cap_reasons": cur.get("cap_reasons") or [],
                    "diagnostic_labels": cur.get("diagnostic_labels") or [],
                    "candidate_sources": cur.get("candidate_sources") or [],
                    "quant_transition_reasons": cur.get("quant_transition_reasons") or [],
                },
                "historical_trade_path_json": hist.get("trade_path") or [],
                "drill_trade_path_json": cur.get("trade_path") or [],
                "entry_timeline_json": _entry_timeline(hist, cur),
                "sizing_cap_chain_json": cur.get("sizing_cap_chain") or [],
                "sell_diagnostics_json": cur.get("sell_diagnostics") or [],
            }
        )
    output.sort(key=lambda row: row["pnl_gap"], reverse=True)
    return output


def _labels(hist: dict[str, Any], drill: dict[str, Any], pnl_gap: float = 0.0) -> list[str]:
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
    if not labels and abs(float(pnl_gap or 0.0)) >= LARGE_GAP_THRESHOLD:
        if hist_has_buy and drill_has_buy and _entry_matches(hist, drill):
            labels.append("same_entry_exit_gap")
        elif _float(hist.get("unrealized_pnl")) or _float(drill.get("unrealized_pnl")):
            labels.append("mark_to_market_gap")
        else:
            labels.append("missing_evidence")
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
        "same_entry_exit_gap": "entry matched but later path diverged",
        "mark_to_market_gap": "difference is mainly from remaining mark-to-market position value",
        "missing_evidence": "available evidence is insufficient for a more precise attribution",
    }
    return mapping.get(labels[0], "no dominant attribution label")


def _classify_v2(hist: dict[str, Any], drill: dict[str, Any], labels: list[str], pnl_gap: float) -> dict[str, Any]:
    primary = _primary_label(labels)
    sub_reason = _sub_reason(primary, hist, drill)
    severity = _severity(pnl_gap)
    actionable = primary not in {"drill_better", "rounding_or_lot_gap"} and sub_reason != "acceptable_exploration_loss"
    if severity == "none":
        actionable = False
    if severity == "low" and primary in {"same_entry_exit_gap", "mark_to_market_gap"}:
        actionable = False
    return {
        "primary_label": primary,
        "sub_reason": sub_reason,
        "severity": severity,
        "actionable": bool(actionable),
        "recommended_action": _recommended_action(primary, sub_reason),
    }


def _primary_label(labels: list[str]) -> str:
    priority = [
        "sell_blocked_or_late",
        "size_too_small",
        "entry_too_late",
        "bad_extra_buy",
        "repeat_probe_loss",
        "same_entry_exit_gap",
        "mark_to_market_gap",
        "missing_evidence",
        "drill_better",
        "unclassified",
    ]
    label_set = set(labels or [])
    if "repeat_probe_loss" in label_set:
        label_set.add("bad_extra_buy")
    for label in priority:
        if label in label_set:
            return "bad_extra_buy" if label == "repeat_probe_loss" else label
    return labels[0] if labels else "unclassified"


def _sub_reason(primary_label: str, hist: dict[str, Any], drill: dict[str, Any]) -> str:
    cap_text = " ".join(str(value).lower() for value in (drill.get("cap_reasons") or []))
    blocked_text = " ".join(str(value).lower() for value in (drill.get("blocked_reasons") or []))
    gate_text = " ".join(str(value).lower() for value in (drill.get("lifecycle_gate_modes") or []))
    tier_text = " ".join(str(value).lower() for value in (drill.get("buy_tiers") or []))
    diagnostic_text = " ".join(str(value).lower() for value in (drill.get("diagnostic_labels") or []))
    source_text = " ".join(str(value).lower() for value in (drill.get("candidate_sources") or []))
    if primary_label == "entry_too_late":
        if not drill.get("first_candidate_event_at"):
            return "candidate_discovered_late"
        if not drill.get("first_quant_state_at") and not drill.get("first_quant_event_at"):
            return "candidate_not_promoted"
        if any(token in gate_text for token in ("cooling", "probe", "trial", "guarded")):
            return "lifecycle_gate_delayed"
        if cap_text or blocked_text:
            return "execution_budget_delayed"
        if "weak" in tier_text or not tier_text:
            return "entry_signal_not_strong_enough"
        return "data_missing_or_stale"
    if primary_label == "size_too_small":
        if "probe" in cap_text or "probe" in gate_text:
            return "recovery_probe_cap"
        if any(token in cap_text for token in ("trial_aggregate", "checkpoint", "daily", "exposure")):
            return "trial_aggregate_cap"
        if "account" in cap_text:
            return "account_tier_cap"
        if any(token in cap_text or token in blocked_text for token in ("slot", "cash", "budget")):
            return "slot_or_cash_cap"
        if any(token in cap_text or token in tier_text for token in ("weak", "normal", "tier")):
            return "weak_or_normal_tier_cap"
        return "weak_or_normal_tier_cap"
    if primary_label == "bad_extra_buy":
        if "repeat_probe_loss" in diagnostic_text or "probe" in diagnostic_text:
            return "probe_repeat_after_loss"
        if "low_price" in source_text or "低价" in source_text:
            return "low_price_source_overreach"
        if any(token in diagnostic_text for token in ("false_strong", "structure_weak", "weak_structure")):
            return "false_strong_structure_weak"
        if any(token in diagnostic_text for token in ("late_rebound", "overheat", "rsi")):
            return "late_rebound_chase"
        return "acceptable_exploration_loss"
    if primary_label == "sell_blocked_or_late":
        sell_text = " ".join(
            str(item.get("blocked_reason") or item.get("reason") or item.get("status") or "").lower()
            for item in (drill.get("sell_diagnostics") or [])
            if isinstance(item, dict)
        )
        combined = f"{blocked_text} {sell_text}"
        if "t+1" in combined or "t1" in combined:
            return "t1_blocked"
        if "sellable" in combined or "quantity" in combined or "可卖" in combined:
            return "no_sellable_quantity"
        if "weak" in combined or "observe" in combined or "观察" in combined:
            return "weak_sell_observe_loss"
        if "hard" in combined or "trailing" in combined or "stop" in combined:
            return "hard_sell_not_executed"
        return "sell_signal_late"
    if primary_label == "same_entry_exit_gap":
        return "same_entry_exit_gap"
    if primary_label == "mark_to_market_gap":
        return "mark_to_market_gap"
    if primary_label == "missing_evidence":
        return "missing_evidence"
    if primary_label == "drill_better":
        return "drill_better"
    return "unclassified"


def _severity(pnl_gap: float) -> str:
    gap = abs(float(pnl_gap or 0.0))
    if gap >= 3000:
        return "high"
    if gap >= 500:
        return "medium"
    if gap >= 100:
        return "low"
    return "none"


def _recommended_action(primary_label: str, sub_reason: str) -> str:
    mapping = {
        "candidate_discovered_late": "Improve historical candidate generation or add earlier eligible sources.",
        "candidate_not_promoted": "Review auto-entry promotion thresholds for supported candidate events.",
        "lifecycle_gate_delayed": "Check lifecycle gate recovery thresholds and confirmed recovery sizing.",
        "execution_budget_delayed": "Review batch budget and execution ordering for delayed BUY signals.",
        "entry_signal_not_strong_enough": "Inspect buy-tier scoring and confirmation inputs for this stock.",
        "data_missing_or_stale": "Backfill missing market or candidate evidence before retuning strategy rules.",
        "recovery_probe_cap": "Allow confirmed recovery probes to escape low probe caps faster.",
        "trial_aggregate_cap": "Review trial aggregate exposure caps and signal priority ordering.",
        "account_tier_cap": "Check account-size cap for high-conviction signals.",
        "slot_or_cash_cap": "Review slot/cash availability at the checkpoint where BUY was delayed.",
        "weak_or_normal_tier_cap": "Check buy-tier cap and whether the signal should upgrade after confirmation.",
        "existing_position_cap": "Review existing position cap before adding more exposure.",
        "false_strong_structure_weak": "Tighten strong-buy confirmation to reject weak trend structures.",
        "late_rebound_chase": "Add late-rebound or overheat penalties before allowing BUY.",
        "probe_repeat_after_loss": "Strengthen probe fatigue cooldown after repeated recovery failures.",
        "low_price_source_overreach": "Limit low-price source auto-entry unless trend confirmation is present.",
        "acceptable_exploration_loss": "Review extra drill-only buy before widening auto-entry.",
        "t1_blocked": "Account for T+1 sellability when evaluating delayed SELL losses.",
        "no_sellable_quantity": "Check lot sellable quantity and position accounting.",
        "weak_sell_observe_loss": "Review weak SELL observation rules when losses grow after warning.",
        "hard_sell_not_executed": "Check hard stop or trailing stop execution path.",
        "sell_signal_late": "Review SELL signal timing and sell execution diagnostics.",
        "same_entry_exit_gap": "Compare exit timing and terminal mark-to-market path for matched entries.",
        "mark_to_market_gap": "Separate open-position mark-to-market effect from realized trade quality.",
        "missing_evidence": "Add missing signal, candidate, or lifecycle evidence for this stock.",
        "drill_better": "No action required; drill outperformed historical replay.",
    }
    return mapping.get(sub_reason, mapping.get(primary_label, "Review evidence before changing strategy parameters."))


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
            "candidate_sources": [],
            "quant_transition_reasons": [],
            "trade_path": [],
            "unrealized_pnl": 0.0,
            "position_market_value": 0.0,
            "sizing_cap_chain": [],
            "sell_diagnostics": [],
            "candidate_events": [],
            "quant_events": [],
            "quant_states": [],
            "first_candidate_event_at": None,
            "first_quant_event_at": None,
            "first_quant_state_at": None,
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
        cap_chain = sizing.get("cap_chain") or sizing.get("cap_chain_json") or sizing.get("caps")
        if isinstance(cap_chain, list):
            item["sizing_cap_chain"].extend(entry for entry in cap_chain if isinstance(entry, dict))
        if _float(diagnostics.get("recent_probe_loss_count")) > 0 or _float(diagnostics.get("probe_attempt_count")) > 1:
            _append_unique(item["diagnostic_labels"], "repeat_probe_loss")
        action = str(signal.get("action") or "").upper()
        status = str(signal.get("status") or "").lower()
        blocked_reason = str(signal.get("blocked_reason") or diagnostics.get("blocked_reason") or "")
        if action == "SELL" and (status == "ignored" or blocked_reason):
            _append_unique(item["diagnostic_labels"], "sell_blocked_or_late")
            item["sell_diagnostics"].append(
                {
                    "checkpoint_at": signal.get("checkpoint_at") or signal.get("created_at"),
                    "status": status,
                    "blocked_reason": blocked_reason,
                    "execution_note": signal.get("execution_note"),
                    "cap_reason": signal.get("cap_reason"),
                }
            )


def _attach_lifecycle_evidence(db: Any, run_id: int, by_code: dict[str, dict[str, Any]]) -> None:
    _attach_candidate_events(db, run_id, by_code)
    _attach_quant_events(db, run_id, by_code)
    _attach_quant_states(db, run_id, by_code)


def _attach_candidate_events(db: Any, run_id: int, by_code: dict[str, dict[str, Any]]) -> None:
    try:
        response = db.list_sim_run_candidate_events(run_id, page_size=100000)
    except AttributeError:
        return
    for event in _items(response):
        code = str(event.get("stock_code") or "").strip()
        if not code:
            continue
        item = _summary_item(by_code, code, event.get("stock_name"))
        event_time = event.get("checkpoint_at_utc") or event.get("checkpoint_at") or event.get("occurred_at")
        item["candidate_events"].append(event)
        _append_unique(item["candidate_sources"], event.get("source_type"))
        if not item.get("first_candidate_event_at") or _sort_key_time(event_time) < _sort_key_time(item.get("first_candidate_event_at")):
            item["first_candidate_event_at"] = event_time


def _attach_quant_events(db: Any, run_id: int, by_code: dict[str, dict[str, Any]]) -> None:
    try:
        response = db.list_sim_run_quant_events(run_id, page_size=100000)
    except AttributeError:
        return
    for event in _items(response):
        code = str(event.get("stock_code") or "").strip()
        if not code:
            continue
        item = _summary_item(by_code, code, event.get("stock_name"))
        event_time = event.get("checkpoint_at_utc") or event.get("checkpoint_at")
        item["quant_events"].append(event)
        _append_unique(item["quant_transition_reasons"], event.get("reason_code"))
        if not item.get("first_quant_event_at") or _sort_key_time(event_time) < _sort_key_time(item.get("first_quant_event_at")):
            item["first_quant_event_at"] = event_time


def _attach_quant_states(db: Any, run_id: int, by_code: dict[str, dict[str, Any]]) -> None:
    try:
        response = db.list_sim_run_quant_states(run_id, page_size=100000)
    except AttributeError:
        return
    for state in _items(response):
        code = str(state.get("stock_code") or "").strip()
        if not code:
            continue
        item = _summary_item(by_code, code, state.get("stock_name"))
        state_time = state.get("checkpoint_at_utc") or state.get("checkpoint_at")
        item["quant_states"].append(state)
        if not item.get("first_quant_state_at") or _sort_key_time(state_time) < _sort_key_time(item.get("first_quant_state_at")):
            item["first_quant_state_at"] = state_time


def _items(response: Any) -> list[dict[str, Any]]:
    if isinstance(response, dict) and isinstance(response.get("items"), list):
        return [item for item in response["items"] if isinstance(item, dict)]
    if isinstance(response, list):
        return [item for item in response if isinstance(item, dict)]
    return []


def _entry_timeline(hist: dict[str, Any], drill: dict[str, Any]) -> dict[str, Any]:
    return {
        "historical_first_buy_at": hist.get("first_buy_at"),
        "drill_first_buy_at": drill.get("first_buy_at"),
        "drill_first_candidate_event_at": drill.get("first_candidate_event_at"),
        "drill_first_quant_event_at": drill.get("first_quant_event_at"),
        "drill_first_quant_state_at": drill.get("first_quant_state_at"),
        "candidate_sources": drill.get("candidate_sources") or [],
        "quant_transition_reasons": drill.get("quant_transition_reasons") or [],
    }


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


def _trade_path_item(trade: dict[str, Any], action: str) -> dict[str, Any]:
    return {
        "id": trade.get("id"),
        "executed_at": trade.get("executed_at") or trade.get("created_at"),
        "action": action,
        "price": _nullable_float(trade.get("price")),
        "quantity": _nullable_float(trade.get("quantity")),
        "amount": _trade_amount(trade),
        "realized_pnl": _float(trade.get("realized_pnl")),
        "execution_note": trade.get("execution_note") or trade.get("detail") or trade.get("notes"),
    }


def _sort_key_time(value: Any) -> str:
    parsed = _parse_dt(value)
    return parsed.isoformat() if parsed is not None else str(value or "")


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
