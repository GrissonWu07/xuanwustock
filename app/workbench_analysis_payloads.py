from __future__ import annotations

from datetime import datetime
from typing import Any

from app.i18n import t
from app import stock_analysis_service


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _txt(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _dict_value(obj: Any, key: str, default: Any = None) -> Any:
    if not isinstance(obj, dict):
        return default
    return obj.get(key, default)


def _num(value: Any, digits: int = 2, default: str = "0.00") -> str:
    if value in (None, ""):
        return default
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _snippet(value: Any, limit: int = 80, default: str = "") -> str:
    # 保留兼容函数签名，但不再执行任何文本截断。
    _ = limit
    return _txt(value, default)


def _insight(title: str, body: str, tone: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"title": _txt(title), "body": _txt(body)}
    if tone:
        payload["tone"] = tone
    return payload


def _first_non_empty(mapping: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def analysis_options(selected: list[str] | set[str] | None = None) -> list[dict[str, Any]]:
    defaults = {"technical", "fundamental", "fund_flow", "risk"}
    if selected is not None:
        defaults = {str(item) for item in selected if str(item).strip()}
    return [
        {"label": t("Technical analyst"), "value": "technical", "selected": "technical" in defaults},
        {"label": t("Fundamental analyst"), "value": "fundamental", "selected": "fundamental" in defaults},
        {"label": t("Fund flow analyst"), "value": "fund_flow", "selected": "fund_flow" in defaults},
        {"label": t("Risk analyst"), "value": "risk", "selected": "risk" in defaults},
        {"label": t("Sentiment analyst"), "value": "sentiment", "selected": "sentiment" in defaults},
        {"label": t("News analyst"), "value": "news", "selected": "news" in defaults},
    ]


def analysis_config(selected_values: list[str] | None) -> dict[str, bool]:
    selected = {str(item) for item in selected_values or [] if str(item).strip()}
    return {
        "technical": "technical" in selected,
        "fundamental": "fundamental" in selected,
        "fund_flow": "fund_flow" in selected,
        "risk": "risk" in selected,
        "sentiment": "sentiment" in selected,
        "news": "news" in selected,
    }


def _analysis_agent_title(agent_key: str) -> str:
    mapping = {
        "technical": t("Technical analyst"),
        "fundamental": t("Fundamental analyst"),
        "fund_flow": t("Fund flow analyst"),
        "risk_management": t("Risk analyst"),
        "market_sentiment": t("Sentiment analyst"),
        "news": t("News analyst"),
        "risk": t("Risk analyst"),
        "sentiment": t("Sentiment analyst"),
    }
    return mapping.get(agent_key, t("{agent} analyst", agent=agent_key))


def _indicator_value(indicators: dict[str, Any], aliases: list[str]) -> Any:
    for alias in aliases:
        if alias in indicators:
            return indicators.get(alias)
    lowered = {str(key).lower(): value for key, value in indicators.items()}
    for alias in aliases:
        alias_lower = str(alias).lower()
        if alias_lower in lowered:
            return lowered.get(alias_lower)
    return None


def _format_indicator_cards(indicators: dict[str, Any] | None, explanations: Any) -> list[dict[str, str]]:
    if isinstance(explanations, list):
        return [{"label": _txt(item.get("label")), "value": _txt(item.get("value"))} for item in explanations if isinstance(item, dict)]
    cards: list[dict[str, str]] = []
    indicators = indicators or {}
    explanation_map = explanations if isinstance(explanations, dict) else {}
    specs = [
        (t("Price"), ["price", "close", "Close"], t("Latest traded price, used for trend location and stop planning.")),
        (t("Volume"), ["volume", "Volume"], t("Latest traded volume in current bar/session.")),
        (t("Volume MA5"), ["volume_ma5", "Volume_MA5"], t("5-period average volume, baseline for volume expansion/shrinkage.")),
        ("MA5", ["ma5", "MA5"], t("5-day moving average for short-term rhythm.")),
        ("MA10", ["ma10", "MA10"], t("10-day moving average for short-to-mid transition.")),
        ("MA20", ["ma20", "MA20"], t("20-day moving average as medium-term strength boundary.")),
        ("MA60", ["ma60", "MA60"], t("60-day moving average for medium-long trend.")),
        ("RSI", ["rsi", "RSI"], t("Relative Strength Index for overbought/oversold signal.")),
        ("MACD", ["macd", "MACD"], t("Trend momentum indicator. Positive favors bullish bias.")),
        (t("MACD histogram"), ["macd_histogram", "MACD_histogram"], t("MACD histogram shows acceleration/deceleration of momentum.")),
        (t("Signal line"), ["macd_signal", "MACD_signal"], t("MACD signal line for momentum turning points.")),
        (t("Bollinger upper"), ["bb_upper", "BB_upper"], t("Upper volatility band. Near upper band often means larger swings.")),
        (t("Bollinger middle"), ["bb_middle", "BB_middle"], t("Bollinger middle band (usually MA20), center line for mean reversion checks.")),
        (t("Bollinger lower"), ["bb_lower", "BB_lower"], t("Lower volatility band. Near lower band requires volume confirmation.")),
        (t("K value"), ["k_value", "K"], t("KDJ fast line for sensitive short-cycle movement.")),
        (t("D value"), ["d_value", "D"], t("KDJ slow line. K/D cross can support turning-point judgment.")),
        (t("Volume ratio"), ["volume_ratio", "Volume_ratio"], t("Relative activity versus historical average volume.")),
    ]
    for label, aliases, fallback_hint in specs:
        value = _indicator_value(indicators, aliases)
        detail = explanation_map.get(label) if isinstance(explanation_map.get(label), dict) else None
        if value is None and detail:
            value = detail.get("state") or detail.get("summary")
        hint = _txt(detail.get("summary")) if detail else fallback_hint
        cards.append(
            {
                "label": label,
                "value": _txt(_num(value, 2) if isinstance(value, (int, float)) else value, "--"),
                "hint": _txt(hint, fallback_hint),
            }
        )
    return cards


def _analysis_curve(points: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    curve: list[dict[str, Any]] = []
    for item in points or []:
        if not isinstance(item, dict):
            continue
        label = _txt(item.get("date") or item.get("日期") or item.get("datetime"))
        value = item.get("close") or item.get("收盘") or item.get("value")
        try:
            curve.append({"label": label, "value": float(value)})
        except (TypeError, ValueError):
            continue
    return curve


def build_workbench_analysis_payload(
    *,
    code: str,
    stock_name: str,
    selected: list[str] | None,
    mode: str,
    cycle: str,
    generated_at: str,
    stock_info: dict[str, Any],
    indicators: dict[str, Any],
    discussion_result: Any,
    final_decision: dict[str, Any],
    agents_results: dict[str, Any],
    historical_data: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    indicator_explanations = stock_analysis_service.build_indicator_explanations(
        indicators,
        current_price=stock_info.get("current_price"),
    )
    summary_body = _txt(_dict_value(discussion_result, "summary")) or _txt(discussion_result)
    if not summary_body:
        summary_body = _txt(stock_analysis_service.build_indicator_summary(indicator_explanations), t("Analysis completed."))
    summary_body = _txt(summary_body, t("Analysis completed."))
    stock_sector = _txt(
        _first_non_empty(
            stock_info if isinstance(stock_info, dict) else {},
            ["sector", "industry", "board", "concept", "所属行业", "板块"],
        )
    )
    summary_header = [f"{t('Stock code')}: {code}"]
    if stock_sector and stock_sector.upper() not in {"N/A", "NA", "--", "未知"}:
        summary_header.append(f"{t('Sector')}: {stock_sector}")
    summary_body = "\n".join(summary_header + ["", summary_body])

    analyst_views: list[dict[str, Any]] = []
    insights: list[dict[str, Any]] = []
    decision_rating = _txt(
        _first_non_empty(final_decision, ["decision", "rating", "verdict", "decision_text"]),
        t("No clear conclusion"),
    )
    operation_advice = _txt(_dict_value(final_decision, "operation_advice"))
    final_reasoning = _txt(_dict_value(final_decision, "reasoning")) or operation_advice or _txt(_dict_value(final_decision, "decision_text"))
    if final_reasoning:
        insights.append(_insight(t("Action advice"), _txt(final_reasoning), "accent"))
    risk_warning = _txt(_dict_value(final_decision, "risk_warning"))
    if risk_warning:
        insights.append(_insight(t("Risk warning"), _txt(risk_warning), "warning"))
    decision_detail_lines = [f"- {t('Investment rating')}: {decision_rating}"]
    detail_fields = [
        (t("Target price"), "target_price"),
        (t("Entry range"), "entry_range"),
        (t("Take-profit"), "take_profit"),
        (t("Stop-loss"), "stop_loss"),
        (t("Holding period"), "holding_period"),
        (t("Position sizing"), "position_size"),
        (t("Confidence"), "confidence_level"),
    ]
    for label, key in detail_fields:
        value = _txt(_dict_value(final_decision, key))
        if value:
            decision_detail_lines.append(f"- {label}：{value}")
    final_decision_text = "\n".join(decision_detail_lines)

    for key, agent_result in agents_results.items():
        if not isinstance(agent_result, dict):
            continue
        agent_text = _txt(_first_non_empty(agent_result, ["summary", "analysis", "decision_text", "result"]))
        if not agent_text:
            continue
        agent_name = _txt(agent_result.get("agent_name"), _analysis_agent_title(key))
        analyst_views.append(_insight(agent_name, _txt(agent_text)))

    return {
        "symbol": code,
        "stockName": stock_name,
        "analysts": analysis_options(selected),
        "mode": mode,
        "cycle": cycle,
        "inputHint": t("Example: 600519 / 300390 / AAPL"),
        "summaryTitle": t("{name} analysis summary", name=stock_name),
        "summaryBody": summary_body,
        "generatedAt": _txt(generated_at, _now()),
        "indicators": _format_indicator_cards(indicators, indicator_explanations),
        "decision": decision_rating,
        "finalDecisionText": final_decision_text,
        "insights": insights or [_insight(t("Current conclusion"), t("Analysis completed, but no additional structured interpretation is available."))],
        "analystViews": analyst_views,
        "curve": _analysis_curve(historical_data),
    }


__all__ = ["analysis_config", "analysis_options", "build_workbench_analysis_payload"]
