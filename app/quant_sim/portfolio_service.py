"""Manual confirmation flow and simulated position helpers."""

from __future__ import annotations

import json
from math import floor
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.db.runtime.registry import DatabaseRuntime
from app.quant_sim.capital_slots import (
    build_sizing_explainability,
    calculate_buy_priority,
    calculate_slot_plan,
    calculate_slot_units,
    gate_size_multiplier,
    normalize_capital_slot_config,
)
from app.quant_sim.db import DEFAULT_DB_FILE, QuantSimDB
from app.quant_sim.execution_constraints import trade_block_reason
from app.quant_sim.execution_sizing import (
    apply_batch_execution_caps,
    build_execution_sizing_plan,
    default_execution_position_cap_policy,
)


_HARD_EXIT_SELL_TOKENS = (
    "hard_stop_loss",
    "stop_loss",
    "risk_stop",
    "quick_stoploss",
    "hard_profit_trailing_stop",
    "profit_tech_sell",
    "recovery_probe_failure_sell",
)

_HARD_EXIT_VETO_IDS = {
    "hard_stop_loss",
    "stop_loss",
    "risk_stop",
    "quick_stoploss",
    "hard_profit_trailing_stop",
    "profit_tech_sell",
}


class PortfolioService:
    """Executes manual confirmations against the simulation ledger."""

    A_SHARE_LOT_SIZE = 100

    def __init__(self, db_file: str | Path = DEFAULT_DB_FILE, *, db_runtime: DatabaseRuntime | None = None):
        self.db = QuantSimDB(db_file, db_runtime=db_runtime)

    def confirm_buy(
        self,
        signal_id: int,
        price: float,
        quantity: int,
        note: Optional[str] = None,
        executed_at: str | datetime | None = None,
    ) -> None:
        self.db.confirm_signal(
            signal_id=signal_id,
            executed_action="buy",
            price=price,
            quantity=quantity,
            note=note,
            executed_at=executed_at,
            apply_trade_cost=True,
        )

    def confirm_sell(
        self,
        signal_id: int,
        price: float,
        quantity: int,
        note: Optional[str] = None,
        executed_at: str | datetime | None = None,
    ) -> None:
        self.db.confirm_signal(
            signal_id=signal_id,
            executed_action="sell",
            price=price,
            quantity=quantity,
            note=note,
            executed_at=executed_at,
            apply_trade_cost=True,
        )

    def delay_signal(self, signal_id: int, note: Optional[str] = None) -> None:
        self.db.delay_signal(signal_id, note=note)

    def ignore_signal(self, signal_id: int, note: Optional[str] = None) -> None:
        self.db.ignore_signal(signal_id, note=note)

    def list_positions(self) -> list[dict]:
        return self.db.get_positions()

    def list_position_lots(self, stock_code: str) -> list[dict]:
        return self.db.get_position_lots(stock_code)

    def get_account_summary(self) -> dict:
        return self.db.get_account_summary()

    def configure_account(self, initial_cash: float) -> None:
        self.db.configure_account(initial_cash)

    def reset_account(self, *, initial_cash: float | None = None) -> None:
        self.db.reset_runtime_state(initial_cash=initial_cash)

    def get_trade_history(self, limit: int = 100) -> list[dict]:
        return self.db.get_trade_history(limit=limit)

    def get_account_snapshots(self, limit: int = 50) -> list[dict]:
        return self.db.get_account_snapshots(limit=limit)

    def auto_execute_signal(
        self,
        signal: dict,
        *,
        note: Optional[str] = None,
        executed_at: str | datetime | None = None,
        settle_slots: bool = True,
    ) -> bool:
        action = str(signal.get("action") or "").upper()
        stock_code = str(signal.get("stock_code") or "").strip()
        if action == "BUY":
            price = self._resolve_signal_price(signal)
            if price <= 0:
                self._record_auto_execute_skip(signal, "自动执行跳过：缺少有效最新价", blocked_reason="missing_price")
                return False
            block_reason = trade_block_reason(
                action=action,
                stock_code=stock_code,
                stock_name=signal.get("stock_name"),
                price=price,
                signal=signal,
            )
            if block_reason:
                self._record_auto_execute_skip(signal, f"自动执行跳过：{block_reason}", blocked_reason="trade_blocked")
                return False
            quantity, sizing_evidence = self._estimate_buy_quantity(signal, price, settle_slots=settle_slots)
            self._attach_sizing_evidence(signal, sizing_evidence)
            if quantity <= 0:
                reason = str(sizing_evidence.get("skip_reason") or "建议仓位不足买入一手")
                self._record_auto_execute_skip(
                    signal,
                    f"自动执行跳过：{reason}",
                    blocked_reason="sizing_skip",
                    cap_reason=self._sizing_skip_cap_reason(sizing_evidence),
                    execution_diagnostics={
                        "blocked_reason": "sizing_skip",
                        "cap_reason": self._sizing_skip_cap_reason(sizing_evidence),
                        "sizing": sizing_evidence,
                    },
                )
                return False
            self._attach_execution_diagnostics(
                signal,
                {
                    "blocked_reason": "",
                    "cap_reason": "",
                    "sizing": sizing_evidence,
                    "actual_buy_at": self._format_execution_time(executed_at) if executed_at else self.db._now(),
                },
            )
            self.confirm_buy(
                int(signal["id"]),
                price=price,
                quantity=quantity,
                note=note or "自动模拟买入",
                executed_at=executed_at,
            )
            return True

        if action == "SELL":
            position = self._get_position(stock_code, as_of=executed_at)
            if not position:
                self._record_auto_execute_skip(
                    signal,
                    "自动执行跳过：当前无可卖持仓",
                    blocked_reason="no_position",
                    execution_diagnostics=self._sell_execution_diagnostics(signal, None, blocked_reason="no_position"),
                )
                return False
            if self._is_weak_dual_track_sell(signal):
                self._record_auto_execute_skip(
                    signal,
                    "自动执行跳过：弱SELL观察，未触发硬止损/浮盈保护，等待连续走弱确认",
                    blocked_reason="weak_sell_observe",
                    cap_reason="weak_sell_observe",
                    execution_diagnostics=self._sell_execution_diagnostics(signal, position, blocked_reason="weak_sell_observe"),
                )
                return False
            quantity = min(
                int(position.get("quantity") or 0),
                int(position.get("sellable_quantity") or 0),
            )
            price = self._resolve_signal_price(signal, fallback=position)
            if price <= 0:
                self._record_auto_execute_skip(
                    signal,
                    "自动执行跳过：缺少有效最新价",
                    blocked_reason="missing_price",
                    execution_diagnostics=self._sell_execution_diagnostics(signal, position, blocked_reason="missing_price"),
                )
                return False
            block_reason = trade_block_reason(
                action=action,
                stock_code=stock_code,
                stock_name=signal.get("stock_name") or position.get("stock_name"),
                price=price,
                signal=signal,
            )
            if block_reason:
                self._record_auto_execute_skip(
                    signal,
                    f"自动执行跳过：{block_reason}",
                    blocked_reason="trade_blocked",
                    execution_diagnostics=self._sell_execution_diagnostics(signal, position, blocked_reason="trade_blocked"),
                )
                return False
            if quantity <= 0:
                self._record_auto_execute_skip(
                    signal,
                    "自动执行跳过：当前无可卖数量",
                    blocked_reason="no_sellable_quantity",
                    execution_diagnostics=self._sell_execution_diagnostics(signal, position, blocked_reason="no_sellable_quantity"),
                )
                return False
            self._attach_execution_diagnostics(
                signal,
                self._sell_execution_diagnostics(
                    signal,
                    position,
                    blocked_reason="",
                    actual_sell_at=executed_at or self.db._now(),
                ),
            )
            self.confirm_sell(
                int(signal["id"]),
                price=price,
                quantity=quantity,
                note=note or "自动模拟卖出",
                executed_at=executed_at,
            )
            return True

        return False

    def auto_execute_pending_signals(
        self,
        signals: list[dict],
        *,
        note: Optional[str] = None,
        executed_at: str | datetime | None = None,
    ) -> int:
        self.db.settle_capital_slots()
        ordered = sorted(signals, key=self._execution_sort_key)
        sells = [signal for signal in ordered if str(signal.get("action") or "").upper() == "SELL"]
        buys = [signal for signal in ordered if str(signal.get("action") or "").upper() == "BUY"]
        others = [signal for signal in ordered if str(signal.get("action") or "").upper() not in {"BUY", "SELL"}]
        executed = 0
        buy_phase_started = False
        config = self.db.get_scheduler_config()
        sell_reuse_policy = str(config.get("capital_sell_cash_reuse_policy") or "next_batch").strip().lower()
        profile_id = (str(config.get("strategy_profile_id") or "").strip() or self._profile_id_from_signal(buys[0])) if buys else ""
        batch_rows: list[dict] = []
        if buys:
            summary = self.db.get_account_summary()
            existing_trial_market_value, existing_weak_buy_market_value = self._current_trial_and_weak_buy_exposure()
            batch_rows = apply_batch_execution_caps(
                signals=buys,
                total_equity=float(summary.get("total_equity") or 0.0),
                existing_trial_market_value=existing_trial_market_value,
                existing_weak_buy_market_value=existing_weak_buy_market_value,
                day_trial_risk_used_pct=self._day_trial_risk_used_pct(executed_at),
                policy=default_execution_position_cap_policy(profile_id),
                day_buy_count_used=self._day_buy_count_used(executed_at),
            )
            for row in batch_rows:
                if not row["allowed"]:
                    skipped_signal = row["signal"]
                    profile = skipped_signal.get("strategy_profile") if isinstance(skipped_signal.get("strategy_profile"), dict) else {}
                    execution_plan = (
                        profile.get("execution_sizing_plan")
                        if isinstance(profile.get("execution_sizing_plan"), dict)
                        else {}
                    )
                    self._record_auto_execute_skip(
                        skipped_signal,
                        f"自动执行跳过：{row['reason_code']}",
                        blocked_reason="batch_execution_cap",
                        cap_reason=str(row.get("reason_code") or ""),
                        execution_diagnostics={
                            "blocked_reason": "batch_execution_cap",
                            "cap_reason": str(row.get("reason_code") or ""),
                            "batch_cap": {
                                "allowed": False,
                                "reason_code": str(row.get("reason_code") or ""),
                                "batch_risk_pct": row.get("batch_risk_pct"),
                            },
                            "sizing": {"sizing": execution_plan},
                        },
                    )
        executable = sells + [row["signal"] for row in batch_rows if row["allowed"]] + others
        for signal in executable:
            action = str(signal.get("action") or "").upper()
            if action == "BUY" and not buy_phase_started:
                buy_phase_started = True
                if sell_reuse_policy == "same_batch":
                    self.db.settle_capital_slots()
            try:
                did_execute = self.auto_execute_signal(signal, note=note, executed_at=executed_at, settle_slots=False)
            except TypeError as exc:
                if "settle_slots" not in str(exc):
                    raise
                did_execute = self.auto_execute_signal(signal, note=note, executed_at=executed_at)
            if did_execute:
                executed += 1
        return executed

    @staticmethod
    def _profile_id_from_signal(signal: dict | None) -> str:
        if not isinstance(signal, dict):
            return ""
        profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
        selected = profile.get("selected_strategy_profile") if isinstance(profile.get("selected_strategy_profile"), dict) else {}
        return str(selected.get("id") or selected.get("profile_id") or profile.get("profile_id") or "").strip()

    def _current_trial_and_weak_buy_exposure(self) -> tuple[float, float]:
        trial_total = 0.0
        weak_total = 0.0
        for position in self.db.get_positions():
            stock_code = str(position.get("stock_code") or "").strip()
            market_value = float(position.get("market_value") or 0.0)
            state = self.db.get_quant_universe_state(stock_code) if stock_code else None
            if str((state or {}).get("quant_status") or "").strip().lower() == "trial":
                trial_total += market_value
            if self.db.get_stock_execution_feedback_summary(stock_code).get("last_buy_was_weak"):
                weak_total += market_value
        return trial_total, weak_total

    def _day_trial_risk_used_pct(self, executed_at: str | datetime | None) -> float:
        day = executed_at.date().isoformat() if isinstance(executed_at, datetime) else str(executed_at or datetime.now().isoformat())[:10]
        total = 0.0
        for trade in self.db.get_trade_history(limit=1000):
            if str(trade.get("action") or "").upper() != "BUY":
                continue
            if str(trade.get("executed_at") or "")[:10] != day:
                continue
            metadata = trade.get("trade_metadata") if isinstance(trade.get("trade_metadata"), dict) else {}
            if not metadata:
                try:
                    metadata = json.loads(str(trade.get("trade_metadata_json") or "{}"))
                except json.JSONDecodeError:
                    metadata = {}
            plan = metadata.get("execution_sizing_plan") if isinstance(metadata.get("execution_sizing_plan"), dict) else {}
            if not plan:
                position_sizing = metadata.get("position_sizing") if isinstance(metadata.get("position_sizing"), dict) else {}
                plan = position_sizing.get("sizing") if isinstance(position_sizing.get("sizing"), dict) else {}
            batch_risk = plan.get("batch_risk_pct")
            if batch_risk not in (None, ""):
                total += float(batch_risk or 0.0)
                continue
            effective_pct = float(plan.get("effective_position_pct") or 0.0)
            stop_loss_pct = float(plan.get("expected_stop_loss_pct") or 0.0)
            if effective_pct > 0 and stop_loss_pct > 0:
                total += effective_pct * stop_loss_pct / 100.0
            else:
                total += float(plan.get("risk_budget_pct") or 0.0)
        return total

    def _day_buy_count_used(self, executed_at: str | datetime | None) -> int:
        day = executed_at.date().isoformat() if isinstance(executed_at, datetime) else str(executed_at or datetime.now().isoformat())[:10]
        count = 0
        for trade in self.db.get_trade_history(limit=1000):
            if str(trade.get("action") or "").upper() != "BUY":
                continue
            if str(trade.get("executed_at") or "")[:10] == day:
                count += 1
        return count

    def preview_signal_sizing(
        self,
        signal: dict,
        *,
        settle_slots: bool = False,
    ) -> dict:
        action = str(signal.get("action") or "").upper()
        if action != "BUY":
            return {}
        price = self._resolve_signal_price(signal)
        if price <= 0:
            return {"skip_reason": "缺少有效最新价", "quantity": 0}
        _, sizing_evidence = self._estimate_buy_quantity(signal, price, settle_slots=settle_slots)
        return sizing_evidence or {}

    def _estimate_buy_quantity(self, signal: dict, price: float, *, settle_slots: bool = True) -> tuple[int, dict]:
        if price <= 0:
            return 0, {"skip_reason": "缺少有效最新价"}
        summary = self.get_account_summary()
        scheduler_config = self.db.get_scheduler_config()
        commission_rate = max(float(scheduler_config.get("commission_rate") or 0), 0.0)
        capital_config = normalize_capital_slot_config(scheduler_config)
        strategy_profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
        execution_plan = (
            strategy_profile.get("execution_sizing_plan")
            if isinstance(strategy_profile.get("execution_sizing_plan"), dict)
            else {}
        )
        final_budget = float(execution_plan.get("final_budget") or 0.0)
        if final_budget > 0:
            if settle_slots:
                self.db.settle_capital_slots()
            slots = self.db.get_capital_slots() if capital_config["capital_slot_enabled"] else []
            slot_available_cash = (
                sum(float(slot.get("available_cash") or 0.0) for slot in slots)
                if slots
                else float(summary["available_cash"] or 0.0)
            )
            slot_plan = calculate_slot_plan(float(summary["total_equity"] or 0), capital_config)
            buy_budget = min(final_budget, float(summary["available_cash"] or 0.0), slot_available_cash)
            lot_cost_with_fee = price * self.A_SHARE_LOT_SIZE * (1 + commission_rate)
            sizing = {**execution_plan, "slot_units_source": "execution_sizing_plan"}
            one_lot_floor_override = False
            original_buy_budget = buy_budget
            if buy_budget < lot_cost_with_fee:
                if self._execution_one_lot_floor_allowed(
                    signal=signal,
                    execution_plan=execution_plan,
                    total_equity=float(summary["total_equity"] or 0.0),
                    available_cash=float(summary["available_cash"] or 0.0),
                    slot_available_cash=slot_available_cash,
                    lot_cost_with_fee=lot_cost_with_fee,
                ):
                    one_lot_floor_override = True
                    buy_budget = lot_cost_with_fee
                    sizing = {
                        **sizing,
                        "one_lot_floor_override": True,
                        "one_lot_floor_original_budget": round(original_buy_budget, 4),
                        "one_lot_floor_reason": "confirmed_lifecycle_signal_within_account_cap",
                    }
                else:
                    return 0, build_sizing_explainability(
                        config=capital_config,
                        slot_plan=slot_plan,
                        sizing=sizing,
                        available_cash=float(summary["available_cash"] or 0),
                        slot_available_cash=slot_available_cash,
                        buy_budget=buy_budget,
                        quantity=0,
                        skip_reason=str(execution_plan.get("skip_reason") or "execution_sizing_budget不足买入一手"),
                        target_position_pct=float(execution_plan.get("effective_position_pct") or 0.0),
                        target_position_budget=final_budget,
                        slot_capacity_capped=slot_available_cash + 1e-6 < final_budget,
                    )
            lots = floor(buy_budget / lot_cost_with_fee)
            quantity = int(lots * self.A_SHARE_LOT_SIZE)
            evidence = build_sizing_explainability(
                config=capital_config,
                slot_plan=slot_plan,
                sizing=sizing,
                available_cash=float(summary["available_cash"] or 0),
                slot_available_cash=slot_available_cash,
                buy_budget=buy_budget,
                quantity=quantity,
                skip_reason=None,
                target_position_pct=float(execution_plan.get("effective_position_pct") or 0.0),
                target_position_budget=final_budget,
                slot_capacity_capped=slot_available_cash + 1e-6 < final_budget,
            )
            if one_lot_floor_override:
                evidence["one_lot_floor_override"] = True
                evidence["one_lot_floor_original_budget"] = round(original_buy_budget, 4)
                evidence["one_lot_floor_reason"] = "confirmed_lifecycle_signal_within_account_cap"
            return quantity, evidence
        if not capital_config["capital_slot_enabled"]:
            quantity = self._estimate_legacy_buy_quantity(signal, price, summary, commission_rate)
            return quantity, {"mode": "legacy_position_pct", "quantity": quantity}
        if settle_slots:
            self.db.settle_capital_slots()
        slots = self.db.get_capital_slots()
        slot_plan = calculate_slot_plan(float(summary["total_equity"] or 0), capital_config)
        if not slot_plan["pool_ready"]:
            return 0, build_sizing_explainability(
                config=capital_config,
                slot_plan=slot_plan,
                sizing={},
                available_cash=float(summary["available_cash"] or 0),
                slot_available_cash=0.0,
                buy_budget=0.0,
                quantity=0,
                skip_reason="slot资金池低于最低额度；建议仓位不足买入一手",
            )
        sizing = calculate_slot_units(
            signal,
            price=price,
            slot_budget=float(slot_plan["slot_budget"] or 0),
            commission_rate=commission_rate,
            config=capital_config,
            strategy_profile_id=str(scheduler_config.get("strategy_profile_id") or ""),
            cash_ratio=(
                float(summary["available_cash"] or 0) / float(summary["total_equity"] or 0)
                if float(summary["total_equity"] or 0) > 0
                else 0.0
            ),
        )
        slot_available_cash = sum(float(slot.get("available_cash") or 0) for slot in slots)
        signal_position_pct = self._resolve_buy_position_pct(signal)
        execution_multiplier = gate_size_multiplier(signal)
        target_position_pct = signal_position_pct * execution_multiplier
        target_position_budget = (
            float(summary["total_equity"] or 0) * target_position_pct / 100.0
            if target_position_pct > 0
            else 0.0
        )
        lot_cost_with_fee = price * self.A_SHARE_LOT_SIZE * (1 + commission_rate)
        if bool(sizing.get("strong_buy")) and 0 < target_position_budget < lot_cost_with_fee:
            target_position_budget = lot_cost_with_fee
        buy_budget = min(
            float(summary["available_cash"]),
            slot_available_cash,
            target_position_budget,
        )
        slot_budget = float(slot_plan["slot_budget"] or 0)
        actual_slot_units = buy_budget / slot_budget if slot_budget > 0 else 0.0
        sizing = {
            **sizing,
            "slot_units": round(actual_slot_units, 6),
            "slot_units_source": "position_budget",
            "target_position_pct": round(target_position_pct, 6),
            "target_position_budget": round(target_position_budget, 4),
            "execution_multiplier": round(execution_multiplier, 6) if signal_position_pct > 0 else 0.0,
        }
        if buy_budget < lot_cost_with_fee:
            if target_position_budget <= 0:
                skip_reason = "信号仓位或执行倍率为0"
            elif float(summary["available_cash"] or 0) < lot_cost_with_fee:
                skip_reason = "账户可用现金不足买入一手"
            elif slot_available_cash < lot_cost_with_fee:
                skip_reason = "slot可用容量不足买入一手"
            else:
                skip_reason = "目标仓位预算不足买入一手"
            return 0, build_sizing_explainability(
                config=capital_config,
                slot_plan=slot_plan,
                sizing=sizing,
                available_cash=float(summary["available_cash"] or 0),
                slot_available_cash=slot_available_cash,
                buy_budget=buy_budget,
                quantity=0,
                skip_reason=skip_reason,
                target_position_pct=target_position_pct,
                target_position_budget=target_position_budget,
                slot_capacity_capped=slot_available_cash + 1e-6 < target_position_budget,
            )
        lots = floor(buy_budget / lot_cost_with_fee)
        quantity = int(lots * self.A_SHARE_LOT_SIZE)
        return quantity, build_sizing_explainability(
            config=capital_config,
            slot_plan=slot_plan,
            sizing=sizing,
            available_cash=float(summary["available_cash"] or 0),
            slot_available_cash=slot_available_cash,
            buy_budget=buy_budget,
            quantity=quantity,
            skip_reason=None,
            target_position_pct=target_position_pct,
            target_position_budget=target_position_budget,
            slot_capacity_capped=slot_available_cash + 1e-6 < target_position_budget,
        )

    def _estimate_legacy_buy_quantity(self, signal: dict, price: float, summary: dict, commission_rate: float) -> int:
        position_size_pct = self._resolve_buy_position_pct(signal) * gate_size_multiplier(signal)
        if position_size_pct <= 0:
            return 0
        target_cash = min(
            float(summary["available_cash"]),
            float(summary["total_equity"]) * position_size_pct / 100.0,
        )
        lot_cost_with_fee = price * self.A_SHARE_LOT_SIZE * (1 + commission_rate)
        if target_cash < lot_cost_with_fee:
            return 0
        lots = floor(target_cash / lot_cost_with_fee)
        return int(lots * self.A_SHARE_LOT_SIZE)

    @staticmethod
    def _resolve_buy_position_pct(signal: dict) -> float:
        strategy_profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
        add_gate = strategy_profile.get("position_add_gate") if isinstance(strategy_profile.get("position_add_gate"), dict) else {}
        intent = str(add_gate.get("intent") or strategy_profile.get("execution_intent") or "").strip().lower()
        if intent == "position_add" and str(add_gate.get("status") or "").strip().lower() == "passed":
            try:
                return max(float(add_gate.get("add_position_delta_pct") or 0), 0.0)
            except (TypeError, ValueError):
                return 0.0
        try:
            return max(float(signal.get("position_size_pct") or 0), 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _execution_sort_key(self, signal: dict) -> tuple[int, float, str, int]:
        action = str(signal.get("action") or "").upper()
        signal_id = int(signal.get("id") or 0)
        stock_code = str(signal.get("stock_code") or "").strip()
        if action == "SELL":
            return (0, 0.0, stock_code, signal_id)
        if action == "BUY":
            return (1, -calculate_buy_priority(signal, self.db.get_scheduler_config()), stock_code, signal_id)
        return (2, 0.0, stock_code, signal_id)

    def _attach_sizing_evidence(self, signal: dict, sizing_evidence: dict) -> None:
        signal_id = signal.get("id")
        if signal_id in (None, ""):
            return
        profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
        next_profile = {**profile, "position_sizing": sizing_evidence}
        signal["strategy_profile"] = next_profile
        try:
            self.db.update_signal_state(int(signal_id), strategy_profile=next_profile)
        except Exception:
            return

    def _resolve_signal_price(self, signal: dict, fallback: Optional[dict] = None) -> float:
        stock_code = str(signal.get("stock_code") or "").strip()
        candidate = self.db.get_candidate(stock_code) if stock_code else None
        for payload in (fallback, candidate):
            if not payload:
                continue
            for field in ("latest_price", "avg_price"):
                value = float(payload.get(field) or 0)
                if value > 0:
                    return value
        return 0.0

    def _get_position(self, stock_code: str, *, as_of: str | datetime | None = None) -> Optional[dict]:
        for position in self.db.get_positions(as_of=as_of):
            if position.get("stock_code") == stock_code:
                return position
        return None

    def _record_auto_execute_skip(
        self,
        signal: dict,
        reason: str,
        *,
        blocked_reason: str = "",
        cap_reason: str = "",
        execution_diagnostics: dict | None = None,
    ) -> None:
        signal_id = signal.get("id")
        if signal_id in (None, ""):
            return
        profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
        diagnostics = execution_diagnostics if isinstance(execution_diagnostics, dict) else {}
        skip_payload = {
            "execution_note": reason,
            "blocked_reason": blocked_reason or self._infer_blocked_reason(reason),
            "cap_reason": cap_reason or "",
            "execution_diagnostics": diagnostics,
        }
        next_profile = {**profile, "auto_execution_skip": skip_payload}
        signal["strategy_profile"] = next_profile
        signal["execution_note"] = reason
        signal["blocked_reason"] = skip_payload["blocked_reason"]
        signal["cap_reason"] = skip_payload["cap_reason"]
        signal["execution_diagnostics"] = diagnostics
        self.db.update_signal_state(
            int(signal_id),
            execution_note=reason,
            blocked_reason=skip_payload["blocked_reason"],
            cap_reason=skip_payload["cap_reason"],
            execution_diagnostics=diagnostics,
            strategy_profile=next_profile,
        )

    def _attach_execution_diagnostics(self, signal: dict, diagnostics: dict) -> None:
        signal_id = signal.get("id")
        if signal_id in (None, ""):
            return
        signal["execution_diagnostics"] = diagnostics
        try:
            self.db.update_signal_state(int(signal_id), execution_diagnostics=diagnostics)
        except Exception:
            return

    def _sell_execution_diagnostics(
        self,
        signal: dict,
        position: dict | None,
        *,
        blocked_reason: str,
        actual_sell_at: str | datetime | None = None,
    ) -> dict:
        quantity = int((position or {}).get("quantity") or 0)
        sellable_quantity = int((position or {}).get("sellable_quantity") or 0)
        locked_quantity = int((position or {}).get("locked_quantity") or max(quantity - sellable_quantity, 0))
        hard_veto_id = self._sell_veto_id(signal)
        sell_trigger_type = "weak_sell_observe" if blocked_reason == "weak_sell_observe" else hard_veto_id
        if not sell_trigger_type:
            sell_trigger_type = str(signal.get("decision_type") or "sell_signal").strip() or "sell_signal"
        return {
            "sell_trigger_type": sell_trigger_type,
            "hard_veto_id": hard_veto_id,
            "is_weak_sell_observe": blocked_reason == "weak_sell_observe",
            "sellable_quantity": sellable_quantity,
            "locked_quantity": locked_quantity,
            "blocked_reason": blocked_reason,
            "first_sell_signal_at": signal.get("created_at") or signal.get("checkpoint_at"),
            "actual_sell_at": self._format_execution_time(actual_sell_at) if actual_sell_at else None,
        }

    @staticmethod
    def _format_execution_time(value: str | datetime | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    @staticmethod
    def _infer_blocked_reason(reason: str) -> str:
        text = str(reason or "")
        if "缺少有效最新价" in text:
            return "missing_price"
        if "无可卖持仓" in text:
            return "no_position"
        if "无可卖数量" in text:
            return "no_sellable_quantity"
        if "不足买入一手" in text or "建议仓位" in text:
            return "sizing_skip"
        return "auto_execution_skip"

    @staticmethod
    def _sizing_skip_cap_reason(sizing_evidence: dict) -> str:
        if not isinstance(sizing_evidence, dict):
            return ""
        for key in ("skip_reason", "reason_code", "cap_reason"):
            value = sizing_evidence.get(key)
            if value:
                return str(value)
        reason_codes = sizing_evidence.get("cap_reason_codes")
        if isinstance(reason_codes, list) and reason_codes:
            return str(reason_codes[0])
        if sizing_evidence.get("slot_capacity_capped"):
            return "slot_capacity_capped"
        return ""

    @classmethod
    def _execution_one_lot_floor_allowed(
        cls,
        *,
        signal: dict,
        execution_plan: dict,
        total_equity: float,
        available_cash: float,
        slot_available_cash: float,
        lot_cost_with_fee: float,
    ) -> bool:
        if not isinstance(execution_plan, dict) or execution_plan.get("skip_reason"):
            return False
        if total_equity <= 0 or lot_cost_with_fee <= 0:
            return False
        if lot_cost_with_fee > available_cash + 1e-6 or lot_cost_with_fee > slot_available_cash + 1e-6:
            return False
        profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
        guard = profile.get("portfolio_execution_guard") if isinstance(profile.get("portfolio_execution_guard"), dict) else {}
        tier = str(execution_plan.get("buy_tier") or guard.get("buy_tier") or "").strip().lower()
        if tier not in {"normal_buy", "strong_buy"}:
            return False
        gate = profile.get("lifecycle_gate") if isinstance(profile.get("lifecycle_gate"), dict) else {}
        gate_mode = str(execution_plan.get("lifecycle_gate_mode") or gate.get("mode") or "").strip().lower()
        if gate_mode == "recovery_probe_quality_limited":
            return cls._quality_limited_one_lot_floor_allowed(
                signal=signal,
                execution_plan=execution_plan,
                profile=profile,
                total_equity=total_equity,
                lot_cost_with_fee=lot_cost_with_fee,
            )
        if gate_mode not in {"recovery_probe_confirmed", "trial_confirmed", "strong_recovery_confirmed"}:
            return False
        account_cap_pct = cls._execution_plan_account_cap_pct(execution_plan, profile, total_equity)
        if account_cap_pct <= 0:
            return False
        one_lot_pct = lot_cost_with_fee / total_equity * 100.0
        return one_lot_pct <= account_cap_pct + 1e-9

    @classmethod
    def _quality_limited_one_lot_floor_allowed(
        cls,
        *,
        signal: dict,
        execution_plan: dict,
        profile: dict,
        total_equity: float,
        lot_cost_with_fee: float,
    ) -> bool:
        guard = profile.get("portfolio_execution_guard") if isinstance(profile.get("portfolio_execution_guard"), dict) else {}
        tier = str(execution_plan.get("buy_tier") or guard.get("buy_tier") or "").strip().lower()
        if tier != "strong_buy":
            return False
        if float(execution_plan.get("final_budget") or 0.0) / lot_cost_with_fee < 0.4:
            return False
        components = guard.get("score_components") if isinstance(guard.get("score_components"), dict) else {}
        trend = guard.get("trend_confirmation") if isinstance(guard.get("trend_confirmation"), dict) else {}
        market_snapshot = profile.get("market_snapshot") if isinstance(profile.get("market_snapshot"), dict) else {}
        strength = cls._safe_float(guard.get("buy_strength_score"), 0.0)
        edge = cls._safe_float(components.get("edge_strength"), 0.0)
        confirmation = cls._safe_float(components.get("confirmation_score"), 0.0)
        rsi = cls._safe_float(
            market_snapshot.get("rsi")
            or market_snapshot.get("rsi12")
            or market_snapshot.get("rsi_12")
            or trend.get("rsi"),
            50.0,
        )
        recent_return = cls._ratio_value(
            trend.get("recent_5d_return")
            if trend.get("recent_5d_return") not in (None, "")
            else market_snapshot.get("recent_5d_return")
        )
        if strength < 0.90 or edge < 0.90 or confirmation < 0.90:
            return False
        if rsi > 80.0:
            return False
        if recent_return is not None and recent_return > 0.08:
            return False
        account_cap_pct = cls._execution_plan_account_cap_pct(execution_plan, profile, total_equity)
        if account_cap_pct <= 0:
            return False
        one_lot_pct = lot_cost_with_fee / total_equity * 100.0
        return one_lot_pct <= account_cap_pct + 1e-9

    @staticmethod
    def _safe_float(value: object, default: float = 0.0) -> float:
        try:
            if value in (None, ""):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _ratio_value(cls, value: object) -> float | None:
        if value in (None, ""):
            return None
        numeric = cls._safe_float(value, 0.0)
        if abs(numeric) > 2.0:
            return numeric / 100.0
        return numeric

    @staticmethod
    def _execution_plan_account_cap_pct(execution_plan: dict, profile: dict, total_equity: float) -> float:
        try:
            explicit = float(execution_plan.get("account_equity_tier_cap_pct") or 0.0)
        except (TypeError, ValueError):
            explicit = 0.0
        if explicit > 0:
            return explicit
        selected = profile.get("selected_strategy_profile") if isinstance(profile.get("selected_strategy_profile"), dict) else {}
        profile_id = str(selected.get("id") or "aggressive").strip() or "aggressive"
        try:
            policy = default_execution_position_cap_policy(profile_id)
            # Reuse the public sizing helper rather than duplicating account tier boundaries.
            probe_plan = {
                "position_size_pct": 100.0,
                "stop_loss_pct": 5.0,
                "strategy_profile": {
                    "portfolio_execution_guard": {"buy_tier": "strong_buy"},
                    "kernel_positioning": {"quality_position_pct": 100.0},
                },
            }
            sized = build_execution_sizing_plan(
                signal=probe_plan,
                total_equity=total_equity,
                available_cash=total_equity,
                slot_available_cash=total_equity,
                quant_status="active",
                policy=policy,
            )
            return float(sized.get("account_equity_tier_cap_pct") or 0.0)
        except Exception:
            return 0.0

    @classmethod
    def _is_weak_dual_track_sell(cls, signal: dict) -> bool:
        if str(signal.get("action") or "").upper() != "SELL":
            return False
        if cls._is_hard_exit_sell(signal):
            return False
        decision_type = str(signal.get("decision_type") or "").strip().lower()
        if decision_type == "dual_track_weighted_sell":
            return True
        fusion_breakdown = cls._fusion_breakdown(signal)
        final_action = str(fusion_breakdown.get("final_action") or "").strip().upper()
        raw_action = str(
            fusion_breakdown.get("weighted_action_raw") or fusion_breakdown.get("weighted_threshold_action") or ""
        ).strip().upper()
        return final_action == "SELL" and raw_action == "SELL"

    @classmethod
    def _is_hard_exit_sell(cls, signal: dict) -> bool:
        if bool(signal.get("quick_stoploss_failure")):
            return True
        decision_type = str(signal.get("decision_type") or "").strip().lower()
        if any(token in decision_type for token in _HARD_EXIT_SELL_TOKENS):
            return True
        return cls._sell_veto_id(signal) in _HARD_EXIT_VETO_IDS

    @classmethod
    def _sell_veto_id(cls, signal: dict) -> str:
        for key in ("veto_id", "veto_trigger_type", "trigger_type"):
            value = str(signal.get(key) or "").strip().lower()
            if value:
                return value
        fusion_breakdown = cls._fusion_breakdown(signal)
        for key in ("veto_id", "veto_trigger_type", "trigger_type"):
            value = str(fusion_breakdown.get(key) or "").strip().lower()
            if value:
                return value
        return ""

    @staticmethod
    def _fusion_breakdown(signal: dict) -> dict:
        profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
        explainability = profile.get("explainability") if isinstance(profile.get("explainability"), dict) else {}
        fusion_breakdown = explainability.get("fusion_breakdown")
        return fusion_breakdown if isinstance(fusion_breakdown, dict) else {}
