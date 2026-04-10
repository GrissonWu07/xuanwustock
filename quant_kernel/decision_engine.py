"""Vendored dual-track decision resolver adapted from stockpolicy core logic."""

from __future__ import annotations

from datetime import datetime

from .config import DualTrackConfig
from .models import ContextualScore, Decision


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
