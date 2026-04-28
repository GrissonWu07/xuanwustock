from __future__ import annotations

from app.gateway.deps import *
from app.gateway.signal_indicators import _safe_json_load, _to_vote_row

def _vote_line(item: dict[str, Any]) -> str:
    factor = _txt(item.get("factor") or item.get("component") or item.get("name") or item.get("title"), "因子")
    signal = _txt(item.get("signal") or item.get("vote") or item.get("decision"), "--")
    score = _txt(item.get("score") or item.get("confidence"), "--")
    reason = _txt(item.get("reason") or item.get("note") or item.get("detail"), "--")
    return f"{factor}: {signal} (score={score}) · {reason}"


def _vote_sort_key(item: dict[str, Any]) -> float:
    return abs(_float(item.get("score"), 0.0) or 0.0)


def _humanize_signal(signal: Any) -> str:
    normalized = _txt(signal, "--").upper()
    mapping = {
        "BUY": "看多（买入）",
        "SELL": "看空（卖出）",
        "HOLD": "中性（持有）",
        "CONTEXT": "环境信号",
    }
    return mapping.get(normalized, _txt(signal, "--"))


def _track_direction_label(signal: Any) -> str:
    normalized = _txt(signal, "--").upper()
    mapping = {
        "BUY": "偏多",
        "SELL": "偏空",
        "HOLD": "中性",
        "CONTEXT": "环境信号",
    }
    return mapping.get(normalized, _txt(signal, "--"))


def _format_signed(value: Any, digits: int = 4) -> str:
    parsed = _float(value)
    if parsed is None:
        return "--"
    return f"{parsed:+.{digits}f}"


def _format_plain(value: Any, digits: int = 4) -> str:
    parsed = _float(value)
    if parsed is None:
        return "--"
    return f"{parsed:.{digits}f}"


def _group_reasonability_line(label: str, groups: list[dict[str, Any]]) -> str:
    ranked = [
        {
            "id": _txt(item.get("id"), "--"),
            "contribution": _float(item.get("track_contribution"), 0.0) or 0.0,
        }
        for item in groups
        if isinstance(item, dict)
    ]
    if not ranked:
        return f"{label}暂无组贡献数据。"
    positive = sorted([item for item in ranked if item["contribution"] > 0], key=lambda item: item["contribution"], reverse=True)
    negative = sorted([item for item in ranked if item["contribution"] < 0], key=lambda item: item["contribution"])
    parts: list[str] = []
    if positive:
        leader = positive[0]
        parts.append(f"主要支撑来自 {leader['id']}（{_format_signed(leader['contribution'])}）")
    if negative:
        drag = negative[0]
        if not positive or drag["id"] != positive[0]["id"]:
            parts.append(f"主要拖累来自 {drag['id']}（{_format_signed(drag['contribution'])}）")
    if not parts:
        neutral = ranked[0]
        return f"{label}整体接近中性，最显著的组是 {neutral['id']}（{_format_signed(neutral['contribution'])}）。"
    return f"{label}" + "，".join(parts) + "。"


