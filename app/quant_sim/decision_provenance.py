"""User-facing provenance payloads for quant decisions."""

from __future__ import annotations

from typing import Any

from app.quant_sim.evidence_models import DecisionProvenanceInput


def build_decision_provenance(request: DecisionProvenanceInput) -> dict[str, Any]:
    """Build an explainable provenance payload for a signal detail response."""

    selected_profile = _dict(request.strategy_profile.get("selected_strategy_profile"))
    context_payload = _stock_analysis_context(request)
    return {
        "decisionTime": request.decision.get("checkpointAt") or "",
        "source": request.source,
        "stockCode": request.decision.get("stockCode") or request.signal.get("stock_code") or "",
        "marketSnapshot": _market_snapshot(request.strategy_profile, request.technical_indicators),
        "strategyProfile": {
            "id": str(selected_profile.get("id") or request.decision.get("strategyProfileId") or "").strip(),
            "name": str(selected_profile.get("name") or request.decision.get("appliedProfile") or "").strip(),
            "version": str(selected_profile.get("version") or "").strip(),
        },
        "stockAnalysisContext": context_payload,
        "signalBreakdown": _signal_breakdown(request.strategy_profile),
        "gateResult": _gate_result(request.strategy_profile),
        "finalAction": request.decision.get("finalAction") or request.decision.get("action") or request.signal.get("action") or "",
    }


def _market_snapshot(strategy_profile: dict[str, Any], indicators: list[dict[str, Any]]) -> dict[str, Any]:
    snapshot = _dict(strategy_profile.get("market_snapshot"))
    price = _first_present(snapshot, ("current_price", "price", "latest_price", "close"))
    if price in (None, ""):
        price = _indicator_value(indicators, "当前价")
    status = str(snapshot.get("status") or ("ready" if price not in (None, "") else "unavailable")).strip()
    snapshot_at = str(snapshot.get("snapshot_at") or snapshot.get("as_of") or "").strip()
    as_of = snapshot_at
    if price not in (None, ""):
        as_of = f"current_price={price}"
    return {
        "status": status or "unavailable",
        "asOf": as_of,
        "snapshotAt": snapshot_at,
        "timeframe": str(strategy_profile.get("analysis_timeframe") or "").strip(),
    }


def _stock_analysis_context(request: DecisionProvenanceInput) -> dict[str, Any]:
    context = _dict(request.strategy_profile.get("stock_analysis_context"))
    if context:
        used = bool(context.get("used"))
        omitted = str(context.get("omitted_reason") or context.get("reason") or "").strip()
        return {
            "status": "used" if used else "omitted",
            "omittedReason": "" if used else omitted,
        }
    if str(request.source or "").lower() == "replay":
        return {"status": "omitted", "omittedReason": "historical_replay_asof_safety"}
    return {"status": "unavailable", "omittedReason": "no_context_payload"}


def _signal_breakdown(strategy_profile: dict[str, Any]) -> dict[str, Any]:
    explainability = _dict(strategy_profile.get("explainability"))
    fusion = _dict(explainability.get("fusion_breakdown"))
    technical = _dict(explainability.get("technical_breakdown"))
    context = _dict(explainability.get("context_breakdown"))
    return {
        "mode": fusion.get("mode") or "",
        "techScore": fusion.get("tech_score") or _dict(technical.get("track")).get("score"),
        "contextScore": fusion.get("context_score") or _dict(context.get("track")).get("score"),
        "fusionScore": fusion.get("fusion_score"),
        "fusionConfidence": fusion.get("fusion_confidence"),
    }


def _gate_result(strategy_profile: dict[str, Any]) -> dict[str, Any]:
    explainability = _dict(strategy_profile.get("explainability"))
    fusion = _dict(explainability.get("fusion_breakdown"))
    reasons = fusion.get("weighted_gate_fail_reasons")
    if not isinstance(reasons, list):
        reasons = []
    return {
        "coreRuleAction": fusion.get("core_rule_action") or "",
        "weightedAction": fusion.get("weighted_threshold_action") or "",
        "weightedGateAction": fusion.get("weighted_action_raw") or "",
        "failReasons": [str(item) for item in reasons if str(item).strip()],
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_present(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if mapping.get(key) not in (None, ""):
            return mapping.get(key)
    return None


def _indicator_value(indicators: list[dict[str, Any]], name: str) -> Any:
    for item in indicators:
        if isinstance(item, dict) and item.get("name") == name:
            return item.get("value")
    return None
