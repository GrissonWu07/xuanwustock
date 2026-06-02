"""A-share corporate-action lookup for replay accounting."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd


def _to_date_text(value: Any) -> str:
    if value in (None, "", pd.NaT):
        return ""
    try:
        return pd.to_datetime(value).date().isoformat()
    except Exception:
        return str(value or "").strip()[:10]


def _to_float(value: Any) -> float:
    try:
        if value in (None, "", pd.NaT):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class AkshareCorporateActionProvider:
    """Fetch stock dividends/splits and normalize them into per-share actions."""

    def __init__(self, *, ak_api: Any = None):
        self.ak = ak_api
        self._cache: dict[str, list[dict[str, Any]]] = {}

    def prepare(self, stock_codes: list[str], start_datetime: datetime, end_datetime: datetime) -> None:
        for stock_code in stock_codes:
            self.get_actions(stock_code, start_datetime, end_datetime)

    def get_actions(self, stock_code: str, start_datetime: datetime, end_datetime: datetime) -> list[dict[str, Any]]:
        code = str(stock_code or "").strip()
        if not code:
            return []
        if code not in self._cache:
            self._cache[code] = self._fetch_actions(code)
        start_date = start_datetime.date()
        end_date = end_datetime.date()
        return [
            action
            for action in self._cache.get(code, [])
            if action.get("ex_date") and start_date <= pd.to_datetime(action["ex_date"]).date() <= end_date
        ]

    def _ak_api(self) -> Any:
        if self.ak is not None:
            return self.ak
        import akshare as ak

        return ak

    def _fetch_actions(self, stock_code: str) -> list[dict[str, Any]]:
        try:
            df = self._ak_api().stock_history_dividend_detail(symbol=stock_code, indicator="分红")
        except Exception:
            return []
        if df is None or df.empty:
            return []
        actions: list[dict[str, Any]] = []
        for _, row in pd.DataFrame(df).iterrows():
            # AkShare/Sina columns are sometimes mojibake in local Windows envs, but the order is stable:
            # 公告日期, 送股, 转增, 派息, 进度, 除权除息日, 股权登记日, 红股上市日
            values = list(row)
            if len(values) < 7:
                continue
            bonus_per_10 = _to_float(values[1]) + _to_float(values[2])
            cash_per_10 = _to_float(values[3])
            ex_date = _to_date_text(values[5])
            record_date = _to_date_text(values[6])
            if not ex_date or (bonus_per_10 <= 0 and cash_per_10 <= 0):
                continue
            bonus_ratio = bonus_per_10 / 10.0
            cash_ratio = cash_per_10 / 10.0
            if bonus_ratio > 0 and cash_ratio > 0:
                action_type = "mixed_dividend_share"
            elif bonus_ratio > 0:
                action_type = "share_transfer"
            else:
                action_type = "cash_dividend"
            actions.append(
                {
                    "stock_code": stock_code,
                    "market": "CN",
                    "action_type": action_type,
                    "ex_date": ex_date,
                    "record_date": record_date,
                    "bonus_share_ratio": bonus_ratio,
                    "cash_dividend_per_share": cash_ratio,
                    "description": f"每10股送转{bonus_per_10:g}股派{cash_per_10:g}元",
                }
            )
        return actions