def _build_audit_summary_lines(
    *,
    decision: dict[str, Any],
    fusion_breakdown: dict[str, Any],
    technical_breakdown: dict[str, Any],
    context_breakdown: dict[str, Any],
    effective_thresholds: dict[str, Any],
    decision_path: list[dict[str, Any]],
    vetoes: list[dict[str, Any]],
) -> list[str]:
    final_action = _txt(fusion_breakdown.get("final_action"), _txt(decision.get("finalAction") or decision.get("action"), "--")).upper()
    core_rule_action = _txt(fusion_breakdown.get("core_rule_action"), "--").upper()
    weighted_threshold_action = _txt(fusion_breakdown.get("weighted_threshold_action"), "--").upper()
    weighted_gate_action = _txt(fusion_breakdown.get("weighted_action_raw"), "--").upper()
    mode = _txt(fusion_breakdown.get("mode"), _txt(decision.get("decisionType"), "--"))
    tech_score = _float(fusion_breakdown.get("tech_score"), _float(technical_breakdown.get("track", {}).get("score")))
    context_score = _float(fusion_breakdown.get("context_score"), _float(context_breakdown.get("track", {}).get("score")))
    fusion_score = _float(fusion_breakdown.get("fusion_score"))
    fusion_confidence = _float(fusion_breakdown.get("fusion_confidence"), _float(decision.get("confidence")))
    buy_threshold = _float(fusion_breakdown.get("buy_threshold_eff"), _float(effective_thresholds.get("buy_threshold")))
    sell_threshold = _float(fusion_breakdown.get("sell_threshold_eff"), _float(effective_thresholds.get("sell_threshold")))
    min_fusion_confidence = _float(effective_thresholds.get("min_fusion_confidence"))
    tech_weight_norm = _float(fusion_breakdown.get("tech_weight_norm"), 0.0) or 0.0
    context_weight_norm = _float(fusion_breakdown.get("context_weight_norm"), 0.0) or 0.0
    tech_weighted = (tech_score or 0.0) * tech_weight_norm if tech_score is not None else None
    context_weighted = (context_score or 0.0) * context_weight_norm if context_score is not None else None
    dominant_track = "技术轨" if abs(tech_weighted or 0.0) >= abs(context_weighted or 0.0) else "环境轨"
    gate_fail_reasons = fusion_breakdown.get("weighted_gate_fail_reasons") if isinstance(fusion_breakdown.get("weighted_gate_fail_reasons"), list) else []
    tech_groups = technical_breakdown.get("groups") if isinstance(technical_breakdown.get("groups"), list) else []
    context_groups = context_breakdown.get("groups") if isinstance(context_breakdown.get("groups"), list) else []
    matched_path = " -> ".join(
        f"{_txt(item.get('step'), '--')}:{_txt(item.get('detail'), '--')}"
        for item in decision_path
        if isinstance(item, dict)
    )

    if vetoes:
        veto_labels = "；".join(
            f"{_txt(item.get('id') or item.get('display_label'), 'veto')}：{_txt(item.get('reason'), '--')}"
            for item in vetoes
            if isinstance(item, dict)
        )
        decision_line = f"本次动作首先受否决/风控链路控制，命中 {veto_labels}，因此最终动作定为 {_humanize_signal(final_action)}。"
    elif final_action == "BUY":
        threshold_reason = (
            f"融合分 {_format_plain(fusion_score)} 高于买入阈值 {_format_plain(buy_threshold)}"
            if fusion_score is not None and buy_threshold is not None and fusion_score >= buy_threshold
            else f"最终仍判为买入，但需要回看阈值链路（当前 fusion_score={_format_plain(fusion_score)}，buy_threshold={_format_plain(buy_threshold)}）"
        )
        confidence_reason = (
            f"融合置信度 {_format_plain(fusion_confidence)} 也高于最低要求 {_format_plain(min_fusion_confidence)}"
            if fusion_confidence is not None and min_fusion_confidence is not None and fusion_confidence >= min_fusion_confidence
            else ""
        )
        decision_line = f"本次买入总体合理，{threshold_reason}" + (f"，{confidence_reason}" if confidence_reason else "") + "。"
    elif final_action == "SELL":
        if core_rule_action == "SELL" and (fusion_score is None or sell_threshold is None or fusion_score > sell_threshold):
            decision_line = f"本次卖出主要由规则层触发，虽然融合分 {_format_plain(fusion_score)} 尚未跌破卖出阈值 {_format_plain(sell_threshold)}，但系统优先执行风险退出。"
        else:
            decision_line = f"本次卖出总体合理，融合分 {_format_plain(fusion_score)} 已跌破卖出阈值 {_format_plain(sell_threshold)}，系统进入退出链路。"
    else:
        if fusion_score is not None and buy_threshold is not None and sell_threshold is not None:
            decision_line = (
                f"本次保持观望是合理的，融合分 {_format_plain(fusion_score)} 没有达到买入阈值 {_format_plain(buy_threshold)}，"
                f"同时也没有跌破卖出阈值 {_format_plain(sell_threshold)}。"
            )
        else:
            decision_line = f"本次保持观望，规则层为 {core_rule_action}，阈值层为 {weighted_threshold_action}，门控层为 {weighted_gate_action}。"
        if gate_fail_reasons:
            decision_line += " 门控补充原因：" + "；".join(_txt(item, "--") for item in gate_fail_reasons) + "。"

    balance_line = (
        f"双轨融合采用 技术轨 {tech_weight_norm * 100:.1f}% / 环境轨 {context_weight_norm * 100:.1f}% 的权重。"
        f"当前技术分 {_format_signed(tech_score)}、环境分 {_format_signed(context_score)}，折算后由 {dominant_track} 主导最终方向。"
    )
    path_line = (
        f"本次链路为 {matched_path or '--'}，最终从 core_rule={core_rule_action} -> weighted_threshold={weighted_threshold_action}"
        f" -> weighted_gate={weighted_gate_action} -> final={final_action}，模式={mode}。"
    )
    return [
        decision_line,
        balance_line,
        _group_reasonability_line("技术侧", tech_groups),
        _group_reasonability_line("环境侧", context_groups),
        path_line,
    ]


