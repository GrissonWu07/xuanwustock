from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from watchlist_db import WatchlistDB


class WatchlistService:
    def __init__(
        self,
        db_file: str | Path = "watchlist.db",
        stock_name_resolver: Callable[[str], str] | None = None,
        quote_fetcher: Callable[[str, str | None], dict[str, Any] | None] | None = None,
    ):
        self.db = WatchlistDB(db_file)
        self.stock_name_resolver = stock_name_resolver or self._resolve_stock_name
        self.quote_fetcher = quote_fetcher or self._fetch_realtime_quote

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

    def add_manual_stock(self, stock_code: str) -> dict[str, Any]:
        normalized_code = str(stock_code).strip().upper()
        stock_name = normalized_code
        summary = self.add_stock(
            stock_code=normalized_code,
            stock_name=stock_name,
            source="manual",
        )
        summary["stock_name"] = stock_name
        return summary

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

    def update_watch_snapshot(
        self,
        stock_code: str,
        *,
        latest_signal: str | None = None,
        latest_price: float | None = None,
        stock_name: str | None = None,
    ) -> None:
        self.db.update_watch_snapshot(
            stock_code,
            latest_signal=latest_signal,
            latest_price=latest_price,
            stock_name=stock_name,
        )

    def refresh_quotes(self, stock_codes: list[str] | None = None) -> dict[str, Any]:
        selected_codes = {str(code).strip().upper() for code in stock_codes or [] if str(code).strip()}
        watches = self.list_watches()
        if selected_codes:
            watches = [watch for watch in watches if watch["stock_code"] in selected_codes]

        summary = {"attempted": 0, "success_count": 0, "failures": []}
        for watch in watches:
            stock_code = watch["stock_code"]
            summary["attempted"] += 1
            try:
                current_name = str(watch.get("stock_name") or "").strip()
                preferred_name = current_name
                if not current_name or current_name.upper() == stock_code or current_name.upper() == "N/A":
                    preferred_name = None

                quote = self.quote_fetcher(stock_code, preferred_name)
                if not quote:
                    summary["failures"].append(f"{stock_code}: quote unavailable")
                    continue

                latest_price = quote.get("current_price")
                quote_name = str(quote.get("name") or "").strip()
                should_update_name = current_name.upper() == stock_code or current_name in {"", "N/A"}
                resolved_name = quote_name if should_update_name and quote_name else None

                self.update_watch_snapshot(
                    stock_code,
                    latest_price=float(latest_price) if latest_price is not None else None,
                    stock_name=resolved_name,
                )
                summary["success_count"] += 1
            except Exception as exc:
                summary["failures"].append(f"{stock_code}: {exc}")
        return summary

    def delete_stock(self, stock_code: str) -> None:
        self.db.delete_watch(stock_code)

    @staticmethod
    def _resolve_stock_name(stock_code: str) -> str:
        try:
            from smart_monitor_tdx_data import SmartMonitorTDXDataFetcher

            return str(SmartMonitorTDXDataFetcher()._get_stock_name(stock_code) or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _fetch_realtime_quote(stock_code: str, preferred_name: str | None = None) -> dict[str, Any] | None:
        try:
            from smart_monitor_tdx_data import SmartMonitorTDXDataFetcher

            fetcher = SmartMonitorTDXDataFetcher()
            return fetcher.get_realtime_quote(stock_code, preferred_name=preferred_name)
        except Exception:
            return None
