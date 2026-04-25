from __future__ import annotations

from datetime import datetime
import os
from typing import Any, Callable

import pandas as pd

from app.local_market_data_store import LocalMarketDataStore


DEFAULT_REALTIME_TTL_SECONDS = int(os.getenv("MARKET_DATA_REALTIME_TTL_SECONDS", "45"))


def _clean_symbol(symbol: Any) -> str:
    text = str(symbol or "").strip().upper()
    return text.split(".")[0] if "." in text else text


def _ts_code(symbol: str) -> str:
    clean = _clean_symbol(symbol)
    if clean.startswith("6"):
        return f"{clean}.SH"
    if clean.startswith(("0", "3")):
        return f"{clean}.SZ"
    if clean.startswith(("4", "8")):
        return f"{clean}.BJ"
    return f"{clean}.SZ"


def _yyyymmdd(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if "-" in text:
        return pd.to_datetime(text).strftime("%Y%m%d")
    return text


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _normalize_akshare_hist(df: pd.DataFrame | None, symbol: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    result = df.rename(
        columns={
            "日期": "datetime",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "振幅": "amplitude",
            "涨跌幅": "pct_change",
            "涨跌额": "change",
            "换手率": "turnover",
        }
    ).copy()
    result["symbol"] = _clean_symbol(symbol)
    result["datetime"] = pd.to_datetime(result["datetime"])
    return result.sort_values("datetime").reset_index(drop=True)


def _normalize_tushare_daily(df: pd.DataFrame | None, symbol: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    result = df.rename(
        columns={
            "trade_date": "datetime",
            "vol": "volume",
        }
    ).copy()
    result["symbol"] = _clean_symbol(symbol)
    result["datetime"] = pd.to_datetime(result["datetime"])
    if "volume" in result.columns:
        result["volume"] = pd.to_numeric(result["volume"], errors="coerce").fillna(0) * 100
    if "amount" in result.columns:
        result["amount"] = pd.to_numeric(result["amount"], errors="coerce").fillna(0) * 1000
    return result.sort_values("datetime").reset_index(drop=True)


def _normalize_chinese_kline(df: pd.DataFrame | None, symbol: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    result = df.rename(
        columns={
            "日期": "datetime",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
        }
    ).copy()
    result["symbol"] = _clean_symbol(symbol)
    result["datetime"] = pd.to_datetime(result["datetime"])
    return result.sort_values("datetime").reset_index(drop=True)


def canonical_to_data_source_frame(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    columns = ["date", "open", "close", "high", "low", "volume", "amount", "amplitude", "pct_change", "change", "turnover"]
    result = df.copy()
    if "date" not in result.columns and "datetime" in result.columns:
        result["date"] = pd.to_datetime(result["datetime"])
    keep = [column for column in columns if column in result.columns]
    metadata = [column for column in ("symbol", "source", "provider", "cache_source", "cache_status", "fetched_at") if column in result.columns]
    return result[keep + metadata].reset_index(drop=True)


def canonical_to_akshare_frame(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    result = df.copy()
    result["日期"] = pd.to_datetime(result["datetime"])
    result = result.rename(
        columns={
            "open": "开盘",
            "close": "收盘",
            "high": "最高",
            "low": "最低",
            "volume": "成交量",
            "amount": "成交额",
            "amplitude": "振幅",
            "pct_change": "涨跌幅",
            "change": "涨跌额",
            "turnover": "换手率",
        }
    )
    columns = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"]
    metadata = [column for column in ("symbol", "source", "provider", "cache_source", "cache_status", "fetched_at") if column in result.columns]
    return result[[column for column in columns if column in result.columns] + metadata].reset_index(drop=True)


def canonical_to_tdx_frame(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    result = df.copy()
    result["日期"] = pd.to_datetime(result["datetime"])
    result = result.rename(
        columns={
            "open": "开盘",
            "close": "收盘",
            "high": "最高",
            "low": "最低",
            "volume": "成交量",
            "amount": "成交额",
        }
    )
    columns = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"]
    metadata = [column for column in ("symbol", "source", "provider", "cache_source", "cache_status", "fetched_at") if column in result.columns]
    return result[[column for column in columns if column in result.columns] + metadata].reset_index(drop=True)


def _quote_frame_from_dict(payload: dict[str, Any] | None, symbol: str, provider: str) -> pd.DataFrame:
    if not payload:
        return pd.DataFrame()
    row = dict(payload)
    row["symbol"] = _clean_symbol(row.get("symbol") or row.get("code") or symbol)
    row["quote_time"] = pd.to_datetime(row.get("quote_time") or row.get("update_time") or datetime.now())
    row["data_source"] = provider
    return pd.DataFrame([row])


def _latest_dict(df: pd.DataFrame, provider: str) -> dict[str, Any] | None:
    if df is None or df.empty:
        return None
    row = df.iloc[-1].to_dict()
    row["code"] = row.get("code") or row.get("symbol")
    row["data_source"] = row.get("data_source") or provider
    return row


class AkshareLocalClient:
    def __init__(self, *, store: LocalMarketDataStore | None = None, ak_api: Any = None):
        self.store = store or LocalMarketDataStore()
        self.ak = ak_api

    def _ak_api(self):
        if self.ak is not None:
            return self.ak
        from app.akshare_client import ak

        return ak

    def get_stock_hist_data(
        self,
        symbol: str,
        *,
        start_date: Any = None,
        end_date: Any = None,
        adjust: str = "qfq",
        period: str = "daily",
        output: str = "data_source",
    ) -> pd.DataFrame | None:
        clean = _clean_symbol(symbol)
        normalized_start = _yyyymmdd(start_date)
        normalized_end = _yyyymmdd(end_date) or datetime.now().strftime("%Y%m%d")
        params = {"period": period, "adjust": adjust or "none"}

        def fetch_remote(start: Any, end: Any) -> pd.DataFrame:
            df = self._ak_api().stock_zh_a_hist(
                symbol=clean,
                period=period,
                start_date=normalized_start,
                end_date=normalized_end,
                adjust=adjust,
            )
            return _normalize_akshare_hist(df, clean)

        result = self.store.fetch_range(
            "akshare",
            "hist_daily",
            clean,
            start=normalized_start,
            end=normalized_end,
            params=params,
            remote_fetcher=fetch_remote,
            key_columns=["symbol", "datetime"],
        )
        if result.data.empty:
            return None
        return canonical_to_akshare_frame(result.data) if output == "akshare" else canonical_to_data_source_frame(result.data)

    def get_realtime_quote(
        self,
        symbol: str,
        *,
        ttl_seconds: int = DEFAULT_REALTIME_TTL_SECONDS,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        clean = _clean_symbol(symbol)

        def fetch_remote() -> pd.DataFrame:
            df = self._ak_api().stock_zh_a_spot_em()
            if df is None or df.empty:
                return pd.DataFrame()
            stock_df = df[df["代码"].astype(str) == clean]
            if stock_df.empty:
                return pd.DataFrame()
            row = stock_df.iloc[0]
            return _quote_frame_from_dict(
                {
                    "symbol": clean,
                    "name": row.get("名称"),
                    "current_price": row.get("最新价"),
                    "price": row.get("最新价"),
                    "change_percent": row.get("涨跌幅"),
                    "change_pct": row.get("涨跌幅"),
                    "change": row.get("涨跌额"),
                    "change_amount": row.get("涨跌额"),
                    "volume": row.get("成交量"),
                    "amount": row.get("成交额"),
                    "high": row.get("最高"),
                    "low": row.get("最低"),
                    "open": row.get("今开"),
                    "pre_close": row.get("昨收"),
                },
                clean,
                "akshare",
            )

        result = self.store.fetch_latest(
            "akshare",
            "spot_quote",
            clean,
            ttl_seconds=ttl_seconds,
            now=now,
            remote_fetcher=fetch_remote,
            key_columns=["symbol", "quote_time"],
        )
        return _latest_dict(result.data, "akshare")

    def get_stock_basic_info(self, symbol: str) -> dict[str, Any] | None:
        clean = _clean_symbol(symbol)
        result = self.store.fetch_latest(
            "akshare",
            "basic_info",
            clean,
            ttl_seconds=int(os.getenv("MARKET_DATA_BASIC_INFO_TTL_DAYS", "30")) * 86400,
            remote_fetcher=lambda: self._fetch_basic_info(clean),
            key_columns=["symbol"],
        )
        return _latest_dict(result.data, "akshare")

    def _fetch_basic_info(self, symbol: str) -> pd.DataFrame:
        df = self._ak_api().stock_individual_info_em(symbol=symbol)
        if df is None or df.empty:
            return pd.DataFrame()
        info = {"symbol": symbol}
        for _, row in df.iterrows():
            key = row.get("item")
            value = row.get("value")
            if key == "股票简称":
                info["name"] = value
            elif key == "所处行业":
                info["industry"] = value
            elif key == "上市时间":
                info["list_date"] = value
            elif key == "总市值":
                info["market_cap"] = value
            elif key == "流通市值":
                info["circulating_market_cap"] = value
            elif key == "市盈率-动态":
                info["pe_ratio"] = value
            elif key == "市净率":
                info["pb_ratio"] = value
        info["fetched_at"] = datetime.now()
        return pd.DataFrame([info])

    def get_financial_data(self, symbol: str, report_type: str = "income") -> pd.DataFrame | None:
        clean = _clean_symbol(symbol)
        dataset_params = {"report_type": report_type}

        def fetch_remote() -> pd.DataFrame:
            report_name = {"income": "利润表", "balance": "资产负债表", "cashflow": "现金流量表"}.get(report_type)
            if not report_name:
                return pd.DataFrame()
            df = self._ak_api().stock_financial_report_sina(stock=clean, symbol=report_name)
            if df is None or df.empty:
                return pd.DataFrame()
            result = df.copy()
            result["symbol"] = clean
            result["fetched_at"] = datetime.now()
            return result

        result = self.store.fetch_latest(
            "akshare",
            "financial",
            clean,
            params=dataset_params,
            ttl_seconds=int(os.getenv("MARKET_DATA_FINANCIAL_TTL_DAYS", "7")) * 86400,
            remote_fetcher=fetch_remote,
            key_columns=["symbol", "fetched_at"],
        )
        return result.data if not result.data.empty else None


class TushareLocalClient:
    def __init__(self, *, store: LocalMarketDataStore | None = None, tushare_api: Any = None):
        self.store = store or LocalMarketDataStore()
        self.tushare_api = tushare_api

    def get_stock_hist_data(
        self,
        symbol: str,
        *,
        start_date: Any = None,
        end_date: Any = None,
        adjust: str = "qfq",
        output: str = "data_source",
    ) -> pd.DataFrame | None:
        clean = _clean_symbol(symbol)
        normalized_start = _yyyymmdd(start_date)
        normalized_end = _yyyymmdd(end_date) or datetime.now().strftime("%Y%m%d")
        params = {"adjust": adjust or "none"}

        def fetch_remote(start: Any, end: Any) -> pd.DataFrame:
            if self.tushare_api is None:
                return pd.DataFrame()
            try:
                df = self.tushare_api.daily(ts_code=_ts_code(clean), start_date=normalized_start, end_date=normalized_end, adj=adjust)
            except TypeError:
                df = self.tushare_api.daily(ts_code=_ts_code(clean), start_date=normalized_start, end_date=normalized_end)
            return _normalize_tushare_daily(df, clean)

        result = self.store.fetch_range(
            "tushare",
            "daily",
            clean,
            start=normalized_start,
            end=normalized_end,
            params=params,
            remote_fetcher=fetch_remote,
            key_columns=["symbol", "datetime"],
        )
        if result.data.empty:
            return None
        return canonical_to_akshare_frame(result.data) if output == "akshare" else canonical_to_data_source_frame(result.data)

    def get_stock_basic_info(self, symbol: str) -> dict[str, Any] | None:
        clean = _clean_symbol(symbol)
        result = self.store.fetch_latest(
            "tushare",
            "stock_basic",
            clean,
            ttl_seconds=int(os.getenv("MARKET_DATA_BASIC_INFO_TTL_DAYS", "30")) * 86400,
            remote_fetcher=lambda: self._fetch_basic_info(clean),
            key_columns=["symbol"],
        )
        return _latest_dict(result.data, "tushare")

    def _fetch_basic_info(self, symbol: str) -> pd.DataFrame:
        if self.tushare_api is None:
            return pd.DataFrame()
        df = self.tushare_api.stock_basic(ts_code=_ts_code(symbol), fields="ts_code,name,area,industry,market,list_date")
        if df is None or df.empty:
            return pd.DataFrame()
        row = df.iloc[0]
        return pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "name": row.get("name"),
                    "industry": row.get("industry"),
                    "market": row.get("market"),
                    "list_date": row.get("list_date"),
                    "fetched_at": datetime.now(),
                }
            ]
        )

    def get_realtime_quote(self, symbol: str, *, ttl_seconds: int = DEFAULT_REALTIME_TTL_SECONDS) -> dict[str, Any] | None:
        clean = _clean_symbol(symbol)
        today = datetime.now().strftime("%Y%m%d")

        def fetch_remote() -> pd.DataFrame:
            if self.tushare_api is None:
                return pd.DataFrame()
            df = self.tushare_api.daily(ts_code=_ts_code(clean), start_date=today, end_date=today)
            if df is None or df.empty:
                return pd.DataFrame()
            row = df.iloc[0]
            return _quote_frame_from_dict(
                {
                    "symbol": clean,
                    "current_price": row.get("close"),
                    "price": row.get("close"),
                    "change_percent": row.get("pct_chg"),
                    "change_pct": row.get("pct_chg"),
                    "volume": _safe_float(row.get("vol")) * 100,
                    "amount": _safe_float(row.get("amount")) * 1000,
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "open": row.get("open"),
                    "pre_close": row.get("pre_close"),
                },
                clean,
                "tushare",
            )

        result = self.store.fetch_latest(
            "tushare",
            "daily_quote",
            clean,
            ttl_seconds=ttl_seconds,
            remote_fetcher=fetch_remote,
            key_columns=["symbol", "quote_time"],
        )
        return _latest_dict(result.data, "tushare")

    def get_financial_data(self, symbol: str, report_type: str = "income") -> pd.DataFrame | None:
        clean = _clean_symbol(symbol)

        def fetch_remote() -> pd.DataFrame:
            if self.tushare_api is None:
                return pd.DataFrame()
            method = {
                "income": getattr(self.tushare_api, "income", None),
                "balance": getattr(self.tushare_api, "balancesheet", None),
                "cashflow": getattr(self.tushare_api, "cashflow", None),
            }.get(report_type)
            if method is None:
                return pd.DataFrame()
            df = method(ts_code=_ts_code(clean))
            if df is None or df.empty:
                return pd.DataFrame()
            result = df.copy()
            result["symbol"] = clean
            result["fetched_at"] = datetime.now()
            return result

        result = self.store.fetch_latest(
            "tushare",
            "financial",
            clean,
            params={"report_type": report_type},
            ttl_seconds=int(os.getenv("MARKET_DATA_FINANCIAL_TTL_DAYS", "7")) * 86400,
            remote_fetcher=fetch_remote,
            key_columns=["symbol", "fetched_at"],
        )
        return result.data if not result.data.empty else None


class TdxLocalClient:
    def __init__(self, *, store: LocalMarketDataStore | None = None):
        self.store = store or LocalMarketDataStore()

    def get_kline_data(
        self,
        symbol: str,
        *,
        kline_type: str,
        limit: int,
        remote_fetcher: Callable[[], pd.DataFrame | None],
    ) -> pd.DataFrame | None:
        clean = _clean_symbol(symbol)
        params = {"kline_type": kline_type}
        local = self.store.read_frame("tdx", "kline", clean, params=params)
        if local is not None and len(local) >= int(limit) and os.getenv("MARKET_DATA_FORCE_REMOTE", "false").lower() not in {"1", "true", "yes"}:
            result = local.sort_values("datetime").tail(int(limit)).reset_index(drop=True)
            result["cache_source"] = "local_tdx"
            result["cache_status"] = "hit"
            return canonical_to_tdx_frame(result)

        remote = _normalize_chinese_kline(remote_fetcher(), clean)
        if remote.empty:
            if local is not None and not local.empty:
                result = local.sort_values("datetime").tail(int(limit)).reset_index(drop=True)
                result["cache_source"] = "local_tdx"
                result["cache_status"] = "stale"
                return canonical_to_tdx_frame(result)
            return None
        merged = self.store.merge_frame("tdx", "kline", clean, remote, params=params, key_columns=["symbol", "datetime"])
        result = merged.sort_values("datetime").tail(int(limit)).reset_index(drop=True)
        result["cache_source"] = "remote_tdx"
        result["cache_status"] = "miss" if local is None or local.empty else "partial"
        return canonical_to_tdx_frame(result)

    def get_kline_data_range(
        self,
        symbol: str,
        *,
        kline_type: str,
        start_datetime: Any = None,
        end_datetime: Any = None,
        remote_fetcher: Callable[[], pd.DataFrame | None],
    ) -> pd.DataFrame | None:
        clean = _clean_symbol(symbol)
        result = self.store.fetch_range(
            "tdx",
            "kline",
            clean,
            start=start_datetime,
            end=end_datetime,
            params={"kline_type": kline_type},
            remote_fetcher=lambda start, end: _normalize_chinese_kline(remote_fetcher(), clean),
            key_columns=["symbol", "datetime"],
        )
        return canonical_to_tdx_frame(result.data) if not result.data.empty else None

    def get_realtime_quote(
        self,
        symbol: str,
        *,
        remote_fetcher: Callable[[], dict[str, Any] | None],
        ttl_seconds: int = DEFAULT_REALTIME_TTL_SECONDS,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        clean = _clean_symbol(symbol)
        result = self.store.fetch_latest(
            "tdx",
            "realtime_quote",
            clean,
            ttl_seconds=ttl_seconds,
            now=now,
            remote_fetcher=lambda: _quote_frame_from_dict(remote_fetcher(), clean, "tdx"),
            key_columns=["symbol", "quote_time"],
        )
        return _latest_dict(result.data, "tdx")

    def get_security_name(self, symbol: str, *, market: int, remote_fetcher: Callable[[], str | None]) -> str | None:
        clean = _clean_symbol(symbol)
        result = self.store.fetch_latest(
            "tdx",
            "security_name",
            clean,
            params={"market": market},
            ttl_seconds=int(os.getenv("MARKET_DATA_BASIC_INFO_TTL_DAYS", "30")) * 86400,
            remote_fetcher=lambda: pd.DataFrame([{"symbol": clean, "market": market, "name": remote_fetcher(), "fetched_at": datetime.now()}]),
            key_columns=["symbol", "market"],
        )
        if result.data.empty:
            return None
        return str(result.data.iloc[-1].get("name") or "").strip() or None
