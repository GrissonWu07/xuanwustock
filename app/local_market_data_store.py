from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import os
from pathlib import Path
import re
import threading
from typing import Any, Callable, Iterable

import pandas as pd

from app.runtime_paths import DATA_DIR


LOGGER = logging.getLogger(__name__)
PARQUET_ENGINE = os.getenv("MARKET_DATA_PARQUET_ENGINE", "pyarrow")
SUPPORTED_PROVIDERS = {"akshare", "tdx", "tushare"}


@dataclass(frozen=True)
class LocalMarketDataResult:
    data: pd.DataFrame
    cache_status: str
    cache_source: str
    path: Path


def default_local_market_data_dir() -> Path:
    return Path(os.getenv("LOCAL_MARKET_DATA_DIR") or (DATA_DIR / "local_sources"))


def _clean_part(value: Any) -> str:
    text = str(value if value not in (None, "") else "none").strip()
    text = text.replace("\\", "_").replace("/", "_").replace(":", "_")
    return re.sub(r"[^0-9A-Za-z_.=\-\u4e00-\u9fff]+", "_", text) or "none"


def _normalize_provider(provider: str) -> str:
    normalized = str(provider).strip().lower()
    if normalized not in SUPPORTED_PROVIDERS:
        raise ValueError(f"unsupported market data provider: {provider}")
    return normalized


def _normalize_symbol(symbol: Any) -> str:
    text = str(symbol or "").strip().upper()
    return text.split(".")[0] if "." in text else text


def _coerce_datetime(value: Any) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    try:
        return pd.to_datetime(value)
    except Exception:
        return None


