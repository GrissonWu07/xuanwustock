"""Reusable strategy runtime that evaluates snapshots into stockpolicy-style decisions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .config import QuantKernelConfig
from .decision_engine import DualTrackResolver
from .interfaces import ContextProvider
from .models import ContextualScore, Decision


class MarketRegimeContextProvider:
    """Build a time-varying contextual score from source priors and market conditions."""

    def __init__(self, config: QuantKernelConfig):
        self.config = config

    def score_context(
        self,
        *,
        sources: list[str],
        market_snapshot: dict[str, Any] | None,
        current_time: datetime,
        candidate: dict[str, Any] | None = None,
        position: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del candidate, position

        source_prior = self._calculate_source_prior(sources)
        components = {
            "source_prior": {
                "score": round(source_prior, 4),
                "reason": f"来源策略先验 {', '.join(sources) if sources else 'default'}",
            }
        }
        if not market_snapshot:
            return {
                "score": round(source_prior, 4),
                "confidence": 0.45,
                "components": components,
                "reason": f"仅基于来源先验给出上下文评分 {source_prior:.2f}，等待更多环境数据。",
            }

        current_price = float(market_snapshot.get("current_price") or market_snapshot.get("latest_price") or 0)
        ma20 = float(market_snapshot.get("ma20") or 0)
        ma60 = float(market_snapshot.get("ma60") or 0)
        macd = float(market_snapshot.get("macd") or 0)
        rsi12 = float(market_snapshot.get("rsi12") or 50)
        volume_ratio = float(market_snapshot.get("volume_ratio") or 1)
        trend = str(market_snapshot.get("trend") or "sideways").lower()

        trend_component = 0.16 if trend == "up" else (-0.16 if trend == "down" else 0.0)
        if current_price > ma20 > ma60 > 0:
            structure_component = 0.14
        elif current_price > ma20 > 0:
            structure_component = 0.08
        elif current_price < ma20 < ma60 and ma60 > 0:
            structure_component = -0.14
        elif current_price < ma20 and ma20 > 0:
            structure_component = -0.08
        else:
            structure_component = 0.0

        momentum_component = max(-0.12, min(0.12, macd * 0.18))
        if 48 <= rsi12 <= 68:
            risk_component = 0.04
        elif rsi12 >= 78:
            risk_component = -0.08
        elif rsi12 <= 28:
            risk_component = -0.05
        else:
            risk_component = 0.0

        if volume_ratio >= 1.8:
            liquidity_component = 0.09
        elif volume_ratio >= 1.2:
            liquidity_component = 0.05
        elif volume_ratio <= 0.7:
            liquidity_component = -0.08
        elif volume_ratio <= 0.9:
            liquidity_component = -0.04
        else:
            liquidity_component = 0.0

        current_clock = current_time.time()
        if current_clock >= datetime.strptime("14:30", "%H:%M").time():
            session_component = 0.03 if trend_component + momentum_component >= 0 else -0.03
        elif current_clock <= datetime.strptime("10:00", "%H:%M").time():
            session_component = -0.02 if volume_ratio < 1 else 0.02
        else:
            session_component = 0.0

        components.update(
            {
                "trend_regime": {
                    "score": round(trend_component, 4),
                    "reason": f"趋势状态 {trend}",
                },
                "price_structure": {
                    "score": round(structure_component, 4),
                    "reason": f"价格结构 P/MA20/MA60={current_price:.2f}/{ma20:.2f}/{ma60:.2f}",
                },
                "momentum": {
                    "score": round(momentum_component, 4),
                    "reason": f"MACD {macd:.3f}",
                },
                "risk_balance": {
                    "score": round(risk_component, 4),
                    "reason": f"RSI12 {rsi12:.2f}",
                },
                "liquidity": {
                    "score": round(liquidity_component, 4),
                    "reason": f"量比 {volume_ratio:.2f}",
                },
                "session": {
                    "score": round(session_component, 4),
                    "reason": f"时间窗口 {current_clock.strftime('%H:%M')}",
                },
            }
        )

        final_score = max(
            -1.0,
            min(
                1.0,
                source_prior
                + trend_component
                + structure_component
                + momentum_component
                + risk_component
                + liquidity_component
                + session_component,
            ),
        )
        confidence = max(
            0.45,
            min(
                0.92,
                0.56
                + abs(trend_component + structure_component + momentum_component + session_component) * 0.45
                + abs(liquidity_component) * 0.2,
            ),
        )
        return {
            "score": round(final_score, 4),
            "confidence": round(confidence, 4),
            "components": components,
            "reason": (
                f"来源先验 {source_prior:.2f}，趋势 {trend_component:+.2f}，结构 {structure_component:+.2f}，"
                f"动量 {momentum_component:+.2f}，流动性 {liquidity_component:+.2f}，时段 {session_component:+.2f}。"
            ),
        }

    def _calculate_source_prior(self, sources: list[str]) -> float:
        config = self.config.source_context
        weights = [
            float(config.source_weights.get(source, config.default_weight))
            for source in sources
            if source
        ]
        if not weights:
            return float(config.default_weight)
        return round(sum(weights) / len(weights), 4)


class KernelStrategyRuntime:
    """Kernel-owned candidate/position evaluator using provider-fed snapshots."""

    def __init__(
        self,
        config: QuantKernelConfig | None = None,
        context_provider: ContextProvider | None = None,
    ):
        self.config = config or QuantKernelConfig.default()
        self.decision_engine = DualTrackResolver(self.config.dual_track)
        self.context_provider = context_provider or MarketRegimeContextProvider(self.config)

    def evaluate_candidate(
        self,
        *,
        candidate: dict[str, Any],
        market_snapshot: dict[str, Any] | None,
        current_time: datetime,
        analysis_timeframe: str = "1d",
        strategy_mode: str = "auto",
    ) -> Decision:
        stock_code = str(candidate["stock_code"])
        sources = candidate.get("sources") or [candidate.get("source", "manual")]
        contextual_score = self._build_contextual_score(
            sources=sources,
            market_snapshot=market_snapshot,
            current_time=current_time,
            candidate=candidate,
        )
        strategy_profile = self._build_strategy_profile(
            candidate=candidate,
            market_snapshot=market_snapshot,
            current_time=current_time,
            analysis_timeframe=analysis_timeframe,
            strategy_mode=strategy_mode,
        )

        if not market_snapshot:
            return self._resolve_dual_track_decision(
                stock_code=stock_code,
                price=float(candidate.get("latest_price") or 0),
                tech_score=0.0,
                tech_votes=[],
                contextual_score=contextual_score,
                reason="暂未取得完整行情与技术指标，保持观察。",
                current_time=current_time,
                strategy_profile=strategy_profile,
            )

        current_price = float(market_snapshot.get("current_price") or candidate.get("latest_price") or 0)
        ma5 = float(market_snapshot.get("ma5") or 0)
        ma20 = float(market_snapshot.get("ma20") or 0)
        ma60 = float(market_snapshot.get("ma60") or 0)
        macd = float(market_snapshot.get("macd") or 0)
        rsi12 = float(market_snapshot.get("rsi12") or 50)
        volume_ratio = float(market_snapshot.get("volume_ratio") or 1)
        trend = str(market_snapshot.get("trend") or "sideways")

        tech_score, tech_votes = self._calculate_candidate_tech_votes(
            current_price=current_price,
            ma5=ma5,
            ma20=ma20,
            ma60=ma60,
            macd=macd,
            rsi12=rsi12,
            volume_ratio=volume_ratio,
            trend=trend,
        )
        reason = self._build_candidate_reasoning(
            candidate=candidate,
            current_price=current_price,
            ma5=ma5,
            ma20=ma20,
            ma60=ma60,
            macd=macd,
            rsi12=rsi12,
            volume_ratio=volume_ratio,
            tech_score=tech_score,
            context_score=contextual_score.score,
        )
        return self._resolve_dual_track_decision(
            stock_code=stock_code,
            price=current_price,
            tech_score=tech_score,
            tech_votes=tech_votes,
            contextual_score=contextual_score,
            reason=reason,
            current_time=current_time,
            strategy_profile=strategy_profile,
        )

    def evaluate_position(
        self,
        *,
        candidate: dict[str, Any],
        position: dict[str, Any],
        market_snapshot: dict[str, Any] | None,
        current_time: datetime,
        analysis_timeframe: str = "1d",
        strategy_mode: str = "auto",
    ) -> Decision:
        stock_code = str(position["stock_code"])
        sources = candidate.get("sources") or [candidate.get("source", "manual")]
        contextual_score = self._build_contextual_score(
            sources=sources,
            market_snapshot=market_snapshot,
            current_time=current_time,
            candidate=candidate,
            position=position,
        )
        strategy_profile = self._build_strategy_profile(
            candidate=candidate,
            market_snapshot=market_snapshot,
            current_time=current_time,
            analysis_timeframe=analysis_timeframe,
            strategy_mode=strategy_mode,
        )

        if not market_snapshot:
            return self._resolve_dual_track_decision(
                stock_code=stock_code,
                price=float(position.get("latest_price") or position.get("avg_price") or 0),
                tech_score=0.0,
                tech_votes=[],
                contextual_score=contextual_score,
                reason="持仓跟踪未取得完整行情，继续观察。",
                current_time=current_time,
                strategy_profile=strategy_profile,
            )

        current_price = float(
            market_snapshot.get("current_price") or position.get("latest_price") or position.get("avg_price") or 0
        )
        ma20 = float(market_snapshot.get("ma20") or 0)
        macd = float(market_snapshot.get("macd") or 0)
        rsi12 = float(market_snapshot.get("rsi12") or 50)
        avg_price = float(position.get("avg_price") or 0)
        pnl_pct = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0

        tech_score, tech_votes = self._calculate_position_tech_votes(
            current_price=current_price,
            ma20=ma20,
            macd=macd,
            rsi12=rsi12,
            pnl_pct=pnl_pct,
        )
        reason = (
            f"{position['stock_code']} 持仓跟踪：现价 {current_price:.2f}，成本 {avg_price:.2f}，"
            f"浮盈亏 {pnl_pct:.2f}% ，MA20 {ma20:.2f}，MACD {macd:.3f}，RSI12 {rsi12:.2f}。"
        )
        return self._resolve_dual_track_decision(
            stock_code=stock_code,
            price=current_price,
            tech_score=tech_score,
            tech_votes=tech_votes,
            contextual_score=contextual_score,
            reason=reason,
            current_time=current_time,
            strategy_profile=strategy_profile,
        )

    def _resolve_dual_track_decision(
        self,
        *,
        stock_code: str,
        price: float,
        tech_score: float,
        tech_votes: list[dict[str, Any]],
        contextual_score: ContextualScore,
        reason: str,
        current_time: datetime,
        strategy_profile: dict[str, Any],
    ) -> Decision:
        thresholds = strategy_profile["effective_thresholds"]
        tech_decision = Decision(
            code=stock_code,
            action=self._select_tech_action(tech_score, thresholds),
            confidence=self._select_tech_confidence(tech_score, contextual_score.score, strategy_profile),
            price=price,
            timestamp=current_time,
            reason=reason,
            agent_votes={"tech_votes": tech_votes},
            tech_score=round(tech_score, 4),
            context_score=round(contextual_score.score, 4),
        )
        resolved = self.decision_engine.resolve(
            tech_decision=tech_decision,
            context_score=contextual_score,
            stock_code=stock_code,
            current_time=current_time,
        )
        resolved.strategy_profile = self._attach_explainability(
            strategy_profile=strategy_profile,
            tech_votes=tech_votes,
            contextual_score=contextual_score,
            resolved=resolved,
        )
        if resolved.action == "BUY":
            max_ratio = float(thresholds.get("max_position_ratio") or 0.0)
            resolved.position_ratio = round(
                min(resolved.position_ratio or max_ratio, max_ratio),
                4,
            )
        return resolved

    def _build_contextual_score(
        self,
        *,
        sources: list[str],
        market_snapshot: dict[str, Any] | None,
        current_time: datetime,
        candidate: dict[str, Any] | None = None,
        position: dict[str, Any] | None = None,
    ) -> ContextualScore:
        payload = self.context_provider.score_context(
            sources=sources,
            market_snapshot=market_snapshot,
            current_time=current_time,
            candidate=candidate,
            position=position,
        )
        score = float(payload.get("score") or 0)
        confidence = float(payload.get("confidence") or max(0.3, min(0.95, 0.55 + abs(score) * 0.35)))
        components = payload.get("components") or {}
        reason = str(payload.get("reason") or f"上下文评分 {score:.2f}")
        return ContextualScore(
            score=round(score, 4),
            signal=self._select_context_signal(score),
            confidence=round(confidence, 4),
            components=components,
            reason=reason,
        )

    def _attach_explainability(
        self,
        *,
        strategy_profile: dict[str, Any],
        tech_votes: list[dict[str, Any]],
        contextual_score: ContextualScore,
        resolved: Decision,
    ) -> dict[str, Any]:
        profile = dict(strategy_profile)
        profile["explainability"] = {
            "tech_votes": tech_votes,
            "context_votes": self._build_context_votes(contextual_score),
            "dual_track": {
                "tech_signal": str((resolved.dual_track_details or {}).get("tech_signal") or resolved.action),
                "context_signal": str((resolved.dual_track_details or {}).get("context_signal") or contextual_score.signal),
                "resonance_type": str((resolved.dual_track_details or {}).get("resonance_type") or resolved.decision_type),
                "rule_hit": str((resolved.dual_track_details or {}).get("rule_hit") or resolved.decision_type),
                "position_ratio": round(float(resolved.position_ratio or 0.0), 4),
                "decision_type": resolved.decision_type,
                "final_action": resolved.action,
                "final_reason": resolved.reason,
            },
        }
        return profile

    def _build_context_votes(self, contextual_score: ContextualScore) -> list[dict[str, Any]]:
        votes: list[dict[str, Any]] = []
        for component, payload in (contextual_score.components or {}).items():
            votes.append(
                {
                    "component": component,
                    "score": round(float(payload.get("score") or 0.0), 4),
                    "reason": str(payload.get("reason") or ""),
                }
            )
        return votes

    @staticmethod
    def _vote(factor: str, signal: str, score: float, reason: str) -> dict[str, Any]:
        return {
            "factor": factor,
            "signal": signal,
            "score": round(float(score), 4),
            "reason": reason,
        }

    def _calculate_candidate_tech_votes(
        self,
        *,
        current_price: float,
        ma5: float,
        ma20: float,
        ma60: float,
        macd: float,
        rsi12: float,
        volume_ratio: float,
        trend: str,
    ) -> tuple[float, list[dict[str, Any]]]:
        cfg = self.config.technical
        votes: list[dict[str, Any]] = []

        if trend == "up":
            votes.append(self._vote("趋势", "BUY", cfg.trend_up_bonus, f"趋势状态 {trend}"))
        elif trend == "down":
            votes.append(self._vote("趋势", "SELL", -cfg.trend_down_penalty, f"趋势状态 {trend}"))
        else:
            votes.append(self._vote("趋势", "HOLD", 0.0, f"趋势状态 {trend}"))

        if current_price > ma5 > ma20 > ma60 > 0:
            votes.append(self._vote("均线结构", "BUY", cfg.alignment_bonus, f"多头排列 {current_price:.2f}>{ma5:.2f}>{ma20:.2f}>{ma60:.2f}"))
        elif current_price < ma5 < ma20 < ma60 and ma60 > 0:
            votes.append(self._vote("均线结构", "SELL", -cfg.misalignment_penalty, f"空头排列 {current_price:.2f}<{ma5:.2f}<{ma20:.2f}<{ma60:.2f}"))
        else:
            votes.append(self._vote("均线结构", "HOLD", 0.0, f"均线结构中性 {current_price:.2f}/{ma5:.2f}/{ma20:.2f}/{ma60:.2f}"))

        if macd > 0:
            votes.append(self._vote("MACD", "BUY", cfg.macd_positive_bonus, f"MACD {macd:.3f} 为正"))
        elif macd < 0:
            votes.append(self._vote("MACD", "SELL", -cfg.macd_negative_penalty, f"MACD {macd:.3f} 为负"))
        else:
            votes.append(self._vote("MACD", "HOLD", 0.0, "MACD 中性"))

        if cfg.balanced_rsi_min <= rsi12 <= cfg.balanced_rsi_max:
            votes.append(self._vote("RSI", "BUY", cfg.balanced_rsi_bonus, f"RSI12 {rsi12:.2f} 处于健康区间"))
        elif rsi12 >= cfg.overbought_rsi_threshold:
            votes.append(self._vote("RSI", "SELL", -cfg.overbought_rsi_penalty, f"RSI12 {rsi12:.2f} 偏高，短线过热"))
        elif rsi12 <= cfg.oversold_rsi_threshold:
            votes.append(self._vote("RSI", "BUY", cfg.oversold_rsi_bonus, f"RSI12 {rsi12:.2f} 偏低，存在修复空间"))
        else:
            votes.append(self._vote("RSI", "HOLD", 0.0, f"RSI12 {rsi12:.2f} 中性"))

        if volume_ratio >= cfg.high_volume_ratio_threshold:
            votes.append(self._vote("量比", "BUY", cfg.high_volume_ratio_bonus, f"量比 {volume_ratio:.2f} 放量确认"))
        elif volume_ratio <= cfg.low_volume_ratio_threshold:
            votes.append(self._vote("量比", "SELL", -cfg.low_volume_ratio_penalty, f"量比 {volume_ratio:.2f} 偏弱"))
        else:
            votes.append(self._vote("量比", "HOLD", 0.0, f"量比 {volume_ratio:.2f} 中性"))

        score = sum(float(vote["score"]) for vote in votes)
        return round(max(-1.0, min(1.0, score)), 4), votes

    def _calculate_position_tech_votes(
        self,
        *,
        current_price: float,
        ma20: float,
        macd: float,
        rsi12: float,
        pnl_pct: float,
    ) -> tuple[float, list[dict[str, Any]]]:
        cfg = self.config.position_scoring
        votes: list[dict[str, Any]] = []
        if current_price < ma20 and ma20 > 0:
            votes.append(self._vote("价格相对MA20", "SELL", -cfg.below_ma20_penalty, f"现价 {current_price:.2f} 低于 MA20 {ma20:.2f}"))
        else:
            votes.append(self._vote("价格相对MA20", "HOLD", 0.0, f"现价 {current_price:.2f} / MA20 {ma20:.2f}"))
        if macd < 0:
            votes.append(self._vote("MACD", "SELL", -cfg.negative_macd_penalty, f"MACD {macd:.3f} 为负"))
        else:
            votes.append(self._vote("MACD", "HOLD", 0.0, f"MACD {macd:.3f} 未触发负向卖出"))
        if pnl_pct <= cfg.deep_loss_threshold:
            votes.append(self._vote("盈亏保护", "SELL", -cfg.deep_loss_penalty, f"浮盈亏 {pnl_pct:.2f}% 触发深度亏损保护"))
        elif pnl_pct >= cfg.strong_profit_threshold:
            votes.append(self._vote("盈亏保护", "SELL", -cfg.strong_profit_penalty, f"浮盈亏 {pnl_pct:.2f}% 触发高位止盈保护"))
        elif pnl_pct >= cfg.guarded_profit_threshold and macd > 0:
            votes.append(self._vote("盈亏保护", "BUY", cfg.guarded_profit_bonus, f"浮盈亏 {pnl_pct:.2f}% 且趋势未破坏"))
        else:
            votes.append(self._vote("盈亏保护", "HOLD", 0.0, f"浮盈亏 {pnl_pct:.2f}% 中性"))
        if rsi12 >= cfg.overbought_rsi_threshold:
            votes.append(self._vote("RSI", "SELL", -cfg.overbought_rsi_penalty, f"RSI12 {rsi12:.2f} 偏高"))
        else:
            votes.append(self._vote("RSI", "HOLD", 0.0, f"RSI12 {rsi12:.2f} 未触发超买"))
        score = sum(float(vote["score"]) for vote in votes)
        return round(max(-1.0, min(1.0, score)), 4), votes

    def _calculate_candidate_tech_score(
        self,
        *,
        current_price: float,
        ma5: float,
        ma20: float,
        ma60: float,
        macd: float,
        rsi12: float,
        volume_ratio: float,
        trend: str,
    ) -> float:
        score, _ = self._calculate_candidate_tech_votes(
            current_price=current_price,
            ma5=ma5,
            ma20=ma20,
            ma60=ma60,
            macd=macd,
            rsi12=rsi12,
            volume_ratio=volume_ratio,
            trend=trend,
        )
        return score

    def _calculate_position_tech_score(
        self,
        *,
        current_price: float,
        ma20: float,
        macd: float,
        rsi12: float,
        pnl_pct: float,
    ) -> float:
        score, _ = self._calculate_position_tech_votes(
            current_price=current_price,
            ma20=ma20,
            macd=macd,
            rsi12=rsi12,
            pnl_pct=pnl_pct,
        )
        return score

    def _build_candidate_reasoning(
        self,
        *,
        candidate: dict[str, Any],
        current_price: float,
        ma5: float,
        ma20: float,
        ma60: float,
        macd: float,
        rsi12: float,
        volume_ratio: float,
        tech_score: float,
        context_score: float,
    ) -> str:
        sources = ",".join(candidate.get("sources") or [candidate.get("source", "manual")])
        return (
            f"{candidate['stock_code']} 来源策略为 {sources}；价格 {current_price:.2f}，MA5/MA20/MA60 为 "
            f"{ma5:.2f}/{ma20:.2f}/{ma60:.2f}，MACD {macd:.3f}，RSI12 {rsi12:.2f}，"
            f"量比 {volume_ratio:.2f}。技术评分 {tech_score:.2f}，上下文评分 {context_score:.2f}。"
        )

    def _build_strategy_profile(
        self,
        *,
        candidate: dict[str, Any],
        market_snapshot: dict[str, Any] | None,
        current_time: datetime,
        analysis_timeframe: str,
        strategy_mode: str,
    ) -> dict[str, Any]:
        market_regime = self._derive_market_regime(market_snapshot, current_time)
        fundamental_quality = self._derive_fundamental_quality(candidate)
        inferred_risk_style = self._derive_auto_risk_style(market_regime["label"], fundamental_quality["label"])
        selected_strategy_mode = self._resolve_strategy_mode(strategy_mode)
        risk_style = self._derive_effective_risk_style(
            market_regime["label"],
            fundamental_quality["label"],
            strategy_mode=selected_strategy_mode["key"],
            inferred_risk_style=inferred_risk_style,
        )
        timeframe_profile = self._resolve_timeframe_profile(analysis_timeframe)
        thresholds = self._build_effective_thresholds(risk_style, timeframe_profile)
        return {
            "strategy_mode": selected_strategy_mode,
            "market_regime": market_regime,
            "fundamental_quality": fundamental_quality,
            "risk_style": risk_style,
            "auto_inferred_risk_style": inferred_risk_style,
            "analysis_timeframe": timeframe_profile,
            "effective_thresholds": thresholds,
        }

    def _derive_market_regime(
        self,
        market_snapshot: dict[str, Any] | None,
        current_time: datetime,
    ) -> dict[str, Any]:
        cfg = self.config.market_regime
        if not market_snapshot:
            return {
                "label": "震荡",
                "score": 0.0,
                "reason": f"{current_time:%Y-%m-%d %H:%M} 暂缺市场快照，默认中性市场。",
            }

        current_price = float(market_snapshot.get("current_price") or market_snapshot.get("latest_price") or 0.0)
        ma20 = float(market_snapshot.get("ma20") or 0.0)
        ma60 = float(market_snapshot.get("ma60") or 0.0)
        macd = float(market_snapshot.get("macd") or 0.0)
        volume_ratio = float(market_snapshot.get("volume_ratio") or 1.0)
        trend = str(market_snapshot.get("trend") or "sideways").lower()

        score = 0.0
        if trend == "up":
            score += cfg.trend_up_weight
        elif trend == "down":
            score -= cfg.trend_down_weight
        if ma20 > 0:
            score += cfg.above_ma20_weight if current_price >= ma20 else -cfg.below_ma20_weight
        if ma60 > 0:
            score += cfg.above_ma60_weight if current_price >= ma60 else -cfg.below_ma60_weight
        if macd > 0:
            score += cfg.positive_macd_weight
        elif macd < 0:
            score -= cfg.negative_macd_weight
        if volume_ratio >= 1.5:
            score += cfg.strong_volume_weight
        elif volume_ratio <= 0.85:
            score -= cfg.weak_volume_weight

        if score >= cfg.bullish_threshold:
            label = "牛市"
        elif score <= cfg.weak_threshold:
            label = "弱市"
        else:
            label = "震荡"
        return {
            "label": label,
            "score": round(max(-1.0, min(1.0, score)), 4),
            "reason": f"趋势={trend}，价格结构={current_price:.2f}/{ma20:.2f}/{ma60:.2f}，MACD={macd:.3f}，量比={volume_ratio:.2f}",
        }

    def _derive_fundamental_quality(self, candidate: dict[str, Any]) -> dict[str, Any]:
        cfg = self.config.fundamental_quality
        metadata = candidate.get("metadata") or {}

        def pick(*names: str) -> float | None:
            for name in names:
                if name in metadata and metadata.get(name) not in (None, ""):
                    return float(metadata[name])
                if name in candidate and candidate.get(name) not in (None, ""):
                    return float(candidate[name])
            return None

        score = 0.0
        profit_growth = pick("profit_growth_pct", "profit_growth")
        roe_pct = pick("roe_pct", "roe")
        pe_ratio = pick("pe_ratio", "pe")
        pb_ratio = pick("pb_ratio", "pb")

        if profit_growth is not None:
            if profit_growth >= cfg.profit_growth_strong:
                score += cfg.strong_bonus
            elif profit_growth <= cfg.profit_growth_weak:
                score -= cfg.weak_penalty
        if roe_pct is not None:
            if roe_pct >= cfg.roe_strong:
                score += cfg.strong_bonus
            elif roe_pct <= cfg.roe_weak:
                score -= cfg.weak_penalty
        if pe_ratio is not None:
            if 0 < pe_ratio <= cfg.pe_reasonable_max:
                score += 0.14
            elif pe_ratio >= cfg.pe_expensive_min:
                score -= 0.14
        if pb_ratio is not None:
            if 0 < pb_ratio <= cfg.pb_reasonable_max:
                score += 0.09
            elif pb_ratio >= cfg.pb_expensive_min:
                score -= 0.09

        if score >= cfg.strong_threshold:
            label = "强基本面"
        elif score <= cfg.weak_threshold:
            label = "弱基本面"
        else:
            label = "中性"
        return {
            "label": label,
            "score": round(max(-1.0, min(1.0, score)), 4),
            "reason": f"成长={profit_growth if profit_growth is not None else 'NA'}，ROE={roe_pct if roe_pct is not None else 'NA'}，PE={pe_ratio if pe_ratio is not None else 'NA'}，PB={pb_ratio if pb_ratio is not None else 'NA'}",
        }

    def _derive_auto_risk_style(self, market_regime: str, fundamental_quality: str) -> dict[str, Any]:
        if market_regime == "牛市" and fundamental_quality == "强基本面":
            label = "激进"
        elif market_regime == "牛市" and fundamental_quality == "中性":
            label = "稳重"
        elif market_regime == "震荡" and fundamental_quality == "强基本面":
            label = "稳重"
        else:
            label = "保守"
        preset = self.config.risk_style_presets[label]
        return {
            "label": preset.label,
            "max_position_ratio": round(preset.max_position_ratio, 4),
            "allow_pyramiding": preset.allow_pyramiding,
            "reason": f"市场状态={market_regime}，基本面质量={fundamental_quality}",
        }

    def _derive_effective_risk_style(
        self,
        market_regime: str,
        fundamental_quality: str,
        *,
        strategy_mode: str,
        inferred_risk_style: dict[str, Any],
    ) -> dict[str, Any]:
        mode_to_label = {
            "auto": inferred_risk_style["label"],
            "aggressive": "激进",
            "neutral": "稳重",
            "defensive": "保守",
        }
        label = mode_to_label.get(strategy_mode, inferred_risk_style["label"])
        preset = self.config.risk_style_presets[label]
        if strategy_mode == "auto":
            reason = f"自动推导：市场状态={market_regime}，基本面质量={fundamental_quality}"
        else:
            reason = (
                f"手动指定策略模式={strategy_mode}，覆盖自动推导风格 {inferred_risk_style['label']}，"
                f"最终使用 {label}"
            )
        return {
            "label": preset.label,
            "max_position_ratio": round(preset.max_position_ratio, 4),
            "allow_pyramiding": preset.allow_pyramiding,
            "reason": reason,
        }

    @staticmethod
    def _resolve_strategy_mode(strategy_mode: str | None) -> dict[str, Any]:
        normalized = str(strategy_mode or "auto").strip().lower()
        mapping = {
            "auto": {"key": "auto", "label": "自动"},
            "aggressive": {"key": "aggressive", "label": "激进"},
            "neutral": {"key": "neutral", "label": "中性"},
            "defensive": {"key": "defensive", "label": "稳健"},
        }
        return mapping.get(normalized, mapping["auto"])

    def _resolve_timeframe_profile(self, analysis_timeframe: str) -> dict[str, Any]:
        key = analysis_timeframe or "1d"
        profile = self.config.timeframe_profiles.get(key, self.config.timeframe_profiles["1d"])
        return {
            "key": profile.key,
            "buy_threshold": round(profile.buy_threshold, 4),
            "sell_threshold": round(profile.sell_threshold, 4),
            "max_position_ratio": round(profile.max_position_ratio, 4),
            "allow_pyramiding": profile.allow_pyramiding,
            "confirmation": profile.confirmation,
        }

    def _build_effective_thresholds(
        self,
        risk_style: dict[str, Any],
        timeframe_profile: dict[str, Any],
    ) -> dict[str, Any]:
        preset = self.config.risk_style_presets[risk_style["label"]]
        buy_threshold = max(0.1, min(0.95, timeframe_profile["buy_threshold"] + preset.buy_threshold_offset))
        sell_threshold = max(-0.95, min(-0.05, timeframe_profile["sell_threshold"] + preset.sell_threshold_offset))
        max_position_ratio = min(
            float(risk_style["max_position_ratio"]),
            float(timeframe_profile["max_position_ratio"]),
        )
        return {
            "buy_threshold": round(buy_threshold, 4),
            "sell_threshold": round(sell_threshold, 4),
            "max_position_ratio": round(max_position_ratio, 4),
            "allow_pyramiding": bool(risk_style["allow_pyramiding"] and timeframe_profile["allow_pyramiding"]),
            "confirmation": timeframe_profile["confirmation"],
        }

    def _select_tech_action(self, tech_score: float, thresholds: dict[str, Any]) -> str:
        if tech_score >= float(thresholds["buy_threshold"]):
            return "BUY"
        if tech_score <= float(thresholds["sell_threshold"]):
            return "SELL"
        return "HOLD"

    @staticmethod
    def _select_context_signal(context_score: float) -> str:
        if context_score >= 0.3:
            return "BUY"
        if context_score <= -0.3:
            return "SELL"
        return "HOLD"

    def _select_tech_confidence(
        self,
        tech_score: float,
        context_score: float,
        strategy_profile: dict[str, Any],
    ) -> float:
        cfg = self.config.technical
        style_label = strategy_profile["risk_style"]["label"]
        confidence_bonus = self.config.risk_style_presets[style_label].confidence_bonus
        return max(
            cfg.min_confidence,
            min(
                cfg.max_confidence,
                cfg.base_confidence
                + abs(tech_score) * cfg.tech_confidence_weight
                + max(context_score, 0) * cfg.context_confidence_weight
                + confidence_bonus,
            ),
        )
