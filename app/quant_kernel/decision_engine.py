"""Vendored dual-track decision resolver adapted from stockpolicy core logic."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .config import DualTrackConfig
from .models import ContextualScore, Decision

VETO_PRIORITY: dict[str, int] = {
    "forced_risk": 1,
    "risk_stop": 2,
    "stop_loss": 2,
    "hard_stop_loss": 3,
    "hard_constraint": 4,
    "context_veto": 9,
}


class DualTrackResolver:
    """Resolve technical timing plus contextual probability into a final decision."""

    def __init__(self, config: DualTrackConfig):
        self.config = config

    def resolve(
        self,
        tech_decision: Decision,
        context_score: ContextualScore,
        stock_code: str,
        current_time: datetime,
    ) -> Decision:
        tech_signal = tech_decision.action
        tech_score = tech_decision.tech_score
        ctx_score = context_score.score

        if ctx_score < self.config.veto_threshold:
            return Decision(
                code=stock_code,
                action="HOLD",
                confidence=0.8,
                price=tech_decision.price,
                timestamp=current_time,
                reason=(
                    f"🚫 环境否决：ContextScore={ctx_score:+.2f} < {self.config.veto_threshold}，"
                    "外部环境极度不利，拦截买入信号"
                ),
                agent_votes=tech_decision.agent_votes,
                tech_score=tech_score,
                context_score=ctx_score,
                position_ratio=0.0,
                decision_type="context_veto",
                dual_track_details={
                    "tech_signal": tech_signal,
                    "context_signal": context_score.signal,
                    "resonance_type": "veto",
                    "rule_hit": "context_veto",
                },
            )

        if tech_signal == "BUY":
            position_rule = self._calculate_position_rule(tech_score, ctx_score)
            position_ratio = float(position_rule["position_ratio"])
            if position_ratio < 0.3:
                return Decision(
                    code=stock_code,
                    action="HOLD",
                    confidence=tech_decision.confidence * 0.5,
                    price=tech_decision.price,
                    timestamp=current_time,
                    reason=f"⚠️ 背离观望: TechScore={tech_score:.2f}, ContextScore={ctx_score:+.2f}，环境不佳，暂不入场",
                    agent_votes=tech_decision.agent_votes,
                    tech_score=tech_score,
                    context_score=ctx_score,
                    position_ratio=0.0,
                    decision_type="dual_track_divergence",
                    dual_track_details={
                        "tech_signal": tech_signal,
                        "context_signal": context_score.signal,
                        "resonance_type": "divergence_block",
                        "rule_hit": str(position_rule["rule_hit"]),
                    },
                )
            return Decision(
                code=stock_code,
                action="BUY",
                confidence=tech_decision.confidence,
                price=tech_decision.price,
                timestamp=current_time,
                reason=(
                    f"{self._decision_emoji(position_ratio)} {self._decision_desc(position_ratio)} | "
                    f"技术面: {tech_decision.reason} | 环境面: {context_score.reason} | 仓位比例: {position_ratio:.0%}"
                ),
                agent_votes=tech_decision.agent_votes,
                tech_score=tech_score,
                context_score=ctx_score,
                position_ratio=position_ratio,
                decision_type="dual_track_resonance" if position_ratio >= 0.5 else "dual_track_divergence",
                dual_track_details={
                    "tech_signal": tech_signal,
                    "context_signal": context_score.signal,
                    "resonance_type": self._resonance_type(position_ratio),
                    "rule_hit": str(position_rule["rule_hit"]),
                },
            )

        if tech_signal == "SELL":
            if ctx_score > self.config.extreme_bullish_threshold:
                return Decision(
                    code=stock_code,
                    action="HOLD",
                    confidence=tech_decision.confidence * 0.5,
                    price=tech_decision.price,
                    timestamp=current_time,
                    reason=f"🤔 背离观望: 技术面SELL但环境极佳 (ContextScore={ctx_score:+.2f})，暂缓卖出",
                    agent_votes=tech_decision.agent_votes,
                    tech_score=tech_score,
                    context_score=ctx_score,
                    position_ratio=0.0,
                    decision_type="dual_track_divergence",
                    dual_track_details={
                        "tech_signal": tech_signal,
                        "context_signal": context_score.signal,
                        "resonance_type": "sell_divergence_block",
                        "rule_hit": "sell_divergence_block",
                    },
                )
            return Decision(
                code=stock_code,
                action="SELL",
                confidence=tech_decision.confidence,
                price=tech_decision.price,
                timestamp=current_time,
                reason=f"{tech_decision.reason} | ContextScore={ctx_score:+.2f}",
                agent_votes=tech_decision.agent_votes,
                tech_score=tech_score,
                context_score=ctx_score,
                position_ratio=1.0,
                decision_type="dual_track_resonance" if ctx_score < -0.3 else "dual_track_divergence",
                dual_track_details={
                    "tech_signal": tech_signal,
                    "context_signal": context_score.signal,
                    "resonance_type": "sell_resonance" if ctx_score < -0.3 else "sell_divergence",
                    "rule_hit": "sell_resonance" if ctx_score < -0.3 else "sell_divergence",
                },
            )

        return Decision(
            code=stock_code,
            action="HOLD",
            confidence=tech_decision.confidence,
            price=tech_decision.price,
            timestamp=current_time,
            reason=f"{tech_decision.reason} | ContextScore={ctx_score:+.2f}",
            agent_votes=tech_decision.agent_votes,
            tech_score=tech_score,
            context_score=ctx_score,
            position_ratio=0.0,
            decision_type="dual_track_hold",
            dual_track_details={
                "tech_signal": tech_signal,
                "context_signal": context_score.signal,
                "resonance_type": "neutral",
                "rule_hit": "neutral_hold",
            },
        )

    def _calculate_position_rule(self, tech_score: float, ctx_score: float) -> dict[str, object]:
        cfg = self.config
        if tech_score >= cfg.resonance_full.tech_score_min and ctx_score >= float(cfg.resonance_full.context_score_min):
            return {"position_ratio": cfg.resonance_full.position_ratio, "rule_hit": "resonance_full"}
        if tech_score >= cfg.resonance_heavy.tech_score_min and ctx_score >= float(cfg.resonance_heavy.context_score_min):
            return {"position_ratio": cfg.resonance_heavy.position_ratio, "rule_hit": "resonance_heavy"}
        if tech_score >= cfg.resonance_moderate.tech_score_min and ctx_score >= float(cfg.resonance_moderate.context_score_min):
            return {"position_ratio": cfg.resonance_moderate.position_ratio, "rule_hit": "resonance_moderate"}
        if tech_score >= cfg.resonance_standard.tech_score_min and ctx_score >= float(cfg.resonance_standard.context_score_min):
            return {"position_ratio": cfg.resonance_standard.position_ratio, "rule_hit": "resonance_standard"}
        if (
            tech_score >= cfg.divergence_light.tech_score_min
            and float(cfg.divergence_light.context_score_min) <= ctx_score < float(cfg.divergence_light.context_score_max)
        ):
            return {"position_ratio": cfg.divergence_light.position_ratio, "rule_hit": "divergence_light"}
        if ctx_score < float(cfg.divergence_none.context_score_max):
            return {"position_ratio": cfg.divergence_none.position_ratio, "rule_hit": "divergence_none"}
        return {"position_ratio": 0.0, "rule_hit": "no_rule"}

    @staticmethod
    def _decision_emoji(position_ratio: float) -> str:
        if position_ratio >= 0.8:
            return "🚀"
        if position_ratio >= 0.5:
            return "✅"
        if position_ratio >= 0.3:
            return "⚠️"
        return "🚫"

    @staticmethod
    def _decision_desc(position_ratio: float) -> str:
        if position_ratio >= 1.0:
            return "共振满仓"
        if position_ratio >= 0.8:
            return "共振重仓"
        if position_ratio >= 0.5:
            return "共振加仓"
        if position_ratio >= 0.3:
            return "背离试探"
        return "观望"

    @staticmethod
    def _resonance_type(position_ratio: float) -> str:
        if position_ratio >= 1.0:
            return "full_resonance"
        if position_ratio >= 0.8:
            return "heavy_resonance"
        if position_ratio >= 0.5:
            return "moderate_resonance"
        if position_ratio >= 0.3:
            return "light_divergence"
        return "no_position"


def resolve_v23_final_action(
    *,
    mode: str,
    core_rule_action: str,
    weighted_action_raw: str,
    fusion_score: float,
    sell_precedence_gate: float,
    vetoes: list[Mapping[str, Any]] | None = None,
    legacy_rule_action: str | None = None,
) -> dict[str, Any]:
    normalized_mode = str(mode or "rule_only")
    normalized_core = str(core_rule_action or "HOLD")
    normalized_weighted = str(weighted_action_raw or "HOLD")
    selected_veto = _highest_priority_veto(vetoes or [])
    decision_path: list[dict[str, str]] = []

    if selected_veto is not None:
        veto_action = str(selected_veto.get("action") or "HOLD")
        veto_id = str(selected_veto.get("id") or "")
        veto_trigger_type = str(selected_veto.get("trigger_type") or veto_id or "veto")
        veto_label = str(selected_veto.get("display_label") or veto_trigger_type)
        veto_reason = str(selected_veto.get("reason") or "")
        decision_path.append(
            {
                "step": "veto_first",
                "matched": "true",
                "detail": f"{veto_label}({veto_id}) => {veto_action}",
            }
        )
        return {
            "final_action": veto_action,
            "veto_action": veto_action,
            "veto_id": veto_id,
            "veto_trigger_type": veto_trigger_type,
            "veto_display_label": veto_label,
            "veto_reason": veto_reason,
            "decision_path": decision_path,
            "matched_branch": "veto_first",
        }

    decision_path.append({"step": "veto_first", "matched": "false", "detail": "no_veto"})
    if normalized_mode == "rule_only":
        final = str(legacy_rule_action or normalized_core)
        decision_path.append({"step": "mode", "matched": "rule_only", "detail": f"legacy_or_core={final}"})
        return {
            "final_action": final,
            "veto_action": None,
            "decision_path": decision_path,
            "matched_branch": "rule_only",
        }
    if normalized_mode == "weighted_only":
        decision_path.append({"step": "mode", "matched": "weighted_only", "detail": f"weighted={normalized_weighted}"})
        return {
            "final_action": normalized_weighted,
            "veto_action": None,
            "decision_path": decision_path,
            "matched_branch": "weighted_only",
        }
    if normalized_mode != "hybrid":
        raise ValueError(f"unsupported mode: {normalized_mode}")

    decision_path.append({"step": "mode", "matched": "hybrid", "detail": "hybrid_matrix"})
    if normalized_weighted == "SELL":
        if float(fusion_score) <= float(sell_precedence_gate):
            decision_path.append(
                {
                    "step": "hybrid",
                    "matched": "weighted_sell_precedence",
                    "detail": f"fusion_score={fusion_score:.6f} <= gate={sell_precedence_gate:.6f}",
                }
            )
            return {
                "final_action": "SELL",
                "veto_action": None,
                "decision_path": decision_path,
                "matched_branch": "hybrid_weighted_sell_precedence",
            }
        decision_path.append(
            {
                "step": "hybrid",
                "matched": "weighted_sell_blocked",
                "detail": f"fusion_score={fusion_score:.6f} > gate={sell_precedence_gate:.6f}",
            }
        )
        return {
            "final_action": "HOLD",
            "veto_action": None,
            "decision_path": decision_path,
            "matched_branch": "hybrid_weighted_sell_blocked",
        }
    if normalized_core == normalized_weighted:
        decision_path.append({"step": "hybrid", "matched": "aligned", "detail": normalized_core})
        return {
            "final_action": normalized_core,
            "veto_action": None,
            "decision_path": decision_path,
            "matched_branch": "hybrid_aligned",
        }
    if normalized_core == "SELL" and normalized_weighted == "HOLD":
        decision_path.append(
            {
                "step": "hybrid",
                "matched": "core_sell_blocked",
                "detail": "core_rule_action=SELL is audit-only without risk veto; use weighted_action=HOLD",
            }
        )
        return {
            "final_action": "HOLD",
            "veto_action": None,
            "decision_path": decision_path,
            "matched_branch": "hybrid_core_sell_blocked",
        }
    if normalized_core == "SELL" and normalized_weighted == "BUY":
        decision_path.append(
            {
                "step": "hybrid",
                "matched": "core_sell_ignored_weighted_buy",
                "detail": "core_rule_action=SELL is audit-only without risk veto; use weighted_action=BUY",
            }
        )
        return {
            "final_action": "BUY",
            "veto_action": None,
            "decision_path": decision_path,
            "matched_branch": "hybrid_core_sell_ignored_weighted_buy",
        }
    if normalized_core == "BUY" and normalized_weighted == "HOLD":
        decision_path.append({"step": "hybrid", "matched": "core_buy_weighted_hold", "detail": "downgrade_to_hold"})
        return {
            "final_action": "HOLD",
            "veto_action": None,
            "decision_path": decision_path,
            "matched_branch": "hybrid_core_buy_weighted_hold",
        }
    if normalized_core == "HOLD" and normalized_weighted == "BUY":
        decision_path.append({"step": "hybrid", "matched": "core_hold_weighted_buy", "detail": "upgrade_to_buy"})
        return {
            "final_action": "BUY",
            "veto_action": None,
            "decision_path": decision_path,
            "matched_branch": "hybrid_core_hold_weighted_buy",
        }
    decision_path.append({"step": "hybrid", "matched": "fallback", "detail": "hold"})
    return {
        "final_action": "HOLD",
        "veto_action": None,
        "decision_path": decision_path,
        "matched_branch": "hybrid_fallback_hold",
    }


def _highest_priority_veto(vetoes: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    if not vetoes:
        return None
    ordered = sorted(
        vetoes,
        key=lambda item: (
            int(item.get("priority")) if item.get("priority") is not None else VETO_PRIORITY.get(str(item.get("id") or ""), 999),
            str(item.get("id") or ""),
        ),
    )
    return ordered[0]
