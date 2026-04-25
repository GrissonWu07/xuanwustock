"""Volume indicators."""

from __future__ import annotations

import pandas as pd


class VolumeIndicators:
    @staticmethod
    def apply(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        result["volume_ma5"] = result["volume"].rolling(window=5).mean()
        result["volume_ma10"] = result["volume"].rolling(window=10).mean()
        result["volume_ratio"] = result["volume"] / result["volume_ma5"].where(result["volume_ma5"] != 0)
        delta = result["close"].diff().fillna(0.0)
        positive = result["volume"].where(delta > 0, 0.0)
        negative = result["volume"].where(delta < 0, 0.0)
        result["obv"] = (positive - negative).cumsum()
        result["obv_prev"] = result["obv"].shift(1)
        return result

