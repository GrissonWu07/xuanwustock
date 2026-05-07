from __future__ import annotations

from app.gateway.deps import *
from app.gateway.signal_explanation import (
    _derive_keep_position_pct,
    _execution_intent_label,
    _is_structured_explainability,
    _position_metric_label,
    _position_metric_value,
    _score_to_signal,
    _track_direction_label,
)
from app.gateway.signal_indicators import _indicator_derivation, _parse_metric_float, _safe_json_load

def _build_parameter_details(
    *,
    decision: dict[str, Any],
    runtime_context: dict[str, Any],
    strategy_profile: dict[str, Any],
    technical_indicators: list[dict[str, str]],
    effective_thresholds: dict[str, Any],
    tech_votes_raw: list[dict[str, Any]],
    context_votes_raw: list[dict[str, Any]],
    explainability: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    def _item(name: str, value: Any, source: str, derivation: str) -> dict[str, str]:
        return {
            "name": _txt(name),
            "value": _txt(value, "--"),
            "source": _txt(source),
            "derivation": _txt(derivation),
        }

    def _adjustment_name(path: Any) -> str:
        text = _txt(path, "")
        if not text:
            return "unknown"
        if "track_weights." in text:
            return f"track_weights.{text.rsplit('track_weights.', 1)[-1]}"
        if "dual_track." in text:
            return text.rsplit("dual_track.", 1)[-1]
        if "group_weights." in text:
            return f"group_weights.{text.rsplit('group_weights.', 1)[-1]}"
        if "dimension_weights." in text:
            return f"dimension_weights.{text.rsplit('dimension_weights.', 1)[-1]}"
        return text

    def _adjustment_value(item: dict[str, Any]) -> str:
        before = _float(item.get("before"))
        after = _float(item.get("after"))
        if before is None or after is None:
            return _txt(item.get("value"), "--")
        return f"{before:.4f} -> {after:.4f} (Δ{after - before:+.4f})"

    explain_obj = explainability if isinstance(explainability, dict) else {}
    if _is_structured_explainability(explain_obj):
        technical_breakdown = _safe_json_load(explain_obj.get("technical_breakdown"))
        context_breakdown = _safe_json_load(explain_obj.get("context_breakdown"))
        fusion_breakdown = _safe_json_load(explain_obj.get("fusion_breakdown"))
        decision_path = explain_obj.get("decision_path") if isinstance(explain_obj.get("decision_path"), list) else []
        vetoes = explain_obj.get("vetoes") if isinstance(explain_obj.get("vetoes"), list) else []

        tech_track = _safe_json_load(technical_breakdown.get("track"))
        context_track = _safe_json_load(context_breakdown.get("track"))
        dynamic_strategy = strategy_profile.get("dynamic_strategy") if isinstance(strategy_profile.get("dynamic_strategy"), dict) else {}
        stock_analysis_context = (
            explain_obj.get("stock_analysis_context")
            if isinstance(explain_obj.get("stock_analysis_context"), dict)
            else {}
        )
        position_metric_label = _position_metric_label(decision.get("action"), decision.get("executionIntent"))
        position_metric_value = _position_metric_value(decision.get("action"), decision.get("positionSizePct"))

        rows: list[dict[str, str]] = [
            _item("动作", decision.get("action"), "fusion_breakdown.final_action", "最终动作来自结构化融合层输出（含 veto/门控/规则合并）。"),
            _item("决策类型", decision.get("decisionType"), "signal.decision_type", "决策类型来自信号记录，用于区分融合路径与执行语义。"),
            _item(
                "执行语义",
                _execution_intent_label(decision.get("executionIntent")),
                "strategy_profile.position_add_gate.intent",
                "持仓股票的 BUY 会被解释为加仓/增持；候选股 BUY 才是新开仓。",
            ),
            _item("核心规则动作", fusion_breakdown.get("core_rule_action"), "fusion_breakdown.core_rule_action", "仅规则引擎输出，不含 veto。"),
            _item("加权阈值动作", fusion_breakdown.get("weighted_threshold_action"), "fusion_breakdown.weighted_threshold_action", "仅由融合分与阈值比较得到的动作。"),
            _item("加权门控后动作", fusion_breakdown.get("weighted_action_raw"), "fusion_breakdown.weighted_action_raw", "在阈值动作基础上应用置信度与分轨门控后的动作。"),
            _item("技术轨方向", _track_direction_label(decision.get("techSignal")), "technical_breakdown.track.score", "技术轨方向由技术轨 TrackScore 符号映射：>0 偏多，<0 偏空，=0 中性。"),
            _item("环境轨方向", _track_direction_label(decision.get("contextSignal")), "context_breakdown.track.score", "环境轨方向由环境轨 TrackScore 符号映射：>0 偏多，<0 偏空，=0 中性。"),
            _item("技术分", decision.get("techScore"), "technical_breakdown.track.score", "技术轨分值=Σ(组权重归一化 × 组分值)，组分值=Σ(组内维度归一化权重 × 维度分)。"),
            _item("环境分", decision.get("contextScore"), "context_breakdown.track.score", "环境轨分值=Σ(组权重归一化 × 组分值)，组分值=Σ(组内维度归一化权重 × 维度分)。"),
            _item("技术轨置信度", tech_track.get("confidence"), "technical_breakdown.track.confidence", "技术轨置信度=Σ(组权重 × 组覆盖率)/Σ组权重。"),
            _item("环境轨置信度", context_track.get("confidence"), "context_breakdown.track.confidence", "环境轨置信度=Σ(组权重 × 组覆盖率)/Σ组权重。"),
            _item("融合分", fusion_breakdown.get("fusion_score"), "fusion_breakdown.fusion_score", "融合分=技术轨归一化权重×技术轨分 + 环境轨归一化权重×环境轨分。"),
            _item(
                "融合置信度",
                fusion_breakdown.get("fusion_confidence"),
                "fusion_breakdown.fusion_confidence",
                "融合置信度=base_confidence × (1 - divergence_penalty)，用于 BUY 门控和动作稳定性控制。",
            ),
            _item(position_metric_label, position_metric_value, "signal.position_size_pct", "仓位建议由融合动作与风险约束共同决定；HOLD 时显示为不变。"),
            _item(
                "建议保持仓位",
                _derive_keep_position_pct(decision.get("action"), decision.get("positionSizePct")),
                "signal.position_size_pct",
                "BUY 时等于目标买入仓位；SELL 时 = 100% - 建议卖出比例；HOLD 时保持不变。",
            ),
            _item("规则命中（兼容派生）", decision.get("ruleHit"), "dual_track.rule_hit", "兼容派生字段，来自 legacy dual_track 摘要，仅用于辅助对照，不作为 canonical 决策口径。"),
            _item("共振类型（兼容派生）", decision.get("resonanceType"), "dual_track.resonance_type", "兼容派生字段，来自 legacy dual_track 摘要，仅用于辅助对照，不作为 canonical 决策口径。"),
            _item("市场", runtime_context.get("market"), "调度配置/回放任务", "实时模式取 scheduler.market；回放模式取 sim_runs.market。"),
            _item("配置模板", decision.get("configuredProfile"), "sim_scheduler_config.strategy_profile_id", "当前调度配置中的策略模板。"),
            _item("应用模板", decision.get("appliedProfile"), "strategy_profile.selected_strategy_profile", "该条信号实际使用的策略模板（信号快照）。"),
            _item("AI动态调整模式", decision.get("aiDynamicStrategy"), "sim_scheduler_config.ai_dynamic_strategy", "AI 动态调整模式，控制是否允许按市场切换模板/权重。"),
            _item("AI动态强度", decision.get("aiDynamicStrength"), "sim_scheduler_config.ai_dynamic_strength", "AI 动态调整强度（0~1，越大调整越激进）。"),
            _item("AI回看窗口(小时)", decision.get("aiDynamicLookback"), "sim_scheduler_config.ai_dynamic_lookback", "AI 评估市场状态时使用的回看窗口。"),
            _item("AI是否切换模板", decision.get("aiProfileSwitched"), "strategy_profile.selected_strategy_profile", "配置模板与应用模板不一致时为“是”，表示本次触发了动态切换。"),
            _item("分析粒度", runtime_context.get("timeframe"), "调度配置/回放任务/策略配置", "实时模式优先策略粒度，其次 scheduler.analysis_timeframe；回放模式取 sim_runs.timeframe。"),
            _item("策略模式", runtime_context.get("strategyMode"), "调度配置/回放任务/策略配置", "实时模式优先策略模式，其次 scheduler.strategy_mode；回放模式取 sim_runs.selected_strategy_mode。"),
            _item("双轨融合模式", fusion_breakdown.get("mode"), "fusion_breakdown.mode", "双轨融合模式支持 rule_only / weighted_only / hybrid。"),
            _item("技术轨权重(raw)", fusion_breakdown.get("tech_weight_raw"), "fusion_breakdown.tech_weight_raw", "技术轨原始权重，融合前参数。"),
            _item("环境轨权重(raw)", fusion_breakdown.get("context_weight_raw"), "fusion_breakdown.context_weight_raw", "环境轨原始权重，融合前参数。"),
            _item("技术轨权重(norm)", fusion_breakdown.get("tech_weight_norm"), "fusion_breakdown.tech_weight_norm", "技术轨融合归一化权重。"),
            _item("环境轨权重(norm)", fusion_breakdown.get("context_weight_norm"), "fusion_breakdown.context_weight_norm", "环境轨融合归一化权重。"),
            _item("方向背离度", fusion_breakdown.get("divergence"), "fusion_breakdown.divergence", "双轨分值差异度，用于冲突惩罚计算。"),
            _item("背离惩罚", fusion_breakdown.get("divergence_penalty"), "fusion_breakdown.divergence_penalty", "融合置信度惩罚项，越大代表轨道冲突越强。"),
            _item("方向冲突标记", fusion_breakdown.get("sign_conflict"), "fusion_breakdown.sign_conflict", "技术轨与环境轨符号是否冲突（0/1）。"),
            _item("veto 来源模式", fusion_breakdown.get("veto_source_mode"), "fusion_breakdown.veto_source_mode", "标记 veto 判定来源（如 legacy/new）。"),
        ]

        if stock_analysis_context:
            rows.extend(
                [
                    _item(
                        "股票分析上下文",
                        "使用" if stock_analysis_context.get("used") else "未使用",
                        "explainability.stock_analysis_context.used",
                        "实时模拟可使用最近有效股票分析作为外部分析维度；历史回放默认禁用，避免当前分析污染历史决策。",
                    ),
                    _item(
                        "股票分析记录ID",
                        stock_analysis_context.get("record_id") or "--",
                        "explainability.stock_analysis_context.record_id",
                        "被交易决策引用的股票分析记录 ID。",
                    ),
                    _item(
                        "股票分析数据时点",
                        _system_time_text(stock_analysis_context.get("data_as_of")),
                        "explainability.stock_analysis_context.data_as_of",
                        "股票分析所依据的数据截止时间，必须早于等于决策点。",
                    ),
                    _item(
                        "股票分析质量",
                        stock_analysis_context.get("data_as_of_quality") or stock_analysis_context.get("omitted_reason") or "--",
                        "explainability.stock_analysis_context.data_as_of_quality",
                        "exact/asof_precomputed 可用于严格 as-of；generated_at_fallback 仅用于实时，不用于历史回放。",
                    ),
                    _item(
                        "股票分析贡献分",
                        stock_analysis_context.get("effective_score", stock_analysis_context.get("score", "--")),
                        "context_breakdown.dimensions.stock_analysis.score",
                        "归一化后的股票分析分，作为环境轨 external_analysis 维度参与融合。",
                    ),
                ]
            )

        position_add_gate = strategy_profile.get("position_add_gate") if isinstance(strategy_profile.get("position_add_gate"), dict) else {}
        if position_add_gate:
            rows.extend(
                [
                    _item(
                        "加仓门控",
                        "通过" if _txt(position_add_gate.get("status")).lower() == "passed" else "未通过",
                        "strategy_profile.position_add_gate.status",
                        "持仓 BUY 必须先通过加仓门控；未通过时降级为 HOLD。",
                    ),
                    _item(
                        "当前持仓比例(%)",
                        position_add_gate.get("current_position_pct"),
                        "strategy_profile.position_add_gate.current_position_pct",
                        "当前持仓市值 / 当前总资产，用于判断是否还有加仓空间。",
                    ),
                    _item(
                        "目标持仓比例(%)",
                        position_add_gate.get("target_position_pct"),
                        "strategy_profile.position_add_gate.target_position_pct",
                        "融合层给出的目标仓位，上限受 max_position_ratio 限制。",
                    ),
                    _item(
                        "建议加仓比例(%)",
                        position_add_gate.get("add_position_delta_pct"),
                        "strategy_profile.position_add_gate.add_position_delta_pct",
                        "实际下单只使用目标仓位与当前仓位的差额，不重复买满目标仓位。",
                    ),
                    _item(
                        "加仓上限比例(%)",
                        position_add_gate.get("max_position_pct"),
                        "strategy_profile.position_add_gate.max_position_pct",
                        "由 max_position_ratio 转换为百分比后的持仓上限。",
                    ),
                    _item(
                        "加仓浮盈门槛(%)",
                        position_add_gate.get("min_unrealized_pnl_pct"),
                        "strategy_profile.position_add_gate.min_unrealized_pnl_pct",
                        "持仓已有浮盈达到该门槛，可以作为加仓放行证据。",
                    ),
                    _item(
                        "加仓趋势门槛",
                        position_add_gate.get("min_tech_score"),
                        "strategy_profile.position_add_gate.min_tech_score",
                        "若浮盈不足，则需要技术分和融合置信度同时达到门槛才能加仓。",
                    ),
                    _item(
                        "加仓门控理由",
                        "；".join(_txt(item, "--") for item in position_add_gate.get("reasons", []) if _txt(item, "")) or "--",
                        "strategy_profile.position_add_gate.reasons",
                        "记录本次加仓门控通过或阻断的具体原因。",
                    ),
                ]
            )

        position_sizing = strategy_profile.get("position_sizing") if isinstance(strategy_profile.get("position_sizing"), dict) else {}
        if position_sizing:
            sizing_slot_plan = _safe_json_load(position_sizing.get("slot_plan"))
            sizing_detail = _safe_json_load(position_sizing.get("sizing"))
            rows.extend(
                [
                    _item(
                        "Slot数量",
                        sizing_slot_plan.get("slot_count"),
                        "strategy_profile.position_sizing.slot_plan.slot_count",
                        "按有效资金池 / 单 slot 最低金额向下取整，并受最大 slot 数限制。",
                    ),
                    _item(
                        "单Slot预算",
                        sizing_slot_plan.get("slot_budget"),
                        "strategy_profile.position_sizing.slot_plan.slot_budget",
                        "每个 slot 的平均预算；BUY 默认最多使用一个 slot。",
                    ),
                    _item(
                        "BUY优先级",
                        sizing_detail.get("priority"),
                        "strategy_profile.position_sizing.sizing.priority",
                        "同一交易点所有 BUY 先按优先级排序，强信号优先占用 slot。",
                    ),
                    _item(
                        "BUY占用Slot",
                        sizing_detail.get("slot_units"),
                        "strategy_profile.position_sizing.sizing.slot_units",
                        "融合分边际和置信度映射出的 slot 使用量；高价强 BUY 可临时放大到最多两个 slot。",
                    ),
                    _item(
                        "BUY预算",
                        position_sizing.get("buy_budget"),
                        "strategy_profile.position_sizing.buy_budget",
                        "最终买入预算=min(slot预算×slot占用、账户可用现金、slot可用资金)。",
                    ),
                    _item(
                        "自动买入股数",
                        position_sizing.get("quantity"),
                        "strategy_profile.position_sizing.quantity",
                        "BUY预算按 A 股 100 股一手和手续费取整后的自动执行股数。",
                    ),
                    _item(
                        "买入跳过原因",
                        position_sizing.get("skip_reason"),
                        "strategy_profile.position_sizing.skip_reason",
                        "当 slot 预算、资金池门槛或一手成本不足时，记录自动执行跳过原因。",
                    ),
                ]
            )

        if dynamic_strategy:
            if _txt(dynamic_strategy.get("as_of")):
                rows.append(
                    _item(
                        "AI动态as_of",
                        dynamic_strategy.get("as_of"),
                        "strategy_profile.dynamic_strategy.as_of",
                        "AI 动态层允许使用的数据截止时间；历史回放中必须等于 checkpoint。",
                    )
                )
            rows.append(
                _item(
                    "AI动态档位",
                    dynamic_strategy.get("overlay_regime"),
                    "strategy_profile.dynamic_strategy.overlay_regime",
                    "AI 动态层将市场状态映射到 risk_on / neutral / risk_off，再由白名单规则调整参数。",
                )
            )
            rows.append(
                _item(
                    "AI动态评分",
                    f"{_txt(dynamic_strategy.get('score'), '--')} / {_txt(dynamic_strategy.get('confidence'), '--')}",
                    "strategy_profile.dynamic_strategy.score/confidence",
                    "格式为 动态评分 / 动态置信度，用于决定是否进入动态调参档位。",
                )
            )
            components = dynamic_strategy.get("components")
            if isinstance(components, list):
                for component in components:
                    if not isinstance(component, dict):
                        continue
                    key = _txt(component.get("key"), "unknown")
                    rows.append(
                        _item(
                            f"AI动态使用组件.{key}",
                            (
                                f"score={_txt(component.get('score'), '--')} / "
                                f"confidence={_txt(component.get('confidence'), '--')} / "
                                f"as_of={_txt(component.get('as_of'), '--')}"
                            ),
                            "strategy_profile.dynamic_strategy.components",
                            _txt(component.get("reason"), "AI 动态层实际使用的 point-in-time 组件。"),
                        )
                    )
            omitted_components = dynamic_strategy.get("omitted_components")
            if isinstance(omitted_components, list):
                for component in omitted_components:
                    if not isinstance(component, dict):
                        continue
                    key = _txt(component.get("key"), "unknown")
                    rows.append(
                        _item(
                            f"AI动态省略组件.{key}",
                            f"{_txt(component.get('reason'), '--')} @ {_txt(component.get('as_of'), '--')}",
                            "strategy_profile.dynamic_strategy.omitted_components",
                            "历史回放中缺少可证明在 checkpoint 前可见的数据，因此该组件未参与动态调参。",
                        )
                    )
            adjustments = dynamic_strategy.get("adjustments")
            if isinstance(adjustments, list):
                for item in adjustments:
                    if not isinstance(item, dict):
                        continue
                    label = _adjustment_name(item.get("path"))
                    rows.append(
                        _item(
                            f"AI动态调整.{label}",
                            _adjustment_value(item),
                            "strategy_profile.dynamic_strategy.adjustments",
                            _txt(item.get("reason"), "AI 动态层白名单参数调整。"),
                        )
                    )

        buy_base = _float(fusion_breakdown.get("buy_threshold_base"))
        buy_eff = _float(fusion_breakdown.get("buy_threshold_eff"))
        if buy_base is not None and buy_eff is not None:
            rows.append(
                _item(
                    "BUY阈值调整",
                    f"{buy_base:.4f} -> {buy_eff:.4f} (Δ{buy_eff - buy_base:+.4f})",
                    "fusion_breakdown.buy_threshold_base/buy_threshold_eff",
                    "显示 BUY 阈值从基础值到生效值的变化（含 AI/波动率策略影响）。",
                )
            )

        sell_base = _float(fusion_breakdown.get("sell_threshold_base"))
        sell_eff = _float(fusion_breakdown.get("sell_threshold_eff"))
        if sell_base is not None and sell_eff is not None:
            rows.append(
                _item(
                    "SELL阈值调整",
                    f"{sell_base:.4f} -> {sell_eff:.4f} (Δ{sell_eff - sell_base:+.4f})",
                    "fusion_breakdown.sell_threshold_base/sell_threshold_eff",
                    "显示 SELL 阈值从基础值到生效值的变化（含 AI/波动率策略影响）。",
                )
            )

        gate_reasons = fusion_breakdown.get("weighted_gate_fail_reasons")
        if isinstance(gate_reasons, list):
            rows.append(
                _item(
                    "加权门控失败原因",
                    " | ".join(_txt(item, "--") for item in gate_reasons) if gate_reasons else "无",
                    "fusion_breakdown.weighted_gate_fail_reasons",
                    "记录 weighted_action_raw 未能通过门控时的失败原因列表。",
                )
            )

        for index, item in enumerate(decision_path):
            if not isinstance(item, dict):
                continue
            step = _txt(item.get("step"), f"step_{index + 1}")
            rows.append(
                _item(
                    f"决策路径.{index + 1}.{step}",
                    _txt(item.get("matched"), "--"),
                    "decision_path",
                    _txt(item.get("detail"), "--"),
                )
            )

        if vetoes:
            for index, item in enumerate(vetoes):
                if not isinstance(item, dict):
                    continue
                rows.append(
                    _item(
                        _txt(item.get("display_label") or item.get("trigger_type"), f"否决.{index + 1}"),
                        _txt(item.get("action"), "--"),
                        "vetoes",
                        f"id={_txt(item.get('id'), '--')}; trigger_type={_txt(item.get('trigger_type'), '--')}; priority={_txt(item.get('priority'), '--')}; reason={_txt(item.get('reason'), '--')}",
                    )
                )
        else:
            rows.append(_item("否决命中", "无", "vetoes", "本次未命中 veto，动作由规则与加权门控链路决定。"))
    else:
        tech_vote_sum = sum((_float(item.get("score"), 0.0) or 0.0) for item in tech_votes_raw if isinstance(item, dict))
        tech_vote_clamped = max(-1.0, min(1.0, tech_vote_sum))
        context_vote_sum = sum((_float(item.get("score"), 0.0) or 0.0) for item in context_votes_raw if isinstance(item, dict))
        context_vote_clamped = max(-1.0, min(1.0, context_vote_sum))

        rows = [
            _item("动作", decision.get("action"), "DualTrackResolver.resolve", "由技术信号、环境信号与规则命中共同决定最终 BUY/SELL/HOLD。"),
            _item("决策类型", decision.get("decisionType"), "DualTrackResolver.resolve", "根据共振/背离/否决路径设置，如 dual_track_resonance、dual_track_divergence、dual_track_hold。"),
            _item("技术信号", decision.get("techSignal"), "KernelStrategyRuntime._select_tech_action", "tech_score >= buy_threshold => BUY；<= sell_threshold => SELL；否则 HOLD。"),
            _item("环境信号", decision.get("contextSignal"), "KernelStrategyRuntime._select_context_signal", "context_score >= 0.3 => BUY；<= -0.3 => SELL；否则 HOLD。"),
            _item("技术分", decision.get("techScore"), "KernelStrategyRuntime._calculate_candidate_tech_votes / _calculate_position_tech_votes", f"技术投票分值求和后截断到 [-1,1]。当前投票和={tech_vote_sum:.4f}，截断后={tech_vote_clamped:.4f}。"),
            _item("环境分", decision.get("contextScore"), "MarketRegimeContextProvider.score_context", f"趋势+结构+动量+风险平衡+流动性+时段求和后截断到 [-1,1]；来源仅用于候选入池，不参与加分。当前组件和={context_vote_sum:.4f}，截断后={context_vote_clamped:.4f}。"),
            _item("置信度", decision.get("confidence"), "KernelStrategyRuntime._select_tech_confidence", "base_confidence + |tech_score|*tech_weight + max(context_score,0)*context_weight + 风格加成，之后夹在[min_confidence,max_confidence]。"),
            _item(
                "仓位建议(%)",
                decision.get("positionSizePct"),
                "DualTrackResolver._calculate_position_rule",
                "BUY 时表示目标买入仓位比例；SELL 时表示建议卖出比例（100% 即清仓可卖仓位）；HOLD 时通常为 0。由技术分与环境分命中共振/背离规则后得到。",
            ),
            _item(
                "建议保持仓位",
                _derive_keep_position_pct(decision.get("action"), decision.get("positionSizePct")),
                "DualTrackResolver._calculate_position_rule",
                "BUY 时等于目标买入仓位；SELL 时 = 100% - 建议卖出比例；HOLD 时表示维持当前仓位不变。",
            ),
            _item("规则命中", decision.get("ruleHit"), "DualTrackResolver._calculate_position_rule", "按 resonance_full/heavy/moderate/standard/divergence 等规则判定。"),
            _item("共振类型", decision.get("resonanceType"), "DualTrackResolver.resolve", "由仓位比例和背离状态映射 full/heavy/moderate/light 等类型。"),
            _item("市场", runtime_context.get("market"), "调度配置/回放任务", "实时模式取 scheduler.market；回放模式取 sim_runs.market。"),
            _item("分析粒度", runtime_context.get("timeframe"), "调度配置/回放任务/策略配置", "实时模式优先取策略分析粒度，其次 scheduler.analysis_timeframe；回放模式取 sim_runs.timeframe。"),
            _item("策略模式", runtime_context.get("strategyMode"), "调度配置/回放任务/策略配置", "实时模式优先取策略模式，其次 scheduler.strategy_mode；回放模式取 sim_runs.selected_strategy_mode。"),
        ]

    for key, value in effective_thresholds.items():
        threshold_key = _txt(key)
        if not threshold_key:
            continue
        rows.append(
            _item(
                f"阈值.{threshold_key}",
                value,
                "KernelStrategyRuntime._resolve_thresholds",
                "由风险风格参数与分析粒度参数融合得到 effective_thresholds。",
            )
        )

    metric_values = {
        _txt(item.get("name")): _parse_metric_float(item.get("value"))
        for item in technical_indicators
        if _txt(item.get("name"))
    }
    for indicator in technical_indicators:
        name = _txt(indicator.get("name"))
        if not name:
            continue
        source = _txt(indicator.get("source"), "行情快照")
        note = _txt(indicator.get("note"))
        rows.append(
            _item(
                f"指标.{name}",
                indicator.get("value"),
                source,
                _indicator_derivation(
                    name=name,
                    value=indicator.get("value"),
                    source=source,
                    note=note,
                    metric_values=metric_values,
                ),
            )
        )

    return rows
