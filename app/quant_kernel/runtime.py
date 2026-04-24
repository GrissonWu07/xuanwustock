"""Reusable strategy runtime that evaluates snapshots into stockpolicy-style decisions."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .config import QuantKernelConfig, StrategyScoringConfig
from .decision_engine import DualTrackResolver, resolve_v23_final_action
from .interfaces import ContextProvider
from .models import ContextualScore, Decision
from .scoring_v23 import score_fusion, score_track


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
        strategy_profile_binding: dict[str, Any] | None = None,
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
                market_snapshot=market_snapshot,
                profile_kind="candidate",
                sources=sources,
                strategy_profile_binding=strategy_profile_binding,
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
            market_snapshot=market_snapshot,
            profile_kind="candidate",
            sources=sources,
            strategy_profile_binding=strategy_profile_binding,
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
        strategy_profile_binding: dict[str, Any] | None = None,
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
                market_snapshot=market_snapshot,
                profile_kind="position",
                sources=sources,
                strategy_profile_binding=strategy_profile_binding,
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
            market_snapshot=market_snapshot,
            profile_kind="position",
            sources=sources,
            strategy_profile_binding=strategy_profile_binding,
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
        market_snapshot: dict[str, Any] | None,
        profile_kind: str,
        sources: list[str],
        strategy_profile_binding: dict[str, Any] | None = None,
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
        v23_profile = self._resolve_v23_profile(profile_kind=profile_kind, strategy_profile_binding=strategy_profile_binding)
        raw_dimensions = self._build_v23_dimension_payload(
            market_snapshot=market_snapshot,
            current_time=current_time,
            sources=sources,
            contextual_score=contextual_score,
            price=price,
            scoring_profile=v23_profile,
        )
        technical_breakdown = score_track(
            track_name="technical",
            track_config=v23_profile["technical"],
            raw_dimensions=raw_dimensions["technical"],
        )
        context_breakdown = score_track(
            track_name="context",
            track_config=v23_profile["context"],
            raw_dimensions=raw_dimensions["context"],
        )
        fusion_breakdown = score_fusion(
            technical=technical_breakdown,
            context=context_breakdown,
            dual_track=v23_profile["dual_track"],
            volatility_regime_score=raw_dimensions.get("volatility_regime_score"),
        )
        vetoes = self._build_v23_vetoes(
            profile_kind=profile_kind,
            contextual_score=contextual_score,
            dual_track=v23_profile["dual_track"],
            veto_config=v23_profile.get("veto") if isinstance(v23_profile.get("veto"), dict) else {},
        )
        v23_action = resolve_v23_final_action(
            mode=str(v23_profile["dual_track"].get("mode") or "rule_only"),
            core_rule_action=tech_decision.action,
            weighted_action_raw=str(fusion_breakdown["weighted_action_raw"]),
            fusion_score=float(fusion_breakdown["fusion_score"]),
            sell_precedence_gate=float(fusion_breakdown["sell_precedence_gate"]),
            vetoes=vetoes,
            legacy_rule_action=resolved.action,
        )
        if str(v23_profile["dual_track"].get("mode") or "rule_only") != "rule_only":
            resolved.action = str(v23_action["final_action"])
            if resolved.action == "BUY":
                resolved.decision_type = "dual_track_weighted_buy"
            elif resolved.action == "SELL":
                resolved.decision_type = "dual_track_weighted_sell"
            else:
                resolved.decision_type = "dual_track_weighted_hold"
        resolved.strategy_profile = self._attach_explainability(
            strategy_profile=strategy_profile,
            market_snapshot=market_snapshot,
            tech_votes=tech_votes,
            contextual_score=contextual_score,
            resolved=resolved,
            technical_breakdown=technical_breakdown,
            context_breakdown=context_breakdown,
            fusion_breakdown=fusion_breakdown,
            v23_action=v23_action,
            vetoes=vetoes,
            profile_kind=profile_kind,
            strategy_profile_binding=strategy_profile_binding,
        )
        if resolved.action == "BUY":
            max_ratio = float(thresholds.get("max_position_ratio") or 0.0)
            resolved.position_ratio = round(
                min(resolved.position_ratio or max_ratio, max_ratio),
                4,
            )
        if profile_kind == "candidate" and resolved.action == "SELL":
            resolved.action = "HOLD"
            resolved.decision_type = "candidate_reject"
        return resolved

    def _build_v23_dimension_payload(
        self,
        *,
        market_snapshot: dict[str, Any] | None,
        current_time: datetime,
        sources: list[str],
        contextual_score: ContextualScore,
        price: float,
        scoring_profile: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot = market_snapshot or {}
        close = float(snapshot.get("current_price") or snapshot.get("latest_price") or price or 0.0)
        ma5 = float(snapshot.get("ma5") or close)
        ma10 = float(snapshot.get("ma10") or ma5)
        ma20 = float(snapshot.get("ma20") or close)
        ma60 = float(snapshot.get("ma60") or ma20)
        macd = float(snapshot.get("macd") or 0.0)
        dif = float(snapshot.get("dif") or macd)
        dea = float(snapshot.get("dea") or 0.0)
        hist = float(snapshot.get("hist") or (dif - dea))
        prev_hist = float(snapshot.get("hist_prev") or hist)
        rsi14 = float(snapshot.get("rsi14") or snapshot.get("rsi12") or 50.0)
        k_value = snapshot.get("k")
        d_value = snapshot.get("d")
        j_value = snapshot.get("j")
        volume_ratio = float(snapshot.get("volume_ratio") or 1.0)
        obv = snapshot.get("obv")
        obv_prev = snapshot.get("obv_prev")
        atr = snapshot.get("atr")
        boll_upper = snapshot.get("boll_upper")
        boll_lower = snapshot.get("boll_lower")
        trend = str(snapshot.get("trend") or "sideways").lower()
        source = str((sources or ["default"])[0])
        technical_config = scoring_profile.get("technical") if isinstance(scoring_profile.get("technical"), dict) else {}
        context_config = scoring_profile.get("context") if isinstance(scoring_profile.get("context"), dict) else {}
        technical_scorers = technical_config.get("scorers") if isinstance(technical_config.get("scorers"), dict) else {}
        context_scorers = context_config.get("scorers") if isinstance(context_config.get("scorers"), dict) else {}

        ma20_slope = float(snapshot.get("ma20_slope") or 0.0)
        distance_ratio = ((close - ma20) / ma20) if ma20 else 0.0
        hist_slope = hist - prev_hist
        atr_pct = (float(atr) / close) if (atr is not None and close > 0) else 0.0
        boll_position_value = 0.0
        boll_available = boll_upper is not None and boll_lower is not None and float(boll_upper) > float(boll_lower)
        if boll_available:
            boll_position_value = (close - float(boll_lower)) / (float(boll_upper) - float(boll_lower) + 1e-9)
        kdj_available = all(value is not None for value in (k_value, d_value, j_value))
        k_float = float(k_value) if k_value is not None else 50.0
        d_float = float(d_value) if d_value is not None else 50.0
        j_float = float(j_value) if j_value is not None else 50.0
        obv_available = obv is not None and obv_prev is not None
        obv_slope = ((float(obv) - float(obv_prev)) / max(abs(float(obv_prev)), 1.0)) if obv_available else 0.0

        order_score = 0
        if ma5 > ma10 > ma20 > ma60:
            order_score = 4
        elif ma5 > ma10 > ma20:
            order_score = 3
        elif ma5 > ma10:
            order_score = 2
        elif ma5 < ma10 < ma20 < ma60:
            order_score = 0
        elif ma5 < ma10 < ma20:
            order_score = 1

        technical: dict[str, dict[str, Any]] = {
            "trend_direction": self._score_trend_direction(
                scorer=technical_scorers.get("trend_direction"),
                close=close,
                ma20=ma20,
                ma60=ma60,
            ),
            "ma_alignment": self._score_ma_alignment(
                scorer=technical_scorers.get("ma_alignment"),
                order_score=order_score,
                ma5=ma5,
                ma10=ma10,
                ma20=ma20,
                ma60=ma60,
            ),
            "ma_slope": self._score_linear_dimension(
                scorer=technical_scorers.get("ma_slope"),
                value=ma20_slope,
                reason=f"ma20_slope={ma20_slope:.6f}",
                available=snapshot.get("ma20_slope") is not None,
            ),
            "price_vs_ma20": self._score_piecewise_dimension(
                scorer=technical_scorers.get("price_vs_ma20"),
                value=distance_ratio,
                bands_key="distance_bands",
                scores_key="band_scores",
                reason=f"distance(close,ma20)={distance_ratio:.6f}",
                available=ma20 > 0,
            ),
            "macd_level": self._score_macd_level(
                scorer=technical_scorers.get("macd_level"),
                dif=dif,
                dea=dea,
                hist=hist,
            ),
            "macd_hist_slope": self._score_piecewise_dimension(
                scorer=technical_scorers.get("macd_hist_slope"),
                value=hist_slope,
                bands_key="slope_bands",
                scores_key="band_scores",
                reason=f"hist_slope={hist_slope:.6f}",
                available=True,
            ),
            "rsi_zone": self._score_rsi_zone(
                scorer=technical_scorers.get("rsi_zone"),
                rsi14=rsi14,
            ),
            "kdj_cross": self._score_kdj_cross(
                scorer=technical_scorers.get("kdj_cross"),
                k_value=k_float,
                d_value=d_float,
                j_value=j_float,
                available=kdj_available,
            ),
            "volume_ratio": self._score_piecewise_dimension(
                scorer=technical_scorers.get("volume_ratio"),
                value=volume_ratio,
                bands_key="ratio_bands",
                scores_key="ratio_scores",
                reason=f"volume_ratio={volume_ratio:.4f}",
                available=True,
            ),
            "obv_trend": self._score_piecewise_dimension(
                scorer=technical_scorers.get("obv_trend"),
                value=obv_slope,
                bands_key="slope_bands",
                scores_key="slope_scores",
                reason=f"obv_slope={obv_slope:.6f}",
                available=obv_available,
            ),
            "atr_risk": self._score_piecewise_dimension(
                scorer=technical_scorers.get("atr_risk"),
                value=atr_pct,
                bands_key="atr_pct_bands",
                scores_key="risk_scores",
                reason=f"atr_pct={atr_pct:.6f}",
                available=atr is not None and close > 0,
            ),
            "boll_position": self._score_piecewise_dimension(
                scorer=technical_scorers.get("boll_position"),
                value=boll_position_value,
                bands_key="position_bands",
                scores_key="position_scores",
                reason=f"boll_position={boll_position_value:.6f}",
                available=boll_available,
            ),
        }

        session_label = "close" if current_time.time() >= datetime.strptime("14:30", "%H:%M").time() else ("open" if current_time.time() <= datetime.strptime("10:00", "%H:%M").time() else "mid")
        context_components = contextual_score.components or {}
        feedback_policy = (
            context_config.get("execution_feedback_policy")
            if isinstance(context_config.get("execution_feedback_policy"), dict)
            else {}
        )
        feedback_cap = max(0.0, float(feedback_policy.get("execution_feedback_score_cap") or 1.0))
        raw_feedback_score = float(snapshot.get("execution_feedback_score") or (context_components.get("execution_feedback") or {}).get("score") or 0.0)
        source_prior_score = float((context_components.get("source_prior") or {}).get("score") or 0.1)
        account_posture_score = float(snapshot.get("account_posture_score") or (context_components.get("account_posture") or {}).get("score") or 0.0)

        context: dict[str, dict[str, Any]] = {
            "source_prior": self._score_lookup_dimension(
                scorer=context_scorers.get("source_prior"),
                key_value=source,
                mapping_key="source_score_map",
                default_score=source_prior_score,
                reason=f"source={source}",
                available=True,
            ),
            "trend_regime": self._score_lookup_dimension(
                scorer=context_scorers.get("trend_regime"),
                key_value=trend,
                mapping_key="regime_score_map",
                default_score=0.0,
                reason=f"regime={trend}",
                available=True,
            ),
            "price_structure": self._score_price_structure(
                scorer=context_scorers.get("price_structure"),
                close=close,
                ma20=ma20,
                ma60=ma60,
            ),
            "momentum": self._score_piecewise_dimension(
                scorer=context_scorers.get("momentum"),
                value=macd,
                bands_key="momentum_bands",
                scores_key="momentum_scores",
                reason=f"context_momentum={macd:.6f}",
                available=True,
            ),
            "risk_balance": self._score_piecewise_dimension(
                scorer=context_scorers.get("risk_balance"),
                value=rsi14,
                bands_key="risk_bands",
                scores_key="risk_scores",
                reason=f"risk_metric={rsi14:.4f}",
                available=True,
            ),
            "liquidity": self._score_piecewise_dimension(
                scorer=context_scorers.get("liquidity"),
                value=volume_ratio,
                bands_key="liq_bands",
                scores_key="liq_scores",
                reason=f"liquidity_value={volume_ratio:.4f}",
                available=True,
            ),
            "session": self._score_lookup_dimension(
                scorer=context_scorers.get("session"),
                key_value=session_label,
                mapping_key="session_score_map",
                default_score=0.0,
                reason=f"session={session_label}",
                available=True,
            ),
            "execution_feedback": {
                **self._score_execution_feedback(
                    scorer=context_scorers.get("execution_feedback"),
                    feedback_score=raw_feedback_score,
                    feedback_sample_count=snapshot.get("feedback_sample_count"),
                    available=(
                        snapshot.get("execution_feedback_score") is not None
                        or (context_components.get("execution_feedback") is not None)
                    ),
                    fallback_cap=feedback_cap,
                ),
            },
            "account_posture": self._score_piecewise_dimension(
                scorer=context_scorers.get("account_posture"),
                value=float(snapshot.get("cash_ratio") or 0.0),
                bands_key="cash_ratio_bands",
                scores_key="posture_scores",
                reason=f"cash_ratio={snapshot.get('cash_ratio')}",
                available=snapshot.get("cash_ratio") is not None or (context_components.get("account_posture") is not None),
                fallback_score=account_posture_score,
            ),
        }

        volatility_regime_score = snapshot.get("volatility_regime_score")
        if volatility_regime_score is None:
            volatility_regime_score = max(-1.0, min(1.0, -atr_pct * 5.0 if atr_pct > 0 else 0.0))

        return {
            "technical": technical,
            "context": context,
            "volatility_regime_score": float(volatility_regime_score)
            if volatility_regime_score is not None
            else None,
        }

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            parsed = float(value)
            if parsed != parsed or parsed in (float("inf"), float("-inf")):
                return default
            return parsed
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
        return max(low, min(high, value))

    @staticmethod
    def _normalize_scorer(scorer: Any) -> dict[str, Any]:
        if not isinstance(scorer, dict):
            return {"algorithm": "", "params": {}, "reason_template": ""}
        params = scorer.get("params")
        return {
            "algorithm": str(scorer.get("algorithm") or "").strip().lower(),
            "params": params if isinstance(params, dict) else {},
            "reason_template": str(scorer.get("reason_template") or ""),
        }

    @classmethod
    def _score_payload(
        cls,
        *,
        score: float,
        available: bool,
        reason: str,
    ) -> dict[str, Any]:
        if not available:
            return {"score": 0.0, "available": False, "reason": reason or "missing_field"}
        return {"score": round(cls._clamp(score), 6), "available": True, "reason": reason or "ok"}

    @staticmethod
    def _select_piecewise_score(
        value: float,
        *,
        bands: list[float],
        scores: list[float],
        default_score: float = 0.0,
    ) -> float:
        if not bands or not scores:
            return default_score
        idx = 0
        for band in bands:
            if value <= band:
                break
            idx += 1
        idx = min(idx, len(scores) - 1)
        return float(scores[idx])

    @classmethod
    def _render_reason(
        cls,
        scorer: dict[str, Any],
        *,
        fallback: str,
        context: dict[str, Any],
    ) -> str:
        template = str(scorer.get("reason_template") or "").strip()
        if not template:
            return fallback
        rendered_context: dict[str, Any] = {}
        for key, value in context.items():
            if isinstance(value, float):
                rendered_context[key] = f"{value:.6f}".rstrip("0").rstrip(".")
            else:
                rendered_context[key] = value
        rendered_context.setdefault("score", rendered_context.get("score", "0"))
        try:
            return template.format(**rendered_context)
        except Exception:
            return fallback

    def _score_trend_direction(
        self,
        *,
        scorer: Any,
        close: float,
        ma20: float,
        ma60: float,
    ) -> dict[str, Any]:
        normalized = self._normalize_scorer(scorer)
        params = normalized["params"]
        available = close > 0 and ma20 > 0
        if not available:
            return self._score_payload(score=0.0, available=False, reason="missing_field")
        if close > ma20 and ma20 > ma60 > 0:
            score = self._to_float(params.get("bull_score"), 1.0)
        elif close > ma20:
            score = self._to_float(params.get("mild_bull_score"), 0.3)
        elif ma60 > 0 and close < ma20 < ma60:
            score = self._to_float(params.get("bear_score"), -1.0)
        elif close < ma20:
            score = self._to_float(params.get("mild_bear_score"), -0.4)
        else:
            score = 0.0
        reason = self._render_reason(
            normalized,
            fallback=f"close/ma20/ma60={close:.2f}/{ma20:.2f}/{ma60:.2f}",
            context={"close": close, "ma20": ma20, "ma60": ma60, "score": score},
        )
        return self._score_payload(score=score, available=True, reason=reason)

    def _score_ma_alignment(
        self,
        *,
        scorer: Any,
        order_score: int,
        ma5: float,
        ma10: float,
        ma20: float,
        ma60: float,
    ) -> dict[str, Any]:
        normalized = self._normalize_scorer(scorer)
        params = normalized["params"]
        order_map = params.get("order_score_map") if isinstance(params.get("order_score_map"), dict) else {}
        raw_score = self._to_float(order_map.get(str(order_score)), 0.0)
        smooth_k = self._clamp(self._to_float(params.get("alignment_smooth_k"), 0.0), 0.0, 0.95)
        score = raw_score * (1.0 - smooth_k)
        reason = self._render_reason(
            normalized,
            fallback=f"ma order score={order_score}",
            context={
                "order_score": order_score,
                "ma5": ma5,
                "ma10": ma10,
                "ma20": ma20,
                "ma60": ma60,
                "score": score,
            },
        )
        return self._score_payload(score=score, available=True, reason=reason)

    def _score_linear_dimension(
        self,
        *,
        scorer: Any,
        value: float,
        reason: str,
        available: bool,
    ) -> dict[str, Any]:
        if not available:
            return self._score_payload(score=0.0, available=False, reason="missing_field")
        normalized = self._normalize_scorer(scorer)
        params = normalized["params"]
        algorithm = normalized["algorithm"]
        score = 0.0
        if algorithm == "sigmoid":
            scale = self._to_float(params.get("scale"), 1.0)
            offset = self._to_float(params.get("offset"), 0.0)
            score = 2.0 / (1.0 + (2.718281828 ** (-(value - offset) * scale))) - 1.0
        else:
            neutral_band = max(0.0, self._to_float(params.get("neutral_band"), 0.0))
            if abs(value) < neutral_band:
                score = 0.0
            else:
                scale = self._to_float(params.get("slope_scale"), 1.0)
                intercept = self._to_float(params.get("intercept"), 0.0)
                score = value * scale + intercept
        min_clip = self._to_float(params.get("min_clip"), -1.0)
        max_clip = self._to_float(params.get("max_clip"), 1.0)
        score = self._clamp(score, min_clip, max_clip)
        rendered = self._render_reason(
            normalized,
            fallback=reason,
            context={"value": value, "score": score},
        )
        return self._score_payload(score=score, available=True, reason=rendered)

    def _score_piecewise_dimension(
        self,
        *,
        scorer: Any,
        value: float,
        bands_key: str,
        scores_key: str,
        reason: str,
        available: bool,
        fallback_score: float = 0.0,
    ) -> dict[str, Any]:
        if not available:
            return self._score_payload(score=fallback_score, available=False, reason="missing_field")
        normalized = self._normalize_scorer(scorer)
        params = normalized["params"]
        algorithm = normalized["algorithm"]
        if algorithm == "linear":
            scale = self._to_float(params.get("scale"), 1.0)
            intercept = self._to_float(params.get("intercept"), 0.0)
            score = value * scale + intercept
        elif algorithm == "sigmoid":
            scale = self._to_float(params.get("scale"), 1.0)
            offset = self._to_float(params.get("offset"), 0.0)
            score = 2.0 / (1.0 + (2.718281828 ** (-(value - offset) * scale))) - 1.0
        else:
            bands_raw = params.get(bands_key)
            scores_raw = params.get(scores_key)
            bands = [self._to_float(item) for item in bands_raw] if isinstance(bands_raw, list) else []
            scores = [self._to_float(item) for item in scores_raw] if isinstance(scores_raw, list) else []
            score = self._select_piecewise_score(value, bands=bands, scores=scores, default_score=fallback_score)
        rendered = self._render_reason(
            normalized,
            fallback=reason,
            context={"value": value, "score": score},
        )
        return self._score_payload(score=score, available=True, reason=rendered)

    def _score_macd_level(
        self,
        *,
        scorer: Any,
        dif: float,
        dea: float,
        hist: float,
    ) -> dict[str, Any]:
        normalized = self._normalize_scorer(scorer)
        params = normalized["params"]
        hist_bands_raw = params.get("hist_bands")
        hist_scores_raw = params.get("hist_scores")
        hist_bands = [self._to_float(item) for item in hist_bands_raw] if isinstance(hist_bands_raw, list) else [-0.3, -0.1, 0.1, 0.3]
        hist_scores = [self._to_float(item) for item in hist_scores_raw] if isinstance(hist_scores_raw, list) else [-0.8, -0.3, 0.3, 0.8]
        base_score = self._select_piecewise_score(hist, bands=hist_bands, scores=hist_scores, default_score=0.0)
        dif_sign_adjust = self._to_float(params.get("dif_sign_adjust"), 0.0)
        if dif > dea:
            score = base_score + dif_sign_adjust
        elif dif < dea:
            score = base_score - dif_sign_adjust
        else:
            score = base_score
        reason = self._render_reason(
            normalized,
            fallback=f"dif/dea/hist={dif:.3f}/{dea:.3f}/{hist:.3f}",
            context={"dif": dif, "dea": dea, "hist": hist, "score": score},
        )
        return self._score_payload(score=score, available=True, reason=reason)

    def _score_rsi_zone(
        self,
        *,
        scorer: Any,
        rsi14: float,
    ) -> dict[str, Any]:
        normalized = self._normalize_scorer(scorer)
        params = normalized["params"]
        oversold = self._to_float(params.get("oversold"), 28.0)
        neutral_low = self._to_float(params.get("neutral_low"), 42.0)
        neutral_high = self._to_float(params.get("neutral_high"), 68.0)
        overbought = self._to_float(params.get("overbought"), 72.0)
        zone_scores = params.get("zone_scores") if isinstance(params.get("zone_scores"), dict) else {}
        oversold_score = self._to_float(zone_scores.get("oversold"), 0.6)
        neutral_score = self._to_float(zone_scores.get("neutral"), 0.1)
        overbought_score = self._to_float(zone_scores.get("overbought"), -0.4)
        if rsi14 <= oversold:
            score = oversold_score
        elif rsi14 >= overbought:
            score = overbought_score
        elif neutral_low <= rsi14 <= neutral_high:
            score = neutral_score
        elif rsi14 < neutral_low:
            score = (oversold_score + neutral_score) / 2.0
        else:
            score = (neutral_score + overbought_score) / 2.0
        reason = self._render_reason(
            normalized,
            fallback=f"rsi14={rsi14:.2f}",
            context={"rsi14": rsi14, "score": score},
        )
        return self._score_payload(score=score, available=True, reason=reason)

    def _score_kdj_cross(
        self,
        *,
        scorer: Any,
        k_value: float,
        d_value: float,
        j_value: float,
        available: bool,
    ) -> dict[str, Any]:
        if not available:
            return self._score_payload(score=0.0, available=False, reason="missing_field")
        normalized = self._normalize_scorer(scorer)
        params = normalized["params"]
        cross_strength = (k_value - d_value) / 100.0
        bands_raw = params.get("cross_strength_bands")
        scores_raw = params.get("band_scores") or params.get("cross_scores")
        bands = [self._to_float(item) for item in bands_raw] if isinstance(bands_raw, list) else [-0.5, -0.1, 0.1, 0.5]
        scores = [self._to_float(item) for item in scores_raw] if isinstance(scores_raw, list) else [-0.8, -0.3, 0.3, 0.8]
        score = self._select_piecewise_score(cross_strength, bands=bands, scores=scores, default_score=0.0)
        extreme_adjust = abs(self._to_float(params.get("extreme_zone_adjust"), 0.0))
        if j_value >= 90:
            score -= extreme_adjust
        elif j_value <= 10:
            score += extreme_adjust
        reason = self._render_reason(
            normalized,
            fallback=f"k/d/j={k_value:.2f}/{d_value:.2f}/{j_value:.2f}",
            context={"k": k_value, "d": d_value, "j": j_value, "score": score},
        )
        return self._score_payload(score=score, available=True, reason=reason)

    def _score_lookup_dimension(
        self,
        *,
        scorer: Any,
        key_value: str,
        mapping_key: str,
        default_score: float,
        reason: str,
        available: bool,
    ) -> dict[str, Any]:
        if not available:
            return self._score_payload(score=default_score, available=False, reason="missing_field")
        normalized = self._normalize_scorer(scorer)
        params = normalized["params"]
        mapping = params.get(mapping_key) if isinstance(params.get(mapping_key), dict) else {}
        lookup_value = str(key_value or "").strip().lower()
        score = self._to_float(mapping.get(lookup_value), self._to_float(mapping.get(str(key_value)), default_score))
        if lookup_value not in mapping and "default" in mapping:
            score = self._to_float(mapping.get("default"), score)
        rendered = self._render_reason(
            normalized,
            fallback=reason,
            context={"source": key_value, "regime": key_value, "session": key_value, "score": score},
        )
        return self._score_payload(score=score, available=True, reason=rendered)

    def _score_price_structure(
        self,
        *,
        scorer: Any,
        close: float,
        ma20: float,
        ma60: float,
    ) -> dict[str, Any]:
        normalized = self._normalize_scorer(scorer)
        params = normalized["params"]
        mapping = params.get("structure_score_map") if isinstance(params.get("structure_score_map"), dict) else {}
        if close > ma20 and ma20 > ma60 > 0:
            structure = "bull_stack"
        elif close > ma20:
            structure = "above_ma20"
        elif ma60 > 0 and close < ma20 < ma60:
            structure = "bear_stack"
        elif close < ma20:
            structure = "below_ma20"
        else:
            structure = "neutral"
        score = self._to_float(mapping.get(structure), self._to_float(mapping.get("default"), 0.0))
        reason = self._render_reason(
            normalized,
            fallback=f"price_structure={structure}",
            context={"price_structure": structure, "score": score},
        )
        return self._score_payload(score=score, available=True, reason=reason)

    def _score_execution_feedback(
        self,
        *,
        scorer: Any,
        feedback_score: float,
        feedback_sample_count: Any,
        available: bool,
        fallback_cap: float,
    ) -> dict[str, Any]:
        normalized = self._normalize_scorer(scorer)
        params = normalized["params"]
        min_samples = max(0.0, self._to_float(params.get("min_feedback_samples"), 0.0))
        cap = max(0.0, self._to_float(params.get("execution_feedback_score_cap"), fallback_cap))
        sample_count = max(0.0, self._to_float(feedback_sample_count, 0.0))
        if sample_count > 0 and sample_count < min_samples:
            score = 0.0
            available = True
            reason = f"feedback_sample_count={sample_count:.0f} < min_feedback_samples={min_samples:.0f}"
            return self._score_payload(score=score, available=available, reason=reason)
        score = self._clamp(self._to_float(feedback_score, 0.0), -cap, cap)
        reason = self._render_reason(
            normalized,
            fallback=f"feedback_sample_count={feedback_sample_count}",
            context={
                "feedback_sample_count": sample_count,
                "score": score,
            },
        )
        return self._score_payload(score=score, available=available, reason=reason if available else "missing_field")

    def _build_v23_vetoes(
        self,
        *,
        profile_kind: str,
        contextual_score: ContextualScore,
        dual_track: dict[str, Any],
        veto_config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        vetoes: list[dict[str, Any]] = []
        thresholds = veto_config.get("thresholds") if isinstance(veto_config.get("thresholds"), dict) else {}
        context_veto_cfg = thresholds.get("context_veto") if isinstance(thresholds.get("context_veto"), dict) else {}
        context_veto_enabled = bool(context_veto_cfg.get("enabled", True))
        context_veto_floor = float(context_veto_cfg.get("min_context_score", dual_track.get("fusion_sell_threshold", -0.7)))
        if context_veto_enabled and contextual_score.score < context_veto_floor:
            vetoes.append(
                {
                    "id": "context_veto",
                    "priority": 3,
                    "action": "HOLD" if profile_kind == "position" else "HOLD",
                    "reason": f"context_score={contextual_score.score:.4f} < {context_veto_floor:.4f}",
                }
            )
        return vetoes

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

    def _resolve_v23_profile(
        self,
        *,
        profile_kind: str,
        strategy_profile_binding: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if isinstance(strategy_profile_binding, dict):
            config_payload = strategy_profile_binding.get("config")
            if isinstance(config_payload, dict):
                schema_version = str(config_payload.get("schema_version") or "quant_explain")
                base = config_payload.get("base")
                profiles = config_payload.get("profiles")
                if isinstance(base, dict) and isinstance(profiles, dict):
                    scoring = StrategyScoringConfig(
                        schema_version=schema_version,
                        base=base,
                        profiles=profiles,
                    )
                    return scoring.resolve(profile_kind)
        return self.config.resolve_strategy_scoring(profile_kind)

    def _attach_explainability(
        self,
        *,
        strategy_profile: dict[str, Any],
        market_snapshot: dict[str, Any] | None,
        tech_votes: list[dict[str, Any]],
        contextual_score: ContextualScore,
        resolved: Decision,
        technical_breakdown: dict[str, Any],
        context_breakdown: dict[str, Any],
        fusion_breakdown: dict[str, Any],
        v23_action: dict[str, Any],
        vetoes: list[dict[str, Any]],
        profile_kind: str,
        strategy_profile_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        profile = dict(strategy_profile)
        if isinstance(market_snapshot, dict):
            profile["market_snapshot"] = json.loads(json.dumps(market_snapshot, ensure_ascii=False, default=str))
        fusion_view = dict(fusion_breakdown)
        fusion_view["core_rule_action"] = str((resolved.dual_track_details or {}).get("tech_signal") or resolved.action)
        fusion_view["final_action"] = str(v23_action.get("final_action") or resolved.action)
        fusion_view["veto_source_mode"] = "legacy"
        if isinstance(strategy_profile_binding, dict):
            profile["selected_strategy_profile"] = {
                "id": str(strategy_profile_binding.get("profile_id") or ""),
                "name": str(strategy_profile_binding.get("profile_name") or ""),
                "version_id": strategy_profile_binding.get("version_id"),
                "version": strategy_profile_binding.get("version"),
            }
            dynamic_strategy = strategy_profile_binding.get("dynamic_strategy")
            if isinstance(dynamic_strategy, dict):
                profile["dynamic_strategy"] = json.loads(json.dumps(dynamic_strategy, ensure_ascii=False))
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
            "explain_schema_version": "quant_explain",
            "profile_kind": profile_kind,
            "technical_breakdown": technical_breakdown,
            "context_breakdown": context_breakdown,
            "fusion_breakdown": fusion_view,
            "vetoes": vetoes,
            "decision_path": v23_action.get("decision_path") or [],
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
            "allow_pyramiding": bool(risk_style["allow_pyramiding"]),
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
