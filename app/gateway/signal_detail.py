from __future__ import annotations

from app.gateway.deps import *
from app.gateway.artifact_diagnostics import build_signal_artifact_diagnostics
from app.gateway.context import UIApiContext
from app.gateway.signal_explanation import _build_explanation_payload, _build_structured_vote_rows, _build_vote_overview, _is_structured_explainability, _score_to_signal
from app.gateway.signal_indicators import (
    _build_runtime_context,
    _extract_technical_indicators,
    _normalize_profile_label,
    _profile_summary_text,
    _profile_text,
    _safe_json_load,
    _to_vote_row,
)
from app.gateway.signal_market import _build_signal_ai_monitor_payload, _enrich_signal_strategy_profile_with_replay_snapshot
from app.gateway.signal_parameters import _build_parameter_details
from app.quant_sim.decision_provenance import build_decision_provenance
from app.quant_sim.evidence_models import DecisionProvenanceInput


def _with_live_position_sizing_preview(
    context: UIApiContext,
    signal: dict[str, Any],
    *,
    source: str,
    strategy_profile: dict[str, Any],
) -> dict[str, Any]:
    if source != "live":
        return strategy_profile
    if str(signal.get("action") or "").upper() != "BUY":
        return strategy_profile
    existing = strategy_profile.get("position_sizing")
    if isinstance(existing, dict) and existing:
        return strategy_profile
    try:
        preview_signal = dict(signal)
        preview_signal["strategy_profile"] = strategy_profile
        sizing_preview = context.portfolio().preview_signal_sizing(preview_signal, settle_slots=False)
    except Exception:
        return strategy_profile
    if not isinstance(sizing_preview, dict) or not sizing_preview:
        return strategy_profile
    return {**strategy_profile, "position_sizing": sizing_preview}


