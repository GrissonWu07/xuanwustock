"""Canonical technical indicator engine."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.data.indicators.momentum import MomentumIndicators
from app.data.indicators.moving_average import MovingAverageIndicators
from app.data.indicators.profiles import FORMULA_PROFILE_CN_TDX_V1, INDICATOR_VERSION
from app.data.indicators.volatility import VolatilityIndicators
from app.data.indicators.volume import VolumeIndicators
from app.data.store.normalizer import normalize_ohlcv_frame


class TechnicalIndicatorEngine:
    """Calculate canonical indicators from canonical or provider-shaped OHLCV."""

    def __init__(self, *, formula_profile: str = FORMULA_PROFILE_CN_TDX_V1, indicator_version: str = INDICATOR_VERSION):
        if formula_profile != FORMULA_PROFILE_CN_TDX_V1:
            raise ValueError(f"unsupported formula profile: {formula_profile}")
        self.formula_profile = formula_profile
        self.indicator_version = indicator_version

    def calculate(
        self,
        frame: pd.DataFrame | None,
        *,
        symbol: str | None = None,
        source: str = "unknown",
        dataset: str = "ohlcv",
        timeframe: str = "1d",
        adjust: str = "none",
        provider: str | None = None,
        cache_source: str = "memory",
        strict: bool = True,
    ) -> pd.DataFrame:
        canonical = normalize_ohlcv_frame(
            frame,
            symbol=symbol,
            source=source,
            dataset=dataset,
            timeframe=timeframe,
            adjust=adjust,
            provider=provider,
            cache_source=cache_source,
            strict=strict,
        )
        if canonical.empty:
            return canonical
        result = MovingAverageIndicators.apply(canonical)
        result = MomentumIndicators.apply_macd(result)
        result = MomentumIndicators.apply_rsi(result)
        result = MomentumIndicators.apply_kdj(result)
        result = VolatilityIndicators.apply_atr(result)
        result = VolatilityIndicators.apply_bollinger(result)
        result = VolumeIndicators.apply(result)
        result["trend"] = result.apply(self._trend_from_row, axis=1)
        result["indicator_version"] = self.indicator_version
        result["formula_profile"] = self.formula_profile
        return result

    @staticmethod
    def _trend_from_row(row: pd.Series) -> str:
        close = float(row.get("close") or 0)
        ma5 = float(row.get("ma5") or 0)
        ma20 = float(row.get("ma20") or 0)
        ma60 = float(row.get("ma60") or 0)
        if close > ma5 > ma20 > ma60:
            return "up"
        if close < ma5 < ma20 < ma60:
            return "down"
        return "sideways"

    @staticmethod
    def latest_dict(frame: pd.DataFrame | None) -> dict[str, Any]:
        if frame is None or frame.empty:
            return {}
        latest = frame.iloc[-1]
        return latest.to_dict()


__all__ = ["TechnicalIndicatorEngine"]