def _is_position_add_intent(intent: Any) -> bool:
    return _txt(intent, "").strip().lower() == "position_add"


def _execution_intent_label(intent: Any) -> str:
    if _is_position_add_intent(intent):
        return "加仓/增持"
    if _txt(intent, "").strip().lower() == "position_add_blocked":
        return "加仓门控未通过"
    return "常规交易"


def _position_metric_label(action: Any, execution_intent: Any = None) -> str:
    action_upper = _txt(action, "--").upper()
    if action_upper == "BUY":
        if _is_position_add_intent(execution_intent):
            return "建议加仓比例(%)"
        return "目标买入仓位(%)"
    if action_upper == "SELL":
        return "建议卖出比例(%)"
    return "仓位建议"


def _position_metric_value(action: Any, position_size_pct: Any) -> str:
    action_upper = _txt(action, "--").upper()
    if action_upper == "HOLD":
        return "不变"
    return _txt(position_size_pct, "--")


def _derive_keep_position_pct(action: Any, position_size_pct: Any) -> str:
    ratio = _float(position_size_pct)
    action_upper = _txt(action, "--").upper()
    if action_upper == "HOLD":
        return "维持当前仓位（不变）"
    if ratio is None:
        return "--"
    ratio = max(0.0, min(100.0, float(ratio)))
    if action_upper == "SELL":
        keep = max(0.0, 100.0 - ratio)
    elif action_upper == "BUY":
        keep = ratio
    else:
        return "--"
    text = f"{keep:.2f}"
    return text.rstrip("0").rstrip(".")


def _dual_track_basis_lines(decision: dict[str, Any], effective_thresholds: dict[str, Any]) -> list[str]:
    tech_signal = _txt(decision.get("techSignal"), "--")
    context_signal = _txt(decision.get("contextSignal"), "--")
    decision_type = _txt(decision.get("decisionType"), "--")
    resonance_type = _txt(decision.get("resonanceType"), "--")
    rule_hit = _txt(decision.get("ruleHit"), "--")
    final_action = _txt(decision.get("finalAction") or decision.get("action"), "--")
    position_size_pct = _txt(decision.get("positionSizePct"), "--")
    keep_position_pct = _derive_keep_position_pct(final_action, position_size_pct)
    tech_score = _txt(decision.get("techScore"), "--")
    context_score = _txt(decision.get("contextScore"), "--")

    buy_threshold = _txt(effective_thresholds.get("buy_threshold"), "--")
    sell_threshold = _txt(effective_thresholds.get("sell_threshold"), "--")
    max_position_ratio = _txt(effective_thresholds.get("max_position_ratio"), "--")
    allow_pyramiding_raw = _txt(effective_thresholds.get("allow_pyramiding")).strip().lower()
    allow_pyramiding = "允许" if allow_pyramiding_raw in {"1", "true", "yes", "y", "on"} else "不允许"
    confirmation = _txt(effective_thresholds.get("confirmation"), "--")

    merge_reason_map = {
        "sell_divergence": "技术轨给出看空，但环境轨未同向看空，系统按“风险优先”的背离规则处理，优先保护资金。",
        "buy_divergence": "技术轨给出看多，但环境轨未同向看多，系统按“确认优先”的背离规则处理，避免盲目追涨。",
        "resonance_full": "技术轨与环境轨同向且强度高，形成强共振，允许更高执行力度。",
        "resonance_heavy": "技术轨与环境轨同向，形成偏强共振，执行力度高于常规。",
        "resonance_moderate": "技术轨与环境轨同向但强度中等，按中等共振规则执行。",
        "resonance_standard": "技术轨与环境轨方向一致但强度一般，按标准共振执行。",
        "neutral_hold": "双轨没有形成明确同向信号，系统保持中性观望。",
    }
    merge_reason = merge_reason_map.get(rule_hit) or merge_reason_map.get(decision_type) or "系统先判断双轨是否同向，再按共振/背离规则确定最终动作和仓位。"
    position_semantics = (
        "建议加仓比例"
        if _txt(final_action).upper() == "BUY" and _is_position_add_intent(decision.get("executionIntent"))
        else ("目标买入仓位" if _txt(final_action).upper() == "BUY" else ("建议卖出比例" if _txt(final_action).upper() == "SELL" else "建议仓位"))
    )
    if keep_position_pct == "--":
        keep_segment = ""
    elif keep_position_pct.endswith("%") or "不变" in keep_position_pct:
        keep_segment = f"，建议保持仓位 {keep_position_pct}"
    else:
        keep_segment = f"，建议保持仓位 {keep_position_pct}%"

    return [
        "双轨决策=技术轨 + 环境轨。技术轨反映价格/指标信号，环境轨反映市场状态与风险约束，二者先独立打分再合并。",
        f"技术轨结论: {_humanize_signal(tech_signal)}，技术分 {tech_score}（阈值: 买入>= {buy_threshold}，卖出<= {sell_threshold}）。",
        f"环境轨结论: {_humanize_signal(context_signal)}，环境分 {context_score}（环境分越高，越支持进攻；越低，越偏防守）。",
        f"合并判定: 决策类型 {decision_type}，共振类型 {resonance_type}，规则命中 {rule_hit}。{merge_reason}",
        f"执行结果: 最终动作为 {_humanize_signal(final_action)}，{position_semantics} {position_size_pct}%{keep_segment}（上限比例 {max_position_ratio}，{allow_pyramiding}加仓，确认条件: {confirmation}）。",
    ]