def _build_signal_detail_payload(
    context: UIApiContext,
    signal: dict[str, Any],
    *,
    source: str,
    replay_run: dict[str, Any] | None = None,
    fetch_realtime_snapshot: bool = False,
) -> dict[str, Any]:
    strategy_profile = _safe_json_load(signal.get("strategy_profile"))
    strategy_profile = _enrich_signal_strategy_profile_with_replay_snapshot(
        context=context,
        signal=signal,
        source=source,
        replay_run=replay_run,
        strategy_profile=strategy_profile,
    )
    strategy_profile = _with_live_position_sizing_preview(
        context=context,
        signal=signal,
        source=source,
        strategy_profile=strategy_profile,
    )
    artifact_diagnostics = build_signal_artifact_diagnostics(
        context,
        signal=signal,
        source=source,
        strategy_profile=strategy_profile,
    )
    selected_strategy_profile = _safe_json_load(strategy_profile.get("selected_strategy_profile"))
    explainability = _safe_json_load(strategy_profile.get("explainability"))
    technical_breakdown = _safe_json_load(explainability.get("technical_breakdown"))
    context_breakdown = _safe_json_load(explainability.get("context_breakdown"))
    fusion_breakdown = _safe_json_load(explainability.get("fusion_breakdown"))
    is_structured = _is_structured_explainability(explainability)
    if not is_structured:
        raise HTTPException(
            status_code=422,
            detail=(
                "Signal detail requires structured explainability schema; "
                f"signal_id={_txt(signal.get('id'), '--')}"
            ),
        )
    dual_track = _safe_json_load(explainability.get("dual_track"))
    tech_votes_raw = _build_structured_vote_rows(technical_breakdown, track="technical")
    context_votes_raw = _build_structured_vote_rows(context_breakdown, track="context")
    tech_votes = [_to_vote_row(item) for item in tech_votes_raw]
    context_votes = [_to_vote_row(item, default_signal="CONTEXT") for item in context_votes_raw]

    analysis_text = _txt(
        strategy_profile.get("analysis")
        or strategy_profile.get("analysis_summary")
        or strategy_profile.get("decision_reason")
        or dual_track.get("final_reason")
        or signal.get("reasoning"),
        "暂无分析数据",
    )
    reasoning_text = _txt(signal.get("reasoning"), analysis_text)

    scheduler_cfg = context.quant_db().get_scheduler_config()
    configured_profile_id = _txt(scheduler_cfg.get("strategy_profile_id"), "--")
    configured_profile_name = "--"
    if configured_profile_id and configured_profile_id != "--":
        configured_profile = context.quant_db().get_strategy_profile(configured_profile_id) or {}
        configured_profile_name = _txt(configured_profile.get("name"), configured_profile_id)

    applied_profile_id = _txt(selected_strategy_profile.get("id"), "")
    applied_profile_name = _txt(selected_strategy_profile.get("name"), "")
    applied_profile_version = _txt(selected_strategy_profile.get("version"), "")
    if not applied_profile_id:
        applied_profile_id = configured_profile_id
    if not applied_profile_name:
        applied_profile_name = configured_profile_name
    ai_profile_switched = bool(
        configured_profile_id
        and configured_profile_id != "--"
        and applied_profile_id
        and applied_profile_id != "--"
        and applied_profile_id != configured_profile_id
    )
    ai_dynamic_strategy = _txt(scheduler_cfg.get("ai_dynamic_strategy"), "off")
    ai_dynamic_strength = _txt(scheduler_cfg.get("ai_dynamic_strength"), "--")
    ai_dynamic_lookback = _txt(scheduler_cfg.get("ai_dynamic_lookback"), "--")
    configured_profile_label = _normalize_profile_label(configured_profile_id, configured_profile_name)
    applied_profile_label = _normalize_profile_label(applied_profile_id, applied_profile_name)
    applied_profile_version_text = (
        f"版本 {applied_profile_version}"
        if applied_profile_version and applied_profile_version != "--"
        else ""
    )

    tech_track = _safe_json_load(technical_breakdown.get("track"))
    context_track = _safe_json_load(context_breakdown.get("track"))
    tech_score_value = _txt(
        fusion_breakdown.get("tech_score"),
        _txt(tech_track.get("score"), _txt(signal.get("tech_score"), "0")),
    )
    context_score_value = _txt(
        fusion_breakdown.get("context_score"),
        _txt(context_track.get("score"), _txt(signal.get("context_score"), "0")),
    )
    confidence_value = _txt(fusion_breakdown.get("fusion_confidence"), _txt(signal.get("confidence"), "0"))
    tech_signal_value = _score_to_signal(_float(tech_score_value, 0.0) or 0.0)
    context_signal_value = _score_to_signal(_float(context_score_value, 0.0) or 0.0)
    final_action_value = _txt(fusion_breakdown.get("final_action") or dual_track.get("final_action") or signal.get("action"), "HOLD").upper()
    final_reason_value = (
        f"core_rule={_txt(fusion_breakdown.get('core_rule_action'), '--')}; "
        f"weighted_threshold={_txt(fusion_breakdown.get('weighted_threshold_action'), '--')}; "
        f"weighted_gate={_txt(fusion_breakdown.get('weighted_action_raw'), '--')}; "
        f"final={final_action_value}; tech_score={tech_score_value}; context_score={context_score_value}; "
        f"fusion_score={_txt(fusion_breakdown.get('fusion_score'), '--')}"
    )
    position_add_gate = strategy_profile.get("position_add_gate") if isinstance(strategy_profile.get("position_add_gate"), dict) else {}
    execution_intent_value = _txt(
        position_add_gate.get("intent") if position_add_gate else strategy_profile.get("execution_intent"),
        "",
    )

    decision = {
        "id": _txt(signal.get("id")),
        "source": source,
        "stockCode": _txt(signal.get("stock_code")),
        "stockName": _txt(signal.get("stock_name")),
        "action": final_action_value,
        "status": _txt(signal.get("status") or signal.get("execution_note"), "observed"),
        "decisionType": _txt(signal.get("decision_type") or fusion_breakdown.get("mode"), "auto"),
        "executionIntent": execution_intent_value,
        "confidence": confidence_value,
        "positionSizePct": _txt(signal.get("position_size_pct"), "0"),
        "techScore": tech_score_value,
        "contextScore": context_score_value,
        "checkpointAt": _system_time_text(signal.get("checkpoint_at") or signal.get("updated_at") or signal.get("created_at"), "--"),
        "createdAt": _system_time_text(signal.get("created_at"), "--"),
        "analysisTimeframe": _profile_text(strategy_profile.get("analysis_timeframe"), "--"),
        "strategyMode": _profile_text(strategy_profile.get("strategy_mode"), "--"),
        "marketRegime": _profile_summary_text(strategy_profile.get("market_regime"), "--"),
        "fundamentalQuality": _profile_summary_text(strategy_profile.get("fundamental_quality"), "--"),
        "riskStyle": _profile_summary_text(strategy_profile.get("risk_style"), "--"),
        "autoInferredRiskStyle": _profile_summary_text(strategy_profile.get("auto_inferred_risk_style"), "--"),
        "techSignal": tech_signal_value,
        "contextSignal": context_signal_value,
        "resonanceType": _txt(dual_track.get("resonance_type"), "--"),
        "ruleHit": _txt(dual_track.get("rule_hit"), _txt(fusion_breakdown.get("mode"), "--")),
        "finalAction": final_action_value,
        "finalReason": final_reason_value,
        "positionRatio": _txt(dual_track.get("position_ratio"), _txt(signal.get("position_size_pct"), "0")),
        "configuredProfile": configured_profile_label,
        "appliedProfile": (
            f"{applied_profile_label} {applied_profile_version_text}".strip()
            if applied_profile_label and applied_profile_label != "--"
            else "--"
        ),
        "aiDynamicStrategy": ai_dynamic_strategy,
        "aiDynamicStrength": ai_dynamic_strength,
        "aiDynamicLookback": ai_dynamic_lookback,
        "aiProfileSwitched": "是" if ai_profile_switched else "否",
        "artifactRef": _txt(artifact_diagnostics.get("artifact_ref")),
        "artifactStatus": _txt(artifact_diagnostics.get("source_status")),
        "artifactReasonCode": _txt(artifact_diagnostics.get("reason_code")),
    }

    technical_indicators = _extract_technical_indicators(
        tech_votes=tech_votes_raw,
        context_votes=context_votes_raw,
        reasoning=reasoning_text,
        analysis_text=analysis_text,
        strategy_profile=strategy_profile,
        technical_breakdown=technical_breakdown,
        context_breakdown=context_breakdown,
    )
    effective_thresholds = _safe_json_load(strategy_profile.get("effective_thresholds"))
    dual_track_profile = _safe_json_load(strategy_profile.get("dual_track"))
    if _txt(fusion_breakdown.get("buy_threshold_eff")):
        effective_thresholds["buy_threshold"] = fusion_breakdown.get("buy_threshold_eff")
    if _txt(fusion_breakdown.get("sell_threshold_eff")):
        effective_thresholds["sell_threshold"] = fusion_breakdown.get("sell_threshold_eff")
    for key in (
        "min_fusion_confidence",
        "min_tech_score_for_buy",
        "min_context_score_for_buy",
        "min_tech_confidence_for_buy",
        "min_context_confidence_for_buy",
    ):
        if _txt(dual_track_profile.get(key)):
            effective_thresholds[key] = dual_track_profile.get(key)
    for key in (
        "buy_threshold_base",
        "buy_threshold_eff",
        "sell_threshold_base",
        "sell_threshold_eff",
        "sell_precedence_gate",
        "threshold_mode",
        "volatility_regime_score",
        "tech_weight_raw",
        "tech_weight_norm",
        "context_weight_raw",
        "context_weight_norm",
        "fusion_score",
        "fusion_confidence",
        "fusion_confidence_base",
        "divergence",
        "divergence_penalty",
        "sign_conflict",
        "mode",
        "veto_source_mode",
    ):
        if _txt(fusion_breakdown.get(key)):
            effective_thresholds[key] = fusion_breakdown.get(key)
    gate_fail_reasons = fusion_breakdown.get("weighted_gate_fail_reasons")
    if isinstance(gate_fail_reasons, list):
        effective_thresholds["weighted_gate_fail_reasons"] = " | ".join(_txt(item, "--") for item in gate_fail_reasons) if gate_fail_reasons else "无"

    runtime_context = _build_runtime_context(
        context,
        source=source,
        strategy_profile=strategy_profile,
        replay_run=replay_run,
    )
    explanation = _build_explanation_payload(
        decision=decision,
        analysis_text=analysis_text,
        reasoning_text=reasoning_text,
        tech_votes_raw=tech_votes_raw,
        context_votes_raw=context_votes_raw,
        effective_thresholds=effective_thresholds,
        explainability=explainability,
    )
    vote_overview = _build_vote_overview(
        tech_votes_raw=tech_votes_raw,
        context_votes_raw=context_votes_raw,
        explainability=explainability,
    )
    parameter_details = _build_parameter_details(
        decision=decision,
        runtime_context=runtime_context,
        strategy_profile=strategy_profile,
        technical_indicators=technical_indicators,
        effective_thresholds=effective_thresholds,
        tech_votes_raw=tech_votes_raw,
        context_votes_raw=context_votes_raw,
        explainability=explainability,
    )

    ai_monitor = _build_signal_ai_monitor_payload(
        context=context,
        signal=signal,
        strategy_profile=strategy_profile,
        checkpoint_at=decision.get("checkpointAt"),
        fetch_realtime_snapshot=fetch_realtime_snapshot,
    )
    decision_provenance = build_decision_provenance(
        DecisionProvenanceInput(
            decision=decision,
            signal=signal,
            strategy_profile=strategy_profile,
            source=source,
            technical_indicators=technical_indicators,
            replay_run=replay_run,
        )
    )

    return {
        "updatedAt": _now(),
        "analysis": analysis_text,
        "reasoning": reasoning_text,
        "runtimeContext": runtime_context,
        "explanation": explanation,
        "voteOverview": vote_overview,
        "parameterDetails": parameter_details,
        "decision": decision,
        "decisionProvenance": decision_provenance,
        "techVotes": tech_votes,
        "contextVotes": context_votes,
        "technicalIndicators": technical_indicators,
        "effectiveThresholds": [{"name": _txt(k), "value": _txt(v)} for k, v in effective_thresholds.items() if _txt(k)],
        "aiMonitor": ai_monitor,
        "artifactDiagnostics": artifact_diagnostics,
        "strategyProfile": strategy_profile,
    }


