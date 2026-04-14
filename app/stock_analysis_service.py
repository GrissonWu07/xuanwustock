"""Reusable stock analysis helpers for the gateway and backend services."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import app.config as config
from app.ai_agents import StockAnalysisAgents
from app.database import db
from app.stock_data import StockDataFetcher


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
    rsi = _coerce_float((indicators or {}).get("rsi"))
    if rsi is None:
        explanations["RSI"] = {"state": "暂无数据", "summary": "当前没有可用的 RSI 数据。"}
    elif rsi > 70:
        explanations["RSI"] = {"state": "偏热", "summary": "RSI 高于 70，短线偏热，继续追高要更谨慎。"}
    elif rsi < 30:
        explanations["RSI"] = {"state": "偏冷", "summary": "RSI 低于 30，短线偏弱，但也意味着市场在观察超跌修复机会。"}
    else:
        explanations["RSI"] = {"state": "中性", "summary": "RSI 位于 30-70 之间，暂未进入极端区间。"}

    ma20 = _coerce_float((indicators or {}).get("ma20"))
    if ma20 is None or current_price_value is None:
        explanations["MA20"] = {"state": "暂无判断", "summary": "缺少当前价或 MA20，暂时无法判断中期趋势强弱。"}
    elif current_price_value >= ma20:
        explanations["MA20"] = {"state": "强于中期趋势", "summary": "当前价高于 MA20，中期趋势仍偏强，回调后更容易获得支撑。"}
    else:
        explanations["MA20"] = {"state": "弱于中期趋势", "summary": "当前价低于 MA20，中期趋势偏弱，反弹更需要成交量和趋势确认。"}

    volume_ratio = _coerce_float((indicators or {}).get("volume_ratio"))
    if volume_ratio is None:
        explanations["量比"] = {"state": "暂无数据", "summary": "当前没有可用的量比数据。"}
    elif volume_ratio > 1.5:
        explanations["量比"] = {"state": "明显放量", "summary": "量比大于 1.5，说明当前成交活跃度明显高于常态，价格波动更值得关注。"}
    elif volume_ratio < 0.8:
        explanations["量比"] = {"state": "成交偏淡", "summary": "量比低于 0.8，说明资金参与意愿偏弱，价格信号的持续性要打折扣。"}
    else:
        explanations["量比"] = {"state": "正常成交", "summary": "量比接近 1，成交活跃度没有明显异常。"}

    macd = _coerce_float((indicators or {}).get("macd"))
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


def analyze_single_stock_for_batch(
    symbol: str,
    period: str,
    enabled_analysts_config: dict[str, bool] | None = None,
    selected_model: str | None = None,
) -> dict[str, Any]:
    """Run the full multi-agent stock analysis without any UI dependency."""
    try:
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

        stock_info, stock_data, indicators = get_stock_data(symbol, period)
        if isinstance(stock_info, dict) and "error" in stock_info:
            return {"symbol": symbol, "error": stock_info["error"], "success": False}
        if stock_data is None:
            data_error = stock_info.get("data_error") if isinstance(stock_info, dict) else None
            return {"symbol": symbol, "error": data_error or "无法获取股票历史数据", "success": False}

        fetcher = StockDataFetcher()
        financial_data = fetcher.get_financial_data(symbol)

        quarterly_data = None
        if enabled_analysts_config.get("fundamental", True) and fetcher._is_chinese_stock(symbol):
            try:
                from app.quarterly_report_data import QuarterlyReportDataFetcher

                quarterly_fetcher = QuarterlyReportDataFetcher()
                quarterly_data = quarterly_fetcher.get_quarterly_reports(symbol)
            except Exception:
                quarterly_data = None

        fund_flow_data = None
        if enabled_analysts_config.get("fund_flow", True) and fetcher._is_chinese_stock(symbol):
            try:
                from app.fund_flow_akshare import FundFlowAkshareDataFetcher

                fund_flow_fetcher = FundFlowAkshareDataFetcher()
                fund_flow_data = fund_flow_fetcher.get_fund_flow_data(symbol)
            except Exception:
                fund_flow_data = None

        sentiment_data = None
        if enabled_analysts_config.get("sentiment", False) and fetcher._is_chinese_stock(symbol):
            try:
                from app.market_sentiment_data import MarketSentimentDataFetcher

                sentiment_fetcher = MarketSentimentDataFetcher()
                sentiment_data = sentiment_fetcher.get_market_sentiment_data(symbol, stock_data)
            except Exception:
                sentiment_data = None

        news_data = None
        if enabled_analysts_config.get("news", False) and fetcher._is_chinese_stock(symbol):
            try:
                from app.qstock_news_data import QStockNewsDataFetcher

                news_fetcher = QStockNewsDataFetcher()
                news_data = news_fetcher.get_stock_news(symbol)
            except Exception:
                news_data = None

        risk_data = None
        if enabled_analysts_config.get("risk", True) and fetcher._is_chinese_stock(symbol):
            try:
                risk_data = fetcher.get_risk_data(symbol)
            except Exception:
                risk_data = None

        agents = StockAnalysisAgents(model=selected_model)
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
        )

        discussion_result = agents.conduct_team_discussion(agents_results, stock_info)
        final_decision = agents.make_final_decision(discussion_result, stock_info, indicators)

        saved_to_db = False
        db_error = None
        try:
            db.save_analysis(
                symbol=stock_info.get("symbol", ""),
                stock_name=stock_info.get("name", ""),
                period=period,
                stock_info=stock_info,
                agents_results=agents_results,
                discussion_result=discussion_result,
                final_decision=final_decision,
            )
            saved_to_db = True
        except Exception as exc:
            db_error = str(exc)

        historical_data = None
        try:
            historical_data = [
                {"date": str(index.date()), "close": float(row.get("Close"))}
                for index, row in stock_data.tail(120).iterrows()
                if row.get("Close") is not None
            ]
        except Exception:
            historical_data = None

        return {
            "symbol": symbol,
            "success": True,
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
