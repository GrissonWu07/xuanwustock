"""Manual confirmation flow and simulated position helpers."""

from __future__ import annotations

from math import floor
from datetime import datetime
from pathlib import Path
from typing import Optional

from quant_sim.db import DEFAULT_DB_FILE, QuantSimDB


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
            if price <= 0 or quantity <= 0:
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
                return False
            quantity = min(
                int(position.get("quantity") or 0),
                int(position.get("sellable_quantity") or 0),
            )
            price = self._resolve_signal_price(signal, fallback=position)
            if price <= 0 or quantity <= 0:
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
        position_size_pct = float(signal.get("position_size_pct") or 0)
        if position_size_pct <= 0:
            return 0
        target_cash = min(
            float(summary["available_cash"]),
            float(summary["total_equity"]) * position_size_pct / 100.0,
        )
        if target_cash < price * self.A_SHARE_LOT_SIZE:
            return 0
        lots = floor(target_cash / (price * self.A_SHARE_LOT_SIZE))
        return int(lots * self.A_SHARE_LOT_SIZE)

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
