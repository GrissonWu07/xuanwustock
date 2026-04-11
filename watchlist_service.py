from __future__ import annotations

from pathlib import Path
from typing import Any

from watchlist_db import WatchlistDB


class WatchlistService:
    def __init__(self, db_file: str | Path = "watchlist.db"):
        self.db = WatchlistDB(db_file)

    def add_stock(
        self,
        stock_code: str,
        stock_name: str,
        source: str,
        latest_price: float | None = None,
        notes: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        watch_id = self.db.add_watch(
            stock_code=stock_code,
            stock_name=stock_name,
            source=source,
            latest_price=latest_price,
            notes=notes,
            metadata=metadata,
        )
        return {"created": True, "watch_id": watch_id}

    def add_many(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        summary = {"attempted": 0, "success_count": 0, "failures": []}
        for row in rows:
            stock_code = str(row.get("stock_code", "")).strip()
            stock_name = str(row.get("stock_name", "")).strip()
            source = str(row.get("source", "")).strip()
            if not stock_code or not stock_name or not source:
                summary["failures"].append(f"{stock_code or 'UNKNOWN'}: missing required field")
                continue

            summary["attempted"] += 1
            self.add_stock(
                stock_code=stock_code,
                stock_name=stock_name,
                source=source,
                latest_price=row.get("latest_price"),
                notes=row.get("notes"),
                metadata=row.get("metadata"),
            )
            summary["success_count"] += 1
        return summary

    def list_watches(self) -> list[dict[str, Any]]:
        return self.db.list_watches()

    def get_watch(self, stock_code: str) -> dict[str, Any] | None:
        return self.db.get_watch(stock_code)

    def mark_in_quant_pool(self, stock_code: str, in_quant_pool: bool) -> None:
        self.db.update_quant_membership(stock_code, in_quant_pool)

    def sync_quant_membership(self, candidate_stock_codes: list[str]) -> None:
        normalized_codes = {str(stock_code).strip().upper() for stock_code in candidate_stock_codes}
        for watch in self.list_watches():
            self.mark_in_quant_pool(watch["stock_code"], watch["stock_code"] in normalized_codes)

    def delete_stock(self, stock_code: str) -> None:
        self.db.delete_watch(stock_code)
