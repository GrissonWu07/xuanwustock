"""Tail helper mixin for SignalCenterService."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.notification_service import notification_service
from app.quant_sim.execution_sizing import build_execution_sizing_plan, default_execution_position_cap_policy
from app.quant_sim.portfolio_execution_guard import normalize_portfolio_execution_guard_policy
from app.quant_sim.stock_execution_feedback import normalize_stock_execution_feedback_policy

_HARD_EXIT_SELL_TOKENS = (
    "hard_stop_loss",
    "stop_loss",
    "risk_stop",
    "quick_stoploss",
    "hard_profit_trailing_stop",
    "profit_tech_sell",
    "recovery_probe_failure_sell",
    "feedback_weak_sell_exit",
)

_HARD_EXIT_VETO_IDS = {
    "hard_stop_loss",
    "stop_loss",
    "risk_stop",
    "quick_stoploss",
    "hard_profit_trailing_stop",
    "profit_tech_sell",
}


class SignalCenterTailMixin:
    """Late-stage gates, sizing, policies, and side effects for SignalCenterService."""
    @classmethod
    def _apply_false_strong_filter(cls, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        if str(normalized.get("action") or "HOLD").upper() not in {"BUY", "ADD"}:
            return normalized
        profile = normalized.get("strategy_profile") if isinstance(normalized.get("strategy_profile"), dict) else {}
        guard = profile.get("portfolio_execution_guard") if isinstance(profile.get("portfolio_execution_guard"), dict) else {}
        if str(guard.get("buy_tier") or "").strip().lower() != "strong_buy":
            return normalized
        trend = guard.get("trend_confirmation") if isinstance(guard.get("trend_confirmation"), dict) else {}
        components = guard.get("score_components") if isinstance(guard.get("score_components"), dict) else {}
        reasons: list[str] = []
        above_ma20 = int(cls._safe_float(trend.get("above_ma20_checkpoints"), 0.0) or 0)
        confirmation_score = cls._safe_float(components.get("confirmation_score"), 0.0) or 0.0
        structure_ok = bool(
            trend.get("ma_stack")
            or trend.get("retest_confirmed")
            or (trend.get("ma20_rising") and above_ma20 >= 2)
            or confirmation_score >= 0.75
        )
        if not structure_ok:
            reasons.append("weak_trend_structure")
        ma20_distance_pct = abs(cls._safe_float(trend.get("ma20_distance_pct"), 0.0) or 0.0)
        rsi = cls._safe_float(trend.get("rsi"), 0.0) or 0.0
        if ma20_distance_pct >= 10.0 and rsi >= 86.0:
            reasons.append("overheated_distance")
        lifecycle_gate = profile.get("lifecycle_gate") if isinstance(profile.get("lifecycle_gate"), dict) else {}
        if int(cls._safe_float(lifecycle_gate.get("recent_probe_loss_count"), 0.0) or 0) > 0:
            reasons.append("recent_probe_failure")
        if not reasons:
            return normalized

        next_profile = dict(profile)
        next_guard = dict(guard)
        next_guard["buy_tier"] = "normal_buy"
        next_guard["buy_tier_label"] = "普通买入"
        next_guard["strong_filter_result"] = "downgraded"
        next_guard["strong_filter_reasons"] = reasons
        next_profile["portfolio_execution_guard"] = next_guard
        normalized["strategy_profile"] = next_profile
        return normalized

    @classmethod
    def _maybe_relax_trial_lifecycle_gate(cls, gate: Any, strategy_profile: dict[str, Any]) -> dict[str, Any]:
        normalized_gate = dict(gate) if isinstance(gate, dict) else {}
        mode = str(normalized_gate.get("mode") or "").strip().lower()
        if mode == "recovery_probe":
            if int(cls._safe_float(normalized_gate.get("recent_probe_loss_count"), 0.0) or 0) > 0:
                return normalized_gate
            if not cls._lifecycle_gate_has_confirmed_recovery_probe_sizing(strategy_profile, normalized_gate):
                return normalized_gate
            guard = (
                strategy_profile.get("portfolio_execution_guard")
                if isinstance(strategy_profile.get("portfolio_execution_guard"), dict)
                else {}
            )
            buy_tier = str(guard.get("buy_tier") or "").strip().lower()
            relaxed = dict(normalized_gate)
            if buy_tier == "strong_buy" and cls._strong_recovery_probe_is_overextended_without_retest(guard):
                reduced_cap = cls._reduced_recovery_probe_cap(normalized_gate)
                relaxed["mode"] = "recovery_probe_quality_limited"
                relaxed["size_multiplier"] = 1.0
                relaxed["max_position_pct"] = reduced_cap
                relaxed["reason_code"] = "strong_recovery_overextended_without_retest"
                relaxed["reason_text"] = "recovery probe 强买未经过回踩且短线涨幅偏高，先降为轻量恢复试探"
                return relaxed
            if buy_tier == "strong_buy" and not cls._lifecycle_gate_has_high_quality_strong_recovery(
                strategy_profile,
                normalized_gate,
            ):
                reduced_cap = cls._reduced_recovery_probe_cap(normalized_gate)
                relaxed["mode"] = "recovery_probe_quality_limited"
                relaxed["size_multiplier"] = 1.0
                relaxed["max_position_pct"] = reduced_cap
                relaxed["reason_code"] = "strong_recovery_quality_not_confirmed"
                relaxed["reason_text"] = "recovery probe 强买缺少高质量恢复确认，先按轻量恢复试探执行"
                return relaxed
            relaxed["mode"] = "strong_recovery_confirmed" if buy_tier == "strong_buy" else "recovery_probe_confirmed"
            relaxed["size_multiplier"] = 1.0
            confirmed_cap = cls._safe_float(
                normalized_gate.get("confirmed_max_position_pct"),
                normalized_gate.get("max_position_pct"),
            )
            if buy_tier == "strong_buy":
                relaxed["max_position_pct"] = cls._reduced_recovery_probe_cap(normalized_gate)
                relaxed["reason_code"] = "strong_recovery_confirmed_probe_capped"
                relaxed["reason_text"] = "recovery probe 首次恢复即使出现 strong BUY，也先按 probe cap 执行"
            else:
                relaxed["max_position_pct"] = cls._safe_float(normalized_gate.get("max_position_pct"), confirmed_cap)
                relaxed["reason_code"] = "recovery_probe_normal_confirmed"
                relaxed["reason_text"] = "recovery probe 出现 normal BUY 且趋势确认，放宽 probe 仓位上限"
            return relaxed
        if mode != "trial_light":
            return normalized_gate
        if not cls._lifecycle_gate_has_confirmed_trial_sizing(strategy_profile, normalized_gate):
            return normalized_gate
        relaxed = dict(normalized_gate)
        relaxed["mode"] = "trial_confirmed"
        relaxed["size_multiplier"] = 1.0
        relaxed["max_position_pct"] = None
        relaxed["reason_code"] = "trial_confirmed_active_like_sizing"
        relaxed["reason_text"] = "trial 中的 normal/strong BUY 已通过趋势确认，按接近 active 的仓位规则执行"
        return relaxed

    @classmethod
    def _lifecycle_gate_has_confirmed_trial_sizing(cls, strategy_profile: dict[str, Any], gate: dict[str, Any]) -> bool:
        guard = strategy_profile.get("portfolio_execution_guard") if isinstance(strategy_profile.get("portfolio_execution_guard"), dict) else {}
        buy_tier = str(guard.get("buy_tier") or "").strip().lower()
        if buy_tier not in {"normal_buy", "strong_buy"}:
            return False
        buy_strength = cls._safe_float(guard.get("buy_strength_score"), 0.0) or 0.0
        threshold = 0.45 + max(cls._safe_float(gate.get("buy_threshold_delta"), 0.0) or 0.0, 0.0)
        trend = guard.get("trend_confirmation") if isinstance(guard.get("trend_confirmation"), dict) else {}
        components = guard.get("score_components") if isinstance(guard.get("score_components"), dict) else {}
        confirmation_score = cls._safe_float(components.get("confirmation_score"), 0.0) or 0.0
        above_ma20 = int(cls._safe_float(trend.get("above_ma20_checkpoints"), 0.0) or 0)
        trend_confirmed = bool(
            trend.get("ma_stack")
            or trend.get("retest_confirmed")
            or (trend.get("ma20_rising") and above_ma20 >= 3)
            or confirmation_score >= 0.75
        )
        return buy_strength >= threshold and trend_confirmed

    @classmethod
    def _lifecycle_gate_has_confirmed_recovery_probe_sizing(
        cls,
        strategy_profile: dict[str, Any],
        gate: dict[str, Any],
    ) -> bool:
        guard = strategy_profile.get("portfolio_execution_guard") if isinstance(strategy_profile.get("portfolio_execution_guard"), dict) else {}
        buy_tier = str(guard.get("buy_tier") or "").strip().lower()
        if buy_tier not in {"normal_buy", "strong_buy"}:
            return False
        return cls._lifecycle_gate_has_confirmed_trial_sizing(strategy_profile, gate)

    @classmethod
    def _lifecycle_gate_has_high_quality_strong_recovery(
        cls,
        strategy_profile: dict[str, Any],
        gate: dict[str, Any],
    ) -> bool:
        guard = strategy_profile.get("portfolio_execution_guard") if isinstance(strategy_profile.get("portfolio_execution_guard"), dict) else {}
        buy_strength = cls._safe_float(guard.get("buy_strength_score"), 0.0) or 0.0
        if buy_strength < 0.68:
            return False
        if int(cls._safe_float(gate.get("recent_probe_loss_count"), 0.0) or 0) > 0:
            return False
        if int(cls._safe_float(gate.get("recovery_probe_attempt_count"), 0.0) or 0) >= 3:
            return False
        trend = guard.get("trend_confirmation") if isinstance(guard.get("trend_confirmation"), dict) else {}
        components = guard.get("score_components") if isinstance(guard.get("score_components"), dict) else {}
        confirmation_score = cls._safe_float(components.get("confirmation_score"), 0.0) or 0.0
        edge_strength = cls._safe_float(components.get("edge_strength"), 0.0) or 0.0
        volume_score = cls._safe_float(components.get("volume_score"), 0.0) or 0.0
        risk_penalty = cls._safe_float(components.get("risk_penalty"), 0.0) or 0.0
        above_ma20 = int(cls._safe_float(trend.get("above_ma20_checkpoints"), 0.0) or 0)
        ma20_rising = cls._truthy(trend.get("ma20_rising"))
        ma_stack = cls._truthy(trend.get("ma_stack"))
        retest_confirmed = cls._truthy(trend.get("retest_confirmed"))
        rsi = cls._safe_float(trend.get("rsi"), 0.0) or 0.0
        recent_return = cls._ratio_value(trend.get("recent_5d_return")) or 0.0
        volume_confirmed = str(trend.get("volume_confirmed") or "").strip().lower()
        if edge_strength < 0.72:
            return False
        if risk_penalty > 0.0:
            return False
        if rsi >= 72.0:
            return False
        if recent_return >= 0.04 and not retest_confirmed:
            return False
        if volume_score < 0.8 and not retest_confirmed:
            return False
        if confirmation_score < 0.65 and not (retest_confirmed or ma_stack):
            return False
        return bool(
            (retest_confirmed and (volume_confirmed == "strong" or confirmation_score >= 0.9))
            or (ma_stack and ma20_rising and above_ma20 >= 5 and confirmation_score >= 0.9 and volume_score >= 0.8)
            or (ma20_rising and above_ma20 >= 8 and confirmation_score >= 0.95 and volume_confirmed == "strong")
        )

    @classmethod
    def _lifecycle_gate_has_strong_confirmation(cls, strategy_profile: dict[str, Any], gate: dict[str, Any]) -> bool:
        guard = strategy_profile.get("portfolio_execution_guard") if isinstance(strategy_profile.get("portfolio_execution_guard"), dict) else {}
        buy_tier = str(guard.get("buy_tier") or "").strip().lower()
        buy_strength = cls._safe_float(guard.get("buy_strength_score"), 0.0) or 0.0
        threshold = 0.45 + max(cls._safe_float(gate.get("buy_threshold_delta"), 0.0) or 0.0, 0.0)
        trend = guard.get("trend_confirmation") if isinstance(guard.get("trend_confirmation"), dict) else {}
        components = guard.get("score_components") if isinstance(guard.get("score_components"), dict) else {}
        confirmation_score = cls._safe_float(components.get("confirmation_score"), 0.0) or 0.0
        above_ma20 = int(cls._safe_float(trend.get("above_ma20_checkpoints"), 0.0) or 0)
        trend_confirmed = bool(
            trend.get("ma_stack")
            or trend.get("retest_confirmed")
            or (trend.get("ma20_rising") and above_ma20 >= 3)
            or confirmation_score >= 0.75
        )
        if str(gate.get("mode") or "").strip().lower() == "cooling_supplemental":
            return buy_tier in {"normal_buy", "strong_buy"} and buy_strength >= threshold and trend_confirmed
        return buy_strength >= threshold and (buy_tier == "strong_buy" or trend_confirmed)

    @classmethod
    def _strong_recovery_probe_is_overextended_without_retest(cls, guard: dict[str, Any]) -> bool:
        trend = guard.get("trend_confirmation") if isinstance(guard.get("trend_confirmation"), dict) else {}
        if cls._truthy(trend.get("retest_confirmed")):
            return False
        recent_return = cls._ratio_value(trend.get("recent_5d_return"))
        if recent_return is None:
            return False
        volume_ratio = cls._safe_float(trend.get("volume_ratio"), 0.0) or 0.0
        return bool(recent_return >= 0.04 or volume_ratio >= 3.0)

    @classmethod
    def _reduced_recovery_probe_cap(cls, gate: dict[str, Any]) -> float:
        max_cap = cls._safe_float(gate.get("max_position_pct"), None)
        if max_cap is None:
            max_cap = cls._safe_float(gate.get("confirmed_max_position_pct"), 6.0) or 6.0
        return round(max(float(max_cap) * 0.5, 0.0), 6)

    @staticmethod
    def _ratio_value(value: Any) -> float | None:
        numeric = SignalCenterTailMixin._safe_float(value, None)
        if numeric is None:
            return None
        if abs(numeric) > 2.0:
            return numeric / 100.0
        return numeric

    def _apply_execution_sizing_plan(self, candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        if str(normalized.get("action") or "HOLD").upper() != "BUY":
            return normalized

        strategy_profile = normalized.get("strategy_profile")
        if not isinstance(strategy_profile, dict):
            strategy_profile = {}
        strategy_profile = self._ensure_kernel_positioning(
            strategy_profile,
            fallback_position_pct=self._safe_float(normalized.get("position_size_pct"), 0.0) or 0.0,
        )
        normalized["strategy_profile"] = strategy_profile
        selected = (
            strategy_profile.get("selected_strategy_profile")
            if isinstance(strategy_profile.get("selected_strategy_profile"), dict)
            else {}
        )
        profile_id = str(
            selected.get("id")
            or selected.get("profile_id")
            or strategy_profile.get("profile_id")
            or strategy_profile.get("strategy_profile_id")
            or ""
        ).strip()
        policy = default_execution_position_cap_policy(profile_id)
        summary = self.db.get_account_summary()
        stock_code = str(candidate.get("stock_code") or normalized.get("stock_code") or normalized.get("code") or "").strip()
        quant_state = self.db.get_quant_universe_state(stock_code) if stock_code else None
        quant_status = str((quant_state or {}).get("quant_status") or candidate.get("quant_status") or "active")
        strategy_profile["quant_status"] = quant_status
        total_equity = self._safe_float(summary.get("total_equity"), self._safe_float(summary.get("initial_capital"), 0.0)) or 0.0
        available_cash = self._safe_float(summary.get("available_cash"), self._safe_float(summary.get("cash"), 0.0)) or 0.0
        slot_available_cash = available_cash
        try:
            slots = self.db.get_capital_slots()
            slot_available_cash = sum(self._safe_float(slot.get("available_cash"), 0.0) or 0.0 for slot in slots) or available_cash
        except Exception:
            slot_available_cash = available_cash
        plan = build_execution_sizing_plan(
            signal=normalized,
            total_equity=total_equity,
            available_cash=available_cash,
            slot_available_cash=slot_available_cash,
            quant_status=quant_status,
            policy=policy,
            price=self._safe_float(candidate.get("latest_price"), None),
        )

        strategy_profile["execution_sizing_plan"] = plan
        normalized["strategy_profile"] = strategy_profile
        normalized["position_size_pct"] = float(plan["effective_position_pct"])
        if plan.get("skip_reason"):
            normalized["action"] = "HOLD"
            normalized["position_size_pct"] = 0.0
            normalized["decision_type"] = "execution_sizing_blocked"
            normalized["reasoning"] = f"{normalized.get('reasoning') or ''} 执行仓位阻断：{plan['skip_reason']}。".strip()
        return normalized

    @staticmethod
    def _ensure_kernel_positioning(
        strategy_profile: dict[str, Any],
        *,
        fallback_position_pct: float = 0.0,
    ) -> dict[str, Any]:
        normalized = dict(strategy_profile)
        if isinstance(normalized.get("kernel_positioning"), dict):
            return normalized
        explainability = normalized.get("explainability") if isinstance(normalized.get("explainability"), dict) else {}
        resonance = explainability.get("resonance") if isinstance(explainability.get("resonance"), dict) else {}
        quality_ratio = resonance.get("quality_adjusted_position_ratio")
        if quality_ratio is not None:
            try:
                quality_position_pct = round(float(quality_ratio) * 100.0, 6)
            except (TypeError, ValueError):
                quality_position_pct = None
            if quality_position_pct is not None:
                normalized["kernel_positioning"] = {
                    "quality_position_pct": quality_position_pct,
                    "rule_hit": resonance.get("rule_hit"),
                    "signal_quality_score": resonance.get("signal_quality_score"),
                    "quality_components": resonance.get("quality_components") if isinstance(resonance.get("quality_components"), dict) else {},
                    "quality_penalties": resonance.get("quality_penalties") if isinstance(resonance.get("quality_penalties"), dict) else {},
                }
                return normalized

        guard = (
            normalized.get("portfolio_execution_guard")
            if isinstance(normalized.get("portfolio_execution_guard"), dict)
            else {}
        )
        has_structured_strategy_context = bool(
            normalized.get("selected_strategy_profile")
            or normalized.get("explainability")
        )
        if not has_structured_strategy_context:
            return normalized
        buy_strength = SignalCenterTailMixin._safe_float(guard.get("buy_strength_score"), None)
        if buy_strength is None:
            return normalized
        buy_tier = str(guard.get("buy_tier") or "").strip().lower()
        if buy_tier not in {"weak_buy", "normal_buy", "strong_buy"} and buy_strength <= 0:
            return normalized
        strength = SignalCenterTailMixin._clamp(buy_strength, 0.0, 1.0)
        quality_position_pct = round(max(0.0, fallback_position_pct) * strength, 6)
        normalized["kernel_positioning"] = {
            "quality_position_pct": quality_position_pct,
            "rule_hit": "non_resonance_guard_quality",
            "signal_quality_score": round(strength, 6),
            "quality_components": {
                "buy_strength_score": round(strength, 6),
                "raw_position_pct": round(max(0.0, fallback_position_pct), 6),
            },
            "quality_penalties": {},
        }
        return normalized

    def _portfolio_execution_guard_policy(self, strategy_profile: dict[str, Any]) -> dict[str, Any]:
        selected = strategy_profile.get("selected_strategy_profile") if isinstance(strategy_profile.get("selected_strategy_profile"), dict) else {}
        profile_id = str(selected.get("id") or "").strip()
        for candidate in (
            strategy_profile.get("portfolio_execution_guard_policy"),
            (strategy_profile.get("effective_thresholds") or {}).get("portfolio_execution_guard_policy")
            if isinstance(strategy_profile.get("effective_thresholds"), dict)
            else None,
        ):
            if isinstance(candidate, dict):
                return normalize_portfolio_execution_guard_policy(candidate, profile_id=profile_id)
        return normalize_portfolio_execution_guard_policy(None, profile_id=profile_id)

    def _stock_execution_feedback_policy(self, strategy_profile: dict[str, Any]) -> dict[str, Any]:
        selected = strategy_profile.get("selected_strategy_profile") if isinstance(strategy_profile.get("selected_strategy_profile"), dict) else {}
        profile_id = str(selected.get("id") or "").strip()
        for candidate in (
            strategy_profile.get("stock_execution_feedback_policy"),
            (strategy_profile.get("effective_thresholds") or {}).get("stock_execution_feedback_policy")
            if isinstance(strategy_profile.get("effective_thresholds"), dict)
            else None,
        ):
            if isinstance(candidate, dict):
                return normalize_stock_execution_feedback_policy(candidate, profile_id=profile_id)
        return normalize_stock_execution_feedback_policy(None, profile_id=profile_id)

    def _last_profit_sell(self, stock_code: str) -> dict[str, Any] | None:
        for signal in self.db.get_signals(stock_code=stock_code, limit=20):
            if str(signal.get("status") or "").lower() != "executed":
                continue
            if str(signal.get("executed_action") or signal.get("action") or "").upper() != "SELL":
                continue
            profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
            explainability = profile.get("explainability") if isinstance(profile.get("explainability"), dict) else {}
            fusion = explainability.get("fusion_breakdown") if isinstance(explainability.get("fusion_breakdown"), dict) else {}
            veto_id = str(fusion.get("veto_id") or fusion.get("veto_trigger_type") or "").strip()
            if veto_id == "profit_tech_sell":
                return signal
            return None
        return None

    def _extract_reentry_market_metrics(self, candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, float | str | None]:
        profile = payload.get("strategy_profile") if isinstance(payload.get("strategy_profile"), dict) else {}
        snapshot = profile.get("market_snapshot") if isinstance(profile.get("market_snapshot"), dict) else {}
        price = (
            self._safe_float(snapshot.get("current_price"), None)
            or self._safe_float(snapshot.get("latest_price"), None)
            or self._safe_float(candidate.get("latest_price"), None)
        )
        ma20 = self._safe_float(snapshot.get("ma20"), None)
        distance = None
        if price is not None and ma20 is not None and ma20 > 0:
            distance = (price - ma20) / ma20 * 100.0
        return {
            "price": price,
            "ma5": self._safe_float(snapshot.get("ma5"), None),
            "ma10": self._safe_float(snapshot.get("ma10"), None),
            "ma20": ma20,
            "ma60": self._safe_float(snapshot.get("ma60"), None),
            "ma20_slope": self._safe_float(snapshot.get("ma20_slope"), None),
            "rsi12": self._safe_float(snapshot.get("rsi12") if snapshot.get("rsi12") is not None else snapshot.get("rsi"), None),
            "macd": self._safe_float(snapshot.get("macd"), None),
            "ma20_distance_pct": distance,
            "update_time": snapshot.get("update_time"),
        }

    def _is_reentry_trend_confirmed(self, metrics: dict[str, Any]) -> bool:
        price = self._safe_float(metrics.get("price"), None)
        ma5 = self._safe_float(metrics.get("ma5"), None)
        ma10 = self._safe_float(metrics.get("ma10"), None)
        ma20 = self._safe_float(metrics.get("ma20"), None)
        ma60 = self._safe_float(metrics.get("ma60"), None)
        ma20_slope = self._safe_float(metrics.get("ma20_slope"), None)
        macd = self._safe_float(metrics.get("macd"), None)
        if price is None or ma20 is None:
            return False
        ma_stack = ma5 is not None and ma10 is not None and ma5 > ma10 > ma20 and price > ma20
        above_major_ma = ma60 is not None and price > ma20 and price > ma60 and (ma20_slope is None or ma20_slope >= 0)
        macd_ok = macd is None or macd >= 0
        return bool((ma_stack or above_major_ma) and macd_ok)

    @staticmethod
    def _is_strong_reentry_resonance(strategy_profile: dict[str, Any]) -> bool:
        explainability = strategy_profile.get("explainability") if isinstance(strategy_profile.get("explainability"), dict) else {}
        dual = explainability.get("dual_track") if isinstance(explainability.get("dual_track"), dict) else {}
        if not dual:
            dual = explainability.get("final") if isinstance(explainability.get("final"), dict) else {}
        tech_signal = str(dual.get("tech_signal") or "").upper()
        context_signal = str(dual.get("context_signal") or "").upper()
        resonance_type = str(dual.get("resonance_type") or "").lower()
        return (tech_signal == "BUY" and context_signal == "BUY") or resonance_type in {"strong_buy", "bullish_resonance", "heavy_resonance"}

    @classmethod
    def _is_hard_exit_sell(cls, payload: dict[str, Any]) -> bool:
        if bool(payload.get("quick_stoploss_failure")):
            return True
        decision_type = str(payload.get("decision_type") or "").strip().lower()
        if any(token in decision_type for token in _HARD_EXIT_SELL_TOKENS):
            return True
        return cls._sell_veto_id(payload) in _HARD_EXIT_VETO_IDS

    @staticmethod
    def _is_dual_track_sell(payload: dict[str, Any]) -> bool:
        decision_type = str(payload.get("decision_type") or "").strip().lower()
        if decision_type == "dual_track_weighted_sell":
            return True
        fusion_breakdown = SignalCenterTailMixin._fusion_breakdown(payload)
        final_action = str(fusion_breakdown.get("final_action") or "").strip().upper()
        raw_action = str(
            fusion_breakdown.get("weighted_action_raw") or fusion_breakdown.get("weighted_threshold_action") or ""
        ).strip().upper()
        return final_action == "SELL" and raw_action == "SELL"

    @classmethod
    def _sell_veto_id(cls, payload: dict[str, Any]) -> str:
        for key in ("veto_id", "veto_trigger_type", "trigger_type"):
            value = str(payload.get(key) or "").strip().lower()
            if value:
                return value
        fusion_breakdown = cls._fusion_breakdown(payload)
        for key in ("veto_id", "veto_trigger_type", "trigger_type"):
            value = str(fusion_breakdown.get(key) or "").strip().lower()
            if value:
                return value
        return ""

    @staticmethod
    def _fusion_breakdown(payload: dict[str, Any]) -> dict[str, Any]:
        strategy_profile = payload.get("strategy_profile")
        if not isinstance(strategy_profile, dict):
            return {}
        explainability = strategy_profile.get("explainability")
        if not isinstance(explainability, dict):
            return {}
        fusion_breakdown = explainability.get("fusion_breakdown")
        return fusion_breakdown if isinstance(fusion_breakdown, dict) else {}

    def _resolve_reentry_time(self, payload: dict[str, Any], metrics: dict[str, Any]) -> datetime | None:
        for value in (metrics.get("update_time"), payload.get("decision_time")):
            parsed = self._parse_datetime(value)
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if value in (None, ""):
            return None
        try:
            return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            try:
                return datetime.strptime(str(value).strip()[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                return None

    def _current_position(self, stock_code: str) -> dict[str, Any] | None:
        code = str(stock_code or "").strip()
        if not code:
            return None
        for position in self.db.get_positions():
            if str(position.get("stock_code") or "").strip() == code:
                return position
        return None

    @staticmethod
    def _safe_float(value: Any, default: float | None = None) -> float | None:
        try:
            if value in (None, ""):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    @staticmethod
    def _truthy(value: Any) -> bool:
        text = str(value or "").strip().lower()
        return text in {"1", "true", "yes", "y", "on"}

    def _sanitize_pending_sell_signals_without_position(self) -> None:
        for signal in self.db.get_pending_signals():
            if str(signal.get("action", "")).upper() != "SELL":
                continue
            stock_code = str(signal.get("stock_code") or "").strip()
            if not stock_code or self.db.has_open_position(stock_code):
                continue

            downgraded = self._downgrade_sell_without_position(signal)
            self.db.update_signal_state(
                int(signal["id"]),
                action=downgraded["action"],
                reasoning=downgraded["reasoning"],
                position_size_pct=float(downgraded.get("position_size_pct", 0)),
                status="observed",
            )

    @staticmethod
    def _downgrade_sell_without_position(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        reasoning = str(normalized.get("reasoning") or "").strip()
        normalized["action"] = "HOLD"
        normalized["position_size_pct"] = 0
        normalized["reasoning"] = (
            f"{reasoning} 当前无持仓，转为HOLD观察。".strip()
            if reasoning
            else "当前无持仓，转为HOLD观察。"
        )
        return normalized

    def _mirror_signal_to_ai_decision(self, candidate: dict[str, Any], payload: dict[str, Any]) -> None:
        if self.smart_monitor_db is None:
            return
        stock_code = str(candidate.get("stock_code") or "").strip()
        if not stock_code:
            return
        strategy_profile = payload.get("strategy_profile") if isinstance(payload.get("strategy_profile"), dict) else {}
        ai_overlay = strategy_profile.get("ai_overlay") if isinstance(strategy_profile.get("ai_overlay"), dict) else {}
        dynamic_risk = ai_overlay.get("dynamic_risk") if isinstance(ai_overlay.get("dynamic_risk"), dict) else {}
        key_levels = ai_overlay.get("key_levels") if isinstance(ai_overlay.get("key_levels"), dict) else {}
        account_posture = ai_overlay.get("account_posture") if isinstance(ai_overlay.get("account_posture"), dict) else {}

        try:
            self.smart_monitor_db.save_ai_decision(
                {
                    "stock_code": stock_code,
                    "stock_name": candidate.get("stock_name"),
                    "decision_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "trading_session": "quant_signal_center",
                    "action": str(payload.get("action") or "HOLD").upper(),
                    "confidence": int(self._safe_float(payload.get("confidence"), 0) or 0),
                    "reasoning": str(payload.get("reasoning") or ""),
                    "position_size_pct": float(self._safe_float(payload.get("position_size_pct"), 0) or 0),
                    "stop_loss_pct": float(self._safe_float(dynamic_risk.get("stop_loss_pct"), payload.get("stop_loss_pct")) or 0),
                    "take_profit_pct": float(self._safe_float(dynamic_risk.get("take_profit_pct"), payload.get("take_profit_pct")) or 0),
                    "risk_level": "medium",
                    "key_price_levels": key_levels,
                    "market_data": {},
                    "account_info": {
                        "available_cash": account_posture.get("available_cash"),
                        "total_value": account_posture.get("total_equity"),
                        "positions_count": 1 if account_posture.get("has_position") else 0,
                    },
                }
            )
        except Exception:
            return

    def _dispatch_live_signal_notification(
        self,
        candidate: dict[str, Any],
        signal: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        action = str(signal.get("action") or payload.get("action") or "HOLD").upper()
        if action not in {"BUY", "SELL"}:
            return

        stock_code = str(candidate.get("stock_code") or signal.get("stock_code") or "").strip()
        if not stock_code:
            return

        stock_name = str(candidate.get("stock_name") or signal.get("stock_name") or stock_code)
        latest_price = self._safe_float(candidate.get("latest_price"), None)
        if latest_price is None:
            latest_price = self._safe_float(signal.get("latest_price"), None)

        position = None
        for item in self.db.get_positions():
            if str(item.get("stock_code") or "").strip() == stock_code:
                position = item
                break

        triggered_at = str(signal.get("updated_at") or signal.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        message = str(signal.get("reasoning") or payload.get("reasoning") or "").strip()
        if len(message) > 1000:
            message = f"{message[:1000]}..."

        notification_payload = {
            "symbol": stock_code,
            "name": stock_name,
            "type": action,
            "message": message or f"{stock_code} generated {action} signal.",
            "triggered_at": triggered_at,
            "current_price": f"{latest_price:.4f}" if latest_price is not None else "N/A",
            "position_status": "holding" if position else "flat",
            "position_cost": f"{float(position.get('avg_price') or 0):.4f}" if position else "N/A",
            "profit_loss_pct": f"{float(position.get('unrealized_pnl_pct') or 0):.2f}" if position else "N/A",
            "trading_session": "quant_live_sim",
        }

        try:
            notification_service.send_notification(notification_payload)
        except Exception:
            return
