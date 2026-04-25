"""Reusable stock analysis helpers for the gateway and backend services."""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
import queue
import threading
import time
from typing import Any, Callable

import app.config as config
from app.ai_agents import StockAnalysisAgents
from app.data.analysis_context import StockAnalysisContextNormalizer
from app.data.indicators.profiles import FORMULA_PROFILE_CN_TDX_V1, INDICATOR_VERSION
from app.database import StockAnalysisDatabase, db
from app.stock_data import StockDataFetcher


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _indicator_value(indicators: dict[str, Any] | None, *aliases: str) -> Any:
    if not isinstance(indicators, dict) or not indicators:
        return None
    for alias in aliases:
        if alias in indicators:
            return indicators.get(alias)
    lowered = {str(key).lower(): value for key, value in indicators.items()}
    for alias in aliases:
        lowered_alias = str(alias).lower()
        if lowered_alias in lowered:
            return lowered[lowered_alias]
    return None


def _format_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def _infer_stock_data_as_of(stock_data: Any, fallback: datetime) -> tuple[datetime, str]:
    try:
        if stock_data is not None and len(stock_data) > 0:
            index = getattr(stock_data, "index", None)
            if index is not None and len(index) > 0:
                maybe_dt = index[-1]
                if hasattr(maybe_dt, "to_pydatetime"):
                    return maybe_dt.to_pydatetime().replace(tzinfo=None), "exact"
                parsed = datetime.fromisoformat(str(maybe_dt).replace("T", " ")[:19])
                return parsed, "exact"
    except Exception:
        pass
    return fallback, "generated_at_fallback"


@lru_cache(maxsize=128)
def get_stock_data(symbol: str, period: str):
    """Fetch stock history, a lightweight stock profile and indicators."""
    fetcher = StockDataFetcher()
    stock_data = fetcher.get_stock_data(symbol, period)
    stock_info = fetcher.get_fast_stock_info(symbol)

    if isinstance(stock_data, dict) and "error" in stock_data:
        if isinstance(stock_info, dict):
            stock_info["data_error"] = stock_data["error"]
        return stock_info, None, None

    if isinstance(stock_info, dict) and stock_data is not None and len(stock_data) > 0:
        latest = stock_data.iloc[-1]
        if stock_info.get("current_price") in (None, "N/A", ""):
            stock_info["current_price"] = latest.get("Close", "N/A")
        if len(stock_data) > 1:
            previous = stock_data.iloc[-2]
            prev_close = previous.get("Close")
            latest_close = latest.get("Close")
            if prev_close not in (None, 0, "N/A") and latest_close not in (None, "N/A"):
                try:
                    if stock_info.get("change_percent") in (None, "N/A", ""):
                        stock_info["change_percent"] = round(((latest_close - prev_close) / prev_close) * 100, 2)
                except Exception:
                    pass

    stock_data_with_indicators = fetcher.calculate_technical_indicators(stock_data)
    indicators = fetcher.get_latest_indicators(stock_data_with_indicators)

    return stock_info, stock_data_with_indicators, indicators


