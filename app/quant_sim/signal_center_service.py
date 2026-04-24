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
            return {
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

        position_size = decision.get("position_size_pct")
        if position_size is None and "position_ratio" in decision:
            position_size = float(decision.get("position_ratio", 0)) * 100
        return {
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

    def _apply_position_constraints(self, candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        stock_code = str(candidate.get("stock_code") or "").strip()
        action = str(normalized.get("action", "HOLD")).upper()

        if action == "SELL" and stock_code and not self.db.has_open_position(stock_code):
            normalized = self._downgrade_sell_without_position(normalized)

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

    @staticmethod
    def _is_failed_execution(value: Any) -> bool:
        text = str(value or "").lower()
        return any(token in text for token in ("fail", "失败", "error", "超时", "timeout", "拒绝", "skip", "跳过"))

    def _apply_ai_overlay(self, candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        stock_code = str(candidate.get("stock_code") or "").strip()
        if not stock_code:
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

        context_votes = explainability.get("context_votes")
        if not isinstance(context_votes, list):
            context_votes = []

        context_score = self._safe_float(normalized.get("context_score"), 0.0) or 0.0
        confidence = self._safe_float(normalized.get("confidence"), 0.0) or 0.0
        action = str(normalized.get("action") or "HOLD").upper()
        position_size_pct = self._safe_float(normalized.get("position_size_pct"), 0.0) or 0.0
        stop_loss_pct = self._safe_float(normalized.get("stop_loss_pct"), 5.0) or 5.0
        take_profit_pct = self._safe_float(normalized.get("take_profit_pct"), 12.0) or 12.0
        allow_pyramiding = self._truthy(thresholds.get("allow_pyramiding"))
        current_price = self._safe_float(candidate.get("latest_price"), 0.0) or 0.0

        latest_ai_decisions: list[dict[str, Any]] = []
        latest_ai = None
        if self.smart_monitor_db is not None:
            try:
                latest_ai_decisions = self.smart_monitor_db.get_ai_decisions(stock_code=stock_code, limit=6) or []
            except Exception:
                latest_ai_decisions = []
        if latest_ai_decisions:
            latest_ai = latest_ai_decisions[0]

        key_levels = latest_ai.get("key_price_levels") if isinstance(latest_ai, dict) and isinstance(latest_ai.get("key_price_levels"), dict) else {}
        support_price = self._safe_float(key_levels.get("support"))
        resistance_price = self._safe_float(key_levels.get("resistance"))
        stop_price = self._safe_float(key_levels.get("stop_loss") if key_levels.get("stop_loss") not in (None, "") else support_price)

        dynamic_stop = None
        dynamic_take = None
        if current_price > 0 and stop_price is not None and stop_price > 0 and stop_price < current_price:
            dynamic_stop = round(self._clamp((current_price - stop_price) / current_price * 100.0, 1.0, 25.0), 2)
            stop_loss_pct = dynamic_stop
        if current_price > 0 and resistance_price is not None and resistance_price > current_price:
            dynamic_take = round(self._clamp((resistance_price - current_price) / current_price * 100.0, 2.0, 45.0), 2)
            take_profit_pct = dynamic_take

        feedback_delta = 0.0
        feedback_reason = "无执行反馈"
        if latest_ai_decisions:
            sample = latest_ai_decisions[:5]
            total = len(sample)
            executed_count = sum(1 for item in sample if int(item.get("executed") or 0) == 1)
            failed_count = sum(1 for item in sample if self._is_failed_execution(item.get("execution_result")))
            success_count = max(executed_count - failed_count, 0)
            success_rate = success_count / total if total else 0.0
            fail_rate = failed_count / total if total else 0.0
            feedback_delta = round(self._clamp(success_rate * 0.12 - fail_rate * 0.25, -0.3, 0.12), 4)
            feedback_reason = f"最近{total}次决策执行反馈：成功{success_count}，失败{failed_count}，反馈分{feedback_delta:+.4f}"

        summary = self.db.get_account_summary()
        available_cash = self._safe_float(summary.get("available_cash"), 0.0) or 0.0
        total_equity = self._safe_float(summary.get("total_equity"), 0.0) or 0.0
        cash_ratio = (available_cash / total_equity) if total_equity > 0 else 0.0
        has_position = self.db.has_open_position(stock_code)

        account_delta = 0.0
        account_multiplier = 1.0
        account_reason_parts = [f"可用资金占比={cash_ratio:.2%}"]
        if action == "BUY":
            if cash_ratio < 0.10:
                account_delta -= 0.18
                account_multiplier *= 0.35
                account_reason_parts.append("现金偏紧，显著降仓")
            elif cash_ratio < 0.20:
                account_delta -= 0.12
                account_multiplier *= 0.55
                account_reason_parts.append("现金较低，降仓")
            elif cash_ratio < 0.35:
                account_delta -= 0.06
                account_multiplier *= 0.78
                account_reason_parts.append("现金一般，适度降仓")
            elif cash_ratio > 0.70:
                account_delta += 0.05
                account_multiplier *= 1.10
                account_reason_parts.append("现金充裕，小幅放宽仓位")

            if has_position and not allow_pyramiding:
                account_delta -= 0.12
                account_multiplier *= 0.2
                account_reason_parts.append("已有持仓且不允许加仓")

            suggested_position = position_size_pct * account_multiplier
            max_ratio = self._safe_float(thresholds.get("max_position_ratio"))
            if max_ratio is not None and max_ratio > 0:
                suggested_position = min(suggested_position, max_ratio * 100.0)
            suggested_position = round(self._clamp(suggested_position, 0.0, 100.0), 2)

            if suggested_position < 1.0:
                action = "HOLD"
                suggested_position = 0.0
                account_reason_parts.append("可执行建议仓位过小，转为观察")

            position_size_pct = suggested_position

        context_score = round(self._clamp(context_score + feedback_delta + account_delta, -1.0, 1.0), 4)
        confidence = round(self._clamp(confidence * (1 - max(0.0, -feedback_delta) * 0.55) + max(0.0, feedback_delta) * 18.0, 0.0, 100.0))

        normalized["action"] = action
        normalized["context_score"] = context_score
        normalized["confidence"] = confidence
        normalized["position_size_pct"] = position_size_pct
        normalized["stop_loss_pct"] = round(stop_loss_pct, 2)
        normalized["take_profit_pct"] = round(take_profit_pct, 2)

        thresholds["dynamic_stop_loss_pct"] = round(stop_loss_pct, 2)
        thresholds["dynamic_take_profit_pct"] = round(take_profit_pct, 2)
        thresholds["execution_feedback_delta"] = feedback_delta
        thresholds["account_posture_delta"] = round(account_delta, 4)
        thresholds["available_cash_ratio"] = round(cash_ratio, 4)
        thresholds["position_sizing_multiplier"] = round(account_multiplier, 4)
        thresholds["suggested_position_pct"] = round(position_size_pct, 2)

        context_votes.append(
            {
                "component": "execution_feedback",
                "score": feedback_delta,
                "reason": feedback_reason,
            }
        )
        context_votes.append(
            {
                "component": "account_posture",
                "score": round(account_delta, 4),
                "reason": "；".join(account_reason_parts),
            }
        )
        explainability["context_votes"] = context_votes
        strategy_profile["explainability"] = explainability
        strategy_profile["ai_overlay"] = {
            "enabled": True,
            "source": "smart_monitor + quant_account",
            "key_levels": key_levels,
            "dynamic_risk": {
                "stop_loss_pct": round(stop_loss_pct, 2),
                "take_profit_pct": round(take_profit_pct, 2),
                "stop_from_key_levels": dynamic_stop is not None,
                "take_from_key_levels": dynamic_take is not None,
            },
            "execution_feedback": {
                "delta": feedback_delta,
                "reason": feedback_reason,
            },
            "account_posture": {
                "available_cash": round(available_cash, 4),
                "total_equity": round(total_equity, 4),
                "cash_ratio": round(cash_ratio, 4),
                "has_position": has_position,
                "allow_pyramiding": allow_pyramiding,
                "multiplier": round(account_multiplier, 4),
            },
        }

        base_reasoning = str(normalized.get("reasoning") or "").strip()
        overlay_reasoning = (
            f" 风控参数动态化：止损 {stop_loss_pct:.2f}% ，止盈 {take_profit_pct:.2f}%。"
            f" 执行反馈修正 {feedback_delta:+.4f}，账户态势修正 {account_delta:+.4f}，最终建议仓位 {position_size_pct:.2f}% 。"
        )
        normalized["reasoning"] = f"{base_reasoning}{overlay_reasoning}".strip()
        return normalized

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
