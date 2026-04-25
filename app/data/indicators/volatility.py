"""Volatility indicators."""

from __future__ import annotations

import pandas as pd


class VolatilityIndicators:
    @staticmethod
    def apply_atr(frame: pd.DataFrame, *, period: int = 14) -> pd.DataFrame:
        result = frame.copy()
        prev_close = result["close"].shift(1)
        high_low = result["high"] - result["low"]
        high_close = (result["high"] - prev_close).abs()
        low_close = (result["low"] - prev_close).abs()
        result["tr"] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        result["atr"] = result["tr"].rolling(window=period, min_periods=period).mean()
        return result

    @staticmethod
    def apply_bollinger(frame: pd.DataFrame, *, period: int = 20, std_num: int = 2) -> pd.DataFrame:
        result = frame.copy()
        result["boll_mid"] = result["close"].rolling(window=period).mean()
        std = result["close"].rolling(window=period).std()
        result["boll_upper"] = result["boll_mid"] + std_num * std
        result["boll_lower"] = result["boll_mid"] - std_num * std
        denominator = result["boll_upper"] - result["boll_lower"]
        result["boll_position_value"] = ((result["close"] - result["boll_lower"]) / denominator.where(denominator != 0)).fillna(0.0)
        return result