def _build_explanation_payload(
    *,
    decision: dict[str, Any],
    analysis_text: str,
    reasoning_text: str,
    tech_votes_raw: list[dict[str, Any]],
    context_votes_raw: list[dict[str, Any]],
    effective_thresholds: dict[str, Any],
    explainability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    explain_obj = explainability if isinstance(explainability, dict) else {}
    if not _is_structured_explainability(explain_obj):
        raise HTTPException(status_code=422, detail="Signal explanation requires structured explainability payload")

    technical_breakdown = _safe_json_load(explain_obj.get("technical_breakdown"))
    context_breakdown = _safe_json_load(explain_obj.get("context_breakdown"))
    fusion_breakdown = _safe_json_load(explain_obj.get("fusion_breakdown"))
    decision_path = explain_obj.get("decision_path") if isinstance(explain_obj.get("decision_path"), list) else []
    vetoes = explain_obj.get("vetoes") if isinstance(explain_obj.get("vetoes"), list) else []

    tech_track = _safe_json_load(technical_breakdown.get("track"))
    context_track = _safe_json_load(context_breakdown.get("track"))
    tech_groups = technical_breakdown.get("groups") if isinstance(technical_breakdown.get("groups"), list) else []
    context_groups = context_breakdown.get("groups") if isinstance(context_breakdown.get("groups"), list) else []
    tech_dims = technical_breakdown.get("dimensions") if isinstance(technical_breakdown.get("dimensions"), list) else []
    context_dims = context_breakdown.get("dimensions") if isinstance(context_breakdown.get("dimensions"), list) else []

    mode = _txt(fusion_breakdown.get("mode"), _txt(decision.get("strategyMode"), "--"))
    weighted_threshold_action = _txt(fusion_breakdown.get("weighted_threshold_action"), "--")
    weighted_action_raw = _txt(fusion_breakdown.get("weighted_action_raw"), "--")
    core_rule_action = _txt(fusion_breakdown.get("core_rule_action"), "--")
    final_action = _txt(fusion_breakdown.get("final_action"), _txt(decision.get("finalAction"), "--"))
    gate_fail_reasons = fusion_breakdown.get("weighted_gate_fail_reasons") if isinstance(
        fusion_breakdown.get("weighted_gate_fail_reasons"), list
    ) else []

    tech_score = _txt(fusion_breakdown.get("tech_score"), _txt(tech_track.get("score"), _txt(decision.get("techScore"), "0")))
    context_score = _txt(
        fusion_breakdown.get("context_score"),
        _txt(context_track.get("score"), _txt(decision.get("contextScore"), "0")),
    )
    fusion_score = _txt(fusion_breakdown.get("fusion_score"), "--")
    tech_conf = _txt(fusion_breakdown.get("tech_confidence"), _txt(tech_track.get("confidence"), "--"))
    context_conf = _txt(fusion_breakdown.get("context_confidence"), _txt(context_track.get("confidence"), "--"))
    fusion_conf = _txt(fusion_breakdown.get("fusion_confidence"), _txt(decision.get("confidence"), "--"))
    divergence = _txt(fusion_breakdown.get("divergence"), "--")
    divergence_penalty = _txt(fusion_breakdown.get("divergence_penalty"), "--")
    sign_conflict = _txt(fusion_breakdown.get("sign_conflict"), "--")

    tech_weight_raw = _txt(fusion_breakdown.get("tech_weight_raw"), "--")
    tech_weight_norm = _txt(fusion_breakdown.get("tech_weight_norm"), "--")
    context_weight_raw = _txt(fusion_breakdown.get("context_weight_raw"), "--")
    context_weight_norm = _txt(fusion_breakdown.get("context_weight_norm"), "--")

    tech_group_lines: list[str] = []
    for group in tech_groups:
        if not isinstance(group, dict):
            continue
        tech_group_lines.append(
            "技术组 "
            + _txt(group.get("id"), "--")
            + f": score={_txt(group.get('score'), '--')}, coverage={_txt(group.get('coverage'), '--')}, "
            + f"weight_raw={_txt(group.get('weight_raw'), '--')}, weight_norm={_txt(group.get('weight_norm_in_track'), '--')}, "
            + f"track_contribution={_txt(group.get('track_contribution'), '--')}"
        )

    context_group_lines: list[str] = []
    for group in context_groups:
        if not isinstance(group, dict):
            continue
        context_group_lines.append(
            "环境组 "
            + _txt(group.get("id"), "--")
            + f": score={_txt(group.get('score'), '--')}, coverage={_txt(group.get('coverage'), '--')}, "
            + f"weight_raw={_txt(group.get('weight_raw'), '--')}, weight_norm={_txt(group.get('weight_norm_in_track'), '--')}, "
            + f"track_contribution={_txt(group.get('track_contribution'), '--')}"
        )

    top_tech_dims = sorted(
        [item for item in tech_dims if isinstance(item, dict)],
        key=lambda item: abs(_float(item.get("track_contribution"), _float(item.get("group_contribution"), _float(item.get("score"), 0.0))) or 0.0),
        reverse=True,
    )[:6]
    top_context_dims = sorted(
        [item for item in context_dims if isinstance(item, dict)],
        key=lambda item: abs(_float(item.get("track_contribution"), _float(item.get("group_contribution"), _float(item.get("score"), 0.0))) or 0.0),
        reverse=True,
    )[:6]

    tech_evidence = [
        "技术维度 "
        + _txt(item.get("id"), "--")
        + f"（组={_txt(item.get('group'), '--')}）: score={_txt(item.get('score'), '--')}, "
        + f"group_contribution={_txt(item.get('group_contribution'), '--')}, track_contribution={_txt(item.get('track_contribution'), '--')} · "
        + _txt(item.get("reason"), "--")
        for item in top_tech_dims
    ]
    context_evidence = [
        "环境维度 "
        + _txt(item.get("id"), "--")
        + f"（组={_txt(item.get('group'), '--')}）: score={_txt(item.get('score'), '--')}, "
        + f"group_contribution={_txt(item.get('group_contribution'), '--')}, track_contribution={_txt(item.get('track_contribution'), '--')} · "
        + _txt(item.get("reason"), "--")
        for item in top_context_dims
    ]

    threshold_lines = [f"{_txt(k)}={_txt(v)}" for k, v in effective_thresholds.items() if _txt(k)]
    decision_path_lines = []
    for item in decision_path:
        if not isinstance(item, dict):
            continue
        decision_path_lines.append(
            _txt(item.get("step"), "--")
            + f": matched={_txt(item.get('matched'), '--')}"
            + f", detail={_txt(item.get('detail'), '--')}"
        )
    veto_lines = []
    for item in vetoes:
        if not isinstance(item, dict):
            continue
        label = _txt(item.get("display_label") or item.get("trigger_type") or item.get("id"), "veto")
        veto_lines.append(
            label
            + f": action={_txt(item.get('action'), '--')}, id={_txt(item.get('id'), '--')}, reason={_txt(item.get('reason'), '--')}, priority={_txt(item.get('priority'), '--')}"
        )

    summary_lines = [
        f"本次信号采用结构化双轨算法，双轨融合模式 {mode}。最终动作 {final_action}，融合分 {fusion_score}，融合置信度 {fusion_conf}。",
        f"策略模板：配置={_txt(decision.get('configuredProfile'), '--')}，应用={_txt(decision.get('appliedProfile'), '--')}，AI动态调整模式={_txt(decision.get('aiDynamicStrategy'), '--')}。"
        + (
            "（本次发生模板切换）"
            if _txt(decision.get("aiProfileSwitched"), "").lower() in {"1", "true", "yes", "是"}
            else ""
        ),
        f"技术轨 score/confidence={tech_score}/{tech_conf}；环境轨 score/confidence={context_score}/{context_conf}。",
        f"动作链路：core_rule={core_rule_action} -> weighted_threshold={weighted_threshold_action} -> weighted_gate={weighted_action_raw} -> final={final_action}。",
    ]
    if gate_fail_reasons:
        summary_lines.append("加权门控未通过原因: " + " | ".join(_txt(item, "--") for item in gate_fail_reasons))
    if veto_lines:
        summary_lines.append("否决命中: " + " | ".join(veto_lines))

    basis = [
        f"决策点: {_txt(decision.get('checkpointAt'), '--')}",
        f"轨道权重: 技术轨 raw={tech_weight_raw}, norm={tech_weight_norm}; 环境轨 raw={context_weight_raw}, norm={context_weight_norm}",
        f"融合参数: divergence={divergence}, divergence_penalty={divergence_penalty}, sign_conflict={sign_conflict}",
        f"canonical_breakdown: tech_score={tech_score}, context_score={context_score}, tech_confidence={tech_conf}, context_confidence={context_conf}, fusion_score={fusion_score}, fusion_confidence={fusion_conf}",
        f"阈值: buy={_txt(fusion_breakdown.get('buy_threshold_eff'), '--')} (base={_txt(fusion_breakdown.get('buy_threshold_base'), '--')}), "
        + f"sell={_txt(fusion_breakdown.get('sell_threshold_eff'), '--')} (base={_txt(fusion_breakdown.get('sell_threshold_base'), '--')}), "
        + f"sell_precedence_gate={_txt(fusion_breakdown.get('sell_precedence_gate'), '--')}, mode={_txt(fusion_breakdown.get('threshold_mode'), '--')}",
        *tech_group_lines,
        *context_group_lines,
        *decision_path_lines,
        *veto_lines,
    ]

    context_component_breakdown = [
        f"{_txt(item.get('id'), '--')}: track_contribution={_txt(item.get('track_contribution'), '--')} · {_txt(item.get('reason'), '--')}"
        for item in top_context_dims
    ]
    context_component_sum = 0.0
    for group in context_groups:
        if not isinstance(group, dict):
            continue
        context_component_sum += _float(group.get("track_contribution"), 0.0) or 0.0

    return {
        "summary": "\n".join(summary_lines),
        "auditSummary": _build_audit_summary_lines(
            decision=decision,
            fusion_breakdown=fusion_breakdown,
            technical_breakdown=technical_breakdown,
            context_breakdown=context_breakdown,
            effective_thresholds=effective_thresholds,
            decision_path=[item for item in decision_path if isinstance(item, dict)],
            vetoes=[item for item in vetoes if isinstance(item, dict)],
        ),
        "contextScoreExplain": {
            "formula": "环境轨分值 = Σ(组权重归一化 × 组分值)，组分值=Σ(组内维度归一化权重 × 维度分)，并截断到 [-1, 1]。",
            "confidenceFormula": "环境轨置信度 = Σ(组权重 × 组覆盖率)/Σ组权重；融合置信度 = base_confidence × (1 - divergence_penalty)。",
            "componentBreakdown": context_component_breakdown,
            "componentSum": round(context_component_sum, 6),
            "finalScore": _txt(context_score, _txt(decision.get("contextScore"), "0")),
        },
        "basis": basis,
        "techEvidence": tech_evidence,
        "contextEvidence": context_evidence,
        "thresholdEvidence": threshold_lines,
        "original": {
            "analysis": analysis_text,
            "reasoning": reasoning_text,
        },
    }


def _build_vote_overview(
    *,
    tech_votes_raw: list[dict[str, Any]],
    context_votes_raw: list[dict[str, Any]],
    explainability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    def _extract_weight(item: dict[str, Any]) -> float:
        for key in ("weight", "vote_weight", "factor_weight", "w"):
            value = _float(item.get(key))
            if value is not None:
                return value
        return 1.0

    def _extract_contribution(item: dict[str, Any], score: float, weight: float) -> float:
        for key in ("weighted_score", "weightedScore", "contribution", "vote_score"):
            value = _float(item.get(key))
            if value is not None:
                return value
        return score * weight

    rows: list[dict[str, str]] = []
    tech_sum = 0.0
    context_sum = 0.0
    tech_count = 0
    context_count = 0

    for track, raw_votes in (("technical", tech_votes_raw), ("context", context_votes_raw)):
        for index, item in enumerate(raw_votes):
            vote_row = _to_vote_row(item, default_signal="CONTEXT" if track == "context" else "")
            if isinstance(item, dict):
                voter = _txt(
                    item.get("agent")
                    or item.get("analyst")
                    or item.get("factor")
                    or item.get("component")
                    or item.get("name")
                    or item.get("title"),
                    vote_row.get("factor") or f"{track}-voter-{index + 1}",
                )
                signal = _txt(item.get("signal") or item.get("vote") or item.get("decision"), vote_row.get("signal") or "--")
                score_value = _float(item.get("score"), _float(item.get("confidence"), 0.0)) or 0.0
                weight_value = _extract_weight(item)
                contribution_value = _extract_contribution(item, score_value, weight_value)
                reason = _txt(item.get("reason") or item.get("note") or item.get("detail"), vote_row.get("reason") or "--")
                calculation = _txt(
                    item.get("calculation") or item.get("formula"),
                    f"单票贡献 = score({score_value:+.4f}) x weight({weight_value:.4f}) = {contribution_value:+.4f}",
                )
            else:
                voter = _txt(vote_row.get("factor"), f"{track}-voter-{index + 1}")
                signal = _txt(vote_row.get("signal"), "--")
                score_value = _float(vote_row.get("score"), 0.0) or 0.0
                weight_value = 1.0
                contribution_value = score_value
                reason = _txt(vote_row.get("reason"), "--")
                calculation = f"单票贡献 = score({score_value:+.4f}) x weight(1.0000) = {contribution_value:+.4f}"

            if track == "technical":
                tech_sum += contribution_value
                tech_count += 1
            else:
                context_sum += contribution_value
                context_count += 1

            rows.append(
                {
                    "track": track,
                    "voter": voter,
                    "signal": signal,
                    "score": f"{score_value:+.4f}",
                    "weight": f"{weight_value:.4f}",
                    "contribution": f"{contribution_value:+.4f}",
                    "reason": reason,
                    "calculation": calculation,
                }
            )

    tech_clamped = max(-1.0, min(1.0, tech_sum))
    context_clamped = max(-1.0, min(1.0, context_sum))

    explain_obj = explainability if isinstance(explainability, dict) else {}
    if _is_structured_explainability(explain_obj):
        technical_breakdown = _safe_json_load(explain_obj.get("technical_breakdown"))
        context_breakdown = _safe_json_load(explain_obj.get("context_breakdown"))
        tech_track = _safe_json_load(technical_breakdown.get("track"))
        context_track = _safe_json_load(context_breakdown.get("track"))
        tech_group_lines = []
        for item in technical_breakdown.get("groups") if isinstance(technical_breakdown.get("groups"), list) else []:
            if not isinstance(item, dict):
                continue
            tech_group_lines.append(
                f"{_txt(item.get('id'), '--')}: score={_txt(item.get('score'), '--')}, "
                f"weight_norm={_txt(item.get('weight_norm_in_track'), '--')}, track_contribution={_txt(item.get('track_contribution'), '--')}"
            )
        context_group_lines = []
        for item in context_breakdown.get("groups") if isinstance(context_breakdown.get("groups"), list) else []:
            if not isinstance(item, dict):
                continue
            context_group_lines.append(
                f"{_txt(item.get('id'), '--')}: score={_txt(item.get('score'), '--')}, "
                f"weight_norm={_txt(item.get('weight_norm_in_track'), '--')}, track_contribution={_txt(item.get('track_contribution'), '--')}"
            )
        return {
            "voterCount": len(rows),
            "technicalVoterCount": tech_count,
            "contextVoterCount": context_count,
            "formula": "结构化聚合：组内维度归一化 -> 轨内组权重归一化 -> 双轨融合；表格贡献分优先展示 track_contribution。",
            "technicalAggregation": (
                f"技术轨 score={_txt(tech_track.get('score'), '--')}, confidence={_txt(tech_track.get('confidence'), '--')}"
                + (f"；组明细: {' | '.join(tech_group_lines)}" if tech_group_lines else "")
            ),
            "contextAggregation": (
                f"环境轨 score={_txt(context_track.get('score'), '--')}, confidence={_txt(context_track.get('confidence'), '--')}"
                + (f"；组明细: {' | '.join(context_group_lines)}" if context_group_lines else "")
            ),
            "rows": rows,
        }

    raise HTTPException(status_code=422, detail="Vote overview requires structured explainability payload")


def _extract_vote_list(explainability: dict[str, Any], keys: tuple[str, ...]) -> list[Any]:
    for key in keys:
        value = explainability.get(key)
        if isinstance(value, list):
            return value
    votes_obj = explainability.get("votes")
    if isinstance(votes_obj, dict):
        for key in keys:
            value = votes_obj.get(key)
            if isinstance(value, list):
                return value
    return []
def _score_to_signal(score: Any, *, epsilon: float = 1e-6) -> str:
    value = _float(score, 0.0) or 0.0
    if value > epsilon:
        return "BUY"
    if value < -epsilon:
        return "SELL"
    return "HOLD"


def _is_structured_explainability(explainability: dict[str, Any]) -> bool:
    technical_breakdown = explainability.get("technical_breakdown")
    context_breakdown = explainability.get("context_breakdown")
    fusion_breakdown = explainability.get("fusion_breakdown")
    return isinstance(technical_breakdown, dict) and isinstance(context_breakdown, dict) and isinstance(fusion_breakdown, dict)


def _build_structured_vote_rows(track_breakdown: dict[str, Any], *, track: str) -> list[dict[str, Any]]:
    rows = track_breakdown.get("dimensions")
    if not isinstance(rows, list):
        return []
    output: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        dim_id = _txt(row.get("id"), f"{track}_dim_{index + 1}")
        dim_group = _txt(row.get("group"))
        score_value = _float(row.get("score"), 0.0) or 0.0
        weight_raw = _float(row.get("weight_raw"), 1.0)
        if weight_raw is None:
            weight_raw = 1.0
        weight_norm_group = _float(row.get("weight_norm_in_group"))
        group_contribution = _float(row.get("group_contribution"))
        track_contribution = _float(row.get("track_contribution"))
        contribution_value = (
            track_contribution
            if track_contribution is not None
            else (
                group_contribution
                if group_contribution is not None
                else score_value
            )
        )
        reason = _txt(row.get("reason"), "--")
        calc_parts = [
            f"score={score_value:+.4f}",
            f"weight_raw={float(weight_raw):.4f}",
        ]
        if weight_norm_group is not None:
            calc_parts.append(f"w_norm_group={float(weight_norm_group):.4f}")
        if group_contribution is not None:
            calc_parts.append(f"group_contrib={float(group_contribution):+.4f}")
        if track_contribution is not None:
            calc_parts.append(f"track_contrib={float(track_contribution):+.4f}")
        calculation = "；".join(calc_parts)
        output.append(
            {
                "factor": dim_id,
                "component": dim_id if track == "context" else "",
                "name": dim_id,
                "group": dim_group,
                "signal": _score_to_signal(score_value),
                "score": round(score_value, 6),
                "weight": round(float(weight_raw), 6),
                "vote_weight": round(float(weight_norm_group), 6) if weight_norm_group is not None else "",
                "contribution": round(contribution_value, 6),
                "reason": f"group={dim_group}; {reason}" if dim_group else reason,
                "calculation": calculation,
            }
        )
    return output
