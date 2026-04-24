from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable

from app.watchlist_db import DEFAULT_DB_FILE, WatchlistDB


class WatchlistService:
    def __init__(
        self,
        db_file: str | Path = DEFAULT_DB_FILE,
        stock_name_resolver: Callable[[str], str] | None = None,
        quote_fetcher: Callable[[str, str | None], dict[str, Any] | None] | None = None,
        basic_info_fetcher: Callable[[str], dict[str, Any] | None] | None = None,
    ):
        self.db = WatchlistDB(db_file)
        self.stock_name_resolver = stock_name_resolver or self._resolve_stock_name
        self.quote_fetcher = quote_fetcher or self._fetch_realtime_quote
        self.basic_info_fetcher = basic_info_fetcher or self._fetch_basic_info
        self.basic_info_cache_ttl_seconds = max(60, self._env_int("WATCHLIST_BASIC_INFO_CACHE_TTL_SECONDS", 4 * 3600))
        self.basic_info_refresh_limit = max(0, self._env_int("WATCHLIST_BASIC_INFO_REFRESH_LIMIT", 2))
        self._basic_info_cache: dict[str, tuple[float, dict[str, Any]]] = {}

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
        if not normalized_code:
            raise ValueError("Invalid stock code")
        existing = self.get_watch(normalized_code)
        if existing:
            return {"created": False, "stock_name": str(existing.get("stock_name") or normalized_code), "watch_id": existing.get("id")}
        summary = self.add_stock(
            stock_code=normalized_code,
            stock_name=normalized_code,
            source="manual",
            latest_price=None,
            metadata=None,
        )
        summary["stock_name"] = normalized_code
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

    def list_watches_page(self, search: str | None = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self.db.list_watches_page(search=search, limit=limit, offset=offset)

    def count_watches(self, search: str | None = None, *, in_quant_pool: bool | None = None) -> int:
        return self.db.count_watches(search=search, in_quant_pool=in_quant_pool)

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
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.db.update_watch_snapshot(
            stock_code,
            latest_signal=latest_signal,
            latest_price=latest_price,
            stock_name=stock_name,
            metadata=metadata,
        )

    def refresh_quotes(
        self,
        stock_codes: list[str] | None = None,
        *,
        full_refresh: bool = False,
    ) -> dict[str, Any]:
        watches = self.list_watches()
        if stock_codes is not None:
            selected_codes = {str(code).strip().upper() for code in stock_codes if str(code).strip()}
            watches = [watch for watch in watches if watch["stock_code"] in selected_codes]

        summary = {"attempted": 0, "success_count": 0, "failures": []}
        basic_info_budget = len(watches) if full_refresh else self.basic_info_refresh_limit
        for watch in watches:
            stock_code = watch["stock_code"]
            summary["attempted"] += 1
            try:
                current_name = str(watch.get("stock_name") or "").strip()
                watch_metadata = watch.get("metadata") if isinstance(watch.get("metadata"), dict) else {}
                preferred_name = current_name
                if not current_name or current_name.upper() == stock_code or current_name.upper() == "N/A":
                    preferred_name = None

                quote = self.quote_fetcher(stock_code, preferred_name)
                quote_available = isinstance(quote, dict) and bool(quote)
                basic_info: dict[str, Any] = {}

                latest_price: float | None = None
                if quote_available:
                    raw_price = quote.get("current_price")
                    try:
                        if raw_price is not None and str(raw_price).strip() not in {"", "N/A", "-"}:
                            latest_price = float(raw_price)
                    except (TypeError, ValueError):
                        latest_price = None

                quote_name = str((quote or {}).get("name") or "").strip()
                should_update_name = current_name.upper() == stock_code or current_name in {"", "N/A"}
                resolved_name = None
                if should_update_name:
                    if quote_name and quote_name.upper() not in {stock_code, "N/A", "-"}:
                        resolved_name = quote_name

                existing_industry = str(watch_metadata.get("industry") or watch_metadata.get("sector") or "").strip()
                need_industry = existing_industry in {"", "-", "N/A", "未知"}
                need_name_from_info = should_update_name and not resolved_name
                need_basic_info = (full_refresh or need_industry or need_name_from_info) and basic_info_budget > 0
                if need_basic_info:
                    cached = self._get_cached_basic_info(stock_code, force_fetch=full_refresh)
                    if cached:
                        basic_info = cached
                        basic_info_budget -= 1

                if need_name_from_info and not resolved_name:
                    info_name = str(basic_info.get("name") or "").strip()
                    if info_name and info_name.upper() not in {stock_code, "N/A", "-", "UNKNOWN", "未知"}:
                        resolved_name = info_name

                industry = str(basic_info.get("industry") or basic_info.get("sector") or "").strip()
                metadata_update: dict[str, Any] = {}
                if industry and industry not in {"未知", "N/A", "-"}:
                    metadata_update["industry"] = industry
                    metadata_update["sector"] = industry

                if not quote_available and latest_price is None and not resolved_name and not metadata_update:
                    summary["failures"].append(f"{stock_code}: quote unavailable")
                    continue

                self.update_watch_snapshot(
                    stock_code,
                    latest_price=latest_price,
                    stock_name=resolved_name,
                    metadata=metadata_update or None,
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
            from app.smart_monitor_tdx_data import SmartMonitorTDXDataFetcher

            return str(SmartMonitorTDXDataFetcher()._get_stock_name(stock_code) or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _fetch_realtime_quote(stock_code: str, preferred_name: str | None = None) -> dict[str, Any] | None:
        try:
            from app.smart_monitor_tdx_data import SmartMonitorTDXDataFetcher

            fetcher = SmartMonitorTDXDataFetcher()
            return fetcher.get_realtime_quote(stock_code, preferred_name=preferred_name)
        except Exception:
            return None

    @staticmethod
    def _fetch_basic_info(stock_code: str) -> dict[str, Any] | None:
        try:
            from app.data_source_manager import data_source_manager

            info = data_source_manager.get_stock_basic_info(stock_code)
            return info if isinstance(info, dict) else None
        except Exception:
            return None

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        raw = str(os.getenv(name, "")).strip()
        if not raw:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    def _get_cached_basic_info(self, stock_code: str, *, force_fetch: bool = False) -> dict[str, Any]:
        now = time.time()
        cached = self._basic_info_cache.get(stock_code)
        if not force_fetch and cached and (now - cached[0]) <= self.basic_info_cache_ttl_seconds:
            return cached[1]
        info = self.basic_info_fetcher(stock_code)
        if isinstance(info, dict) and info:
            self._basic_info_cache[stock_code] = (now, info)
            return info
        if force_fetch and cached:
            return cached[1]
        return {}
