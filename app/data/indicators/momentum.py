"""Momentum indicators."""

from __future__ import annotations

import pandas as pd


class MomentumIndicators:
    @staticmethod
    def apply_macd(frame: pd.DataFrame, *, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        result = frame.copy()
        ema_fast = result["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = result["close"].ewm(span=slow, adjust=False).mean()
        result["dif"] = ema_fast - ema_slow
        result["dea"] = result["dif"].ewm(span=signal, adjust=False).mean()
        result["hist"] = result["dif"] - result["dea"]
        result["macd"] = result["hist"] * 2
        return result

    @staticmethod
    def apply_rsi(frame: pd.DataFrame, periods: tuple[int, ...] = (6, 12, 14, 24)) -> pd.DataFrame:
        result = frame.copy()
        delta = result["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        for period in periods:
            avg_gain = gain.rolling(window=period).mean()
            avg_loss = loss.rolling(window=period).mean()
            rs = avg_gain / avg_loss
            result[f"rsi{period}"] = 100 - (100 / (1 + rs))
        return result

    @staticmethod
    def apply_kdj(frame: pd.DataFrame, *, n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
        result = frame.copy()
        low_list = result["low"].rolling(window=n).min()
        high_list = result["high"].rolling(window=n).max()
        rsv = (result["close"] - low_list) / (high_list - low_list) * 100
        result["kdj_k"] = rsv.ewm(com=m1 - 1, adjust=False).mean()
        result["kdj_d"] = result["kdj_k"].ewm(com=m2 - 1, adjust=False).mean()
        result["kdj_j"] = 3 * result["kdj_k"] - 2 * result["kdj_d"]
        return result

