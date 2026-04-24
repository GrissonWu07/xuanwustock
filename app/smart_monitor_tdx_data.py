"""
智能盯盘 - TDX 数据获取模块
使用 pytdx 直连通达信行情服务器获取实时行情和技术指标
"""

from app.console_utils import safe_print as print
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
from pytdx.config.hosts import hq_hosts
from pytdx.hq import TdxHq_API

from app.pytdx_host_config import load_pytdx_hosts


DEFAULT_TDX_PORT = 7709
DEFAULT_TDX_TIMEOUT = 5
DEFAULT_HOST_LIMIT = 10
DEFAULT_TDX_MAX_HOST_ATTEMPTS = 4
SECURITY_LIST_PAGE_SIZE = 1000
DEFAULT_DEPRIORITIZED_TDX_HOSTS = {
    ("218.85.139.19", 7709),
    ("218.85.139.20", 7709),
    ("58.23.131.163", 7709),
    ("218.6.170.47", 7709),
}
DEFAULT_DEPRIORITIZED_TDX_NAME_KEYWORDS = ("长城国瑞",)

KLINE_TYPE_MAP = {
    "minute5": 0,
    "minute15": 1,
    "minute30": 2,
    "hour": 3,
    "day": 9,
    "week": 5,
    "month": 6,
    "minute1": 8,
}


