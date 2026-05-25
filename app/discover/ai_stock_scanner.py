from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import logging
import math
import os
from typing import Any

import pandas as pd

from app.akshare_client import ak


logger = logging.getLogger(__name__)


PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


@dataclass(frozen=True)
class AIStockScannerConfig:
    top_k_sectors: int = 5
    max_stocks: int = 20
    max_candidates_per_sector: int = 5
    min_sector_score: float = 0.0
    lookback_days: int = 180
    enable_llm_themes: bool = True
    max_news_count: int = 20
    lookback_hours: int = 24
    max_llm_retries: int = 2
    weight_sector: float = 0.4
    weight_technical: float = 0.3
    weight_theme: float = 0.3


@dataclass(frozen=True)
class ThemeInfo:
    name: str
    weight: float
    keywords: tuple[str, ...]
    sentiment: str


@dataclass(frozen=True)
class _SectorCandidate:
    name: str
    source: str
    score: float
    change_pct: float
    amount: float


@dataclass(frozen=True)
class _ThemeAlignment:
    score: float
    names: tuple[str, ...] = ()


@dataclass(frozen=True)
class _TechnicalScore:
    score: float
    reasons: tuple[str, ...] = ()


class AIStockScanner:
    """Project-local AI scanner for the discover workflow.

    It ranks hot sectors, extracts market themes, scores technical state from
    local market data, and maps results to the discover candidate schema.
    """

    def __init__(
        self,
        config: AIStockScannerConfig | None = None,
        *,
        ak_api: Any = None,
        wencai_get: Any = None,
        news_provider: Callable[[], Any] | None = None,
        llm_client: Any = None,
        market_client: Any = None,
        history_provider: Callable[[str], pd.DataFrame | None] | None = None,
        fallback_history_provider: Callable[[str, str, str], pd.DataFrame | None] | None = None,
        tdx_fetcher: Any = None,
        indicator_engine: Any = None,
    ) -> None:
        self.config = config or AIStockScannerConfig()
        self.ak = ak_api or ak
        self._wencai_get = wencai_get
        self._news_provider = news_provider
        self._llm_client = llm_client
        self._market_client = market_client
        self._history_provider = history_provider
        self._fallback_history_provider = fallback_history_provider
        self._tdx_fetcher = tdx_fetcher
        self._indicator_engine = indicator_engine
        self._llm_failures = 0

    def scan(self) -> pd.DataFrame:
        sectors = self._top_sectors()
        rows = self._sector_stock_rows(sectors)
        if not rows:
            rows = self._wencai_rows()
        themes = self._extract_themes() if rows and self.config.enable_llm_themes else {}
        return self._rank_rows(rows, themes)

    def _top_sectors(self) -> list[_SectorCandidate]:
        frames: list[tuple[str, pd.DataFrame]] = []
        for source, fetcher_name in (
            ("concept", "stock_board_concept_name_em"),
            ("industry", "stock_board_industry_name_em"),
        ):
            fetcher = getattr(self.ak, fetcher_name, None)
            if not callable(fetcher):
                continue
            try:
                with _without_proxy_env():
                    frame = fetcher()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[AIStockScanner] fetch %s failed: %s", fetcher_name, exc)
                continue
            if isinstance(frame, pd.DataFrame) and not frame.empty:
                frames.append((source, frame))

        sectors: list[_SectorCandidate] = []
        for source, frame in frames:
            for _, row in frame.head(max(self.config.top_k_sectors * 4, self.config.top_k_sectors)).iterrows():
                name = _text(_first(row, "板块名称", "行业名称", "概念名称", "name"))
                if not name:
                    continue
                change_pct = _number(_first(row, "涨跌幅", "change_pct", "涨幅"))
                amount = _number(_first(row, "成交额", "amount"))
                score = _normalize(change_pct, -5.0, 10.0) * 0.65 + _normalize(amount, 0.0, 2.0e10) * 0.35
                if score < self.config.min_sector_score:
                    continue
                sectors.append(
                    _SectorCandidate(
                        name=name,
                        source=source,
                        score=round(score, 4),
                        change_pct=change_pct,
                        amount=amount,
                    )
                )

        sectors.sort(key=lambda item: (item.score, item.change_pct, item.amount), reverse=True)
        deduped: list[_SectorCandidate] = []
        seen: set[str] = set()
        for sector in sectors:
            if sector.name in seen:
                continue
            seen.add(sector.name)
            deduped.append(sector)
            if len(deduped) >= self.config.top_k_sectors:
                break
        return deduped

    def _sector_stock_rows(self, sectors: list[_SectorCandidate]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for sector in sectors:
            fetcher_names = (
                ("stock_board_concept_cons_em",)
                if sector.source == "concept"
                else ("stock_board_industry_cons_em", "stock_board_concept_cons_em")
            )
            frame = pd.DataFrame()
            for fetcher_name in fetcher_names:
                fetcher = getattr(self.ak, fetcher_name, None)
                if not callable(fetcher):
                    continue
                try:
                    with _without_proxy_env():
                        candidate_frame = fetcher(symbol=sector.name)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[AIStockScanner] fetch %s(%s) failed: %s", fetcher_name, sector.name, exc)
                    continue
                if isinstance(candidate_frame, pd.DataFrame) and not candidate_frame.empty:
                    frame = candidate_frame
                    break
            if frame.empty:
                continue

            max_rows = max(1, self.config.max_candidates_per_sector)
            for rank, (_, row) in enumerate(frame.head(max_rows).iterrows(), start=1):
                code = _stock_code(_first(row, "代码", "股票代码", "code", "symbol"))
                if not code:
                    continue
                change_pct = _number(_first(row, "涨跌幅", "change_pct", "涨幅"))
                rank_score = 1.0 - ((rank - 1) / max(max_rows, 1))
                change_score = _normalize(change_pct, -5.0, 10.0)
                stock_score = sector.score * 0.55 + change_score * 0.25 + rank_score * 0.20
                rows.append(
                    {
                        "股票代码": code,
                        "股票简称": _text(_first(row, "名称", "股票简称", "name"), code),
                        "所属行业": sector.name,
                        "最新价": _first(row, "最新价", "price", "当前价"),
                        "总市值": _first(row, "总市值", "市值", "market_cap"),
                        "市盈率": _first(row, "市盈率", "市盈率-动态", "pe", "PE"),
                        "市净率": _first(row, "市净率", "pb", "PB"),
                        "sector_score": round(sector.score, 4),
                        "rank_score": round(rank_score, 4),
                        "price_change_score": round(change_score, 4),
                        "scanner_score": round(stock_score, 4),
                        "source_reason": f"sector={sector.name}, sector_score={sector.score:.2f}, rank={rank}",
                    }
                )
        return rows

    def _wencai_rows(self) -> list[dict[str, Any]]:
        try:
            import pywencai
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AIStockScanner] pywencai unavailable: %s", exc)
            return []

        getter = self._wencai_get or pywencai.get
        query = (
            "热门题材，主力资金净流入，非ST，非科创板，非创业板，沪深A股，"
            "所属行业，最新价，总市值，市盈率，市净率，按主力资金净流入由高到低排名"
        )
        try:
            with _without_proxy_env():
                result = getter(query=query, loop=True, retry=1, sleep=0)
        except TypeError:
            with _without_proxy_env():
                result = getter(query=query, loop=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AIStockScanner] pywencai query failed: %s", exc)
            return []

        frame = _to_frame(result)
        if frame.empty:
            return []
        rows: list[dict[str, Any]] = []
        for rank, (_, row) in enumerate(frame.head(max(self.config.max_stocks, 1)).iterrows(), start=1):
            code = _stock_code(_first(row, "股票代码", "代码", "code", "symbol"))
            if not code:
                continue
            score = 1.0 - ((rank - 1) / max(self.config.max_stocks, 1))
            rows.append(
                {
                    "股票代码": code,
                    "股票简称": _text(_first(row, "股票简称", "名称", "name"), code),
                    "所属行业": _text(_first(row, "所属行业", "所属同花顺行业", "行业", "板块")),
                    "最新价": _first_matching(row, "最新价", "收盘价", "股价", "price"),
                    "总市值": _first_matching(row, "总市值", "市值", "market_cap"),
                    "市盈率": _first_matching(row, "市盈率", "pe"),
                    "市净率": _first_matching(row, "市净率", "pb"),
                    "sector_score": 0.5,
                    "rank_score": round(score, 4),
                    "price_change_score": 0.5,
                    "scanner_score": round(score, 4),
                    "source_reason": "hot theme and main fund flow query",
                }
            )
        return rows

    def _rank_rows(self, rows: list[dict[str, Any]], themes: dict[str, ThemeInfo]) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame()
        frame = pd.DataFrame(rows)
        frame["股票代码"] = frame["股票代码"].map(_stock_code)
        frame = frame[frame["股票代码"].astype(bool)].copy()
        if frame.empty:
            return pd.DataFrame()
        frame["preliminary_score"] = frame.apply(self._preliminary_score, axis=1)
        frame = frame.sort_values("preliminary_score", ascending=False)
        frame = frame.drop_duplicates(subset=["股票代码"], keep="first")
        scoring_limit = max(max(self.config.max_stocks, 1) * 3, 1)
        frame = frame.head(scoring_limit).reset_index(drop=True)
        frame["_candidate_order"] = range(len(frame))

        scored_rows: list[dict[str, Any]] = []
        for _, row in frame.iterrows():
            row_dict = row.to_dict()
            sector_score = _clamp(_number(row_dict.get("sector_score"), 0.5))
            theme = self._calculate_theme_alignment(row_dict, themes)
            technical = self._technical_score(_stock_code(row_dict.get("股票代码")))
            final_score = self._weighted_score(
                sector_score=sector_score,
                technical_score=technical.score,
                theme_score=theme.score,
            )
            row_dict["sector_score"] = round(sector_score, 4)
            row_dict["theme_score"] = round(theme.score, 4)
            row_dict["technical_score"] = round(technical.score, 4)
            row_dict["technical_reasons"] = "; ".join(technical.reasons)
            row_dict["scanner_score"] = round(final_score, 4)
            row_dict["reason"] = self._build_reason(row_dict, theme, technical)
            scored_rows.append(row_dict)

        result = pd.DataFrame(scored_rows)
        if result.empty:
            return pd.DataFrame()
        # Keep tied candidates deterministic without changing the primary score.
        result = result.sort_values(
            [
                "scanner_score",
                "sector_score",
                "technical_score",
                "preliminary_score",
                "_candidate_order",
                "股票代码",
            ],
            ascending=[False, False, False, False, True, True],
            kind="mergesort",
        )
        result = result.drop_duplicates(subset=["股票代码"], keep="first").head(max(self.config.max_stocks, 1)).reset_index(drop=True)
        return result.drop(columns=["_candidate_order"], errors="ignore")

    def _preliminary_score(self, row: pd.Series) -> float:
        existing = _number(row.get("scanner_score"), None)
        if existing is not None:
            return existing
        sector_score = _number(row.get("sector_score"), 0.5)
        rank_score = _number(row.get("rank_score"), 0.5)
        change_score = _number(row.get("price_change_score"), 0.5)
        return sector_score * 0.5 + rank_score * 0.3 + change_score * 0.2

    def _weighted_score(self, *, sector_score: float, technical_score: float, theme_score: float) -> float:
        weights = (
            max(0.0, _number(self.config.weight_sector, 0.0)),
            max(0.0, _number(self.config.weight_technical, 0.0)),
            max(0.0, _number(self.config.weight_theme, 0.0)),
        )
        total = sum(weights)
        if total <= 0:
            weights = (1.0, 1.0, 1.0)
            total = 3.0
        return _clamp(
            (weights[0] * sector_score + weights[1] * technical_score + weights[2] * theme_score) / total
        )

    def _build_reason(self, row: dict[str, Any], theme: _ThemeAlignment, technical: _TechnicalScore) -> str:
        parts = ["AI scanner"]
        source_reason = _text(row.get("source_reason") or row.get("reason"))
        if source_reason:
            parts.append(source_reason)
        if theme.names:
            parts.append(f"theme={theme.names[0]}")
        parts.append(f"theme_score={theme.score:.2f}")
        parts.append(f"technical_score={technical.score:.2f}")
        if technical.reasons:
            parts.append("technical=" + "/".join(technical.reasons[:3]))
        return ", ".join(parts)

    def _extract_themes(self) -> dict[str, ThemeInfo]:
        if self._llm_failures >= max(1, self.config.max_llm_retries):
            logger.warning("[AIStockScanner] skip theme extraction after repeated LLM failures")
            return {}
        news_items = self._fetch_recent_news()
        if not news_items:
            return {}
        themes = self._extract_themes_with_llm(news_items)
        if themes:
            self._llm_failures = 0
            return themes
        self._llm_failures += 1
        return {}

    def _fetch_recent_news(self) -> list[dict[str, Any]]:
        if self._news_provider is not None:
            return _news_items_from_payload(self._news_provider(), self.config.max_news_count)

        items: list[dict[str, Any]] = []
        try:
            from app.sector_strategy_db import SectorStrategyDatabase

            payload = SectorStrategyDatabase().get_latest_news_data(within_hours=max(1, self.config.lookback_hours))
            items.extend(_news_items_from_payload(payload, self.config.max_news_count))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AIStockScanner] read sector news cache failed: %s", exc)

        if len(items) >= self.config.max_news_count:
            return items[: self.config.max_news_count]

        try:
            from app.news_flow_db import NewsFlowDatabase

            db = NewsFlowDatabase()
            snapshot = db.get_latest_snapshot()
            snapshot_id = snapshot.get("id") if isinstance(snapshot, dict) else None
            if snapshot_id:
                detail = db.get_snapshot_detail(int(snapshot_id))
                items.extend(_news_items_from_payload(detail, self.config.max_news_count - len(items)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AIStockScanner] read news flow cache failed: %s", exc)

        return items[: self.config.max_news_count]

    def _extract_themes_with_llm(self, news_items: list[dict[str, Any]]) -> dict[str, ThemeInfo]:
        client = self._llm_client
        if client is None:
            try:
                from app.deepseek_client import DeepSeekClient

                client = DeepSeekClient()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[AIStockScanner] LLM client unavailable: %s", exc)
                return {}

        prompt = _build_theme_prompt(_prepare_news_summary(news_items))
        try:
            if hasattr(client, "call_api"):
                response = client.call_api(
                    [
                        {
                            "role": "system",
                            "content": "You extract concise A-share market investment themes and return strict JSON.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=1200,
                )
            elif callable(client):
                response = client(prompt)
            else:
                return {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AIStockScanner] LLM theme extraction failed: %s", exc)
            return {}

        if isinstance(response, dict):
            response_text = _text(response.get("response") or response.get("content") or response.get("text"))
        else:
            response_text = _text(response)
        if not response_text or response_text.startswith("API调用失败"):
            logger.warning("[AIStockScanner] LLM theme extraction unavailable: %s", response_text[:120])
            return {}
        return _parse_theme_response(response_text)

    def _calculate_theme_alignment(self, row: dict[str, Any], themes: dict[str, ThemeInfo]) -> _ThemeAlignment:
        if not themes:
            return _ThemeAlignment(score=0.5)

        searchable = " ".join(
            _text(value)
            for value in (
                row.get("股票简称"),
                row.get("所属行业"),
                row.get("source_reason"),
                row.get("reason"),
            )
            if _text(value)
        ).lower()
        if not searchable:
            return _ThemeAlignment(score=0.5)

        best_score = 0.0
        best_names: list[str] = []
        fallback_score = 0.0
        for theme in themes.values():
            keyword_hits = [
                keyword
                for keyword in (theme.name, *theme.keywords)
                if keyword and str(keyword).strip().lower() in searchable
            ]
            sentiment_adjustment = 0.08 if theme.sentiment == "bullish" else -0.18 if theme.sentiment == "bearish" else 0.0
            if keyword_hits:
                score = 0.55 + theme.weight * 0.3 + min(0.12, len(keyword_hits) * 0.04) + sentiment_adjustment
            else:
                score = 0.45 + theme.weight * 0.1 + sentiment_adjustment * 0.5
            score = _clamp(score)
            fallback_score += score
            if score > best_score:
                best_score = score
                best_names = [theme.name]
            elif math.isclose(score, best_score):
                best_names.append(theme.name)

        if best_score <= 0:
            return _ThemeAlignment(score=_clamp(fallback_score / max(len(themes), 1)))
        return _ThemeAlignment(score=best_score, names=tuple(best_names[:3]))

    def _technical_score(self, code: str) -> _TechnicalScore:
        frame = self._history_frame(code)
        if frame is None or frame.empty:
            return _TechnicalScore(score=0.5, reasons=("technical_data_unavailable",))
        try:
            engine = self._indicator_engine
            if engine is None:
                from app.data.indicators import TechnicalIndicatorEngine

                engine = TechnicalIndicatorEngine()
            indicators = engine.calculate(
                frame,
                symbol=code,
                source="ai_scanner",
                dataset="ohlcv",
                timeframe="1d",
                adjust="qfq",
                provider="local_market_data",
                strict=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AIStockScanner] technical indicators failed for %s: %s", code, exc)
            return _TechnicalScore(score=0.5, reasons=("technical_score_error",))
        if indicators is None or indicators.empty:
            return _TechnicalScore(score=0.5, reasons=("technical_data_unavailable",))
        return _score_indicator_frame(indicators)

    def _history_frame(self, code: str) -> pd.DataFrame | None:
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=max(self.config.lookback_days, 90))).strftime("%Y%m%d")
        try:
            if self._history_provider is not None:
                return self._history_provider(code)
            market_client = self._market_client
            if market_client is None:
                from app.local_market_data_clients import AkshareLocalClient

                market_client = AkshareLocalClient()
            with _without_proxy_env():
                frame = market_client.get_stock_hist_data(
                    code,
                    start_date=start_date,
                    end_date=end_date,
                    adjust="qfq",
                    period="daily",
                    output="data_source",
                )
            if frame is not None and not frame.empty:
                return frame
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AIStockScanner] history fetch failed for %s: %s", code, exc)
        return self._fallback_history_frame(code, start_date, end_date)

    def _fallback_history_frame(self, code: str, start_date: str, end_date: str) -> pd.DataFrame | None:
        try:
            if self._fallback_history_provider is not None:
                return self._fallback_history_provider(code, start_date, end_date)
            fetcher = self._tdx_fetcher
            if fetcher is None:
                from app.smart_monitor_tdx_data import SmartMonitorTDXDataFetcher

                fetcher = SmartMonitorTDXDataFetcher()
                self._tdx_fetcher = fetcher
            return fetcher.get_kline_data_range(
                code,
                kline_type="day",
                start_datetime=pd.to_datetime(start_date),
                end_datetime=pd.to_datetime(end_date),
                max_bars=max(self.config.lookback_days + 80, 260),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AIStockScanner] fallback TDX history fetch failed for %s: %s", code, exc)
            return None


