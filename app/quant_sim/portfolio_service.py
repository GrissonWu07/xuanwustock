"""Manual confirmation flow and simulated position helpers."""

from __future__ import annotations

from math import floor
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.quant_sim.db import DEFAULT_DB_FILE, QuantSimDB


class PortfolioService:
    """Executes manual confirmations against the simulation ledger."""

    A_SHARE_LOT_SIZE = 100

    def __init__(self, db_file: str | Path = DEFAULT_DB_FILE):
        self.db = QuantSimDB(db_file)

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
    ) -> bool:
        action = str(signal.get("action") or "").upper()
        stock_code = str(signal.get("stock_code") or "").strip()
        if action == "BUY":
            price = self._resolve_signal_price(signal)
            quantity = self._estimate_buy_quantity(signal, price)
            if price <= 0:
                self._record_auto_execute_skip(signal, "自动执行跳过：缺少有效最新价")
                return False
            if quantity <= 0:
                self._record_auto_execute_skip(signal, "自动执行跳过：建议仓位不足买入一手")
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

    def _estimate_buy_quantity(self, signal: dict, price: float) -> int:
        if price <= 0:
            return 0
        summary = self.get_account_summary()
        scheduler_config = self.db.get_scheduler_config()
        commission_rate = max(float(scheduler_config.get("commission_rate") or 0), 0.0)
        position_size_pct = self._resolve_buy_position_pct(signal)
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
