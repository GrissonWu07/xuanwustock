"""Signal creation and listing helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.db.runtime.registry import DatabaseRuntime
from app.notification_service import notification_service
from app.quant_sim.db import DEFAULT_DB_FILE, QuantSimDB
from app.quant_kernel.models import Decision
from app.quant_sim.stock_execution_feedback import (
    evaluate_stock_execution_feedback_gate,
    normalize_stock_execution_feedback_policy,
)
from app.quant_sim.portfolio_execution_guard import (
    evaluate_portfolio_execution_guard,
    normalize_portfolio_execution_guard_policy,
)
from app.quant_sim.execution_sizing import build_execution_sizing_plan, default_execution_position_cap_policy
from app.smart_monitor_db import SmartMonitorDB, DEFAULT_DB_FILE as SMART_MONITOR_DB_FILE


class SignalCenterService:
    """Normalizes strategy decisions into persisted signals."""

    def __init__(
        self,
        db_file: str | Path = DEFAULT_DB_FILE,
        *,
        db_runtime: DatabaseRuntime | None = None,
    ):
        self.db_file = Path(db_file)
        self.external_side_effects_enabled = self._is_default_db_file(self.db_file)
        self.db_runtime = db_runtime
        self.db = QuantSimDB(db_file, db_runtime=db_runtime)
        self.smart_monitor_db: SmartMonitorDB | None = None
        if self.external_side_effects_enabled:
            try:
                self.smart_monitor_db = SmartMonitorDB(str(SMART_MONITOR_DB_FILE), db_runtime=db_runtime)
            except Exception:
                self.smart_monitor_db = None

    def create_signal(
        self,
        candidate: dict[str, Any],
        decision: dict[str, Any] | Decision,
        *,
        notify: bool = True,
        mirror_to_ai: bool | None = None,
        dedupe_pending: bool = True,
    ) -> dict[str, Any]:
        if mirror_to_ai is None:
            mirror_to_ai = notify
        payload = self.build_signal_payload(candidate, decision)
        action = str(payload.get("action", "HOLD")).upper()
        status = "pending" if action in {"BUY", "SELL"} else "observed"
        existing_pending_ids = {
            int(item.get("id"))
            for item in self.db.get_signals(stock_code=candidate["stock_code"], limit=50)
            if str(item.get("status", "")).lower() == "pending"
            and str(item.get("action", "")).upper() == action
            and item.get("id") is not None
        }
        signal_id = self.db.add_signal(
            {
                "candidate_id": candidate.get("id"),
                "stock_code": candidate["stock_code"],
                "stock_name": candidate.get("stock_name"),
                "action": action,
                "confidence": int(payload.get("confidence", 0)),
                "reasoning": payload.get("reasoning", ""),
                "position_size_pct": float(payload.get("position_size_pct", 0)),
                "stop_loss_pct": float(payload.get("stop_loss_pct", 5)),
                "take_profit_pct": float(payload.get("take_profit_pct", 12)),
                "decision_type": payload.get("decision_type"),
                "tech_score": float(payload.get("tech_score", 0)),
                "context_score": float(payload.get("context_score", 0)),
                "strategy_profile": payload.get("strategy_profile"),
                "status": status,
            },
            dedupe_pending=dedupe_pending,
        )
        if mirror_to_ai and self.external_side_effects_enabled:
            self._mirror_signal_to_ai_decision(candidate, payload)
        signal = self.db.get_signals(stock_code=candidate["stock_code"], limit=1)[0]
        if (
            notify
            and self.external_side_effects_enabled
            and status == "pending"
            and int(signal_id) not in existing_pending_ids
        ):
            self._dispatch_live_signal_notification(candidate, signal, payload)
        return signal

    def build_signal_payload(self, candidate: dict[str, Any], decision: dict[str, Any] | Decision) -> dict[str, Any]:
        payload = self._normalize_decision_payload(decision)
        payload = self._apply_position_constraints(candidate, payload)
        payload = self._apply_position_add_gate(candidate, payload)
        payload = self._apply_reentry_constraints(candidate, payload)
        payload = self._apply_stock_execution_feedback(candidate, payload)
        payload = self._apply_portfolio_execution_guard(candidate, payload)
        payload = self._apply_lifecycle_gate_profile(candidate, payload)
        payload = self._apply_execution_sizing_plan(candidate, payload)
        payload = self._apply_transaction_cost_constraints(candidate, payload)
        payload = self._apply_lifecycle_exit_only_guard(candidate, payload)
        action = str(payload.get("action", "HOLD")).upper()
        if action == "HOLD":
            payload["position_size_pct"] = 0
        return payload

    @staticmethod
    def _is_default_db_file(db_file: str | Path) -> bool:
        try:
            return Path(db_file).expanduser().resolve() == Path(DEFAULT_DB_FILE).expanduser().resolve()
        except Exception:
            return str(db_file) == str(DEFAULT_DB_FILE)

    def list_pending_signals(self) -> list[dict[str, Any]]:
        self._sanitize_pending_sell_signals_without_position()
        return self.db.get_pending_signals()

    def list_signals(self, stock_code: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        return self.db.get_signals(stock_code=stock_code, limit=limit)

    @staticmethod
    def _normalize_decision_payload(decision: dict[str, Any] | Decision) -> dict[str, Any]:
        if isinstance(decision, Decision):
            confidence = decision.confidence * 100 if decision.confidence <= 1 else decision.confidence
            payload = {
                "action": decision.action,
                "confidence": round(confidence),
                "reasoning": decision.reason,
                "position_size_pct": round(decision.position_ratio * 100, 2),
                "stop_loss_pct": 5,
                "take_profit_pct": 12,
                "decision_type": decision.decision_type,
                "tech_score": decision.tech_score,
                "context_score": decision.context_score,
                "strategy_profile": decision.strategy_profile,
                "decision_time": decision.timestamp,
            }
            return SignalCenterService._apply_canonical_scores(payload)

        position_size = decision.get("position_size_pct")
        if position_size is None and "position_ratio" in decision:
            position_size = float(decision.get("position_ratio", 0)) * 100
        payload = {
            "action": decision.get("action", "HOLD"),
            "confidence": decision.get("confidence", 0),
            "reasoning": decision.get("reasoning", decision.get("reason", "")),
            "position_size_pct": position_size or 0,
            "stop_loss_pct": decision.get("stop_loss_pct", 5),
            "take_profit_pct": decision.get("take_profit_pct", 12),
            "decision_type": decision.get("decision_type"),
            "tech_score": decision.get("tech_score", 0),
            "context_score": decision.get("context_score", 0),
            "strategy_profile": decision.get("strategy_profile"),
            "decision_time": decision.get("timestamp") or decision.get("decision_time") or decision.get("checkpoint_at"),
        }
        return SignalCenterService._apply_canonical_scores(payload)

    @staticmethod
    def _apply_canonical_scores(payload: dict[str, Any]) -> dict[str, Any]:
        strategy_profile = payload.get("strategy_profile")
        if not isinstance(strategy_profile, dict):
            return payload
        explainability = strategy_profile.get("explainability")
        if not isinstance(explainability, dict):
            return payload
        fusion_breakdown = explainability.get("fusion_breakdown")
        if not isinstance(fusion_breakdown, dict):
            return payload

        normalized = dict(payload)
        for source_key, target_key in (("tech_score", "tech_score"), ("context_score", "context_score")):
            value = SignalCenterService._safe_float(fusion_breakdown.get(source_key), None)
            if value is not None:
                normalized[target_key] = value

        confidence = SignalCenterService._safe_float(fusion_breakdown.get("fusion_confidence"), None)
        if confidence is not None:
            normalized["confidence"] = int(confidence * 100 if confidence <= 1 else confidence)
        return normalized

    def _apply_position_constraints(self, candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        stock_code = str(candidate.get("stock_code") or "").strip()
        action = str(normalized.get("action", "HOLD")).upper()

        if action == "SELL" and stock_code and not self.db.has_open_position(stock_code):
            normalized = self._downgrade_sell_without_position(normalized)

        return normalized

    def _apply_position_add_gate(self, candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        action = str(normalized.get("action") or "HOLD").upper()
        stock_code = str(candidate.get("stock_code") or "").strip()
        if action != "BUY" or not stock_code:
            return normalized

        current_position = self._current_position(stock_code)
        if not current_position:
            return normalized

        strategy_profile = normalized.get("strategy_profile")
        if not isinstance(strategy_profile, dict):
            strategy_profile = {}
        normalized["strategy_profile"] = strategy_profile

        thresholds = strategy_profile.get("effective_thresholds")
        if not isinstance(thresholds, dict):
            thresholds = {}
        strategy_profile["effective_thresholds"] = thresholds

        explainability = strategy_profile.get("explainability")
        if not isinstance(explainability, dict):
            explainability = {}
        strategy_profile["explainability"] = explainability
        fusion_breakdown = explainability.get("fusion_breakdown")
        if not isinstance(fusion_breakdown, dict):
            fusion_breakdown = {}

        allow_pyramiding = self._truthy(thresholds.get("allow_pyramiding"))
        target_position_pct = self._safe_float(normalized.get("position_size_pct"), 0.0) or 0.0
        max_position_ratio = self._safe_float(thresholds.get("max_position_ratio"), None)
        max_position_pct = (max_position_ratio * 100.0) if max_position_ratio and max_position_ratio > 0 else 100.0
        target_position_pct = round(self._clamp(target_position_pct, 0.0, max_position_pct), 2)

        summary = self.db.get_account_summary()
        total_equity = self._safe_float(summary.get("total_equity"), 0.0) or 0.0
        market_value = self._safe_float(current_position.get("market_value"), 0.0) or 0.0
        if market_value <= 0:
            quantity = self._safe_float(current_position.get("quantity"), 0.0) or 0.0
            latest_price = (
                self._safe_float(candidate.get("latest_price"), None)
                or self._safe_float(current_position.get("latest_price"), None)
                or self._safe_float(current_position.get("avg_price"), 0.0)
                or 0.0
            )
            market_value = quantity * latest_price
        current_position_pct = round((market_value / total_equity * 100.0) if total_equity > 0 else 0.0, 2)
        capacity_delta_pct = round(max(0.0, max_position_pct - current_position_pct), 2)
        target_delta_pct = round(max(0.0, target_position_pct - current_position_pct), 2)
        add_position_delta_pct = round(min(target_delta_pct, capacity_delta_pct), 2)

        unrealized_pnl_pct = self._safe_float(current_position.get("unrealized_pnl_pct"), 0.0) or 0.0
        min_unrealized_pnl_pct = self._safe_float(thresholds.get("add_min_unrealized_pnl_pct"), 2.0) or 2.0
        min_tech_score = self._safe_float(thresholds.get("add_min_tech_score"), 0.25) or 0.25
        min_fusion_confidence = self._safe_float(
            thresholds.get("add_min_fusion_confidence"),
            self._safe_float(thresholds.get("min_fusion_confidence"), 0.0),
        )
        if min_fusion_confidence is None:
            min_fusion_confidence = 0.0
        tech_score = self._safe_float(
            fusion_breakdown.get("tech_score"),
            self._safe_float(normalized.get("tech_score"), 0.0),
        )
        if tech_score is None:
            tech_score = 0.0
        fusion_confidence = self._safe_float(
            fusion_breakdown.get("fusion_confidence"),
            (self._safe_float(normalized.get("confidence"), 0.0) or 0.0) / 100.0,
        )
        if fusion_confidence is None:
            fusion_confidence = 0.0

        profit_gate_passed = unrealized_pnl_pct >= min_unrealized_pnl_pct
        trend_gate_passed = tech_score >= min_tech_score and fusion_confidence >= min_fusion_confidence
        capacity_gate_passed = add_position_delta_pct > 0
        reasons: list[str] = []
        if not allow_pyramiding:
            reasons.append("策略阈值不允许加仓")
        if not capacity_gate_passed:
            reasons.append("当前持仓已达到目标或上限")
        if not (profit_gate_passed or trend_gate_passed):
            reasons.append(
                "未满足已有浮盈或强趋势确认："
                f"浮盈 {unrealized_pnl_pct:.2f}% / 门槛 {min_unrealized_pnl_pct:.2f}%，"
                f"技术分 {tech_score:.4f} / 门槛 {min_tech_score:.4f}"
            )
        if profit_gate_passed:
            reasons.append(f"已有浮盈 {unrealized_pnl_pct:.2f}% >= {min_unrealized_pnl_pct:.2f}%")
        if trend_gate_passed:
            reasons.append(f"趋势确认 技术分 {tech_score:.4f} >= {min_tech_score:.4f}")

        passed = allow_pyramiding and capacity_gate_passed and (profit_gate_passed or trend_gate_passed)
        gate = {
            "intent": "position_add",
            "status": "passed" if passed else "blocked",
            "allow_pyramiding": allow_pyramiding,
            "current_position_pct": current_position_pct,
            "target_position_pct": target_position_pct,
            "max_position_pct": round(max_position_pct, 2),
            "capacity_delta_pct": capacity_delta_pct,
            "add_position_delta_pct": add_position_delta_pct if passed else 0.0,
            "unrealized_pnl_pct": round(unrealized_pnl_pct, 4),
            "min_unrealized_pnl_pct": round(min_unrealized_pnl_pct, 4),
            "tech_score": round(tech_score, 6),
            "min_tech_score": round(min_tech_score, 6),
            "fusion_confidence": round(fusion_confidence, 6),
            "min_fusion_confidence": round(float(min_fusion_confidence), 6),
            "profit_gate_passed": profit_gate_passed,
            "trend_gate_passed": trend_gate_passed,
            "capacity_gate_passed": capacity_gate_passed,
            "reasons": reasons,
        }
        strategy_profile["position_add_gate"] = gate
        strategy_profile["execution_intent"] = "position_add" if passed else "position_add_blocked"
        thresholds.setdefault("add_min_unrealized_pnl_pct", round(min_unrealized_pnl_pct, 4))
        thresholds.setdefault("add_min_tech_score", round(min_tech_score, 6))
        thresholds.setdefault("add_min_fusion_confidence", round(float(min_fusion_confidence), 6))

        base_reasoning = str(normalized.get("reasoning") or "").strip()
        if passed:
            normalized["position_size_pct"] = add_position_delta_pct
            normalized["decision_type"] = "position_add"
            normalized["reasoning"] = (
                f"{base_reasoning} 持仓加仓门控通过：目标 {target_position_pct:.2f}% ，"
                f"当前 {current_position_pct:.2f}% ，本次按差额加仓 {add_position_delta_pct:.2f}% 。"
            ).strip()
            return normalized

        normalized["action"] = "HOLD"
        normalized["position_size_pct"] = 0.0
        normalized["decision_type"] = "position_add_blocked"
        normalized["confidence"] = round(self._clamp((self._safe_float(normalized.get("confidence"), 0.0) or 0.0) * 0.7, 0.0, 100.0))
        normalized["reasoning"] = (
            f"{base_reasoning} 持仓加仓门控未通过：{'；'.join(reasons)}，转为HOLD。"
        ).strip()
        return normalized

    def _apply_lifecycle_exit_only_guard(self, candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        action = str(normalized.get("action") or "HOLD").upper()
        if action not in {"BUY", "ADD"}:
            return normalized
        quant_status = str(candidate.get("quant_status") or "").strip()
        if quant_status != "exit_only":
            stock_code = str(candidate.get("stock_code") or "").strip()
            state = self.db.get_quant_universe_state(stock_code) if stock_code else None
            quant_status = str((state or {}).get("quant_status") or "").strip()
        if quant_status != "exit_only":
            return normalized

        strategy_profile = normalized.get("strategy_profile")
        if not isinstance(strategy_profile, dict):
            strategy_profile = {}
        strategy_profile = dict(strategy_profile)
        explainability = strategy_profile.get("explainability")
        if not isinstance(explainability, dict):
            explainability = {}
        explainability = dict(explainability)
        explainability["lifecycle"] = {
            "quant_status": "exit_only",
            "status": "blocked",
            "original_action": action,
            "reason": "exit_only 状态只允许 SELL/HOLD，禁止新 BUY 或加仓。",
        }
        strategy_profile["explainability"] = explainability
        normalized["strategy_profile"] = strategy_profile
        normalized["action"] = "HOLD"
        normalized["position_size_pct"] = 0.0
        normalized["decision_type"] = "exit_only_blocked"
        base_reasoning = str(normalized.get("reasoning") or "").strip()
        normalized["reasoning"] = f"{base_reasoning} 生命周期门控：exit_only 只出场管理，禁止新买入或加仓，转为HOLD。".strip()
        return normalized

    def _apply_transaction_cost_constraints(self, candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        action = str(normalized.get("action") or "HOLD").upper()
        if action not in {"BUY", "SELL"}:
            return normalized

        strategy_profile = normalized.get("strategy_profile")
        has_structured_profile = isinstance(strategy_profile, dict) and bool(strategy_profile)
        if not isinstance(strategy_profile, dict):
            strategy_profile = {}
        if action == "SELL" and not has_structured_profile:
            return normalized

        scheduler_config = self.db.get_scheduler_config()
        commission_rate = max(self._safe_float(scheduler_config.get("commission_rate"), 0.0) or 0.0, 0.0)
        sell_tax_rate = max(self._safe_float(scheduler_config.get("sell_tax_rate"), 0.0) or 0.0, 0.0)
        roundtrip_cost_pct = round((commission_rate * 2.0 + sell_tax_rate) * 100.0, 4)
        sell_side_cost_pct = round((commission_rate + sell_tax_rate) * 100.0, 4)
        min_buy_edge_pct = round(roundtrip_cost_pct + 0.2, 4)
        thresholds = strategy_profile.get("effective_thresholds")
        if not isinstance(thresholds, dict):
            thresholds = {}
        thresholds["commission_rate"] = round(commission_rate, 8)
        thresholds["sell_tax_rate"] = round(sell_tax_rate, 8)
        thresholds["roundtrip_cost_pct"] = roundtrip_cost_pct
        thresholds["sell_side_cost_pct"] = sell_side_cost_pct
        strategy_profile["effective_thresholds"] = thresholds
        strategy_profile["cost_model"] = {
            "commission_rate": round(commission_rate, 8),
            "sell_tax_rate": round(sell_tax_rate, 8),
            "roundtrip_cost_pct": roundtrip_cost_pct,
            "sell_side_cost_pct": sell_side_cost_pct,
            "buy_min_edge_pct": min_buy_edge_pct,
        }
        normalized["strategy_profile"] = strategy_profile

        reasoning = str(normalized.get("reasoning") or "").strip()
        confidence = self._safe_float(normalized.get("confidence"), 0.0) or 0.0

        if action == "BUY":
            take_profit_pct = self._safe_float(normalized.get("take_profit_pct"), 0.0) or 0.0
            if take_profit_pct > 0 and take_profit_pct <= min_buy_edge_pct:
                normalized["action"] = "HOLD"
                normalized["position_size_pct"] = 0.0
                normalized["confidence"] = round(self._clamp(confidence * 0.6, 0.0, 100.0))
                normalized["reasoning"] = (
                    f"{reasoning} 交易成本校正：双边成本约 {roundtrip_cost_pct:.3f}% ，高于可用止盈空间 "
                    f"{take_profit_pct:.3f}% ，转为HOLD观察。".strip()
                )
                return normalized

            normalized["confidence"] = round(self._clamp(confidence - min(8.0, roundtrip_cost_pct * 8.0), 0.0, 100.0))
            normalized["reasoning"] = f"{reasoning} 已计入交易成本：双边成本约 {roundtrip_cost_pct:.3f}% 。".strip()
            return normalized

        stock_code = str(candidate.get("stock_code") or "").strip()
        current_position = None
        if stock_code:
            for position in self.db.get_positions():
                if str(position.get("stock_code") or "").strip() == stock_code:
                    current_position = position
                    break
        unrealized_pnl_pct = self._safe_float((current_position or {}).get("unrealized_pnl_pct"), None)
        if unrealized_pnl_pct is not None and unrealized_pnl_pct >= 0 and unrealized_pnl_pct < sell_side_cost_pct and confidence < 80:
            normalized["action"] = "HOLD"
            normalized["position_size_pct"] = 0.0
            normalized["confidence"] = round(self._clamp(confidence * 0.7, 0.0, 100.0))
            normalized["reasoning"] = (
                f"{reasoning} 交易成本校正：当前浮盈 {unrealized_pnl_pct:.3f}% 尚未覆盖卖出成本 "
                f"{sell_side_cost_pct:.3f}% ，转为HOLD等待更优退出。".strip()
            )
            return normalized

        normalized["confidence"] = round(self._clamp(confidence - min(6.0, sell_side_cost_pct * 8.0), 0.0, 100.0))
        normalized["reasoning"] = f"{reasoning} 已计入卖出成本：预计单次退出成本约 {sell_side_cost_pct:.3f}% 。".strip()
        return normalized

    def _apply_reentry_constraints(self, candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        action = str(normalized.get("action") or "HOLD").upper()
        stock_code = str(candidate.get("stock_code") or "").strip()
        if action != "BUY" or not stock_code:
            return normalized
        if self._current_position(stock_code):
            return normalized

        strategy_profile = normalized.get("strategy_profile")
        if not isinstance(strategy_profile, dict):
            strategy_profile = {}
        thresholds = strategy_profile.get("effective_thresholds")
        if not isinstance(thresholds, dict):
            thresholds = {}

        metrics = self._extract_reentry_market_metrics(candidate, normalized)
        current_time = self._resolve_reentry_time(normalized, metrics)
        last_profit_sell = self._last_profit_sell(stock_code)
        days_since_profit_sell = None
        if last_profit_sell and current_time is not None:
            last_sell_time = self._parse_datetime(last_profit_sell.get("executed_at") or last_profit_sell.get("updated_at"))
            if last_sell_time is not None:
                days_since_profit_sell = max((current_time.date() - last_sell_time.date()).days, 0)

        cooldown_days = int(self._safe_float(thresholds.get("profit_reentry_cooldown_days"), 5) or 5)
        hot_rsi = self._safe_float(thresholds.get("profit_reentry_hot_rsi"), 75.0) or 75.0
        very_hot_rsi = self._safe_float(thresholds.get("profit_reentry_very_hot_rsi"), 85.0) or 85.0
        extreme_rsi = self._safe_float(thresholds.get("profit_reentry_extreme_rsi"), 88.0) or 88.0
        extreme_ma20_distance_pct = self._safe_float(thresholds.get("profit_reentry_extreme_ma20_distance_pct"), 5.0) or 5.0
        base_reentry_multiplier = self._safe_float(thresholds.get("profit_reentry_size_multiplier"), 0.5) or 0.5
        hot_multiplier = self._safe_float(thresholds.get("profit_reentry_hot_rsi_size_multiplier"), 0.5) or 0.5
        very_hot_multiplier = self._safe_float(thresholds.get("profit_reentry_very_hot_rsi_size_multiplier"), 0.25) or 0.25

        trend_confirmed = self._is_reentry_trend_confirmed(metrics)
        strong_resonance = self._is_strong_reentry_resonance(strategy_profile)
        rsi12 = metrics.get("rsi12")
        ma20_distance_pct = metrics.get("ma20_distance_pct")
        within_profit_reentry = bool(
            last_profit_sell
            and days_since_profit_sell is not None
            and days_since_profit_sell <= cooldown_days
        )

        reasons: list[str] = []
        multiplier = 1.0
        status = "passed"
        decision_type = None

        if rsi12 is not None and ma20_distance_pct is not None and rsi12 >= extreme_rsi and ma20_distance_pct >= extreme_ma20_distance_pct:
            status = "blocked"
            decision_type = "reentry_overheat_blocked"
            reasons.append(
                f"RSI12 {rsi12:.2f} >= {extreme_rsi:.2f} 且高于MA20 {ma20_distance_pct:.2f}% >= {extreme_ma20_distance_pct:.2f}%"
            )
        elif rsi12 is not None and rsi12 > very_hot_rsi:
            if not strong_resonance:
                status = "blocked"
                decision_type = "reentry_overheat_blocked"
                reasons.append(f"RSI12 {rsi12:.2f} > {very_hot_rsi:.2f}，但未达到强共振")
            else:
                status = "downgraded"
                multiplier = min(multiplier, very_hot_multiplier)
                reasons.append(f"RSI12 {rsi12:.2f} > {very_hot_rsi:.2f}，强共振仅允许轻仓再入场")
        elif rsi12 is not None and rsi12 >= hot_rsi:
            status = "downgraded"
            multiplier = min(multiplier, hot_multiplier)
            reasons.append(f"RSI12 {rsi12:.2f} >= {hot_rsi:.2f}，热区买入降仓")

        if within_profit_reentry:
            if not trend_confirmed:
                status = "blocked"
                decision_type = "profit_reentry_confirmation_blocked"
                reasons.append("止盈后短期再入场缺少趋势结构确认")
            else:
                if status != "blocked":
                    status = "downgraded"
                    multiplier = min(multiplier, base_reentry_multiplier)
                reasons.append(f"距上次止盈卖出 {days_since_profit_sell} 天，再入场降仓")

        if status == "passed":
            return normalized

        strategy_profile = dict(strategy_profile)
        thresholds = dict(thresholds)
        strategy_profile["effective_thresholds"] = thresholds
        normalized["strategy_profile"] = strategy_profile
        gate = {
            "intent": "profit_reentry" if within_profit_reentry else "hot_buy_control",
            "status": status,
            "last_sell_trigger": "profit_tech_sell" if within_profit_reentry else None,
            "days_since_profit_sell": days_since_profit_sell,
            "cooldown_days": cooldown_days,
            "trend_confirmed": trend_confirmed,
            "strong_resonance": strong_resonance,
            "rsi12": round(rsi12, 4) if rsi12 is not None else None,
            "ma20_distance_pct": round(ma20_distance_pct, 4) if ma20_distance_pct is not None else None,
            "size_multiplier": round(multiplier, 6) if status == "downgraded" else 0.0,
            "reasons": reasons,
        }
        strategy_profile["reentry_gate"] = gate
        thresholds.setdefault("profit_reentry_cooldown_days", cooldown_days)
        thresholds.setdefault("profit_reentry_size_multiplier", base_reentry_multiplier)
        thresholds.setdefault("profit_reentry_hot_rsi", hot_rsi)
        thresholds.setdefault("profit_reentry_very_hot_rsi", very_hot_rsi)
        thresholds.setdefault("profit_reentry_extreme_rsi", extreme_rsi)
        thresholds.setdefault("profit_reentry_extreme_ma20_distance_pct", extreme_ma20_distance_pct)

        base_reasoning = str(normalized.get("reasoning") or "").strip()
        if status == "blocked":
            normalized["action"] = "HOLD"
            normalized["position_size_pct"] = 0.0
            normalized["decision_type"] = decision_type or "reentry_blocked"
            normalized["confidence"] = round(self._clamp((self._safe_float(normalized.get("confidence"), 0.0) or 0.0) * 0.65, 0.0, 100.0))
            normalized["reasoning"] = f"{base_reasoning} 再入场门控阻断：{'；'.join(reasons)}，转为HOLD。".strip()
            return normalized

        original_size = self._safe_float(normalized.get("position_size_pct"), 0.0) or 0.0
        normalized["decision_type"] = normalized.get("decision_type") or "reentry_downgraded_buy"
        normalized["reasoning"] = (
            f"{base_reasoning} 再入场门控降仓：{'；'.join(reasons)}，"
            f"资金槽执行时将按 {multiplier:.2f} 倍缩放，信号仓位保持 {original_size:.2f}% 。"
        ).strip()
        return normalized

    def _apply_stock_execution_feedback(self, candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        action = str(normalized.get("action") or "HOLD").upper()
        stock_code = str(candidate.get("stock_code") or "").strip()
        if action != "BUY" or not stock_code:
            return normalized
        if self._current_position(stock_code):
            return normalized

        strategy_profile = normalized.get("strategy_profile")
        if not isinstance(strategy_profile, dict):
            strategy_profile = {}
        policy = self._stock_execution_feedback_policy(strategy_profile)
        if not bool(policy.get("enabled", True)):
            return normalized

        metrics = self._extract_reentry_market_metrics(candidate, normalized)
        current_time = self._resolve_reentry_time(normalized, metrics)
        summary = self.db.get_stock_execution_feedback_summary(
            stock_code,
            as_of=current_time,
            lookback_days=int(policy.get("lookback_days") or 20),
        )
        market_snapshot = (
            strategy_profile.get("market_snapshot")
            if isinstance(strategy_profile.get("market_snapshot"), dict)
            else {}
        )
        recent_checkpoints = market_snapshot.get("recent_checkpoints")
        if isinstance(recent_checkpoints, list):
            summary["recent_checkpoints"] = recent_checkpoints

        gate = evaluate_stock_execution_feedback_gate(
            action=action,
            stock_code=stock_code,
            policy=policy,
            summary=summary,
            market_snapshot=market_snapshot,
            current_time=current_time,
        )
        if str(gate.get("status") or "passed") == "passed":
            return normalized

        strategy_profile = dict(strategy_profile)
        strategy_profile["stock_execution_feedback_policy"] = policy
        strategy_profile["stock_execution_feedback_gate"] = gate
        thresholds = strategy_profile.get("effective_thresholds")
        if not isinstance(thresholds, dict):
            thresholds = {}
        thresholds = dict(thresholds)
        thresholds["stock_execution_feedback_policy"] = policy
        strategy_profile["effective_thresholds"] = thresholds
        market_snapshot = dict(market_snapshot)
        market_snapshot["execution_feedback_score"] = gate.get("execution_feedback_score", 0.0)
        strategy_profile["market_snapshot"] = market_snapshot
        normalized["strategy_profile"] = strategy_profile

        base_reasoning = str(normalized.get("reasoning") or "").strip()
        reasons = "；".join(str(item) for item in gate.get("reasons") or [] if str(item))
        if str(gate.get("status")) == "blocked":
            normalized["action"] = "HOLD"
            normalized["position_size_pct"] = 0.0
            normalized["decision_type"] = "stock_execution_feedback_blocked"
            normalized["confidence"] = round(self._clamp((self._safe_float(normalized.get("confidence"), 0.0) or 0.0) * 0.65, 0.0, 100.0))
            normalized["reasoning"] = f"{base_reasoning} 个股执行反馈阻断：{reasons}，转为HOLD。".strip()
            return normalized

        original_size = self._safe_float(normalized.get("position_size_pct"), 0.0) or 0.0
        raw_multiplier = self._safe_float(gate.get("size_multiplier"), 1.0)
        multiplier = 1.0 if raw_multiplier is None else raw_multiplier
        normalized["decision_type"] = normalized.get("decision_type") or "stock_execution_feedback_downgraded_buy"
        normalized["reasoning"] = (
            f"{base_reasoning} 个股执行反馈降仓：{reasons}，"
            f"资金槽执行时将按 {multiplier:.2f} 倍缩放，信号仓位保持 {original_size:.2f}% 。"
        ).strip()
        return normalized

    def _apply_portfolio_execution_guard(self, candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        action = str(normalized.get("action") or "HOLD").upper()
        if action != "BUY":
            return normalized
        if str(normalized.get("decision_type") or "").strip() == "position_add":
            return normalized

        strategy_profile = normalized.get("strategy_profile")
        if not isinstance(strategy_profile, dict):
            strategy_profile = {}
        if str(strategy_profile.get("execution_intent") or "").strip() == "position_add":
            return normalized
        policy = self._portfolio_execution_guard_policy(strategy_profile)
        if not bool(policy.get("enabled", True)):
            return normalized

        summary_provider = getattr(self.db, "get_portfolio_execution_guard_summary", None)
        if callable(summary_provider):
            try:
                portfolio_summary = summary_provider(
                    as_of=normalized.get("decision_time"),
                    lookback_checkpoints=int(policy.get("lookback_checkpoints") or 0),
                    lookback_days=int(policy.get("lookback_days") or 0),
                )
            except TypeError:
                portfolio_summary = summary_provider()
        else:
            portfolio_summary = {}

        signal_payload = {
            **normalized,
            "market": candidate.get("market") or normalized.get("market") or "A",
            "timeframe": normalized.get("analysis_timeframe") or normalized.get("timeframe") or "30m",
        }
        gate = evaluate_portfolio_execution_guard(
            signal=signal_payload,
            policy=policy,
            portfolio_summary=portfolio_summary if isinstance(portfolio_summary, dict) else {},
        )

        strategy_profile = dict(strategy_profile)
        strategy_profile["portfolio_execution_guard_policy"] = policy
        strategy_profile["portfolio_execution_guard"] = gate
        thresholds = strategy_profile.get("effective_thresholds")
        if not isinstance(thresholds, dict):
            thresholds = {}
        thresholds = dict(thresholds)
        thresholds["portfolio_execution_guard_policy"] = policy
        strategy_profile["effective_thresholds"] = thresholds
        normalized["strategy_profile"] = strategy_profile

        base_reasoning = str(normalized.get("reasoning") or "").strip()
        reasons = "；".join(str(item) for item in gate.get("reasons") or [] if str(item))
        if str(gate.get("status") or "") == "blocked":
            normalized["action"] = "HOLD"
            normalized["position_size_pct"] = 0.0
            normalized["decision_type"] = "portfolio_execution_guard_blocked"
            normalized["confidence"] = round(self._clamp((self._safe_float(normalized.get("confidence"), 0.0) or 0.0) * 0.65, 0.0, 100.0))
            normalized["reasoning"] = f"{base_reasoning} 组合执行防守阻断：{reasons}，转为HOLD。".strip()
            return normalized

        if str(gate.get("status") or "") == "downgraded":
            raw_multiplier = self._safe_float(gate.get("size_multiplier"), 1.0)
            multiplier = 1.0 if raw_multiplier is None else raw_multiplier
            normalized["decision_type"] = normalized.get("decision_type") or "portfolio_execution_guard_downgraded_buy"
            normalized["reasoning"] = (
                f"{base_reasoning} 组合执行防守分层：{gate.get('buy_tier_label')}，"
                f"资金槽执行时将按 {multiplier:.2f} 倍缩放。"
            ).strip()
        return normalized

    def _apply_lifecycle_gate_profile(self, candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        gate = candidate.get("lifecycle_gate")
        if not isinstance(gate, dict):
            return normalized
        strategy_profile = normalized.get("strategy_profile")
        if not isinstance(strategy_profile, dict):
            strategy_profile = {}
        strategy_profile = dict(strategy_profile)
        strategy_profile.setdefault("lifecycle_gate", dict(gate))
        normalized["strategy_profile"] = strategy_profile
        action = str(normalized.get("action") or "HOLD").upper()
        if action not in {"BUY", "ADD"}:
            return normalized
        if bool(gate.get("buy_blocked")):
            normalized["action"] = "HOLD"
            normalized["position_size_pct"] = 0.0
            normalized["decision_type"] = "lifecycle_gate_blocked"
            normalized["reasoning"] = f"{normalized.get('reasoning') or ''} 生命周期门控：{gate.get('reason_text') or gate.get('reason_code') or '禁止新买入'}。".strip()
            return normalized
        if bool(gate.get("requires_strong_confirmation")) and not self._lifecycle_gate_has_strong_confirmation(
            strategy_profile,
            gate,
        ):
            normalized["action"] = "HOLD"
            normalized["position_size_pct"] = 0.0
            normalized["decision_type"] = "lifecycle_gate_blocked"
            normalized["reasoning"] = (
                f"{normalized.get('reasoning') or ''} 生命周期门控：{gate.get('mode') or 'soft_gate'} "
                "需要更强趋势确认，转为HOLD。"
            ).strip()
        return normalized

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
        return buy_strength >= threshold and (buy_tier == "strong_buy" or trend_confirmed)

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
        buy_strength = SignalCenterService._safe_float(guard.get("buy_strength_score"), None)
        if buy_strength is None:
            return normalized
        buy_tier = str(guard.get("buy_tier") or "").strip().lower()
        if buy_tier not in {"weak_buy", "normal_buy", "strong_buy"} and buy_strength <= 0:
            return normalized
        strength = SignalCenterService._clamp(buy_strength, 0.0, 1.0)
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