def build_indicator_explanations(indicators: dict[str, Any] | None, current_price: Any = None) -> dict[str, dict[str, str]]:
    """Convert raw indicator values into user-facing explanations."""
    explanations: dict[str, dict[str, str]] = {}

    current_price_value = _coerce_float(current_price)
    rsi = _coerce_float(_indicator_value(indicators, "rsi", "RSI"))
    if rsi is None:
        explanations["RSI"] = {"state": "暂无数据", "summary": "当前没有可用的 RSI 数据。"}
    elif rsi > 70:
        explanations["RSI"] = {"state": "偏热", "summary": "RSI 高于 70，短线偏热，继续追高要更谨慎。"}
    elif rsi < 30:
        explanations["RSI"] = {"state": "偏冷", "summary": "RSI 低于 30，短线偏弱，但也意味着市场在观察超跌修复机会。"}
    else:
        explanations["RSI"] = {"state": "中性", "summary": "RSI 位于 30-70 之间，暂未进入极端区间。"}

    ma20 = _coerce_float(_indicator_value(indicators, "ma20", "MA20", "Ma20"))
    if ma20 is None or current_price_value is None:
        explanations["MA20"] = {"state": "暂无判断", "summary": "缺少当前价或 MA20，暂时无法判断中期趋势强弱。"}
    elif current_price_value >= ma20:
        explanations["MA20"] = {"state": "强于中期趋势", "summary": "当前价高于 MA20，中期趋势仍偏强，回调后更容易获得支撑。"}
    else:
        explanations["MA20"] = {"state": "弱于中期趋势", "summary": "当前价低于 MA20，中期趋势偏弱，反弹更需要成交量和趋势确认。"}

    volume_ratio = _coerce_float(_indicator_value(indicators, "volume_ratio", "量比", "volumeRatio", "VolumeRatio"))
    if volume_ratio is None:
        explanations["量比"] = {"state": "暂无数据", "summary": "当前没有可用的量比数据。"}
    elif volume_ratio > 1.5:
        explanations["量比"] = {"state": "明显放量", "summary": "量比大于 1.5，说明当前成交活跃度明显高于常态，价格波动更值得关注。"}
    elif volume_ratio < 0.8:
        explanations["量比"] = {"state": "成交偏淡", "summary": "量比低于 0.8，说明资金参与意愿偏弱，价格信号的持续性要打折扣。"}
    else:
        explanations["量比"] = {"state": "正常成交", "summary": "量比接近 1，成交活跃度没有明显异常。"}

    macd = _coerce_float(_indicator_value(indicators, "macd", "MACD"))
    if macd is None:
        explanations["MACD"] = {"state": "暂无数据", "summary": "当前没有可用的 MACD 数据。"}
    elif macd > 0:
        explanations["MACD"] = {"state": "多头动能", "summary": "MACD 大于 0，说明价格动能偏强，多头仍占优势。"}
    elif macd < 0:
        explanations["MACD"] = {"state": "空头动能", "summary": "MACD 小于 0，说明价格动能偏弱，空头压力仍在。"}
    else:
        explanations["MACD"] = {"state": "动能平衡", "summary": "MACD 接近 0，说明多空动能暂时比较均衡。"}

    return explanations


def build_indicator_summary(explanations: dict[str, dict[str, str]]) -> str:
    ordered_keys = ["RSI", "MA20", "量比", "MACD"]
    parts: list[str] = []
    for key in ordered_keys:
        payload = explanations.get(key)
        if not payload:
            continue
        parts.append(f"{key}：{payload['state']}。{payload['summary']}")
    return " ".join(parts)


