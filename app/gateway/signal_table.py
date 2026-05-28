from __future__ import annotations

import json
import re
from typing import Any

from app.gateway.artifact_diagnostics import artifact_diagnostics_from_signal_payload
from app.gateway.common import first_non_empty as _first_non_empty
from app.gateway.common import float_value as _float
from app.gateway.common import num as _num
from app.gateway.common import system_time_text as _system_time_text
from app.gateway.common import table as _table
from app.gateway.common import txt as _txt


SIGNAL_SUMMARY_COLUMNS = [
    "信号ID",
    "时间",
    "股票代码",
    "股票名称",
    "动作",
    "BUY分层",
    "仓位倍率",
    "防守原因",
    "执行状态",
    "市场状态",
    "趋势",
    "量比",
    "融合分",
    "置信度",
    "买入阈值",
    "卖出阈值",
]


def _safe_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _metric_text(value: Any, *, digits: int = 4) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return "--"
    parsed = _float(value)
    if parsed is None:
        return _txt(value, "--")
    return _num(parsed, digits, default="--")


def _confidence_text(signal: dict[str, Any], fusion: dict[str, Any]) -> str:
    raw = _float(fusion.get("fusion_confidence"))
    if raw is None:
        raw = _float(signal.get("confidence"))
        if raw is not None and raw > 1:
            raw = raw / 100
    return _metric_text(raw)


def _extract_reason_number(explainability: dict[str, Any], dimension_id: str) -> Any:
    for breakdown_key in ("technical_breakdown", "context_breakdown"):
        breakdown = _safe_dict(explainability.get(breakdown_key))
        for item in breakdown.get("dimensions") or []:
            if not isinstance(item, dict) or _txt(item.get("id")) != dimension_id:
                continue
            reason = _txt(item.get("reason"))
            match = re.search(rf"{re.escape(dimension_id)}\s*[:=]\s*(-?\d+(?:\.\d+)?)", reason)
            if match:
                return match.group(1)
    return None


def _signal_market_snapshot(profile: dict[str, Any], explainability: dict[str, Any]) -> dict[str, Any]:
    for candidate in (
        profile.get("market_snapshot"),
        explainability.get("market_snapshot"),
        profile.get("snapshot"),
    ):
        snapshot = _safe_dict(candidate)
        if snapshot:
            return snapshot
    return {}


def _portfolio_guard_summary(profile: dict[str, Any]) -> tuple[str, str, str]:
    gate = _safe_dict(profile.get("portfolio_execution_guard"))
    if not gate:
        return "--", "--", "--"
    tier = _txt(gate.get("buy_tier_label") or gate.get("buy_tier"), "--")
    score = _metric_text(gate.get("buy_strength_score"))
    multiplier = _metric_text(gate.get("size_multiplier"))
    reasons: list[str] = []
    for source in (
        gate.get("reasons"),
        _safe_dict(gate.get("portfolio_guard")).get("reasons"),
        gate.get("late_rebound_reasons"),
    ):
        if not isinstance(source, list):
            continue
        reasons.extend(_txt(item) for item in source if _txt(item))
    tier_text = tier if score == "--" else f"{tier} · {score}"
    multiplier_text = "--" if multiplier == "--" else f"x{multiplier}"
    return tier_text, multiplier_text, "；".join(reasons) if reasons else "--"


def build_signal_summary_row(item: dict[str, Any], index: int, *, time_key: str, status_key: str) -> dict[str, Any]:
    signal_id = _txt(item.get("id"), str(index))
    profile = _safe_dict(item.get("strategy_profile"))
    explainability = _safe_dict(profile.get("explainability"))
    fusion = _safe_dict(explainability.get("fusion_breakdown"))
    market = _signal_market_snapshot(profile, explainability)
    artifact_diagnostics = artifact_diagnostics_from_signal_payload(item, profile)

    market_state = _txt(
        _first_non_empty(
            market,
            ["market_state", "market_status", "state", "trading_status", "trading_session", "session", "market_phase", "regime"],
        ),
        "--",
    )
    trend = _txt(_first_non_empty(market, ["trend", "trend_state", "trend_regime", "price_trend", "direction"]), "--")
    volume_ratio = _first_non_empty(market, ["volume_ratio", "Volume_ratio", "量比"])
    if volume_ratio is None:
        volume_ratio = _extract_reason_number(explainability, "volume_ratio")
    buy_tier_text, size_multiplier_text, guard_reason_text = _portfolio_guard_summary(profile)
    action = _txt(item.get("action"), "HOLD").upper()
    execution_status = _txt(item.get(status_key) or item.get("status") or item.get("execution_note"), "observed")
    decision_time = _system_time_text(item.get(time_key) or item.get("updated_at") or item.get("created_at"), "--")
    ignored_reason = _txt(item.get("reasoning") or guard_reason_text, "") if execution_status.lower() == "ignored" else ""

    return {
        "id": signal_id,
        "cells": [
            f"#{signal_id}",
            decision_time,
            _txt(item.get("stock_code")),
            _txt(item.get("stock_name")),
            action,
            buy_tier_text,
            size_multiplier_text,
            guard_reason_text,
            execution_status,
            market_state,
            trend,
            _metric_text(volume_ratio),
            _metric_text(fusion.get("fusion_score")),
            _confidence_text(item, fusion),
            _metric_text(fusion.get("buy_threshold_eff") if fusion.get("buy_threshold_eff") is not None else fusion.get("buy_threshold_base")),
            _metric_text(fusion.get("sell_threshold_eff") if fusion.get("sell_threshold_eff") is not None else fusion.get("sell_threshold_base")),
        ],
        "code": _txt(item.get("stock_code")),
        "name": _txt(item.get("stock_name")),
        "decisionProvenance": {
            "signalId": signal_id,
            "decisionTime": decision_time,
            "finalAction": action,
            "executionStatus": execution_status,
            "ignoredReason": ignored_reason,
            "gateResult": {
                "buyTier": buy_tier_text,
                "sizeMultiplier": size_multiplier_text,
                "guardReason": guard_reason_text,
            },
            "artifactDiagnostics": artifact_diagnostics,
        },
    }


def build_signal_summary_table(rows: list[dict[str, Any]], empty_label: str = "暂无信号") -> dict[str, Any]:
    return _table(SIGNAL_SUMMARY_COLUMNS, rows, empty_label)
