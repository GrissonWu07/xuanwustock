"""Stockpolicy-inspired strategy adapter built on the main project's data stack."""

from __future__ import annotations

from typing import Any, Optional

from smart_monitor_tdx_data import SmartMonitorTDXDataFetcher


SOURCE_CONTEXT_SCORES = {
    "main_force": 0.28,
    "profit_growth": 0.22,
    "low_price_bull": 0.18,
    "value_stock": 0.2,
    "manual": 0.12,
}


class StockPolicyAdapter:
    """Generate semi-auto decisions from unified market data and selector context."""

    def __init__(self, data_fetcher: Optional[SmartMonitorTDXDataFetcher] = None):
        self.data_fetcher = data_fetcher or SmartMonitorTDXDataFetcher()

    def analyze_candidate(
        self,
        candidate: dict[str, Any],
        market_snapshot: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        stock_code = candidate["stock_code"]
        source = candidate.get("source", "manual")

        snapshot = market_snapshot or self.data_fetcher.get_comprehensive_data(stock_code)
        if not snapshot:
            return {
                "action": "HOLD",
                "confidence": 55,
                "reasoning": "暂未取得完整行情与技术指标，保持观察。",
                "position_size_pct": 0,
                "stop_loss_pct": 5,
                "take_profit_pct": 12,
                "tech_score": 0.0,
                "context_score": SOURCE_CONTEXT_SCORES.get(source, 0.1),
            }

        current_price = float(snapshot.get("current_price") or candidate.get("latest_price") or 0)
        ma5 = float(snapshot.get("ma5") or 0)
        ma20 = float(snapshot.get("ma20") or 0)
        ma60 = float(snapshot.get("ma60") or 0)
        macd = float(snapshot.get("macd") or 0)
        rsi12 = float(snapshot.get("rsi12") or 50)
        volume_ratio = float(snapshot.get("volume_ratio") or 1)
        trend = snapshot.get("trend", "sideways")

        tech_score = self._calculate_tech_score(
            current_price=current_price,
            ma5=ma5,
            ma20=ma20,
            ma60=ma60,
            macd=macd,
            rsi12=rsi12,
            volume_ratio=volume_ratio,
            trend=trend,
        )
        context_score = SOURCE_CONTEXT_SCORES.get(source, 0.1)
        combined_score = tech_score * 0.75 + context_score * 0.25

        if combined_score >= 0.32 and tech_score > 0:
            action = "BUY"
        elif combined_score <= -0.18:
            action = "SELL"
        else:
            action = "HOLD"

        confidence = self._calculate_confidence(combined_score, action)
        position_size_pct = self._suggest_position_size(combined_score, action)
        reasoning = self._build_reasoning(
            candidate=candidate,
            action=action,
            current_price=current_price,
            ma5=ma5,
            ma20=ma20,
            ma60=ma60,
            macd=macd,
            rsi12=rsi12,
            volume_ratio=volume_ratio,
            tech_score=tech_score,
            context_score=context_score,
        )

        return {
            "action": action,
            "confidence": confidence,
            "reasoning": reasoning,
            "position_size_pct": position_size_pct,
            "stop_loss_pct": 5,
            "take_profit_pct": 12,
            "tech_score": round(tech_score, 4),
            "context_score": round(context_score, 4),
        }

    @staticmethod
    def _calculate_tech_score(
        current_price: float,
        ma5: float,
        ma20: float,
        ma60: float,
        macd: float,
        rsi12: float,
        volume_ratio: float,
        trend: str,
    ) -> float:
        score = 0.0

        if trend == "up":
            score += 0.35
        elif trend == "down":
            score -= 0.35

        if current_price > ma5 > ma20 > ma60 > 0:
            score += 0.25
        elif current_price < ma5 < ma20 < ma60 and ma60 > 0:
            score -= 0.25

        if macd > 0:
            score += 0.15
        elif macd < 0:
            score -= 0.15

        if 45 <= rsi12 <= 68:
            score += 0.1
        elif rsi12 >= 75:
            score -= 0.12
        elif rsi12 <= 25:
            score += 0.08

        if volume_ratio >= 1.2:
            score += 0.08
        elif volume_ratio <= 0.8:
            score -= 0.05

        return max(-1.0, min(1.0, score))

    @staticmethod
    def _calculate_confidence(score: float, action: str) -> int:
        base = 58 if action == "HOLD" else 62
        scaled = base + int(abs(score) * 35)
        return max(55, min(92, scaled))

    @staticmethod
    def _suggest_position_size(score: float, action: str) -> float:
        if action != "BUY":
            return 0.0
        if score >= 0.55:
            return 30.0
        if score >= 0.4:
            return 20.0
        return 10.0

    @staticmethod
    def _build_reasoning(
        candidate: dict[str, Any],
        action: str,
        current_price: float,
        ma5: float,
        ma20: float,
        ma60: float,
        macd: float,
        rsi12: float,
        volume_ratio: float,
        tech_score: float,
        context_score: float,
    ) -> str:
        source = candidate.get("source", "manual")
        return (
            f"{candidate['stock_code']} 当前给出 {action}，"
            f"来源策略为 {source}；价格 {current_price:.2f}，MA5/MA20/MA60 为 "
            f"{ma5:.2f}/{ma20:.2f}/{ma60:.2f}，MACD {macd:.3f}，RSI12 {rsi12:.2f}，"
            f"量比 {volume_ratio:.2f}。技术评分 {tech_score:.2f}，上下文评分 {context_score:.2f}。"
        )