def _run_parallel_enrichment_tasks(
    tasks: dict[str, Callable[[], Any]],
    *,
    timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Run enrichment fetches in parallel and cap the total blocking time."""
    if not tasks:
        return {}, {}

    results: dict[str, Any] = {name: None for name in tasks}
    errors: dict[str, str] = {}
    handles: list[tuple[str, threading.Thread, queue.Queue[Any], queue.Queue[BaseException]]] = []

    for name, task in tasks.items():
        result_box: queue.Queue[Any] = queue.Queue(maxsize=1)
        error_box: queue.Queue[BaseException] = queue.Queue(maxsize=1)

        def runner(task_name: str = name, task_callable: Callable[[], Any] = task) -> None:
            try:
                result_box.put(task_callable())
            except BaseException as exc:  # pragma: no cover - defensive
                error_box.put(exc)

        worker = threading.Thread(
            target=runner,
            name=f"analysis-enrich-{name}",
            daemon=True,
        )
        worker.start()
        handles.append((name, worker, result_box, error_box))

    total_timeout = max(float(timeout_seconds), 0.01)
    deadline = time.monotonic() + total_timeout
    for name, worker, result_box, error_box in handles:
        remaining = max(deadline - time.monotonic(), 0.0)
        worker.join(timeout=remaining)
        if worker.is_alive():
            errors[name] = f"{name} timeout after {total_timeout:.2f}s"
            continue
        if not error_box.empty():
            errors[name] = str(error_box.get())
            continue
        if not result_box.empty():
            results[name] = result_box.get()

    return results, errors


def analyze_single_stock_for_batch(
    symbol: str,
    period: str,
    enabled_analysts_config: dict[str, bool] | None = None,
    selected_model: str | None = None,
    progress_callback: Callable[[str, str, int | None], None] | None = None,
    analysis_db: StockAnalysisDatabase | None = None,
    stock_analysis_db_path: str | None = None,
    valid_hours: float = 24.0,
    replace_same_day: bool = True,
) -> dict[str, Any]:
    """Run the full multi-agent stock analysis without any UI dependency."""
    try:
        def report(stage: str, message: str, progress: int | None = None) -> None:
            if progress_callback:
                progress_callback(stage, message, progress)

        if selected_model is None:
            selected_model = config.DEFAULT_MODEL_NAME

        if enabled_analysts_config is None:
            enabled_analysts_config = {
                "technical": True,
                "fundamental": True,
                "fund_flow": True,
                "risk": True,
                "sentiment": False,
                "news": False,
            }

        report("fetch", "正在获取行情与基础信息", 8)
        stock_info, stock_data, indicators = get_stock_data(symbol, period)
        if isinstance(stock_info, dict) and "error" in stock_info:
            return {"symbol": symbol, "error": stock_info["error"], "success": False}
        if stock_data is None:
            data_error = stock_info.get("data_error") if isinstance(stock_info, dict) else None
            return {"symbol": symbol, "error": data_error or "无法获取股票历史数据", "success": False}

        fetcher = StockDataFetcher()
        report("enrich", "正在补充财务与资金面数据", 18)
        is_chinese_stock = fetcher._is_chinese_stock(symbol)
        enrichment_tasks: dict[str, Callable[[], Any]] = {
            "financial_data": lambda: fetcher.get_financial_data(symbol),
        }

        if enabled_analysts_config.get("fundamental", True) and is_chinese_stock:
            def fetch_quarterly_data() -> Any:
                from app.quarterly_report_data import QuarterlyReportDataFetcher

                quarterly_fetcher = QuarterlyReportDataFetcher()
                return quarterly_fetcher.get_quarterly_reports(symbol)

            enrichment_tasks["quarterly_data"] = fetch_quarterly_data

        if enabled_analysts_config.get("fund_flow", True) and is_chinese_stock:
            def fetch_fund_flow_data() -> Any:
                from app.fund_flow_akshare import FundFlowAkshareDataFetcher

                fund_flow_fetcher = FundFlowAkshareDataFetcher()
                return fund_flow_fetcher.get_fund_flow_data(symbol)

            enrichment_tasks["fund_flow_data"] = fetch_fund_flow_data

        if enabled_analysts_config.get("sentiment", False) and is_chinese_stock:
            def fetch_sentiment_data() -> Any:
                from app.market_sentiment_data import MarketSentimentDataFetcher

                sentiment_fetcher = MarketSentimentDataFetcher()
                return sentiment_fetcher.get_market_sentiment_data(symbol, stock_data)

            enrichment_tasks["sentiment_data"] = fetch_sentiment_data

        if enabled_analysts_config.get("news", False) and is_chinese_stock:
            def fetch_news_data() -> Any:
                from app.qstock_news_data import QStockNewsDataFetcher

                news_fetcher = QStockNewsDataFetcher()
                return news_fetcher.get_stock_news(symbol)

            enrichment_tasks["news_data"] = fetch_news_data

        if enabled_analysts_config.get("risk", True) and is_chinese_stock:
            enrichment_tasks["risk_data"] = lambda: fetcher.get_risk_data(symbol)

        enrichment_results, enrichment_errors = _run_parallel_enrichment_tasks(
            enrichment_tasks,
            timeout_seconds=config.EXTERNAL_DATA_TASK_TIMEOUT_SECONDS,
        )
        financial_data = enrichment_results.get("financial_data")
        quarterly_data = enrichment_results.get("quarterly_data")
        fund_flow_data = enrichment_results.get("fund_flow_data")
        sentiment_data = enrichment_results.get("sentiment_data")
        news_data = enrichment_results.get("news_data")
        risk_data = enrichment_results.get("risk_data")

        if enrichment_errors:
            report(
                "enrich",
                "部分补充数据获取较慢，已使用当前可用数据继续分析",
                24,
            )

        agents = StockAnalysisAgents(model=selected_model)
        report("analyst", "正在生成分析师观点", 30)
        agents_results = agents.run_multi_agent_analysis(
            stock_info,
            stock_data,
            indicators,
            financial_data,
            fund_flow_data,
            sentiment_data,
            news_data,
            quarterly_data,
            risk_data,
            enabled_analysts=enabled_analysts_config,
            progress_callback=progress_callback,
        )

        report("discussion", "正在组织团队讨论", 78)
        discussion_result = agents.conduct_team_discussion(agents_results, stock_info)
        report("decision", "正在生成最终决策", 88)
        final_decision = agents.make_final_decision(discussion_result, stock_info, indicators)

        historical_data = None
        try:
            historical_data = [
                {"date": str(index.date()), "close": float(row.get("Close"))}
                for index, row in stock_data.tail(120).iterrows()
                if row.get("Close") is not None
            ]
        except Exception:
            historical_data = None

        saved_to_db = False
        db_error = None
        generated_dt = datetime.now()
        generated_at = _format_dt(generated_dt)
        data_as_of_dt, data_as_of_quality = _infer_stock_data_as_of(stock_data, generated_dt)
        try:
            resolved_valid_hours = max(float(valid_hours), 0.01)
        except (TypeError, ValueError):
            resolved_valid_hours = 24.0
        valid_until_dt = generated_dt + timedelta(hours=resolved_valid_hours)
        analysis_context = StockAnalysisContextNormalizer().normalize(
            final_decision=final_decision,
            agents_results=agents_results,
            discussion_result=discussion_result,
            indicators=indicators,
        )
        analysis_context["data_as_of"] = _format_dt(data_as_of_dt)
        analysis_context["data_as_of_quality"] = data_as_of_quality
        analysis_context["valid_until"] = _format_dt(valid_until_dt)
        try:
            report("persist", "正在保存分析结果", 96)
            target_db = analysis_db or (StockAnalysisDatabase(stock_analysis_db_path) if stock_analysis_db_path else db)
            target_db.save_analysis(
                symbol=stock_info.get("symbol", ""),
                stock_name=stock_info.get("name", ""),
                period=period,
                stock_info=stock_info,
                agents_results=agents_results,
                discussion_result=discussion_result,
                final_decision=final_decision,
                indicators=indicators,
                historical_data=historical_data,
                data_as_of=_format_dt(data_as_of_dt),
                data_as_of_quality=data_as_of_quality,
                valid_until=_format_dt(valid_until_dt),
                analysis_context=analysis_context,
                formula_profile=str((indicators or {}).get("formula_profile") or FORMULA_PROFILE_CN_TDX_V1),
                indicator_version=str((indicators or {}).get("indicator_version") or INDICATOR_VERSION),
                replace_same_day=replace_same_day,
            )
            saved_to_db = True
        except Exception as exc:
            db_error = str(exc)

        return {
            "symbol": symbol,
            "success": True,
            "generated_at": generated_at,
            "data_as_of": _format_dt(data_as_of_dt),
            "data_as_of_quality": data_as_of_quality,
            "valid_until": _format_dt(valid_until_dt),
            "analysis_context": analysis_context,
            "stock_info": stock_info,
            "indicators": indicators,
            "agents_results": agents_results,
            "discussion_result": discussion_result,
            "final_decision": final_decision,
            "saved_to_db": saved_to_db,
            "db_error": db_error,
            "historical_data": historical_data,
        }
    except Exception as exc:
        return {"symbol": symbol, "error": str(exc), "success": False}
