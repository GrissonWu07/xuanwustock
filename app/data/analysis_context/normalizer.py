"""Normalize multi-agent stock analysis into bounded decision context."""

from __future__ import annotations

import json
import re
from typing import Any


_BUY_TERMS = ("买入", "增持", "看多", "偏多", "推荐", "建仓", "加仓", "buy", "bullish", "positive")
_SELL_TERMS = ("卖出", "减持", "看空", "偏空", "清仓", "规避", "sell", "bearish", "negative")
_HOLD_TERMS = ("持有", "观望", "中性", "等待", "hold", "neutral", "watch")
_RISK_TERMS = ("风险", "偏贵", "高估", "回撤", "波动", "压力", "下行", "不确定")
_FUND_IN_TERMS = ("流入", "净流入", "增仓", "主力买入")
_FUND_OUT_TERMS = ("流出", "净流出", "减仓", "主力卖出")
_FUNDAMENTAL_POSITIVE_TERMS = ("增长", "改善", "盈利", "低估", "优势", "稳健")
_FUNDAMENTAL_NEGATIVE_TERMS = ("下滑", "亏损", "高估", "承压", "恶化", "偏贵")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _parse_confidence(final_decision: dict[str, Any], text: str) -> float:
    for key in ("confidence", "confidence_level", "信心度", "置信度"):
        raw = final_decision.get(key)
        if raw is None:
            continue
        if isinstance(raw, (int, float)):
            value = float(raw)
            return _clamp(value / 10.0 if value > 1 else value, 0.0, 1.0)
        match = re.search(r"(\d+(?:\.\d+)?)", str(raw))
        if match:
            value = float(match.group(1))
            return _clamp(value / 10.0 if value > 1 else value, 0.0, 1.0)
    if _has_any(text, _BUY_TERMS + _SELL_TERMS):
        return 0.58
    return 0.45


class StockAnalysisContextNormalizer:
    """Convert stock-analysis output into deterministic bounded signals."""

    def normalize(
        self,
        *,
        final_decision: dict[str, Any] | None = None,
        agents_results: dict[str, Any] | None = None,
        discussion_result: Any = None,
        indicators: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        final_decision = final_decision if isinstance(final_decision, dict) else {}
        agents_results = agents_results if isinstance(agents_results, dict) else {}
        indicators = indicators if isinstance(indicators, dict) else {}

        final_text = _text(final_decision)
        agent_text = _text(agents_results)
        discussion_text = _text(discussion_result)
        combined_text = " ".join(part for part in (final_text, agent_text, discussion_text) if part)

        action_bias = 0.0
        if _has_any(final_text, _BUY_TERMS):
            action_bias += 0.55
        if _has_any(final_text, _SELL_TERMS):
            action_bias -= 0.65
        if not action_bias and _has_any(final_text, _HOLD_TERMS):
            action_bias += 0.0
        if _has_any(agent_text, _BUY_TERMS):
            action_bias += 0.12
        if _has_any(agent_text, _SELL_TERMS):
            action_bias -= 0.15

        risk_text = " ".join(
            _text(final_decision.get(key))
            for key in ("risk_warning", "risk", "风险提示")
            if final_decision.get(key) is not None
        )
        risk_bias = -0.28 if _has_any(" ".join((risk_text, agent_text)), _RISK_TERMS) else 0.0

        fundamental_text = _text(agents_results.get("fundamental") or agents_results.get("基本面") or "")
        fundamental_bias = 0.0
        if _has_any(fundamental_text, _FUNDAMENTAL_POSITIVE_TERMS):
            fundamental_bias += 0.12
        if _has_any(fundamental_text, _FUNDAMENTAL_NEGATIVE_TERMS):
            fundamental_bias -= 0.12

        fund_flow_text = _text(agents_results.get("fund_flow") or agents_results.get("资金流向") or "")
        fund_flow_bias = 0.0
        if _has_any(fund_flow_text, _FUND_IN_TERMS):
            fund_flow_bias += 0.18
        if _has_any(fund_flow_text, _FUND_OUT_TERMS):
            fund_flow_bias -= 0.18

        sentiment_text = _text(agents_results.get("sentiment") or agents_results.get("news") or "")
        sentiment_bias = 0.0
        if _has_any(sentiment_text, _BUY_TERMS):
            sentiment_bias += 0.08
        if _has_any(sentiment_text, _SELL_TERMS) or _has_any(sentiment_text, _RISK_TERMS):
            sentiment_bias -= 0.08

        confidence = _parse_confidence(final_decision, combined_text)
        if risk_bias < 0:
            confidence = max(0.0, confidence - 0.05)
        raw_score = _clamp(action_bias + risk_bias + fundamental_bias + fund_flow_bias + sentiment_bias)
        effective_score = _clamp(raw_score * max(0.0, min(1.0, confidence)))

        source_fields = []
        if final_decision:
            source_fields.append("final_decision")
        if agents_results:
            source_fields.append("agents_results")
        if discussion_result:
            source_fields.append("discussion_result")
        if indicators:
            source_fields.append("indicators")

        summary = self._build_summary(final_decision, raw_score, confidence)
        return {
            "score": round(raw_score, 6),
            "effective_score": round(effective_score, 6),
            "confidence": round(confidence, 6),
            "action_bias": round(_clamp(action_bias), 6),
            "risk_bias": round(_clamp(risk_bias), 6),
            "fundamental_bias": round(_clamp(fundamental_bias), 6),
            "fund_flow_bias": round(_clamp(fund_flow_bias), 6),
            "sentiment_bias": round(_clamp(sentiment_bias), 6),
            "summary": summary,
            "source_fields": source_fields,
            "schema_version": "stock_analysis_context_v1",
            "normalizer_version": "stock_analysis_context_v1",
        }

    @staticmethod
    def _build_summary(final_decision: dict[str, Any], score: float, confidence: float) -> str:
        rating = final_decision.get("rating") or final_decision.get("decision") or final_decision.get("decision_text")
        advice = final_decision.get("operation_advice") or final_decision.get("reasoning") or ""
        if rating:
            return f"{str(rating)[:60]}；score={score:.3f}；confidence={confidence:.2f}"
        if advice:
            return f"{str(advice)[:80]}；score={score:.3f}；confidence={confidence:.2f}"
        return f"stock_analysis_context score={score:.3f}; confidence={confidence:.2f}"
