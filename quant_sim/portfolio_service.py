"""Manual confirmation flow and simulated position helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from quant_sim.db import DEFAULT_DB_FILE, QuantSimDB


class PortfolioService:
    """Executes manual confirmations against the simulation ledger."""

    def __init__(self, db_file: str | Path = DEFAULT_DB_FILE):
        self.db = QuantSimDB(db_file)

    def confirm_buy(self, signal_id: int, price: float, quantity: int, note: Optional[str] = None) -> None:
        self.db.confirm_signal(
            signal_id=signal_id,
            executed_action="buy",
            price=price,
            quantity=quantity,
            note=note,
        )

    def confirm_sell(self, signal_id: int, price: float, quantity: int, note: Optional[str] = None) -> None:
        self.db.confirm_signal(
            signal_id=signal_id,
            executed_action="sell",
            price=price,
            quantity=quantity,
            note=note,
        )

    def delay_signal(self, signal_id: int, note: Optional[str] = None) -> None:
        self.db.delay_signal(signal_id, note=note)

    def ignore_signal(self, signal_id: int, note: Optional[str] = None) -> None:
        self.db.ignore_signal(signal_id, note=note)

    def list_positions(self) -> list[dict]:
        return self.db.get_positions()
