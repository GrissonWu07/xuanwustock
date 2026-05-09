from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable

import schedule

from app.quant_sim.scheduler import TRADING_DAYS, TRADING_HOURS
from app.quant_sim.time_utils import format_utc_iso_z, market_timezone
from app.selector_result_store import DEFAULT_SELECTOR_RESULT_DIR, load_latest_result, save_latest_result
from app.watchlist_selector_integration import normalize_stock_code


RUNTIME_SNAPSHOT_KEY = "stock_runtime_snapshot"
REFRESH_INTERVAL_MINUTES = 2
DEFAULT_POLL_SECONDS = 20.0
MAX_FETCH_WORKERS = max(1, int(os.getenv("UNIFIED_STOCK_REFRESH_WORKERS", "6")))
QUOTE_REALTIME_TTL_SECONDS = 120
BASIC_INFO_TTL_SECONDS = 24 * 60 * 60
REMOTE_FAILURE_COOLDOWN_SECONDS = 600
_SCHEDULER_INSTANCE: "UnifiedStockRefreshScheduler | None" = None


def _txt(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _price(value: Any) -> float | None:
    try:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text in {"N/A", "-", "--"}:
            return None
        number = float(text)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def _metric_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        text = str(value).strip().replace(",", "")
        if not text or text in {"N/A", "NA", "-", "--", "None", "nan"}:
            return None
        number = float(text)
        return number if number == number else None
    except (TypeError, ValueError):
        return None


def _first_metric(mapping: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = _metric_float(mapping.get(key))
        if value is not None:
            return value
    return None


def _has_basic_metrics(entry: dict[str, Any] | None) -> bool:
    if not isinstance(entry, dict):
        return False
    return all(_metric_float(entry.get(key)) is not None for key in ("market_cap", "pe_ratio", "pb_ratio"))


def _is_basic_info_check_recent(entry: dict[str, Any] | None, *, now_utc: datetime | None = None) -> bool:
    if not isinstance(entry, dict):
        return False
    checked_at = _parse_utc_timestamp(entry.get("basic_info_checked_at"))
    if checked_at is None:
        return False
    base = now_utc or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return (base.astimezone(timezone.utc) - checked_at).total_seconds() < BASIC_INFO_TTL_SECONDS


def _valid_name(value: Any) -> str:
    text = _txt(value)
    if not text:
        return ""
    if text.upper() in {"N/A", "-", "--", "UNKNOWN", "未知"}:
        return ""
    return text


def _valid_sector(value: Any) -> str:
    text = _txt(value)
    if not text:
        return ""
    if text.upper() in {"N/A", "-", "--", "UNKNOWN", "未知"}:
        return ""
    return text


def _first_non_empty(mapping: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _code_from_mapping(row: dict[str, Any]) -> str:
    return normalize_stock_code(
        _first_non_empty(
            row,
            [
                "股票代码",
                "stock_code",
                "stockCode",
                "code",
                "symbol",
                "证券代码",
                "代码",
                "id",
            ],
        )
    )


def load_stock_runtime_entries(base_dir: str | Path = DEFAULT_SELECTOR_RESULT_DIR) -> dict[str, dict[str, Any]]:
    payload = load_latest_result(RUNTIME_SNAPSHOT_KEY, base_dir=base_dir) or {}
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_code, item in entries.items():
        code = normalize_stock_code(raw_code)
        if not code or not isinstance(item, dict):
            continue
        normalized[code] = dict(item)
    return normalized


def get_stock_runtime_entry(stock_code: str, base_dir: str | Path = DEFAULT_SELECTOR_RESULT_DIR) -> dict[str, Any] | None:
    code = normalize_stock_code(stock_code)
    if not code:
        return None
    return load_stock_runtime_entries(base_dir=base_dir).get(code)


def save_stock_runtime_entries(
    entries: dict[str, dict[str, Any]],
    *,
    base_dir: str | Path = DEFAULT_SELECTOR_RESULT_DIR,
    updated_at: str | None = None,
) -> None:
    normalized: dict[str, dict[str, Any]] = {}
    for raw_code, item in entries.items():
        code = normalize_stock_code(raw_code)
        if not code or not isinstance(item, dict):
            continue
        normalized[code] = {
            "stock_code": code,
            "stock_name": _valid_name(item.get("stock_name")) or code,
            "latest_price": _price(item.get("latest_price")),
            "market_cap": _metric_float(item.get("market_cap")),
            "pe_ratio": _metric_float(item.get("pe_ratio")),
            "pb_ratio": _metric_float(item.get("pb_ratio")),
            "sector": _valid_sector(item.get("sector")),
            "price_as_of": _txt(item.get("price_as_of")),
            "data_source": _txt(item.get("data_source")),
            "updated_at": _txt(item.get("updated_at"), updated_at or _now()),
            "basic_info_checked_at": _txt(item.get("basic_info_checked_at")),
        }
        for key in ("refresh_status", "failure_at", "failure_reason", "failure_count"):
            if item.get(key) not in (None, ""):
                normalized[code][key] = item.get(key)
    save_latest_result(
        RUNTIME_SNAPSHOT_KEY,
        {
            "updatedAt": updated_at or _now(),
            "entries": normalized,
        },
        base_dir=base_dir,
    )


def _now() -> str:
    return format_utc_iso_z()


def _parse_utc_timestamp(value: Any) -> datetime | None:
    text = _txt(value)
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


class UnifiedStockRefreshScheduler:
    def __init__(
        self,
        context_provider: Callable[[], Any],
        *,
        interval_minutes: int = REFRESH_INTERVAL_MINUTES,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
    ) -> None:
        self._context_provider = context_provider
        self.interval_minutes = max(1, int(interval_minutes))
        self.poll_seconds = max(1.0, float(poll_seconds))
        self.scheduler = schedule.Scheduler()
        self.running = False
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.job_tag = "unified_stock_refresh"
        self.last_run_at: str | None = None
        self.last_summary: dict[str, Any] | None = None
        self._executor_lock = threading.Lock()
        self._active_executor: ThreadPoolExecutor | None = None

    def set_context_provider(self, provider: Callable[[], Any]) -> None:
        self._context_provider = provider

    def start(self) -> bool:
        if self.running:
            return False
        self.running = True
        self.stop_event.clear()
        self._register_jobs()
        self.thread = threading.Thread(target=self._schedule_loop, daemon=True, name="stock-refresh-scheduler")
        self.thread.start()
        return True

    def stop(self) -> bool:
        if not self.running:
            self._clear_jobs()
            return False
        self.running = False
        self.stop_event.set()
        self._clear_jobs()
        with self._executor_lock:
            if self._active_executor is not None:
                self._active_executor.shutdown(wait=False, cancel_futures=True)
        if self.thread:
            self.thread.join(timeout=5)
            self.thread = None
        return True

    def get_status(self) -> dict[str, Any]:
        jobs = self.scheduler.get_jobs(self.job_tag)
        next_run = format_utc_iso_z(jobs[0].next_run.astimezone()) if jobs else None
        return {
            "running": self.running,
            "interval_minutes": self.interval_minutes,
            "last_run_at": self.last_run_at,
            "next_run": next_run,
            "last_summary": self.last_summary or {},
        }

    def run_once(self, *, context: Any | None = None, run_reason: str = "manual") -> dict[str, Any]:
        ctx = context or self._context_provider()
        if ctx is None:
            return {"reason": run_reason, "updated": 0, "failed": 0, "totalCodes": 0, "updatedAt": _now()}
        if self.stop_event.is_set():
            return {"reason": run_reason, "updated": 0, "failed": 0, "totalCodes": 0, "stopped": True, "updatedAt": _now()}

        market = self._resolve_market(ctx)
        market_is_trading = self._is_trading_time(market)
        prefer_last_trading_snapshot = not market_is_trading
        codes = sorted(self._collect_codes(ctx))
        existing_entries = load_stock_runtime_entries(base_dir=ctx.selector_result_dir)
        if not codes:
            summary = {
                "reason": run_reason,
                "updated": 0,
                "failed": 0,
                "totalCodes": 0,
                "market": market,
                "marketState": "trading" if market_is_trading else "last_trading_snapshot",
                "updatedAt": _now(),
            }
            self.last_run_at = summary["updatedAt"]
            self.last_summary = summary
            return summary

        watchlist_service = ctx.watchlist()
        watchlist_codes = {
            normalize_stock_code(item.get("stock_code"))
            for item in watchlist_service.list_watches()
            if normalize_stock_code(item.get("stock_code"))
        }
        manager = ctx.portfolio_manager()
        portfolio_rows = manager.get_all_stocks()
        portfolio_map = {
            normalize_stock_code(item.get("code")): item
            for item in portfolio_rows
            if normalize_stock_code(item.get("code"))
        }
        quant_db = ctx.quant_db()

        next_entries = dict(existing_entries)
        failures: list[str] = []
        fetched: dict[str, dict[str, Any]] = {}
        remote_fetched = 0
        cache_hits = 0
        cooldown_skipped = 0
        if self.stop_event.is_set():
            return {
                "reason": run_reason,
                "updated": 0,
                "failed": 0,
                "totalCodes": len(codes),
                "market": market,
                "marketState": "trading" if market_is_trading else "last_trading_snapshot",
                "stopped": True,
                "updatedAt": _now(),
            }

        worker_count = min(MAX_FETCH_WORKERS, len(codes))
        pool = ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="stock-refresh-fetch")
        with self._executor_lock:
            self._active_executor = pool
        try:
            future_map = {}
            for code in codes:
                if self.stop_event.is_set():
                    break
                existing_entry = existing_entries.get(code)
                if self._is_failure_cooldown_active(existing_entry):
                    if isinstance(existing_entry, dict):
                        next_entries[code] = {**existing_entry, "cache_status": "negative_hit"}
                    cooldown_skipped += 1
                    continue
                if self._is_runtime_entry_fresh(existing_entry) and (
                    _has_basic_metrics(existing_entry) or _is_basic_info_check_recent(existing_entry)
                ):
                    fetched[code] = {**existing_entry, "cache_status": "hit"}
                    cache_hits += 1
                    continue
                future = pool.submit(
                    self._fetch_runtime_entry,
                    stock_code=code,
                    existing=existing_entry,
                    prefer_last_trading_snapshot=prefer_last_trading_snapshot,
                    stop_event=self.stop_event,
                )
                future_map[future] = code

            pending = set(future_map)
            while pending:
                if self.stop_event.is_set():
                    for future in pending:
                        future.cancel()
                    break
                done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                for future in done:
                    code = future_map[future]
                    try:
                        entry = future.result()
                    except Exception as exc:
                        failures.append(f"{code}: {exc}")
                        previous = existing_entries.get(code) if isinstance(existing_entries.get(code), dict) else {}
                        failure_count = int(previous.get("failure_count") or 0) + 1 if isinstance(previous, dict) else 1
                        next_entries[code] = {
                            **previous,
                            "stock_code": code,
                            "stock_name": _valid_name(previous.get("stock_name")) or code,
                            "data_source": _txt(previous.get("data_source"), "remote_failed"),
                            "refresh_status": "remote_failed",
                            "failure_at": _now(),
                            "failure_reason": str(exc),
                            "failure_count": failure_count,
                            "updated_at": _txt(previous.get("updated_at"), _now()),
                        }
                        continue
                    if not isinstance(entry, dict):
                        continue
                    fetched[code] = entry
                    remote_fetched += 1
        finally:
            with self._executor_lock:
                if self._active_executor is pool:
                    self._active_executor = None
            pool.shutdown(wait=not self.stop_event.is_set(), cancel_futures=True)

        applied = 0
        for code, entry in fetched.items():
            next_entries[code] = entry
            applied += 1

            latest_price = _price(entry.get("latest_price"))
            resolved_name = _valid_name(entry.get("stock_name"))
            stock_name = resolved_name or code
            sector = _valid_sector(entry.get("sector"))

            if code in watchlist_codes:
                metadata: dict[str, Any] = {}
                if sector:
                    metadata["industry"] = sector
                    metadata["sector"] = sector
                for key in ("market_cap", "pe_ratio", "pb_ratio"):
                    if _metric_float(entry.get(key)) is not None:
                        metadata[key] = entry.get(key)
                watchlist_service.update_watch_snapshot(
                    code,
                    latest_price=latest_price,
                    stock_name=stock_name,
                    metadata=metadata or None,
                )

            candidate_metadata: dict[str, Any] = {}
            if sector:
                candidate_metadata["industry"] = sector
                candidate_metadata["sector"] = sector
            for key in ("market_cap", "pe_ratio", "pb_ratio"):
                if _metric_float(entry.get(key)) is not None:
                    candidate_metadata[key] = entry.get(key)
            candidate_name = resolved_name if resolved_name and resolved_name.upper() != code.upper() else None
            if hasattr(quant_db, "update_candidate_snapshot"):
                quant_db.update_candidate_snapshot(
                    code,
                    latest_price=latest_price,
                    stock_name=candidate_name,
                    metadata=candidate_metadata or None,
                )
            elif latest_price is not None:
                quant_db.update_candidate_latest_price(code, latest_price)
            if latest_price is not None:
                quant_db.update_position_market_price(code, latest_price)

            portfolio_item = portfolio_map.get(code)
            if portfolio_item:
                update_fields: dict[str, Any] = {}
                if stock_name and _txt(portfolio_item.get("name")) != stock_name:
                    update_fields["name"] = stock_name
                if sector and _txt(portfolio_item.get("sector")) != sector:
                    update_fields["sector"] = sector
                if update_fields:
                    stock_id = int(portfolio_item.get("id") or 0)
                    if stock_id > 0:
                        try:
                            manager.db.update_stock(stock_id, **update_fields)
                        except Exception as exc:
                            failures.append(f"{code}: {exc}")

        save_stock_runtime_entries(next_entries, base_dir=ctx.selector_result_dir, updated_at=_now())

        summary = {
            "reason": run_reason,
            "updated": remote_fetched,
            "applied": applied,
            "cacheHit": cache_hits,
            "remoteFetched": remote_fetched,
            "cooldownSkipped": cooldown_skipped,
            "failed": len(failures),
            "totalCodes": len(codes),
            "market": market,
            "marketState": "trading" if market_is_trading else "last_trading_snapshot",
            "updatedAt": _now(),
        }
        if self.stop_event.is_set():
            summary["stopped"] = True
        self.last_run_at = summary["updatedAt"]
        self.last_summary = summary
        return summary

    def _schedule_loop(self) -> None:
        while self.running and not self.stop_event.is_set():
            try:
                self.scheduler.run_pending()
            finally:
                self.stop_event.wait(self.poll_seconds)

    def _register_jobs(self) -> None:
        self._clear_jobs()
        self.scheduler.every(self.interval_minutes).minutes.do(self._run_scheduled_cycle).tag(self.job_tag)

    def _clear_jobs(self) -> None:
        for job in self.scheduler.get_jobs(self.job_tag):
            self.scheduler.cancel_job(job)

    def _run_scheduled_cycle(self) -> None:
        if self.stop_event.is_set():
            return
        context = self._context_provider()
        if context is None:
            return
        self.run_once(context=context, run_reason="scheduled")

    @staticmethod
    def _is_runtime_entry_fresh(entry: dict[str, Any] | None, *, now_utc: datetime | None = None) -> bool:
        if not isinstance(entry, dict):
            return False
        if _price(entry.get("latest_price")) is None:
            return False
        updated_at = _parse_utc_timestamp(entry.get("updated_at"))
        if updated_at is None:
            return False
        base = now_utc or datetime.now(timezone.utc)
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        return (base.astimezone(timezone.utc) - updated_at).total_seconds() < QUOTE_REALTIME_TTL_SECONDS

    @staticmethod
    def _is_failure_cooldown_active(entry: dict[str, Any] | None, *, now_utc: datetime | None = None) -> bool:
        if not isinstance(entry, dict):
            return False
        if _txt(entry.get("refresh_status")) != "remote_failed":
            return False
        failure_at = _parse_utc_timestamp(entry.get("failure_at"))
        if failure_at is None:
            return False
        base = now_utc or datetime.now(timezone.utc)
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        return (base.astimezone(timezone.utc) - failure_at).total_seconds() < REMOTE_FAILURE_COOLDOWN_SECONDS

    @staticmethod
    def _resolve_market(context: Any) -> str:
        try:
            return _txt(context.scheduler().get_status().get("market"), "CN")
        except Exception:
            return "CN"

    @staticmethod
    def _is_trading_time(market: str, *, now_utc: datetime | None = None) -> bool:
        base = now_utc or datetime.now(timezone.utc)
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        now = base.astimezone(market_timezone(market))
        weekday = now.weekday() + 1
        if weekday not in TRADING_DAYS:
            return False

        current_time = now.time()
        periods = TRADING_HOURS.get((market or "CN").upper(), TRADING_HOURS["CN"])
        for start_str, end_str in periods:
            start_time = datetime.strptime(start_str, "%H:%M").time()
            end_time = datetime.strptime(end_str, "%H:%M").time()
            if start_time <= end_time:
                if start_time <= current_time <= end_time:
                    return True
            else:
                if current_time >= start_time or current_time <= end_time:
                    return True
        return False

    @staticmethod
    def _fetch_runtime_entry(
        *,
        stock_code: str,
        existing: dict[str, Any] | None,
        prefer_last_trading_snapshot: bool = False,
        stop_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        existing_entry = existing if isinstance(existing, dict) else {}
        existing_name = _valid_name(existing_entry.get("stock_name"))
        if existing_name.upper() == stock_code.upper():
            existing_name = ""
        existing_sector = _valid_sector(existing_entry.get("sector"))
        existing_price = _price(existing_entry.get("latest_price"))
        existing_price_as_of = _txt(existing_entry.get("price_as_of"))

        last_trading_snapshot: dict[str, Any] = {}
        if prefer_last_trading_snapshot and not (stop_event and stop_event.is_set()):
            last_trading_snapshot = UnifiedStockRefreshScheduler._latest_trading_snapshot(
                stock_code,
                preferred_name=existing_name or None,
            )

        quote: dict[str, Any] = {}
        if not (stop_event and stop_event.is_set()):
            quote = UnifiedStockRefreshScheduler._fetch_realtime_quote(stock_code, existing_name or None)

        need_basic_info = (not existing_sector or not existing_name or not _has_basic_metrics(existing_entry)) and not _is_basic_info_check_recent(existing_entry)
        basic_info: dict[str, Any] = {}
        if need_basic_info and not (stop_event and stop_event.is_set()):
            basic_info = UnifiedStockRefreshScheduler._fetch_basic_info(stock_code)
        basic_info_checked_at = _now() if need_basic_info else _txt(existing_entry.get("basic_info_checked_at"))

        quote_name = _valid_name(quote.get("name"))
        if quote_name.upper() == stock_code.upper():
            quote_name = ""
        info_name = _valid_name(basic_info.get("name"))
        if info_name.upper() == stock_code.upper():
            info_name = ""
        snapshot_name = _valid_name(last_trading_snapshot.get("name"))
        if snapshot_name.upper() == stock_code.upper():
            snapshot_name = ""

        stock_name = (
            quote_name
            or info_name
            or snapshot_name
            or existing_name
            or stock_code
        )
        sector = (
            _valid_sector(basic_info.get("industry"))
            or _valid_sector(basic_info.get("sector"))
            or _valid_sector(quote.get("industry"))
            or existing_sector
        )
        latest_price = (
            _price(last_trading_snapshot.get("current_price"))
            or _price(last_trading_snapshot.get("price"))
            or _price(quote.get("current_price"))
            or _price(quote.get("price"))
            or _price(basic_info.get("current_price"))
            or existing_price
        )
        price_as_of = (
            _txt(last_trading_snapshot.get("update_time"))
            or _txt(quote.get("update_time"))
            or existing_price_as_of
        )
        data_source = (
            _txt(last_trading_snapshot.get("data_source"))
            or _txt(quote.get("data_source"))
            or _txt(existing_entry.get("data_source"))
        )
        market_cap = (
            _first_metric(basic_info, ["market_cap", "marketCap", "total_market_cap", "total_market_value", "总市值", "市值"])
            or _first_metric(quote, ["market_cap", "marketCap", "total_market_cap", "total_market_value", "总市值", "市值"])
            or _metric_float(existing_entry.get("market_cap"))
        )
        pe_ratio = (
            _first_metric(basic_info, ["pe_ratio", "pe", "pe_ttm", "PE", "市盈率", "市盈率TTM"])
            or _first_metric(quote, ["pe_ratio", "pe", "pe_ttm", "PE", "市盈率", "市盈率TTM"])
            or _metric_float(existing_entry.get("pe_ratio"))
        )
        pb_ratio = (
            _first_metric(basic_info, ["pb_ratio", "pb", "PB", "市净率"])
            or _first_metric(quote, ["pb_ratio", "pb", "PB", "市净率"])
            or _metric_float(existing_entry.get("pb_ratio"))
        )

        return {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "latest_price": latest_price,
            "market_cap": market_cap,
            "pe_ratio": pe_ratio,
            "pb_ratio": pb_ratio,
            "sector": sector,
            "price_as_of": price_as_of,
            "data_source": data_source,
            "basic_info_checked_at": basic_info_checked_at,
            "updated_at": _now(),
        }

    @staticmethod
    def _fetch_realtime_quote(stock_code: str, preferred_name: str | None = None) -> dict[str, Any]:
        try:
            from app.smart_monitor_tdx_data import SmartMonitorTDXDataFetcher

            quote = SmartMonitorTDXDataFetcher().get_realtime_quote(stock_code, preferred_name=preferred_name)
            if isinstance(quote, dict) and quote:
                return quote
        except Exception:
            pass
        try:
            from app.data_source_manager import data_source_manager

            quote = data_source_manager.get_realtime_quotes(stock_code)
            if isinstance(quote, dict) and quote:
                if preferred_name and not quote.get("name"):
                    quote["name"] = preferred_name
                return quote
        except Exception:
            pass
        return {}

    @staticmethod
    def _fetch_basic_info(stock_code: str) -> dict[str, Any]:
        try:
            from app.data_source_manager import data_source_manager

            info = data_source_manager.get_stock_basic_info(stock_code)
            return info if isinstance(info, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _latest_trading_snapshot(stock_code: str, preferred_name: str | None = None) -> dict[str, Any]:
        try:
            from app.smart_monitor_tdx_data import SmartMonitorTDXDataFetcher

            fetcher = SmartMonitorTDXDataFetcher()
            frame = fetcher.get_kline_data(stock_code, kline_type="day", limit=2)
            if frame is None or getattr(frame, "empty", True):
                return {}

            latest = frame.iloc[-1]
            previous = frame.iloc[-2] if len(frame) >= 2 else None
            latest_close = _price(latest.get("收盘"))
            if latest_close is None:
                return {}

            previous_close = _price(previous.get("收盘")) if previous is not None else _price(latest.get("开盘"))
            stock_name = preferred_name or ""
            if not stock_name:
                try:
                    stock_name = fetcher._get_stock_name(stock_code)
                except Exception:
                    stock_name = ""

            return {
                "code": normalize_stock_code(stock_code),
                "name": _valid_name(stock_name) or normalize_stock_code(stock_code),
                "current_price": latest_close,
                "price": latest_close,
                "pre_close": previous_close,
                "update_time": UnifiedStockRefreshScheduler._format_snapshot_time(latest.get("日期")),
                "data_source": "tdx_daily_latest",
            }
        except Exception:
            return {}

    @staticmethod
    def _format_snapshot_time(value: Any) -> str:
        if value is None:
            return ""
        try:
            if hasattr(value, "to_pydatetime"):
                value = value.to_pydatetime()
            if isinstance(value, datetime):
                return value.replace(microsecond=0).isoformat(sep=" ")
        except Exception:
            pass
        text = _txt(value)
        return text[:19] if len(text) > 19 else text

    @staticmethod
    def _collect_codes(context: Any) -> set[str]:
        codes: set[str] = set()

        try:
            for item in context.watchlist().list_watches():
                code = normalize_stock_code(item.get("stock_code"))
                if code:
                    codes.add(code)
        except Exception:
            pass

        try:
            for item in context.portfolio_manager().get_all_stocks():
                code = normalize_stock_code(item.get("code") or item.get("symbol"))
                if code:
                    codes.add(code)
        except Exception:
            pass

        try:
            db = context.quant_db()
            for item in db.get_candidates(status="active"):
                code = normalize_stock_code(item.get("stock_code"))
                if code:
                    codes.add(code)
            for item in db.get_positions():
                code = normalize_stock_code(item.get("stock_code"))
                if code:
                    codes.add(code)
        except Exception:
            pass

        return codes


def get_unified_stock_refresh_scheduler(context: Any | None = None) -> UnifiedStockRefreshScheduler:
    global _SCHEDULER_INSTANCE
    if _SCHEDULER_INSTANCE is None:
        if context is None:
            raise RuntimeError("context is required for initial scheduler creation")
        _SCHEDULER_INSTANCE = UnifiedStockRefreshScheduler(lambda: context)
    elif context is not None:
        _SCHEDULER_INSTANCE.set_context_provider(lambda: context)
    return _SCHEDULER_INSTANCE


__all__ = [
    "get_stock_runtime_entry",
    "get_unified_stock_refresh_scheduler",
    "load_stock_runtime_entries",
    "save_stock_runtime_entries",
]
