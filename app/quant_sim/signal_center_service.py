"""Signal creation and listing helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.db.runtime.registry import DatabaseRuntime
from app.quant_sim.signal_center_tail import SignalCenterTailMixin
from app.quant_sim.db import DEFAULT_DB_FILE, QuantSimDB
from app.quant_kernel.models import Decision
from app.quant_sim.stock_execution_feedback import (
    evaluate_stock_execution_feedback_gate,
)
from app.quant_sim.portfolio_execution_guard import (
    evaluate_portfolio_execution_guard,
)
from app.quant_sim.lifecycle_artifact_adapter import ARTIFACT_DIAGNOSTIC_KEYS
from app.smart_monitor_db import SmartMonitorDB, DEFAULT_DB_FILE as SMART_MONITOR_DB_FILE


class SignalCenterService(SignalCenterTailMixin):
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
                "strategy_profile": self._persistable_strategy_profile(payload.get("strategy_profile")),
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

    @staticmethod
    def _persistable_strategy_profile(strategy_profile: Any) -> Any:
        if not isinstance(strategy_profile, dict):
            return strategy_profile
        profile = dict(strategy_profile)
        snapshot = profile.get("market_snapshot")
        if isinstance(snapshot, dict):
            profile["market_snapshot"] = {
                key: snapshot.get(key)
                for key in ARTIFACT_DIAGNOSTIC_KEYS
                if key in snapshot
            }
        return profile

    def build_signal_payload(self, candidate: dict[str, Any], decision: dict[str, Any] | Decision) -> dict[str, Any]:
        payload = self._normalize_decision_payload(decision)
        payload = self._apply_position_constraints(candidate, payload)
        payload = self._apply_position_add_gate(candidate, payload)
        payload = self._apply_divergence_probe_guard(candidate, payload)
        payload = self._apply_reentry_constraints(candidate, payload)
        payload = self._apply_stock_execution_feedback(candidate, payload)
        payload = self._apply_portfolio_execution_guard(candidate, payload)
        payload = self._apply_false_strong_filter(payload)
        payload = self._apply_lifecycle_gate_profile(candidate, payload)
        payload = self._apply_execution_sizing_plan(candidate, payload)
        payload = self._apply_weak_sell_observation_guard(candidate, payload)
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
        divergence_probe_blocked = self._is_divergence_probe_signal(normalized, strategy_profile)
        add_hot_rsi = self._safe_float(thresholds.get("add_hot_rsi"), 78.0) or 78.0
        add_extreme_ma20_distance_pct = (
            self._safe_float(thresholds.get("add_extreme_ma20_distance_pct"), 5.0) or 5.0
        )
        add_very_hot_rsi = self._safe_float(thresholds.get("add_very_hot_rsi"), 85.0) or 85.0
        metrics = self._extract_reentry_market_metrics(candidate, normalized)
        rsi12 = self._safe_float(metrics.get("rsi12"), None)
        ma20_distance_pct = self._safe_float(metrics.get("ma20_distance_pct"), None)
        hot_zone_blocked = bool(
            (rsi12 is not None and rsi12 >= add_very_hot_rsi)
            or (
                rsi12 is not None
                and ma20_distance_pct is not None
                and rsi12 >= add_hot_rsi
                and ma20_distance_pct >= add_extreme_ma20_distance_pct
            )
        )
        reasons: list[str] = []
        if not allow_pyramiding:
            reasons.append("策略阈值不允许加仓")
        if not capacity_gate_passed:
            reasons.append("当前持仓已达到目标或上限")
        if divergence_probe_blocked:
            reasons.append("背离试探不允许加仓")
        if hot_zone_blocked:
            if rsi12 is not None and ma20_distance_pct is not None:
                reasons.append(
                    f"RSI12 {rsi12:.2f} 热区且高于MA20 {ma20_distance_pct:.2f}% ，不允许加仓"
                )
            elif rsi12 is not None:
                reasons.append(f"RSI12 {rsi12:.2f} 极热区，不允许加仓")
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

        passed = (
            allow_pyramiding
            and capacity_gate_passed
            and not divergence_probe_blocked
            and not hot_zone_blocked
            and (profit_gate_passed or trend_gate_passed)
        )
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
            "divergence_probe_blocked": divergence_probe_blocked,
            "hot_zone_blocked": hot_zone_blocked,
            "rsi12": round(rsi12, 4) if rsi12 is not None else None,
            "add_hot_rsi": round(add_hot_rsi, 4),
            "add_very_hot_rsi": round(add_very_hot_rsi, 4),
            "ma20_distance_pct": round(ma20_distance_pct, 4) if ma20_distance_pct is not None else None,
            "add_extreme_ma20_distance_pct": round(add_extreme_ma20_distance_pct, 4),
            "reasons": reasons,
        }
        strategy_profile["position_add_gate"] = gate
        strategy_profile["execution_intent"] = "position_add" if passed else "position_add_blocked"
        thresholds.setdefault("add_min_unrealized_pnl_pct", round(min_unrealized_pnl_pct, 4))
        thresholds.setdefault("add_min_tech_score", round(min_tech_score, 6))
        thresholds.setdefault("add_min_fusion_confidence", round(float(min_fusion_confidence), 6))
        thresholds.setdefault("add_hot_rsi", round(add_hot_rsi, 4))
        thresholds.setdefault("add_very_hot_rsi", round(add_very_hot_rsi, 4))
        thresholds.setdefault("add_extreme_ma20_distance_pct", round(add_extreme_ma20_distance_pct, 4))

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

    def _apply_divergence_probe_guard(self, candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        action = str(normalized.get("action") or "HOLD").upper()
        if action != "BUY":
            return normalized
        stock_code = str(candidate.get("stock_code") or "").strip()
        if stock_code and self._current_position(stock_code):
            return normalized

        strategy_profile = normalized.get("strategy_profile")
        if not isinstance(strategy_profile, dict):
            strategy_profile = {}
        if not self._is_divergence_probe_signal(normalized, strategy_profile):
            return normalized

        strategy_profile = dict(strategy_profile)
        gate = {
            "intent": "divergence_probe",
            "status": "blocked",
            "has_position": False,
            "reasons": ["背离试探不新开仓"],
        }
        strategy_profile["divergence_probe_gate"] = gate
        normalized["strategy_profile"] = strategy_profile
        normalized["action"] = "HOLD"
        normalized["position_size_pct"] = 0.0
        normalized["decision_type"] = "divergence_probe_blocked"
        normalized["confidence"] = round(
            self._clamp((self._safe_float(normalized.get("confidence"), 0.0) or 0.0) * 0.65, 0.0, 100.0)
        )
        base_reasoning = str(normalized.get("reasoning") or "").strip()
        normalized["reasoning"] = f"{base_reasoning} 背离试探门控阻断：背离试探不新开仓，转为HOLD。".strip()
        return normalized

    def _is_divergence_probe_signal(self, payload: dict[str, Any], strategy_profile: dict[str, Any]) -> bool:
        reasoning = str(payload.get("reasoning") or "")
        if "背离试探" in reasoning:
            return True

        explainability = strategy_profile.get("explainability")
        if not isinstance(explainability, dict):
            return False

        dual_track = explainability.get("dual_track")
        if isinstance(dual_track, dict):
            resonance_type = str(dual_track.get("resonance_type") or "").strip().lower()
            rule_hit = str(dual_track.get("rule_hit") or "").strip().lower()
            if resonance_type in {"light_divergence", "divergence_light"}:
                return True
            if rule_hit in {"divergence_light", "light_divergence"}:
                return True

        resonance = explainability.get("resonance")
        if isinstance(resonance, dict):
            rule_hit = str(resonance.get("rule_hit") or "").strip().lower()
            if rule_hit in {"divergence_light", "light_divergence"}:
                return True
            quality_ratio = self._safe_float(resonance.get("quality_adjusted_position_ratio"), None)
            if quality_ratio is not None and 0.3 <= quality_ratio < 0.5:
                return True

        return False

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

    def _apply_weak_sell_observation_guard(self, candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        action = str(normalized.get("action") or "HOLD").upper()
        if action != "SELL":
            return normalized
        if self._is_hard_exit_sell(normalized):
            return normalized
        if not self._is_dual_track_sell(normalized):
            return normalized

        strategy_profile = normalized.get("strategy_profile")
        if not isinstance(strategy_profile, dict):
            strategy_profile = {}
        strategy_profile = dict(strategy_profile)
        explainability = strategy_profile.get("explainability")
        if not isinstance(explainability, dict):
            explainability = {}
        explainability = dict(explainability)
        explainability["weak_sell_observation_gate"] = {
            "status": "observed",
            "original_action": "SELL",
            "reason": "普通双轨 SELL 不属于硬止损或浮盈保护，需连续确认后再退出。",
            "hard_exit_veto_id": self._sell_veto_id(normalized),
        }
        strategy_profile["explainability"] = explainability
        normalized["strategy_profile"] = strategy_profile
        normalized["action"] = "HOLD"
        normalized["position_size_pct"] = 0.0
        normalized["decision_type"] = "weak_sell_observe"
        confidence = self._safe_float(normalized.get("confidence"), 0.0) or 0.0
        normalized["confidence"] = round(self._clamp(confidence * 0.75, 0.0, 100.0))
        base_reasoning = str(normalized.get("reasoning") or "").strip()
        normalized["reasoning"] = (
            f"{base_reasoning} 弱SELL观察：普通双轨卖出未触发硬止损/浮盈保护，"
            "先转为HOLD，等待连续走弱确认。"
        ).strip()
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

        strategy_profile = normalized.get("strategy_profile")
        if not isinstance(strategy_profile, dict):
            strategy_profile = {}
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
        strategy_profile["lifecycle_gate"] = self._maybe_relax_trial_lifecycle_gate(
            strategy_profile.get("lifecycle_gate"),
            strategy_profile,
        )
        gate = strategy_profile["lifecycle_gate"]
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
