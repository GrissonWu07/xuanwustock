"""Signal creation and listing helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from quant_sim.db import DEFAULT_DB_FILE, QuantSimDB


class SignalCenterService:
    """Normalizes strategy decisions into persisted signals."""

    def __init__(self, db_file: str | Path = DEFAULT_DB_FILE):
        self.db = QuantSimDB(db_file)

    def create_signal(self, candidate: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        action = str(decision.get("action", "HOLD")).upper()
        status = "pending" if action in {"BUY", "SELL"} else "observed"
        signal_id = self.db.add_signal(
            {
                "candidate_id": candidate.get("id"),
                "stock_code": candidate["stock_code"],
                "stock_name": candidate.get("stock_name"),
                "action": action,
                "confidence": int(decision.get("confidence", 0)),
                "reasoning": decision.get("reasoning", ""),
                "position_size_pct": float(decision.get("position_size_pct", 0)),
                "stop_loss_pct": float(decision.get("stop_loss_pct", 5)),
                "take_profit_pct": float(decision.get("take_profit_pct", 12)),
                "status": status,
            }
        )
        return self.db.get_signals(stock_code=candidate["stock_code"], limit=1)[0]

    def list_pending_signals(self) -> list[dict[str, Any]]:
        return self.db.get_pending_signals()

    def list_signals(self, stock_code: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        return self.db.get_signals(stock_code=stock_code, limit=limit)
