"""Signal creation and listing helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.notification_service import notification_service
from app.quant_sim.db import DEFAULT_DB_FILE, QuantSimDB
from app.quant_kernel.models import Decision
from app.smart_monitor_db import SmartMonitorDB, DEFAULT_DB_FILE as SMART_MONITOR_DB_FILE


class SignalCenterService:
    """Normalizes strategy decisions into persisted signals."""

    def __init__(self, db_file: str | Path = DEFAULT_DB_FILE):
        self.db_file = Path(db_file)
        self.external_side_effects_enabled = self._is_default_db_file(self.db_file)
        self.db = QuantSimDB(db_file)
        self.smart_monitor_db: SmartMonitorDB | None = None
        if self.external_side_effects_enabled:
            try:
                self.smart_monitor_db = SmartMonitorDB(str(SMART_MONITOR_DB_FILE))
            except Exception:
                self.smart_monitor_db = None

    def create_signal(
        self,
        candidate: dict[str, Any],
        decision: dict[str, Any] | Decision,
        *,
        notify: bool = True,
        mirror_to_ai: bool | None = None,
    ) -> dict[str, Any]:
        if mirror_to_ai is None:
            mirror_to_ai = notify
        payload = self._normalize_decision_payload(decision)
        payload = self._apply_position_constraints(candidate, payload)
        payload = self._apply_position_add_gate(candidate, payload)
        payload = self._apply_transaction_cost_constraints(candidate, payload)
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
            }
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
            }
            return SignalCenterService._apply_canonical_v23_scores(payload)

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
        }
        return SignalCenterService._apply_canonical_v23_scores(payload)

    @staticmethod
    def _apply_canonical_v23_scores(payload: dict[str, Any]) -> dict[str, Any]:
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
            normalized["confidence"] = round(confidence * 100 if confidence <= 1 else confidence)
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

    def _apply_transaction_cost_constraints(self, candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        action = str(normalized.get("action") or "HOLD").upper()
        if action not in {"BUY", "SELL"}:
            return normalized

        strategy_profile = normalized.get("strategy_profile")
        if not isinstance(strategy_profile, dict) or not strategy_profile:
            return normalized

        scheduler_config = self.db.get_scheduler_config()
        commission_rate = max(self._safe_float(scheduler_config.get("commission_rate"), 0.0) or 0.0, 0.0)
        sell_tax_rate = max(self._safe_float(scheduler_config.get("sell_tax_rate"), 0.0) or 0.0, 0.0)
        roundtrip_cost_pct = round((commission_rate * 2.0 + sell_tax_rate) * 100.0, 4)
        sell_side_cost_pct = round((commission_rate + sell_tax_rate) * 100.0, 4)
        min_buy_edge_pct = round(roundtrip_cost_pct + 0.2, 4)
        thresholds = strategy_profile.get("effective_thresholds")
        cost_model = strategy_profile.get("cost_model")
        if not isinstance(thresholds, dict) and not isinstance(cost_model, dict):
            return normalized
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