def _find_signal_detail(
    context: UIApiContext,
    signal_id: str,
    *,
    source: str = "auto",
    fetch_realtime_snapshot: bool = False,
) -> dict[str, Any]:
    db = context.quant_db()
    replay_db = context.replay_db()
    normalized_source = _txt(source, "auto").lower()
    sid_int = _int(signal_id)
    if sid_int is None:
        raise HTTPException(status_code=400, detail=f"Invalid signal id: {signal_id}")

    if normalized_source in {"auto", "live"}:
        live_signal = db.get_signal(sid_int)
        if live_signal:
            return _build_signal_detail_payload(
                context,
                live_signal,
                source="live",
                fetch_realtime_snapshot=fetch_realtime_snapshot,
            )

    if normalized_source in {"auto", "replay"}:
        replay_signal = replay_db.get_sim_run_signal(sid_int)
        if replay_signal:
            run_id = _int(replay_signal.get("run_id"))
            replay_run = replay_db.get_sim_run(run_id) if run_id is not None else None
            return _build_signal_detail_payload(
                context,
                replay_signal,
                source="replay",
                replay_run=replay_run,
                fetch_realtime_snapshot=fetch_realtime_snapshot,
            )

    raise HTTPException(status_code=404, detail=f"Signal not found: {signal_id}")