class LocalMarketDataStore:
    """Parquet-backed local-first store for provider-specific market data."""

    _LOCKS_GUARD = threading.Lock()
    _LOCKS: dict[Path, threading.RLock] = {}

    def __init__(self, root_dir: str | Path | None = None, *, enabled: bool | None = None):
        self.root_dir = Path(root_dir) if root_dir is not None else default_local_market_data_dir()
        if enabled is None:
            enabled = os.getenv("MARKET_DATA_CACHE_ENABLED", "true").lower() not in {"0", "false", "no", "off"}
        self.enabled = bool(enabled)

    def path_for(
        self,
        provider: str,
        dataset: str,
        symbol: Any,
        params: dict[str, Any] | None = None,
    ) -> Path:
        provider_name = _normalize_provider(provider)
        parts = [self.root_dir, provider_name, _clean_part(dataset)]
        for key, value in sorted((params or {}).items()):
            parts.append(_clean_part(f"{key}={value if value not in (None, '') else 'none'}"))
        return Path(*parts) / f"{_clean_part(_normalize_symbol(symbol))}.parquet"

    def read_frame(
        self,
        provider: str,
        dataset: str,
        symbol: Any,
        params: dict[str, Any] | None = None,
    ) -> pd.DataFrame | None:
        if not self.enabled:
            return None
        path = self.path_for(provider, dataset, symbol, params)
        if not path.exists():
            return None
        try:
            return pd.read_parquet(path, engine=PARQUET_ENGINE)
        except Exception as exc:
            LOGGER.warning(
                "local market data read failed provider=%s dataset=%s symbol=%s path=%s error=%s",
                provider,
                dataset,
                symbol,
                path,
                exc,
            )
            return None

    def write_frame(
        self,
        provider: str,
        dataset: str,
        symbol: Any,
        frame: pd.DataFrame,
        params: dict[str, Any] | None = None,
    ) -> Path:
        path = self.path_for(provider, dataset, symbol, params)
        if not self.enabled or frame is None or frame.empty:
            return path
        with self._lock_for(path):
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(f".tmp-{threading.get_ident()}.parquet")
            frame.to_parquet(tmp_path, index=False, engine=PARQUET_ENGINE)
            tmp_path.replace(path)
        return path

    def merge_frame(
        self,
        provider: str,
        dataset: str,
        symbol: Any,
        new_frame: pd.DataFrame,
        *,
        params: dict[str, Any] | None = None,
        key_columns: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        provider_name = _normalize_provider(provider)
        path = self.path_for(provider_name, dataset, symbol, params)
        prepared = self._prepare_frame(new_frame, provider_name)
        if prepared.empty:
            existing = self.read_frame(provider_name, dataset, symbol, params)
            return existing if existing is not None else prepared

        existing = self.read_frame(provider_name, dataset, symbol, params)
        merged = pd.concat([existing, prepared], ignore_index=True) if existing is not None and not existing.empty else prepared
        keys = [key for key in (key_columns or []) if key in merged.columns]
        if keys:
            merged = merged.drop_duplicates(subset=keys, keep="last")
        sort_columns = [column for column in ("datetime", "date", "quote_time", "fetched_at") if column in merged.columns]
        if sort_columns:
            merged = merged.sort_values(sort_columns).reset_index(drop=True)
        self.write_frame(provider_name, dataset, symbol, merged, params)
        LOGGER.info(
            "local market data write provider=%s dataset=%s symbol=%s rows=%s path=%s",
            provider_name,
            dataset,
            symbol,
            len(merged),
            path,
        )
        return merged

    def fetch_range(
        self,
        provider: str,
        dataset: str,
        symbol: Any,
        *,
        start: Any = None,
        end: Any = None,
        params: dict[str, Any] | None = None,
        remote_fetcher: Callable[[Any, Any], pd.DataFrame | None],
        key_columns: Iterable[str],
        datetime_col: str = "datetime",
    ) -> LocalMarketDataResult:
        provider_name = _normalize_provider(provider)
        path = self.path_for(provider_name, dataset, symbol, params)
        local = self.read_frame(provider_name, dataset, symbol, params)
        local_slice = self._filter_range(local, start, end, datetime_col=datetime_col)
        if self._range_covers(local, start, end, datetime_col=datetime_col) and local_slice is not None and not local_slice.empty:
            return self._result(local_slice, "hit", f"local_{provider_name}", path)

        status = "miss" if local is None or local.empty else "partial"
        remote = remote_fetcher(start, end)
        if remote is None or remote.empty:
            if local_slice is not None and not local_slice.empty:
                return self._result(local_slice, "stale", f"local_{provider_name}", path)
            return self._result(pd.DataFrame(), "remote_failed", f"remote_{provider_name}", path)

        merged = self.merge_frame(provider_name, dataset, symbol, remote, params=params, key_columns=key_columns)
        merged_slice = self._filter_range(merged, start, end, datetime_col=datetime_col)
        return self._result(merged_slice if merged_slice is not None else merged, status, f"remote_{provider_name}", path)

    def fetch_latest(
        self,
        provider: str,
        dataset: str,
        symbol: Any,
        *,
        ttl_seconds: int,
        remote_fetcher: Callable[[], pd.DataFrame | None],
        key_columns: Iterable[str],
        now: datetime | None = None,
        params: dict[str, Any] | None = None,
        fetched_at_col: str = "fetched_at",
    ) -> LocalMarketDataResult:
        provider_name = _normalize_provider(provider)
        path = self.path_for(provider_name, dataset, symbol, params)
        current_time = pd.Timestamp(now or datetime.now())
        local = self.read_frame(provider_name, dataset, symbol, params)
        latest = self._latest(local, fetched_at_col=fetched_at_col)
        if latest is not None and not latest.empty:
            fetched_at = _coerce_datetime(latest.iloc[0].get(fetched_at_col))
            if fetched_at is not None and (current_time - fetched_at).total_seconds() <= ttl_seconds:
                return self._result(latest, "hit", f"local_{provider_name}", path)

        status = "miss" if latest is None or latest.empty else "stale"
        remote = remote_fetcher()
        if remote is None or remote.empty:
            if latest is not None and not latest.empty:
                return self._result(latest, "stale", f"local_{provider_name}", path)
            return self._result(pd.DataFrame(), "remote_failed", f"remote_{provider_name}", path)

        prepared = remote.copy()
        if fetched_at_col not in prepared.columns:
            prepared[fetched_at_col] = current_time
        merged = self.merge_frame(provider_name, dataset, symbol, prepared, params=params, key_columns=key_columns)
        latest_merged = self._latest(merged, fetched_at_col=fetched_at_col)
        return self._result(
            latest_merged if latest_merged is not None and not latest_merged.empty else prepared,
            status,
            f"remote_{provider_name}",
            path,
        )

    def _lock_for(self, path: Path) -> threading.RLock:
        resolved = path.resolve()
        with self._LOCKS_GUARD:
            if resolved not in self._LOCKS:
                self._LOCKS[resolved] = threading.RLock()
            return self._LOCKS[resolved]

    def _prepare_frame(self, frame: pd.DataFrame | None, provider: str) -> pd.DataFrame:
        if frame is None or frame.empty:
            return pd.DataFrame()
        prepared = frame.copy()
        if "symbol" in prepared.columns:
            prepared["symbol"] = prepared["symbol"].map(_normalize_symbol)
        if "datetime" in prepared.columns:
            prepared["datetime"] = pd.to_datetime(prepared["datetime"])
            if "date" not in prepared.columns:
                prepared["date"] = prepared["datetime"].dt.strftime("%Y-%m-%d")
        if "quote_time" in prepared.columns:
            prepared["quote_time"] = pd.to_datetime(prepared["quote_time"])
        if "fetched_at" not in prepared.columns:
            prepared["fetched_at"] = pd.Timestamp(datetime.now())
        else:
            prepared["fetched_at"] = pd.to_datetime(prepared["fetched_at"])
        if "provider" not in prepared.columns:
            prepared["provider"] = provider
        if "source" not in prepared.columns:
            prepared["source"] = provider
        return prepared

    def _filter_range(
        self,
        frame: pd.DataFrame | None,
        start: Any,
        end: Any,
        *,
        datetime_col: str,
    ) -> pd.DataFrame | None:
        if frame is None or frame.empty or datetime_col not in frame.columns:
            return frame
        result = frame.copy()
        result[datetime_col] = pd.to_datetime(result[datetime_col])
        start_dt = _coerce_datetime(start)
        end_dt = _coerce_datetime(end)
        if start_dt is not None:
            result = result[result[datetime_col] >= start_dt]
        if end_dt is not None:
            result = result[result[datetime_col] <= end_dt]
        return result.reset_index(drop=True)

    def _range_covers(
        self,
        frame: pd.DataFrame | None,
        start: Any,
        end: Any,
        *,
        datetime_col: str,
    ) -> bool:
        if frame is None or frame.empty or datetime_col not in frame.columns:
            return False
        values = pd.to_datetime(frame[datetime_col])
        start_dt = _coerce_datetime(start)
        end_dt = _coerce_datetime(end)
        if start_dt is not None and values.min() > start_dt:
            return False
        if end_dt is not None and values.max() < end_dt:
            return False
        return True

    def _latest(self, frame: pd.DataFrame | None, *, fetched_at_col: str) -> pd.DataFrame | None:
        if frame is None or frame.empty:
            return None
        if fetched_at_col not in frame.columns:
            return frame.tail(1).reset_index(drop=True)
        result = frame.copy()
        result[fetched_at_col] = pd.to_datetime(result[fetched_at_col])
        return result.sort_values(fetched_at_col).tail(1).reset_index(drop=True)

    def _result(self, frame: pd.DataFrame, status: str, cache_source: str, path: Path) -> LocalMarketDataResult:
        data = frame.copy() if frame is not None else pd.DataFrame()
        data["cache_source"] = cache_source
        data["cache_status"] = status
        return LocalMarketDataResult(data=data, cache_status=status, cache_source=cache_source, path=path)