class SmartMonitorTDXDataFetcher:
    """基于 pytdx 的 TDX 数据获取器"""
    _HOST_HEALTH_LOCK = threading.Lock()
    _HOST_HEALTH: Dict[Tuple[str, int], Dict[str, float]] = {}

    def __init__(
        self,
        host: Optional[str] = None,
        port: int = DEFAULT_TDX_PORT,
        fallback_hosts: Optional[Sequence[Tuple[str, str, int] | str]] = None,
        hosts_file: Optional[str | Path] = None,
        timeout: int = DEFAULT_TDX_TIMEOUT,
    ):
        self.logger = logging.getLogger(__name__)
        self.timeout = timeout
        config_host = None
        config_fallback_hosts: Sequence[Tuple[str, str, int] | str] | None = None
        config_hosts_file = None
        try:
            from app.config import TDX_CONFIG

            config_host = TDX_CONFIG.get("host")
            config_fallback_hosts = TDX_CONFIG.get("fallback_hosts", [])
            config_hosts_file = TDX_CONFIG.get("hosts_file")
        except Exception:
            pass

        effective_host = host if host is not None else config_host
        effective_fallback_hosts = fallback_hosts if fallback_hosts is not None else config_fallback_hosts
        effective_hosts_file = hosts_file if hosts_file is not None else config_hosts_file

        self._deprioritized_host_keys, self._deprioritized_host_only, self._deprioritized_name_keywords = self._load_deprioritized_hosts()
        self.hosts = self._build_hosts(effective_host, port, effective_fallback_hosts, effective_hosts_file)
        self._name_cache: Dict[Tuple[int, str], str] = {}

        host_summary = ", ".join(f"{name}:{ip}:{host_port}" for name, ip, host_port in self.hosts[:3])
        self.logger.info(f"TDX数据源初始化成功，使用pytdx直连: {host_summary}")

    def get_realtime_quote(self, stock_code: str, preferred_name: Optional[str] = None) -> Optional[Dict]:
        """
        获取实时行情

        Args:
            stock_code: 股票代码（如：600519）

        Returns:
            实时行情数据
        """
        clean_code = self._normalize_stock_code(stock_code)
        market = self._get_market(clean_code)

        try:
            quote_data = self._fetch_quote_data(market, clean_code)
            if not quote_data:
                self.logger.warning(f"TDX未返回股票 {clean_code} 的行情数据")
                return None

            current_price = self._safe_float(quote_data.get("price"))
            pre_close = self._safe_float(quote_data.get("last_close"))
            change_amount = round(current_price - pre_close, 4)
            change_pct = round((change_amount / pre_close * 100), 4) if pre_close > 0 else 0.0

            stock_name = preferred_name or self._get_stock_name(clean_code)

            self.logger.info(f"✅ TDX成功获取 {clean_code} ({stock_name}) 实时行情")

            return {
                "code": clean_code,
                "name": stock_name,
                "current_price": current_price,
                "change_pct": change_pct,
                "change_amount": change_amount,
                "volume": self._safe_float(quote_data.get("vol")),
                "amount": self._safe_float(quote_data.get("amount")),
                "high": self._safe_float(quote_data.get("high")),
                "low": self._safe_float(quote_data.get("low")),
                "open": self._safe_float(quote_data.get("open")),
                "pre_close": pre_close,
                "turnover_rate": 0.0,
                "volume_ratio": 1.0,
                "update_time": self._format_update_time(quote_data.get("servertime")),
                "data_source": "tdx",
            }
        except Exception as exc:
            self.logger.error(f"TDX获取行情失败 {clean_code}: {type(exc).__name__}: {exc}")
            return None

    def _get_stock_name(self, stock_code: str) -> str:
        """
        获取股票名称

        Args:
            stock_code: 股票代码

        Returns:
            股票名称
        """
        clean_code = self._normalize_stock_code(stock_code)
        market = self._get_market(clean_code)
        cache_key = (market, clean_code)

        if cache_key in self._name_cache:
            return self._name_cache[cache_key]

        try:
            def operation(api: TdxHq_API):
                total = api.get_security_count(market)
                for start in range(0, total, SECURITY_LIST_PAGE_SIZE):
                    for item in api.get_security_list(market, start):
                        if item.get("code") == clean_code:
                            return item.get("name", "N/A")
                return None

            stock_name = self._call_with_failover(operation)
            stock_name = stock_name or "N/A"
            self._name_cache[cache_key] = stock_name
            return stock_name
        except Exception as exc:
            self.logger.warning(f"获取股票名称失败 {clean_code}: {exc}")
            return "N/A"

    def get_kline_data(self, stock_code: str, kline_type: str = "day", limit: int = 200) -> Optional[pd.DataFrame]:
        """
        获取K线数据

        Args:
            stock_code: 股票代码
            kline_type: K线类型（minute1/minute5/minute15/minute30/hour/day/week/month）
            limit: 返回条数（最多800）

        Returns:
            K线数据 DataFrame
        """
        clean_code = self._normalize_stock_code(stock_code)
        market = self._get_market(clean_code)
        category = KLINE_TYPE_MAP.get(kline_type, KLINE_TYPE_MAP["day"])

        try:
            bars = self._fetch_kline_data(market, clean_code, category, 0, limit)
            if not bars:
                self.logger.warning(f"TDX未返回股票 {clean_code} 的K线数据")
                return None

            df = pd.DataFrame(bars)
            if df.empty:
                return None

            df = df.rename(
                columns={
                    "datetime": "日期",
                    "open": "开盘",
                    "close": "收盘",
                    "high": "最高",
                    "low": "最低",
                    "vol": "成交量",
                    "amount": "成交额",
                }
            )
            df["日期"] = pd.to_datetime(df["日期"])
            df = df.sort_values("日期").reset_index(drop=True)

            if len(df) > limit:
                df = df.tail(limit).reset_index(drop=True)

            df = df[["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"]]

            self.logger.info(f"✅ TDX成功获取 {clean_code} K线数据，共{len(df)}条")
            return df
        except Exception as exc:
            self.logger.error(f"TDX获取K线失败 {clean_code}: {type(exc).__name__}: {exc}")
            return None

    def get_kline_data_range(
        self,
        stock_code: str,
        kline_type: str = "day",
        *,
        start_datetime: Optional[datetime | str] = None,
        end_datetime: Optional[datetime | str] = None,
        max_bars: int = 3200,
    ) -> Optional[pd.DataFrame]:
        """Fetch a larger historical K-line window and filter it by datetime range."""

        clean_code = self._normalize_stock_code(stock_code)
        market = self._get_market(clean_code)
        category = KLINE_TYPE_MAP.get(kline_type, KLINE_TYPE_MAP["day"])
        normalized_start = pd.to_datetime(start_datetime) if start_datetime is not None else None
        normalized_end = pd.to_datetime(end_datetime) if end_datetime is not None else None

        try:
            chunk_size = 800
            rows: list[dict] = []
            start_offset = 0

            while start_offset < max_bars:
                batch = self._fetch_kline_data(market, clean_code, category, start_offset, min(chunk_size, max_bars - start_offset))
                if not batch:
                    break
                rows.extend(batch)
                if len(batch) < chunk_size:
                    break
                start_offset += chunk_size

            if not rows:
                return None

            df = pd.DataFrame(rows)
            if df.empty:
                return None

            df = df.rename(
                columns={
                    "datetime": "日期",
                    "open": "开盘",
                    "close": "收盘",
                    "high": "最高",
                    "low": "最低",
                    "vol": "成交量",
                    "amount": "成交额",
                }
            )
            df["日期"] = pd.to_datetime(df["日期"])
            df = (
                df[["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"]]
                .sort_values("日期")
                .drop_duplicates(subset=["日期"], keep="last")
                .reset_index(drop=True)
            )

            if normalized_start is not None:
                df = df[df["日期"] >= normalized_start]
            if normalized_end is not None:
                df = df[df["日期"] <= normalized_end]

            return df.reset_index(drop=True)
        except Exception as exc:
            self.logger.error(f"TDX获取历史区间K线失败 {clean_code}: {type(exc).__name__}: {exc}")
            return None

    def get_technical_indicators(self, stock_code: str, period: str = "daily") -> Optional[Dict]:
        """
        计算技术指标

        Args:
            stock_code: 股票代码
            period: 周期（daily/weekly/monthly）

        Returns:
            技术指标数据
        """
        try:
            kline_type_map = {
                "daily": "day",
                "weekly": "week",
                "monthly": "month",
            }
            kline_type = kline_type_map.get(period, "day")

            df = self.get_kline_data(stock_code, kline_type=kline_type, limit=200)
            if df is None or df.empty or len(df) < 60:
                self.logger.warning(f"股票 {stock_code} K线数据不足，无法计算技术指标")
                return None

            return self._calculate_all_indicators(df, stock_code)
        except Exception as exc:
            self.logger.error(f"TDX计算技术指标失败 {stock_code}: {exc}")
            return None

    def _calculate_all_indicators(self, df: pd.DataFrame, stock_code: str) -> Optional[Dict]:
        """
        根据历史数据计算所有技术指标

        Args:
            df: 历史数据 DataFrame
            stock_code: 股票代码

        Returns:
            技术指标数据
        """
        try:
            if df.empty or len(df) < 60:
                self.logger.warning(f"股票 {stock_code} 历史数据不足")
                return None

            df["ma5"] = df["收盘"].rolling(window=5).mean()
            df["ma20"] = df["收盘"].rolling(window=20).mean()
            df["ma60"] = df["收盘"].rolling(window=60).mean()
            ma20_prev = df["ma20"].shift(1)
            df["ma20_slope"] = ((df["ma20"] - ma20_prev) / ma20_prev.where(ma20_prev != 0)).fillna(0.0)

            df = self._calculate_macd(df)
            df = self._calculate_rsi(df, periods=[6, 12, 24])
            df = self._calculate_kdj(df)
            df = self._calculate_obv(df)
            df = self._calculate_atr(df)
            df = self._calculate_bollinger(df)

            df["vol_ma5"] = df["成交量"].rolling(window=5).mean()
            df["vol_ma10"] = df["成交量"].rolling(window=10).mean()

            latest = df.iloc[-1]

            current_price = float(latest["收盘"])
            ma5 = float(latest["ma5"])
            ma20 = float(latest["ma20"])
            ma60 = float(latest["ma60"])

            if current_price > ma5 > ma20 > ma60:
                trend = "up"
            elif current_price < ma5 < ma20 < ma60:
                trend = "down"
            else:
                trend = "sideways"

            boll_upper = float(latest["boll_upper"])
            boll_mid = float(latest["boll_mid"])
            boll_lower = float(latest["boll_lower"])

            if current_price >= boll_upper:
                boll_position = "上轨附近（超买）"
            elif current_price <= boll_lower:
                boll_position = "下轨附近（超卖）"
            elif current_price > boll_mid:
                boll_position = "中轨上方"
            else:
                boll_position = "中轨下方"

            return {
                "ma5": ma5,
                "ma20": ma20,
                "ma60": ma60,
                "trend": trend,
                "ma20_slope": float(latest["ma20_slope"]),
                "macd_dif": float(latest["dif"]),
                "macd_dea": float(latest["dea"]),
                "macd": float(latest["macd"]),
                "dif": float(latest["dif"]),
                "dea": float(latest["dea"]),
                "hist": float(latest["dif"] - latest["dea"]),
                "hist_prev": float(df.iloc[-2]["dif"] - df.iloc[-2]["dea"]) if len(df) >= 2 else 0.0,
                "rsi6": float(latest["rsi6"]),
                "rsi12": float(latest["rsi12"]),
                "rsi24": float(latest["rsi24"]),
                "kdj_k": float(latest["kdj_k"]),
                "kdj_d": float(latest["kdj_d"]),
                "kdj_j": float(latest["kdj_j"]),
                "k": float(latest["kdj_k"]),
                "d": float(latest["kdj_d"]),
                "j": float(latest["kdj_j"]),
                "obv": float(latest["obv"]),
                "obv_prev": float(df.iloc[-2]["obv"]) if len(df) >= 2 else float(latest["obv"]),
                "atr": float(latest["atr"]) if pd.notna(latest["atr"]) else 0.0,
                "boll_upper": boll_upper,
                "boll_mid": boll_mid,
                "boll_lower": boll_lower,
                "boll_position": boll_position,
                "vol_ma5": float(latest["vol_ma5"]),
                "volume_ratio": float(latest["成交量"]) / float(latest["vol_ma5"]) if latest["vol_ma5"] > 0 else 1.0,
            }
        except Exception as exc:
            self.logger.error(f"计算技术指标失败 {stock_code}: {exc}")
            self.logger.debug("技术指标计算异常详情", exc_info=True)
            return None

    def get_comprehensive_data(self, stock_code: str, preferred_name: Optional[str] = None) -> Dict:
        """获取综合数据（实时行情 + 技术指标）"""
        result = {}

        quote = self.get_realtime_quote(stock_code, preferred_name=preferred_name)
        if quote:
            result.update(quote)

        indicators = self.get_technical_indicators(stock_code)
        if indicators:
            result.update(indicators)

        return result

    def build_snapshot_from_history(
        self,
        stock_code: str,
        history_df: Optional[pd.DataFrame],
        *,
        stock_name: Optional[str] = None,
    ) -> Dict:
        """Build a comprehensive snapshot from historical bars only."""

        if history_df is None or history_df.empty:
            return {}

        df = history_df.copy()
        if "日期" not in df.columns:
            raise ValueError("history_df must contain 日期 column")

        df["日期"] = pd.to_datetime(df["日期"])
        df = df.sort_values("日期").reset_index(drop=True)

        latest = df.iloc[-1]
        snapshot = {
            "code": self._normalize_stock_code(stock_code),
            "name": stock_name or self._get_stock_name(stock_code),
            "current_price": float(latest["收盘"]),
            "change_pct": 0.0,
            "change_amount": 0.0,
            "volume": float(latest.get("成交量", 0) or 0),
            "amount": float(latest.get("成交额", 0) or 0),
            "high": float(latest.get("最高", 0) or 0),
            "low": float(latest.get("最低", 0) or 0),
            "open": float(latest.get("开盘", 0) or 0),
            "pre_close": float(df.iloc[-2]["收盘"]) if len(df) >= 2 else 0.0,
            "turnover_rate": 0.0,
            "volume_ratio": 1.0,
            "update_time": latest["日期"].strftime("%Y-%m-%d %H:%M:%S"),
            "data_source": "historical_replay",
        }
        if snapshot["pre_close"] > 0:
            snapshot["change_amount"] = round(snapshot["current_price"] - snapshot["pre_close"], 4)
            snapshot["change_pct"] = round(snapshot["change_amount"] / snapshot["pre_close"] * 100, 4)

        indicators = self._calculate_all_indicators(df, stock_code)
        if indicators:
            snapshot.update(indicators)

        return snapshot

    def _fetch_quote_data(self, market: int, code: str) -> Optional[Dict]:
        def operation(api: TdxHq_API):
            rows = api.get_security_quotes([(market, code)])
            return rows[0] if rows else None

        return self._call_with_failover(operation)

    def _fetch_kline_data(self, market: int, code: str, category: int, start: int, count: int) -> List[Dict]:
        def operation(api: TdxHq_API):
            rows = api.get_security_bars(category, market, code, start, count)
            return rows or []

        return self._call_with_failover(operation) or []

    def _call_with_failover(self, operation):
        last_error = None
        now = time.monotonic()
        sorted_hosts = self._prioritize_hosts(self.hosts)
        max_attempts = DEFAULT_TDX_MAX_HOST_ATTEMPTS
        try:
            max_attempts = max(1, int(os.getenv("TDX_MAX_HOST_ATTEMPTS", str(DEFAULT_TDX_MAX_HOST_ATTEMPTS))))
        except Exception:
            max_attempts = DEFAULT_TDX_MAX_HOST_ATTEMPTS

        active_hosts: List[Tuple[str, str, int]] = []
        blocked_count = 0
        for name, host, port in sorted_hosts:
            health = self._get_host_health(host, port)
            if float(health.get("blocked_until", 0.0)) > now:
                blocked_count += 1
                continue
            active_hosts.append((name, host, port))

        if not active_hosts:
            active_hosts = sorted_hosts[:max_attempts]
        else:
            active_hosts = active_hosts[:max_attempts]

        if blocked_count:
            self.logger.debug(f"TDX节点冷却中，已跳过 {blocked_count} 个节点，本次最多尝试 {len(active_hosts)} 个节点")

        for name, host, port in active_hosts:
            api = TdxHq_API(multithread=False, heartbeat=False, auto_retry=True, raise_exception=True)
            try:
                connection = api.connect(host, port, self.timeout)
                if not connection:
                    raise ConnectionError(f"连接 {host}:{port} 失败")

                result = operation(api)
                self._record_host_success(host, port)
                api.disconnect()
                return result
            except Exception as exc:
                last_error = exc
                self._record_host_failure(host, port)
                self.logger.warning(f"TDX服务器 {name}({host}:{port}) 请求失败: {type(exc).__name__}: {exc}")
                try:
                    api.disconnect()
                except Exception:
                    pass

        if last_error is not None:
            raise last_error

        return None

    def _build_hosts(
        self,
        host: Optional[str],
        port: int,
        fallback_hosts: Optional[Sequence[Tuple[str, str, int] | str]],
        hosts_file: Optional[str | Path],
    ) -> List[Tuple[str, str, int]]:
        hosts: List[Tuple[str, str, int]] = []
        repo_hosts = load_pytdx_hosts(hosts_file)

        if host:
            hosts.append(("primary", host, int(port)))

        for item in fallback_hosts or []:
            if isinstance(item, tuple):
                name, host_name, host_port = item
                hosts.append((str(name), host_name, int(host_port)))
                continue

            host_info = str(item).strip()
            if not host_info:
                continue
            if ":" in host_info:
                host_name, host_port = host_info.rsplit(":", 1)
                hosts.append((f"fallback-{host_name}", host_name, int(host_port)))
            else:
                hosts.append((f"fallback-{host_info}", host_info, DEFAULT_TDX_PORT))

        hosts.extend(repo_hosts)

        if not hosts:
            for name, host_name, host_port in hq_hosts[:DEFAULT_HOST_LIMIT]:
                hosts.append((name, host_name, int(host_port)))

        deduplicated: List[Tuple[str, str, int]] = []
        seen = set()
        for name, host_name, host_port in hosts:
            key = (host_name, host_port)
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append((name, host_name, host_port))

        if repo_hosts:
            prioritized_repo: List[Tuple[str, str, int]] = []
            used_repo_keys: set[tuple[str, int]] = set()
            for _, repo_host, repo_port in repo_hosts:
                key = (repo_host, repo_port)
                if key in used_repo_keys:
                    continue
                matched = next((item for item in deduplicated if item[1] == repo_host and item[2] == repo_port), None)
                if matched is None:
                    continue
                prioritized_repo.append(matched)
                used_repo_keys.add(key)
            remaining = [item for item in deduplicated if (item[1], item[2]) not in used_repo_keys]
            return prioritized_repo + self._prioritize_hosts(remaining)

        return self._prioritize_hosts(deduplicated)

    def _load_deprioritized_hosts(self) -> tuple[set[tuple[str, int]], set[str], tuple[str, ...]]:
        host_keys = set(DEFAULT_DEPRIORITIZED_TDX_HOSTS)
        host_only: set[str] = set()
        name_keywords = tuple(DEFAULT_DEPRIORITIZED_TDX_NAME_KEYWORDS)

        raw = os.getenv("TDX_DEPRIORITIZED_HOSTS", "").strip()
        if raw:
            for item in raw.split(","):
                value = item.strip()
                if not value:
                    continue
                if ":" in value:
                    host_name, raw_port = value.rsplit(":", 1)
                    try:
                        host_keys.add((host_name.strip(), int(raw_port)))
                        continue
                    except ValueError:
                        pass
                host_only.add(value)

        return host_keys, host_only, name_keywords

    def _is_deprioritized_host(self, name: str, host: str, port: int) -> bool:
        if (host, port) in self._deprioritized_host_keys:
            return True
        if host in self._deprioritized_host_only:
            return True
        return any(keyword in name for keyword in self._deprioritized_name_keywords)

    @classmethod
    def _get_host_health(cls, host: str, port: int) -> Dict[str, float]:
        key = (host, port)
        with cls._HOST_HEALTH_LOCK:
            state = cls._HOST_HEALTH.get(key)
            if state is None:
                state = {"successes": 0.0, "failures": 0.0, "blocked_until": 0.0}
                cls._HOST_HEALTH[key] = state
            return dict(state)

    @classmethod
    def _record_host_success(cls, host: str, port: int) -> None:
        key = (host, port)
        with cls._HOST_HEALTH_LOCK:
            state = cls._HOST_HEALTH.setdefault(key, {"successes": 0.0, "failures": 0.0, "blocked_until": 0.0})
            state["successes"] = float(state.get("successes", 0.0)) + 1.0
            state["failures"] = max(0.0, float(state.get("failures", 0.0)) - 1.0)
            state["blocked_until"] = 0.0

    @classmethod
    def _record_host_failure(cls, host: str, port: int) -> None:
        key = (host, port)
        now = time.monotonic()
        with cls._HOST_HEALTH_LOCK:
            state = cls._HOST_HEALTH.setdefault(key, {"successes": 0.0, "failures": 0.0, "blocked_until": 0.0})
            failures = float(state.get("failures", 0.0)) + 1.0
            state["failures"] = failures
            penalty_step = max(0.0, failures - 1.0)
            cooldown = min(600.0, 10.0 * (2.0 ** min(penalty_step, 6.0)))
            state["blocked_until"] = max(float(state.get("blocked_until", 0.0)), now + cooldown)

    def _prioritize_hosts(self, hosts: Sequence[Tuple[str, str, int]]) -> List[Tuple[str, str, int]]:
        now = time.monotonic()

        def _sort_key(item: Tuple[str, str, int]) -> tuple[float, float, float, str]:
            name, host, port = item
            health = self._get_host_health(host, port)
            failures = float(health.get("failures", 0.0))
            successes = float(health.get("successes", 0.0))
            blocked_until = float(health.get("blocked_until", 0.0))
            static_penalty = 1000.0 if self._is_deprioritized_host(name, host, port) else 0.0
            blocked_penalty = 200.0 if blocked_until > now else 0.0
            dynamic_penalty = min(120.0, failures * 12.0) - min(20.0, successes * 2.0)
            score = static_penalty + blocked_penalty + dynamic_penalty
            return (score, failures, -successes, name)

        return sorted(list(hosts), key=_sort_key)

    def _normalize_stock_code(self, stock_code: str) -> str:
        code = stock_code.strip().upper()
        if "." in code:
            code = code.split(".", 1)[0]
        for prefix in ("SH", "SZ", "BJ"):
            if code.startswith(prefix):
                return code[2:]
        return code

    def _get_market(self, stock_code: str) -> int:
        if stock_code.startswith(("5", "6", "9")):
            return 1
        return 0

    def _format_update_time(self, servertime: Optional[str]) -> str:
        time_text = str(servertime or "").split(".", 1)[0]
        if time_text.count(":") == 2:
            return f"{datetime.now().strftime('%Y-%m-%d')} {time_text}"
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _safe_float(self, value) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _calculate_macd(self, df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        """计算 MACD 指标"""
        ema_fast = df["收盘"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["收盘"].ewm(span=slow, adjust=False).mean()

        df["dif"] = ema_fast - ema_slow
        df["dea"] = df["dif"].ewm(span=signal, adjust=False).mean()
        df["macd"] = (df["dif"] - df["dea"]) * 2
        return df

    def _calculate_rsi(self, df: pd.DataFrame, periods: Iterable[int] = (6, 12, 24)) -> pd.DataFrame:
        """计算 RSI 指标"""
        for period in periods:
            delta = df["收盘"].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            df[f"rsi{period}"] = 100 - (100 / (1 + rs))
        return df

    def _calculate_kdj(self, df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
        """计算 KDJ 指标"""
        low_list = df["最低"].rolling(window=n).min()
        high_list = df["最高"].rolling(window=n).max()
        rsv = (df["收盘"] - low_list) / (high_list - low_list) * 100

        df["kdj_k"] = rsv.ewm(com=m1 - 1, adjust=False).mean()
        df["kdj_d"] = df["kdj_k"].ewm(com=m2 - 1, adjust=False).mean()
        df["kdj_j"] = 3 * df["kdj_k"] - 2 * df["kdj_d"]
        return df

    def _calculate_obv(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算 OBV 累积能量线"""
        delta = df["收盘"].diff().fillna(0.0)
        positive = df["成交量"].where(delta > 0, 0.0)
        negative = df["成交量"].where(delta < 0, 0.0)
        df["obv"] = (positive - negative).cumsum()
        return df

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """计算 ATR 波动率"""
        prev_close = df["收盘"].shift(1)
        high_low = df["最高"] - df["最低"]
        high_close = (df["最高"] - prev_close).abs()
        low_close = (df["最低"] - prev_close).abs()
        df["tr"] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr"] = df["tr"].rolling(window=period, min_periods=period).mean()
        return df

    def _calculate_bollinger(self, df: pd.DataFrame, period: int = 20, std_num: int = 2) -> pd.DataFrame:
        """计算布林带"""
        df["boll_mid"] = df["收盘"].rolling(window=period).mean()
        std = df["收盘"].rolling(window=period).std()

        df["boll_upper"] = df["boll_mid"] + std_num * std
        df["boll_lower"] = df["boll_mid"] - std_num * std
        return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    fetcher = SmartMonitorTDXDataFetcher()
    print("测试获取平安银行(000001)数据...")
    data = fetcher.get_comprehensive_data("000001")

    if data:
        print("\n实时行情:")
        print(f"  股票名称: {data.get('name')}")
        print(f"  当前价格: {data.get('current_price')} 元")
        print(f"  涨跌幅: {data.get('change_pct')}%")
        print(f"  数据源: {data.get('data_source')}")

        print("\n技术指标:")
        print(f"  MA5: {data.get('ma5', 0):.2f}")
        print(f"  MA20: {data.get('ma20', 0):.2f}")
        print(f"  MACD: {data.get('macd', 0):.4f}")
        print(f"  RSI(6): {data.get('rsi6', 0):.2f}")
        print(f"  趋势: {data.get('trend')}")
    else:
        print("获取数据失败")
