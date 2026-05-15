"""Shared market trading-day and trading-hour utilities."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable, List

try:
    import chinese_calendar

    HAS_CHINESE_CALENDAR = True
except ImportError:  # pragma: no cover - optional dependency
    HAS_CHINESE_CALENDAR = False


class TradingTimeUtils:
    """Generate and evaluate market trading checkpoints."""

    MARKET_TRADING_HOURS = {
        "CN": [(time(9, 30), time(11, 30)), (time(13, 0), time(15, 0))],
        "HK": [(time(9, 30), time(12, 0)), (time(13, 0), time(16, 0))],
        "US": [(time(9, 30), time(16, 0))],
    }
    MORNING_OPEN = time(9, 30)
    MORNING_CLOSE = time(11, 30)
    AFTERNOON_OPEN = time(13, 0)
    AFTERNOON_CLOSE = time(15, 0)
    DAILY_POINT = time(14, 50)
    INTRADAY_POINTS = (
        time(10, 0),
        time(10, 30),
        time(11, 0),
        time(11, 30),
        time(13, 30),
        time(14, 0),
        time(14, 30),
        time(15, 0),
    )

    def __init__(self, *, skip_weekends: bool = True, skip_holidays: bool = True):
        self.skip_weekends = skip_weekends
        self.skip_holidays = skip_holidays

    def generate(self, start_datetime: datetime, end_datetime: datetime, timeframe: str) -> List[datetime]:
        normalized = str(timeframe).lower()
        if normalized in {"1d", "day", "daily"}:
            return self._generate_daily_points(start_datetime, end_datetime)
        if normalized in {"30m", "30min", "minute30", "1d+30m"}:
            return self._generate_intraday_points(start_datetime, end_datetime, self.INTRADAY_POINTS)
        raise ValueError(f"Unsupported replay timeframe: {timeframe}")

    def _generate_daily_points(self, start_datetime: datetime, end_datetime: datetime) -> List[datetime]:
        points: list[datetime] = []
        current_date = start_datetime.date()
        while current_date <= end_datetime.date():
            checkpoint = datetime.combine(current_date, self.DAILY_POINT)
            if self.is_trading_day(checkpoint) and start_datetime <= checkpoint <= end_datetime:
                points.append(checkpoint)
            current_date += timedelta(days=1)
        return points

    def _generate_intraday_points(
        self,
        start_datetime: datetime,
        end_datetime: datetime,
        time_points: Iterable[time],
    ) -> List[datetime]:
        points: list[datetime] = []
        current_date = start_datetime.date()
        while current_date <= end_datetime.date():
            for point in time_points:
                checkpoint = datetime.combine(current_date, point)
                if not self.is_trading_day(checkpoint):
                    continue
                if not self.is_trading_hour(checkpoint):
                    continue
                if start_datetime <= checkpoint <= end_datetime:
                    points.append(checkpoint)
            current_date += timedelta(days=1)
        return sorted(points)

    def is_trading_day(self, dt: datetime, market: str = "CN") -> bool:
        if self.skip_weekends and dt.weekday() >= 5:
            return False
        normalized_market = str(market or "CN").upper()
        if self.skip_holidays and normalized_market == "CN" and HAS_CHINESE_CALENDAR:
            return bool(chinese_calendar.is_workday(dt.date()))
        return True

    def is_trading_hour(self, dt: datetime, market: str = "CN") -> bool:
        normalized_market = str(market or "CN").upper()
        current = dt.time()
        for start, end in self.MARKET_TRADING_HOURS.get(normalized_market, self.MARKET_TRADING_HOURS["CN"]):
            if start <= end:
                if start <= current <= end:
                    return True
            elif current >= start or current <= end:
                return True
        return False

    def is_trading_time(self, dt: datetime, market: str = "CN") -> bool:
        return self.is_trading_day(dt, market=market) and self.is_trading_hour(dt, market=market)

    def next_trading_day(self, value: date | datetime, market: str = "CN") -> date:
        current_date = value.date() if isinstance(value, datetime) else value
        next_date = current_date + timedelta(days=1)
        while not self.is_trading_day(datetime.combine(next_date, self.DAILY_POINT), market=market):
            next_date += timedelta(days=1)
        return next_date
