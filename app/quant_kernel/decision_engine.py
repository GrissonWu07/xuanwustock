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
    "profit_tech_sell": 3,
    "hard_profit_trailing_stop": 3,
    "hard_constraint": 4,
    "context_veto": 9,
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
        *,
        market_snapshot: Mapping[str, Any] | None = None,
        strategy_profile_id: str | None = None,
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
            position_rule = self._calculate_position_rule(
                tech_score,
                ctx_score,
                market_snapshot=market_snapshot,
                strategy_profile_id=strategy_profile_id,
            )
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
                        "resonance_quality": self._resonance_quality_details(position_rule),
                    },
                )
            rule_hit = str(position_rule["rule_hit"])
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
                decision_type="dual_track_resonance" if rule_hit.startswith("resonance") else "dual_track_divergence",
                dual_track_details={
                    "tech_signal": tech_signal,
                    "context_signal": context_score.signal,
                    "resonance_type": self._resonance_type(position_ratio),
                    "rule_hit": rule_hit,
                    "resonance_quality": self._resonance_quality_details(position_rule),
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

    def _calculate_position_rule(
        self,
        tech_score: float,
        ctx_score: float,
        *,
        market_snapshot: Mapping[str, Any] | None = None,
        strategy_profile_id: str | None = None,
    ) -> dict[str, object]:
        cfg = self.config
        if tech_score >= cfg.resonance_full.tech_score_min and ctx_score >= float(cfg.resonance_full.context_score_min):
            return self._build_position_rule(
                cfg.resonance_full,
                "resonance_full",
                tech_score,
                ctx_score,
                market_snapshot=market_snapshot,
                strategy_profile_id=strategy_profile_id,
            )
        if tech_score >= cfg.resonance_heavy.tech_score_min and ctx_score >= float(cfg.resonance_heavy.context_score_min):
            return self._build_position_rule(
                cfg.resonance_heavy,
                "resonance_heavy",
                tech_score,
                ctx_score,
                market_snapshot=market_snapshot,
                strategy_profile_id=strategy_profile_id,
            )
        if tech_score >= cfg.resonance_moderate.tech_score_min and ctx_score >= float(cfg.resonance_moderate.context_score_min):
            return self._build_position_rule(
                cfg.resonance_moderate,
                "resonance_moderate",
                tech_score,
                ctx_score,
                market_snapshot=market_snapshot,
                strategy_profile_id=strategy_profile_id,
            )
        if tech_score >= cfg.resonance_standard.tech_score_min and ctx_score >= float(cfg.resonance_standard.context_score_min):
            return self._build_position_rule(
                cfg.resonance_standard,
                "resonance_standard",
                tech_score,
                ctx_score,
                market_snapshot=market_snapshot,
                strategy_profile_id=strategy_profile_id,
            )
        if (
            tech_score >= cfg.divergence_light.tech_score_min
            and float(cfg.divergence_light.context_score_min) <= ctx_score < float(cfg.divergence_light.context_score_max)
        ):
            return self._build_position_rule(
                cfg.divergence_light,
                "divergence_light",
                tech_score,
                ctx_score,
                market_snapshot=market_snapshot,
                strategy_profile_id=strategy_profile_id,
            )
        if ctx_score < float(cfg.divergence_none.context_score_max):
            return self._build_position_rule(
                cfg.divergence_none,
                "divergence_none",
                tech_score,
                ctx_score,
                market_snapshot=market_snapshot,
                strategy_profile_id=strategy_profile_id,
            )
        return {"position_ratio": 0.0, "rule_hit": "no_rule"}

    def _build_position_rule(
        self,
        rule: Any,
        rule_hit: str,
        tech_score: float,
        ctx_score: float,
        *,
        market_snapshot: Mapping[str, Any] | None,
        strategy_profile_id: str | None,
    ) -> dict[str, object]:
        policy = self._quality_policy(strategy_profile_id)
        quality = self._signal_quality_score(
            tech_score=tech_score,
            ctx_score=ctx_score,
            market_snapshot=market_snapshot,
            policy=policy,
        )
        ranges = policy.get("position_ranges") if isinstance(policy.get("position_ranges"), Mapping) else {}
        range_config = ranges.get(rule_hit) if isinstance(ranges.get(rule_hit), Mapping) else {}
        ratio_min = _to_float(range_config.get("min"), float(rule.position_ratio_min))
        ratio_max = _to_float(range_config.get("max"), float(rule.position_ratio_max))
        position_ratio = ratio_min + (ratio_max - ratio_min) * float(quality["score"])
        return {
            "position_ratio": round(position_ratio, 6),
            "rule_hit": rule_hit,
            "base_position_ratio_min": round(ratio_min, 6),
            "base_position_ratio_max": round(ratio_max, 6),
            "signal_quality_score": round(float(quality["score"]), 6),
            "quality_components": quality["components"],
            "quality_penalties": quality["penalties"],
        }

    def _quality_policy(self, profile_id: str | None) -> Mapping[str, Any]:
        key = str(profile_id or "stable").lower()
        if "aggressive" in key:
            return self.config.resonance_quality_policy["aggressive"]
        if "conservative" in key:
            return self.config.resonance_quality_policy["conservative"]
        return self.config.resonance_quality_policy["stable"]

    def _signal_quality_score(
        self,
        *,
        tech_score: float,
        ctx_score: float,
        market_snapshot: Mapping[str, Any] | None,
        policy: Mapping[str, Any],
    ) -> dict[str, Any]:
        snapshot = market_snapshot or {}
        weights = policy["weights"]
        volatility = policy["volatility"]
        price = _to_float(snapshot.get("current_price") or snapshot.get("latest_price") or snapshot.get("close"), 0.0)
        ma5 = _to_float(snapshot.get("ma5"), 0.0)
        ma10 = _to_float(snapshot.get("ma10"), 0.0)
        ma20 = _to_float(snapshot.get("ma20"), 0.0)
        ma20_slope = _to_float(snapshot.get("ma20_slope"), 0.0)
        macd = _to_float(snapshot.get("macd"), 0.0)
        rsi = _to_float(snapshot.get("rsi12") or snapshot.get("rsi"), 50.0)
        volume_ratio = _to_float(snapshot.get("volume_ratio"), 1.0)
        recent_5d_return = _to_float(snapshot.get("recent_5d_return"), 0.0)

        standard = self.config.resonance_standard
        strong_tech = self.config.resonance_full.tech_score_min
        strong_context = float(self.config.resonance_full.context_score_min or 0.0)
        standard_context = float(standard.context_score_min or 0.0)
        tech_edge = _clamp((tech_score - standard.tech_score_min) / max(strong_tech - standard.tech_score_min, 0.0001), 0.0, 1.0)
        context_edge = _clamp((ctx_score - standard_context) / max(strong_context - standard_context, 0.0001), 0.0, 1.0)
        confirmed_checkpoints = _quality_confirmed_checkpoint_count(snapshot)

        if price > ma20 > 0 and ma5 > ma10 > ma20 and ma20_slope > 0:
            trend_structure = 1.0
        elif confirmed_checkpoints >= 3 and ma20_slope >= 0:
            trend_structure = 0.5
        elif price > ma20 > 0:
            trend_structure = 0.3
        else:
            trend_structure = 0.0

        confirmation = _quality_confirmation_score(snapshot)
        volume_score = 1.0 if volume_ratio >= 1.6 else 0.6 if volume_ratio >= 1.2 else 0.0

        if rsi < 75:
            heat_penalty = 0.0
        elif rsi < 85:
            heat_penalty = 0.05 + (rsi - 75.0) / 10.0 * 0.15
        elif rsi < 88:
            heat_penalty = 0.25
        else:
            heat_penalty = 0.35
        if trend_structure >= 1.0:
            relief_multiplier = _to_float(volatility.get("hot_rsi_trend_relief_multiplier"), 0.6)
            heat_penalty = max(heat_penalty * relief_multiplier, heat_penalty * 0.4)

        weak_structure_penalty = 0.0
        if ma20_slope < 0:
            weak_structure_penalty += 0.20
        if ma5 > 0 and ma10 > 0 and ma5 < ma10:
            weak_structure_penalty += 0.10
        if macd > 0 and confirmation < 1.0:
            weak_structure_penalty += 0.10

        volatility_penalty = 0.0
        if ma20 > 0 and abs(price - ma20) / ma20 > _to_float(volatility["ma20_deviation_penalty_threshold"]):
            volatility_penalty += _to_float(volatility["ma20_deviation_penalty"])
        if recent_5d_return > _to_float(volatility["recent_return_penalty_threshold"]):
            volatility_penalty += _to_float(volatility["recent_return_penalty"])
        volatility_penalty = _clamp(volatility_penalty, 0.0, _to_float(volatility["max_volatility_penalty"]))

        raw_score = (
            tech_edge * _to_float(weights["tech_edge"])
            + context_edge * _to_float(weights["context_edge"])
            + trend_structure * _to_float(weights["trend_structure"])
            + confirmation * _to_float(weights["confirmation"])
            + volume_score * _to_float(weights["volume"])
            - heat_penalty
            - weak_structure_penalty
            - volatility_penalty
        )
        return {
            "score": _clamp(raw_score, 0.0, 1.0),
            "components": {
                "tech_edge_score": round(tech_edge, 6),
                "context_edge_score": round(context_edge, 6),
                "trend_structure_score": round(trend_structure, 6),
                "confirmation_score": round(confirmation, 6),
                "volume_score": round(volume_score, 6),
            },
            "penalties": {
                "heat_penalty": round(heat_penalty, 6),
                "weak_structure_penalty": round(weak_structure_penalty, 6),
                "volatility_penalty": round(volatility_penalty, 6),
                "recent_return_missing": "recent_5d_return" not in snapshot,
            },
        }

    @staticmethod
    def _resonance_quality_details(position_rule: Mapping[str, object]) -> dict[str, object]:
        return {
            "rule_hit": str(position_rule.get("rule_hit") or ""),
            "base_position_ratio_min": position_rule.get("base_position_ratio_min", 0.0),
            "base_position_ratio_max": position_rule.get("base_position_ratio_max", 0.0),
            "signal_quality_score": position_rule.get("signal_quality_score", 0.0),
            "quality_adjusted_position_ratio": position_rule.get("position_ratio", 0.0),
            "quality_components": position_rule.get("quality_components") or {},
            "quality_penalties": position_rule.get("quality_penalties") or {},
        }

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


def _quality_confirmation_score(snapshot: Mapping[str, Any]) -> float:
    required = max(_to_float(snapshot.get("required_confirm_checkpoints"), 3.0), 1.0)
    explicit_count = _to_float(snapshot.get("trend_confirmed_checkpoints"), 0.0)
    explicit_score = _clamp(explicit_count / required, 0.0, 1.0)
    recent_score = _recent_checkpoint_confirmation_score(snapshot, required)
    return max(explicit_score, recent_score)


def _quality_confirmed_checkpoint_count(snapshot: Mapping[str, Any]) -> int:
    return max(int(_to_float(snapshot.get("trend_confirmed_checkpoints"), 0.0)), _recent_above_ma20_count(snapshot))


def _recent_checkpoint_confirmation_score(snapshot: Mapping[str, Any], required: float) -> float:
    above = _recent_above_ma20_count(snapshot)
    if above <= 0:
        recent = snapshot.get("recent_checkpoints")
        if isinstance(recent, list) and _recent_retest_confirmed(snapshot, recent):
            return 0.75
        return 0.0
    recent = snapshot.get("recent_checkpoints")
    score = _clamp(above / required, 0.0, 1.0)
    return max(score, 0.75) if isinstance(recent, list) and _recent_retest_confirmed(snapshot, recent) else score


def _recent_above_ma20_count(snapshot: Mapping[str, Any]) -> int:
    recent = snapshot.get("recent_checkpoints")
    if not isinstance(recent, list) or not recent:
        return 0
    above = 0
    for raw_item in reversed(recent):
        item = raw_item if isinstance(raw_item, Mapping) else {}
        close = _to_float(item.get("close"), 0.0)
        ma20 = _to_float(item.get("ma20"), 0.0)
        if close <= 0 or ma20 <= 0 or close <= ma20:
            break
        above += 1
    return above


def _recent_retest_confirmed(snapshot: Mapping[str, Any], recent: list[Any]) -> bool:
    price = _to_float(snapshot.get("current_price") or snapshot.get("latest_price") or snapshot.get("close"), 0.0)
    ma10 = _to_float(snapshot.get("ma10"), 0.0)
    ma20 = _to_float(snapshot.get("ma20"), 0.0)
    if price <= 0 or ma10 <= 0 or ma20 <= 0 or price <= ma20 or price <= ma10:
        return False
    tolerance = 1.0 - _to_float(snapshot.get("retest_tolerance_pct"), 1.5) / 100.0
    window = [item if isinstance(item, Mapping) else {} for item in recent[-5:]]
    broke_above = any(_to_float(item.get("close"), 0.0) > _to_float(item.get("ma20"), float("inf")) for item in window)
    retested = any(
        _to_float(item.get("low"), 0.0) > 0
        and _to_float(item.get("ma20"), 0.0) > 0
        and _to_float(item.get("low"), 0.0) >= _to_float(item.get("ma20"), 0.0) * tolerance
        for item in window
    )
    return bool(broke_above and retested)


def resolve_final_action(
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