def _prepare_news_summary(news_items: list[dict[str, Any]]) -> str:
    summaries: list[str] = []
    for index, item in enumerate(news_items[:15], start=1):
        title = _text(item.get("title") or item.get("topic"), "Untitled")
        content = _text(item.get("content") or item.get("summary") or item.get("analysis"))[:220]
        summaries.append(f"{index}. {title}\n   {content}")
    return "\n\n".join(summaries)


def _build_theme_prompt(news_summary: str) -> str:
    return f"""你是A股金融分析师。请基于下面的最近市场新闻，提取最重要的3到5个投资主题。

每个主题必须包含：
1. name: 2到6个字的主题名
2. weight: 0.0到1.0的重要性
3. keywords: 3到6个可用于匹配行业、题材、股票名称的关键词
4. sentiment: bullish、bearish 或 neutral

新闻摘要：
{news_summary}

只返回 JSON 数组，不要输出其他解释：
[
  {{
    "name": "主题名",
    "weight": 0.8,
    "keywords": ["关键词1", "关键词2", "关键词3"],
    "sentiment": "bullish"
  }}
]"""


def _parse_theme_response(response: str) -> dict[str, ThemeInfo]:
    start_idx = response.find("[")
    end_idx = response.rfind("]") + 1
    if start_idx == -1 or end_idx <= start_idx:
        logger.warning("[AIStockScanner] no JSON array found in LLM response")
        return {}
    try:
        payload = json.loads(response[start_idx:end_idx])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AIStockScanner] parse LLM theme JSON failed: %s", exc)
        return {}
    if not isinstance(payload, list):
        return {}

    themes: dict[str, ThemeInfo] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"))
        if not name:
            continue
        raw_keywords = item.get("keywords") or []
        if isinstance(raw_keywords, str):
            keywords = tuple(keyword.strip() for keyword in raw_keywords.replace("，", ",").split(",") if keyword.strip())
        elif isinstance(raw_keywords, list):
            keywords = tuple(_text(keyword) for keyword in raw_keywords if _text(keyword))
        else:
            keywords = ()
        sentiment = _text(item.get("sentiment"), "neutral").lower()
        if sentiment not in {"bullish", "bearish", "neutral"}:
            sentiment = "neutral"
        themes[name] = ThemeInfo(
            name=name,
            weight=_clamp(_number(item.get("weight"), 0.5)),
            keywords=keywords,
            sentiment=sentiment,
        )
    return themes


