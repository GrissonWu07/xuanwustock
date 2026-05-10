"""Manual confirmation flow and simulated position helpers."""

from __future__ import annotations

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
                self._record_auto_execute_skip(signal, "自动执行跳过：缺少有效最新价")
                return False
            block_reason = trade_block_reason(
                action=action,
                stock_code=stock_code,
                stock_name=signal.get("stock_name"),
                price=price,
                signal=signal,
            )
            if block_reason:
                self._record_auto_execute_skip(signal, f"自动执行跳过：{block_reason}")
                return False
            quantity, sizing_evidence = self._estimate_buy_quantity(signal, price, settle_slots=settle_slots)
            self._attach_sizing_evidence(signal, sizing_evidence)
            if quantity <= 0:
                reason = str(sizing_evidence.get("skip_reason") or "建议仓位不足买入一手")
                self._record_auto_execute_skip(signal, f"自动执行跳过：{reason}")
                return False
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
                self._record_auto_execute_skip(signal, "自动执行跳过：当前无可卖持仓")
                return False
            quantity = min(
                int(position.get("quantity") or 0),
                int(position.get("sellable_quantity") or 0),
            )
            price = self._resolve_signal_price(signal, fallback=position)
            if price <= 0:
                self._record_auto_execute_skip(signal, "自动执行跳过：缺少有效最新价")
                return False
            block_reason = trade_block_reason(
                action=action,
                stock_code=stock_code,
                stock_name=signal.get("stock_name") or position.get("stock_name"),
                price=price,
                signal=signal,
            )
            if block_reason:
                self._record_auto_execute_skip(signal, f"自动执行跳过：{block_reason}")
                return False
            if quantity <= 0:
                self._record_auto_execute_skip(signal, "自动执行跳过：当前无可卖数量")
                return False
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
        executed = 0
        buy_phase_started = False
        config = self.db.get_scheduler_config()
        sell_reuse_policy = str(config.get("capital_sell_cash_reuse_policy") or "next_batch").strip().lower()
        for signal in ordered:
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
            if buy_budget < lot_cost_with_fee:
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
            return quantity, build_sizing_explainability(
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

    def _execution_sort_key(self, signal: dict) -> tuple[int, float, int]:
        action = str(signal.get("action") or "").upper()
        signal_id = int(signal.get("id") or 0)
        if action == "SELL":
            return (0, 0.0, signal_id)
        if action == "BUY":
            return (1, -calculate_buy_priority(signal, self.db.get_scheduler_config()), signal_id)
        return (2, 0.0, signal_id)

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

    def _record_auto_execute_skip(self, signal: dict, reason: str) -> None:
        signal_id = signal.get("id")
        if signal_id in (None, ""):
            return
        self.db.update_signal_state(int(signal_id), execution_note=reason)
