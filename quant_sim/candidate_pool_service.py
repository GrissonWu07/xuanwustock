"""Candidate pool operations for the quant simulation workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from quant_sim.db import DEFAULT_DB_FILE, QuantSimDB


class CandidatePoolService:
    """Service layer for manual and selector-driven candidate management."""

    def __init__(self, db_file: str | Path = DEFAULT_DB_FILE):
        self.db = QuantSimDB(db_file)

    def add_manual_candidate(
        self,
        stock_code: str,
        stock_name: str,
        source: str,
        latest_price: Optional[float] = None,
        notes: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> int:
        return self.db.add_candidate(
            {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "source": source,
                "latest_price": latest_price or 0,
                "notes": notes,
                "metadata": metadata or {},
                "status": "active",
            }
        )

    def add_candidate(
        self,
        *,
        stock_code: str,
        stock_name: str,
        source: str,
        latest_price: Optional[float] = None,
        notes: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        status: str = "active",
    ) -> int:
        return self.db.add_candidate(
            {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "source": source,
                "latest_price": latest_price or 0,
                "notes": notes,
                "metadata": metadata or {},
                "status": status,
            }
        )

    def list_candidates(self, status: Optional[str] = None) -> list[dict[str, Any]]:
        return self.db.get_candidates(status=status)

    def delete_candidate(self, stock_code: str) -> None:
        self.db.delete_candidate(stock_code)
