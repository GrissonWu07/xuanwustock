"""Moving-average indicators."""

from __future__ import annotations

import pandas as pd


class MovingAverageIndicators:
    @staticmethod
    def apply(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        result["ma5"] = result["close"].rolling(window=5).mean()
        result["ma10"] = result["close"].rolling(window=10).mean()
        result["ma20"] = result["close"].rolling(window=20).mean()
        result["ma60"] = result["close"].rolling(window=60).mean()
        ma20_prev = result["ma20"].shift(1)
        result["ma20_slope"] = ((result["ma20"] - ma20_prev) / ma20_prev.where(ma20_prev != 0)).fillna(0.0)
        return result

