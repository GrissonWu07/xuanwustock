"""Thin adapter that binds main-project providers to the reusable quant kernel."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.quant_kernel import KernelStrategyRuntime
from app.quant_kernel.interfaces import MarketDataProvider
from app.quant_kernel.models import Decision
from app.smart_monitor_tdx_data import SmartMonitorTDXDataFetcher


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

    @staticmethod
    def _call_with_signature_fallback(method: Any, base_kwargs: dict[str, Any]) -> Decision:
        drop_orders = [
            (),
            ("strategy_profile_binding",),
            ("strategy_mode",),
            ("strategy_mode", "strategy_profile_binding"),
            ("analysis_timeframe",),
            ("analysis_timeframe", "strategy_profile_binding"),
            ("analysis_timeframe", "strategy_mode"),
            ("analysis_timeframe", "strategy_mode", "strategy_profile_binding"),
        ]
        last_error: TypeError | None = None
        for drop_keys in drop_orders:
            kwargs = {key: value for key, value in base_kwargs.items() if key not in drop_keys}
            try:
                return method(**kwargs)
            except TypeError as exc:
                message = str(exc)
                if "unexpected keyword argument" not in message:
                    raise
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        raise RuntimeError("Kernel runtime evaluate call failed")

    def analyze_candidate(
        self,
        candidate: dict[str, Any],
        market_snapshot: Optional[dict[str, Any]] = None,
        analysis_timeframe: str = "1d",
        strategy_mode: str = "auto",
        strategy_profile_binding: Optional[dict[str, Any]] = None,
    ) -> Decision:
        preferred_name = candidate.get("stock_name") or candidate.get("name")
        snapshot = market_snapshot or self.market_data_provider.get_comprehensive_data(
            candidate["stock_code"],
            preferred_name=preferred_name,
        )
        snapshot = self._merge_account_context(snapshot, candidate)
        return self._call_with_signature_fallback(
            self.runtime.evaluate_candidate,
            {
                "candidate": candidate,
                "market_snapshot": snapshot,
                "current_time": self.now(),
                "analysis_timeframe": analysis_timeframe,
                "strategy_mode": strategy_mode,
                "strategy_profile_binding": strategy_profile_binding,
            },
        )

    def analyze_position(
        self,
        candidate: dict[str, Any],
        position: dict[str, Any],
        market_snapshot: Optional[dict[str, Any]] = None,
        analysis_timeframe: str = "1d",
        strategy_mode: str = "auto",
        strategy_profile_binding: Optional[dict[str, Any]] = None,
    ) -> Decision:
        preferred_name = position.get("stock_name") or candidate.get("stock_name") or candidate.get("name")
        snapshot = market_snapshot or self.market_data_provider.get_comprehensive_data(
            position["stock_code"],
            preferred_name=preferred_name,
        )
        snapshot = self._merge_account_context(snapshot, position, candidate)
        return self._call_with_signature_fallback(
            self.runtime.evaluate_position,
            {
                "candidate": candidate,
                "position": position,
                "market_snapshot": snapshot,
                "current_time": self.now(),
                "analysis_timeframe": analysis_timeframe,
                "strategy_mode": strategy_mode,
                "strategy_profile_binding": strategy_profile_binding,
            },
        )

    @staticmethod
    def _merge_account_context(snapshot: Optional[dict[str, Any]], *payloads: dict[str, Any]) -> Optional[dict[str, Any]]:
        if snapshot is None:
            return None
        account_context: dict[str, Any] = {}
        stock_analysis_context: dict[str, Any] | None = None
        for payload in payloads:
            context = payload.get("_quant_account_context") if isinstance(payload, dict) else None
            if isinstance(context, dict) and context:
                account_context = context
            stock_context = payload.get("_quant_stock_analysis_context") if isinstance(payload, dict) else None
            if isinstance(stock_context, dict) and stock_context:
                stock_analysis_context = stock_context
        if not account_context and not stock_analysis_context:
            return snapshot

        merged = dict(snapshot)
        for key in ("available_cash", "total_equity", "cash_ratio", "position_count"):
            if key in account_context and key not in merged:
                merged[key] = account_context[key]
        if stock_analysis_context is not None and "stock_analysis_context" not in merged:
            merged["stock_analysis_context"] = stock_analysis_context
        return merged