def _news_items_from_payload(payload: Any, limit: int) -> list[dict[str, Any]]:
    if limit <= 0 or payload is None:
        return []
    if isinstance(payload, list):
        items: list[dict[str, Any]] = []
        for item in payload:
            items.extend(_news_items_from_payload(item, limit - len(items)))
            if len(items) >= limit:
                break
        return items[:limit]
    if not isinstance(payload, dict):
        return []

    for key in ("data_content", "stock_news", "news", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return _news_items_from_payload(value, limit)
    if isinstance(payload.get("hot_topics"), list):
        items = []
        for topic in payload["hot_topics"]:
            if isinstance(topic, dict):
                sources = topic.get("sources")
                items.append(
                    {
                        "title": topic.get("title") or topic.get("topic"),
                        "content": topic.get("content")
                        or topic.get("summary")
                        or (" ".join(str(value) for value in sources[:3]) if isinstance(sources, list) else ""),
                    }
                )
        return _news_items_from_payload(items, limit)

    title = _text(payload.get("title") or payload.get("topic"))
    content = _text(payload.get("content") or payload.get("summary") or payload.get("analysis"))
    if not title and not content:
        return []
    return [{"title": title, "content": content, "source": payload.get("source")}]


def _score_indicator_frame(indicators: pd.DataFrame) -> _TechnicalScore:
    latest = indicators.iloc[-1]
    previous = indicators.iloc[-2] if len(indicators) >= 2 else latest
    score = 0.5
    reasons: list[str] = []

    trend = _text(latest.get("trend"), "sideways")
    if trend == "up":
        score += 0.07
        reasons.append("trend=up")
    elif trend == "down":
        score -= 0.09
        reasons.append("trend=down")
    else:
        reasons.append("trend=sideways")

    close = _latest_float(latest, "close")
    ma5 = _latest_float(latest, "ma5")
    ma20 = _latest_float(latest, "ma20")
    ma60 = _latest_float(latest, "ma60")
    if close and ma5 and ma20 and close > ma5 > ma20:
        score += 0.10
        reasons.append("ma_short_up")
    elif close and ma5 and ma20 and close < ma5 < ma20:
        score -= 0.10
        reasons.append("ma_short_down")
    if close and ma20:
        if close > ma20:
            score += 0.06
            reasons.append("close_above_ma20")
        else:
            score -= 0.05
            reasons.append("close_below_ma20")
    if close and ma60 and close > ma60:
        score += 0.04
    ma20_slope = _latest_float(latest, "ma20_slope")
    if ma20_slope > 0:
        score += 0.07
        reasons.append("ma20_slope_up")
    elif ma20_slope < 0:
        score -= 0.06
        reasons.append("ma20_slope_down")

    dif = _latest_float(latest, "dif")
    dea = _latest_float(latest, "dea")
    hist = _latest_float(latest, "hist")
    previous_hist = _latest_float(previous, "hist")
    if dif > dea and hist > 0:
        score += 0.10
        reasons.append("macd_bullish")
    elif dif < dea and hist < 0:
        score -= 0.09
        reasons.append("macd_bearish")
    if hist > previous_hist:
        score += 0.03

    rsi12 = _latest_float(latest, "rsi12")
    if 45 <= rsi12 <= 70:
        score += 0.07
        reasons.append("rsi_healthy")
    elif 70 < rsi12 <= 82:
        score += 0.02
        reasons.append("rsi_strong")
    elif rsi12 > 82:
        score -= 0.07
        reasons.append("rsi_overheated")
    elif 0 < rsi12 < 35:
        score -= 0.07
        reasons.append("rsi_weak")

    volume_ratio = _latest_float(latest, "volume_ratio")
    if 1.05 <= volume_ratio <= 3.0:
        score += 0.05
        reasons.append("volume_expansion")
    elif volume_ratio > 4.0:
        score -= 0.04
        reasons.append("volume_overheated")
    elif 0 < volume_ratio < 0.6:
        score -= 0.03
        reasons.append("volume_shrink")

    if len(indicators) >= 20:
        close_20 = _latest_float(indicators.iloc[-20], "close")
        if close and close_20:
            momentum_20 = (close - close_20) / close_20
            if 0 < momentum_20 <= 0.25:
                score += 0.04
                reasons.append("momentum_20d_positive")
            elif momentum_20 < 0:
                score -= 0.05
                reasons.append("momentum_20d_negative")
            elif momentum_20 > 0.35:
                score -= 0.03
                reasons.append("momentum_20d_overextended")

    return _TechnicalScore(score=round(_clamp(score), 4), reasons=tuple(reasons[:6]))


def _latest_float(row: Any, key: str) -> float:
    return _number(row.get(key), 0.0)


def _first(row: Any, *keys: str) -> Any:
    for key in keys:
        try:
            value = row.get(key)
        except Exception:
            value = None
        if value not in (None, ""):
            return value
    return None


def _first_matching(row: Any, *keys: str) -> Any:
    exact = _first(row, *keys)
    if exact not in (None, ""):
        return exact

    try:
        row_keys = list(row.keys())
    except Exception:
        return None

    normalized_keys = [_normalize_column_key(key) for key in keys if key]
    for column in row_keys:
        normalized_column = _normalize_column_key(column)
        if not normalized_column:
            continue
        if any(key and key in normalized_column for key in normalized_keys):
            try:
                value = row.get(column)
            except Exception:
                value = None
            if value not in (None, ""):
                return value
    return None


def _normalize_column_key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("（", "(").replace("）", ")")


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return default
    return text or default


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        number = float(str(value).replace(",", "").replace("%", ""))
        return number if math.isfinite(number) else default
    except Exception:
        return default


def _normalize(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    if high <= low:
        return low
    try:
        number = float(value)
    except Exception:
        return low
    if not math.isfinite(number):
        return low
    return max(low, min(high, number))


def _stock_code(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    text = text.split(".")[0].strip()
    if text.isdigit() and len(text) < 6:
        return f"{int(text):06d}"
    return text


def _to_frame(result: Any) -> pd.DataFrame:
    if isinstance(result, pd.DataFrame):
        return result
    if isinstance(result, dict):
        for key in ("data", "result", "tableV1"):
            value = result.get(key)
            if value is not None:
                return _to_frame(value)
        return pd.DataFrame([result])
    if isinstance(result, list):
        return pd.DataFrame(result)
    return pd.DataFrame()


@contextmanager
def _without_proxy_env():
    original_env = {key: os.environ.get(key) for key in PROXY_ENV_KEYS}
    try:
        for key in PROXY_ENV_KEYS:
            os.environ.pop(key, None)
        yield
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


__all__ = ["AIStockScanner", "AIStockScannerConfig", "ThemeInfo"]
