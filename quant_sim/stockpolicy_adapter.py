"""Thin adapter that binds main-project providers to the reusable quant kernel."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from quant_kernel import KernelStrategyRuntime
from quant_kernel.interfaces import MarketDataProvider
from quant_kernel.models import Decision
from smart_monitor_tdx_data import SmartMonitorTDXDataFetcher


class MainProjectMarketDataProvider:
    """Market-data provider backed by the main project's TDX fetcher."""

    def __init__(self, data_fetcher: Optional[SmartMonitorTDXDataFetcher] = None):
        self.data_fetcher = data_fetcher or SmartMonitorTDXDataFetcher()

    def get_comprehensive_data(self, stock_code: str, preferred_name: str | None = None) -> dict[str, Any] | None:
        return self.data_fetcher.get_comprehensive_data(stock_code, preferred_name=preferred_name)


class StockPolicyAdapter:
    """Bridge main-project candidates/positions into the reusable quant kernel."""

    def __init__(
        self,
        data_fetcher: Optional[SmartMonitorTDXDataFetcher] = None,
        market_data_provider: Optional[MarketDataProvider] = None,
        runtime: Optional[KernelStrategyRuntime] = None,
    ):
        if market_data_provider is not None:
            self.market_data_provider = market_data_provider
        else:
            self.market_data_provider = MainProjectMarketDataProvider(data_fetcher)
        self.runtime = runtime or KernelStrategyRuntime()

    @staticmethod
    def now() -> datetime:
        return datetime.now()

    def analyze_candidate(
        self,
        candidate: dict[str, Any],
        market_snapshot: Optional[dict[str, Any]] = None,
        analysis_timeframe: str = "1d",
        strategy_mode: str = "auto",
    ) -> Decision:
        preferred_name = candidate.get("stock_name") or candidate.get("name")
        snapshot = market_snapshot or self.market_data_provider.get_comprehensive_data(
            candidate["stock_code"],
            preferred_name=preferred_name,
        )
        try:
            return self.runtime.evaluate_candidate(
                candidate=candidate,
                market_snapshot=snapshot,
                current_time=self.now(),
                analysis_timeframe=analysis_timeframe,
                strategy_mode=strategy_mode,
            )
        except TypeError as exc:
            first_message = str(exc)
            if "strategy_mode" not in first_message and "analysis_timeframe" not in first_message:
                raise
            try:
                return self.runtime.evaluate_candidate(
                    candidate=candidate,
                    market_snapshot=snapshot,
                    current_time=self.now(),
                    analysis_timeframe=analysis_timeframe,
                )
            except TypeError as retry_exc:
                if "analysis_timeframe" not in str(retry_exc):
                    raise
                return self.runtime.evaluate_candidate(
                    candidate=candidate,
                    market_snapshot=snapshot,
                    current_time=self.now(),
                )

    def analyze_position(
        self,
        candidate: dict[str, Any],
        position: dict[str, Any],
        market_snapshot: Optional[dict[str, Any]] = None,
        analysis_timeframe: str = "1d",
        strategy_mode: str = "auto",
    ) -> Decision:
        preferred_name = position.get("stock_name") or candidate.get("stock_name") or candidate.get("name")
        snapshot = market_snapshot or self.market_data_provider.get_comprehensive_data(
            position["stock_code"],
            preferred_name=preferred_name,
        )
        try:
            return self.runtime.evaluate_position(
                candidate=candidate,
                position=position,
                market_snapshot=snapshot,
                current_time=self.now(),
                analysis_timeframe=analysis_timeframe,
                strategy_mode=strategy_mode,
            )
        except TypeError as exc:
            first_message = str(exc)
            if "strategy_mode" not in first_message and "analysis_timeframe" not in first_message:
                raise
            try:
                return self.runtime.evaluate_position(
                    candidate=candidate,
                    position=position,
                    market_snapshot=snapshot,
                    current_time=self.now(),
                    analysis_timeframe=analysis_timeframe,
                )
            except TypeError as retry_exc:
                if "analysis_timeframe" not in str(retry_exc):
                    raise
                return self.runtime.evaluate_position(
                    candidate=candidate,
                    position=position,
                    market_snapshot=snapshot,
                    current_time=self.now(),
                )
