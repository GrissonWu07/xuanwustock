"""Strategy orchestration for quant simulation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.db import DEFAULT_DB_FILE
from app.quant_sim.dynamic_strategy import (
    DEFAULT_AI_DYNAMIC_LOOKBACK,
    DEFAULT_AI_DYNAMIC_STRENGTH,
    DEFAULT_AI_DYNAMIC_STRATEGY,
    DynamicStrategyController,
)
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.signal_center_service import SignalCenterService
from app.quant_sim.stockpolicy_adapter import StockPolicyAdapter
from app.runtime_paths import default_db_path
from app.watchlist_service import WatchlistService


DEFAULT_WATCHLIST_DB_FILE = str(default_db_path("watchlist.db"))


class QuantSimEngine:
    """Analyze candidates and persist normalized signals."""

    def __init__(
        self,
        db_file: str | Path = DEFAULT_DB_FILE,
        adapter: Optional[StockPolicyAdapter] = None,
        watchlist_db_file: str | Path = DEFAULT_WATCHLIST_DB_FILE,
        watchlist_service: WatchlistService | None = None,
    ):
        self.db_file = db_file
        self.candidate_pool = CandidatePoolService(db_file=db_file)
        self.signal_center = SignalCenterService(db_file=db_file)
        self.portfolio = PortfolioService(db_file=db_file)
        self.adapter = adapter or StockPolicyAdapter()
        self.watchlist = watchlist_service or WatchlistService(db_file=watchlist_db_file)
        self.dynamic_strategy = DynamicStrategyController(db_file=db_file)

    def analyze_candidate(
        self,
        candidate: dict,
        analysis_timeframe: str = "1d",
        strategy_mode: str = "auto",
        strategy_profile_id: str | None = None,
        strategy_profile_binding: dict | None = None,
        ai_dynamic_strategy: str | None = None,
        ai_dynamic_strength: float | None = None,
        ai_dynamic_lookback: int | None = None,
    ) -> dict:
        profile_binding = (
            dict(strategy_profile_binding)
            if isinstance(strategy_profile_binding, dict)
            else self._resolve_strategy_binding(
                strategy_profile_id=strategy_profile_id,
                ai_dynamic_strategy=ai_dynamic_strategy,
                ai_dynamic_strength=ai_dynamic_strength,
                ai_dynamic_lookback=ai_dynamic_lookback,
                stock_code=str(candidate.get("stock_code") or ""),
                stock_name=str(candidate.get("stock_name") or ""),
            )
        )
        decision = self._evaluate_candidate_decision(
            candidate,
            analysis_timeframe=analysis_timeframe,
            strategy_mode=strategy_mode,
            strategy_profile_binding=profile_binding,
        )
        decision_price = self._extract_decision_price(decision)
        if decision_price > 0:
            self.candidate_pool.db.update_candidate_latest_price(candidate["stock_code"], decision_price)
        signal = self.signal_center.create_signal(candidate, decision)
        self._sync_watchlist_snapshot(candidate["stock_code"], signal, decision_price)
        return signal

    def analyze_active_candidates(
        self,
        analysis_timeframe: str = "1d",
        strategy_mode: str = "auto",
        strategy_profile_id: str | None = None,
        ai_dynamic_strategy: str | None = None,
        ai_dynamic_strength: float | None = None,
        ai_dynamic_lookback: int | None = None,
        exclude_codes: set[str] | None = None,
    ) -> list[dict]:
        dynamic_mode = (
            str(ai_dynamic_strategy).strip().lower()
            if ai_dynamic_strategy is not None
            else DEFAULT_AI_DYNAMIC_STRATEGY
        )
        profile_binding = None
        if dynamic_mode == DEFAULT_AI_DYNAMIC_STRATEGY:
            profile_binding = self._resolve_strategy_binding(
                strategy_profile_id=strategy_profile_id,
                ai_dynamic_strategy=ai_dynamic_strategy,
                ai_dynamic_strength=ai_dynamic_strength,
                ai_dynamic_lookback=ai_dynamic_lookback,
            )
        signals = []
        blocked = {str(code).strip() for code in (exclude_codes or set()) if str(code).strip()}
        for candidate in self.candidate_pool.list_candidates(status="active"):
            code = str(candidate.get("stock_code") or "").strip()
            if code and code in blocked:
                continue
            candidate_kwargs = {
                "analysis_timeframe": analysis_timeframe,
                "strategy_mode": strategy_mode,
            }
            if dynamic_mode == DEFAULT_AI_DYNAMIC_STRATEGY:
                candidate_kwargs["strategy_profile_binding"] = profile_binding
            else:
                candidate_kwargs["strategy_profile_id"] = strategy_profile_id
                candidate_kwargs["ai_dynamic_strategy"] = ai_dynamic_strategy
                candidate_kwargs["ai_dynamic_strength"] = ai_dynamic_strength
                candidate_kwargs["ai_dynamic_lookback"] = ai_dynamic_lookback
            signals.append(self.analyze_candidate(candidate, **candidate_kwargs))
        return signals

    def analyze_positions(
        self,
        analysis_timeframe: str = "1d",
        strategy_mode: str = "auto",
        strategy_profile_id: str | None = None,
        ai_dynamic_strategy: str | None = None,
        ai_dynamic_strength: float | None = None,
        ai_dynamic_lookback: int | None = None,
    ) -> list[dict]:
        dynamic_mode = (
            str(ai_dynamic_strategy).strip().lower()
            if ai_dynamic_strategy is not None
            else DEFAULT_AI_DYNAMIC_STRATEGY
        )
        profile_binding = None
        if dynamic_mode == DEFAULT_AI_DYNAMIC_STRATEGY:
            profile_binding = self._resolve_strategy_binding(
                strategy_profile_id=strategy_profile_id,
                ai_dynamic_strategy=ai_dynamic_strategy,
                ai_dynamic_strength=ai_dynamic_strength,
                ai_dynamic_lookback=ai_dynamic_lookback,
            )
        signals = []
        for position in self.portfolio.list_positions():
            candidate = self.candidate_pool.db.get_candidate(position["stock_code"]) or {
                "stock_code": position["stock_code"],
                "stock_name": position.get("stock_name"),
                "source": "manual",
                "sources": ["manual"],
            }
            effective_binding = profile_binding
            if dynamic_mode != DEFAULT_AI_DYNAMIC_STRATEGY:
                effective_binding = self._resolve_strategy_binding(
                    strategy_profile_id=strategy_profile_id,
                    ai_dynamic_strategy=ai_dynamic_strategy,
                    ai_dynamic_strength=ai_dynamic_strength,
                    ai_dynamic_lookback=ai_dynamic_lookback,
                    stock_code=str(candidate.get("stock_code") or ""),
                    stock_name=str(candidate.get("stock_name") or position.get("stock_name") or ""),
                )
            decision = self._evaluate_position_decision(
                candidate,
                position,
                analysis_timeframe=analysis_timeframe,
                strategy_mode=strategy_mode,
                strategy_profile_binding=effective_binding,
            )
            decision_price = self._extract_decision_price(decision)
            if decision_price > 0:
                self.portfolio.db.update_position_market_price(position["stock_code"], decision_price)
                self.candidate_pool.db.update_candidate_latest_price(position["stock_code"], decision_price)
            signal = self.signal_center.create_signal(candidate, decision)
            self._sync_watchlist_snapshot(position["stock_code"], signal, decision_price)
            signals.append(signal)
        return signals

    def _resolve_strategy_binding(
        self,
        *,
        strategy_profile_id: str | None,
        ai_dynamic_strategy: str | None = None,
        ai_dynamic_strength: float | None = None,
        ai_dynamic_lookback: int | None = None,
        stock_code: str | None = None,
        stock_name: str | None = None,
    ) -> dict[str, Any]:
        base_binding = self.candidate_pool.db.resolve_strategy_profile_binding(strategy_profile_id)
        mode = (
            str(ai_dynamic_strategy).strip().lower()
            if ai_dynamic_strategy is not None
            else DEFAULT_AI_DYNAMIC_STRATEGY
        )
        if mode == DEFAULT_AI_DYNAMIC_STRATEGY:
            return base_binding
        return self.dynamic_strategy.resolve_binding(
            base_binding=base_binding,
            stock_code=stock_code,
            stock_name=stock_name,
            ai_dynamic_strategy=mode,
            ai_dynamic_strength=ai_dynamic_strength
            if ai_dynamic_strength is not None
            else DEFAULT_AI_DYNAMIC_STRENGTH,
            ai_dynamic_lookback=ai_dynamic_lookback
            if ai_dynamic_lookback is not None
            else DEFAULT_AI_DYNAMIC_LOOKBACK,
        )

    def _evaluate_candidate_decision(
        self,
        candidate: dict,
        *,
        market_snapshot: dict | None = None,
        analysis_timeframe: str = "1d",
        strategy_mode: str = "auto",
        strategy_profile_binding: dict | None = None,
    ):
        attempts = [
            {
                "market_snapshot": market_snapshot,
                "analysis_timeframe": analysis_timeframe,
                "strategy_mode": strategy_mode,
                "strategy_profile_binding": strategy_profile_binding,
            },
            {
                "market_snapshot": market_snapshot,
                "analysis_timeframe": analysis_timeframe,
                "strategy_mode": strategy_mode,
            },
            {
                "market_snapshot": market_snapshot,
                "analysis_timeframe": analysis_timeframe,
                "strategy_profile_binding": strategy_profile_binding,
            },
            {
                "market_snapshot": market_snapshot,
                "analysis_timeframe": analysis_timeframe,
            },
            {
                "market_snapshot": market_snapshot,
            },
            {},
        ]
        last_error: TypeError | None = None
        for kwargs in attempts:
            kwargs = {key: value for key, value in kwargs.items() if value is not None}
            try:
                return self.adapter.analyze_candidate(candidate, **kwargs)
            except TypeError as exc:
                message = str(exc)
                if "unexpected keyword argument" not in message:
                    raise
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        return self.adapter.analyze_candidate(candidate)

    def _evaluate_position_decision(
        self,
        candidate: dict,
        position: dict,
        *,
        market_snapshot: dict | None = None,
        analysis_timeframe: str = "1d",
        strategy_mode: str = "auto",
        strategy_profile_binding: dict | None = None,
    ):
        attempts = [
            {
                "market_snapshot": market_snapshot,
                "analysis_timeframe": analysis_timeframe,
                "strategy_mode": strategy_mode,
                "strategy_profile_binding": strategy_profile_binding,
            },
            {
                "market_snapshot": market_snapshot,
                "analysis_timeframe": analysis_timeframe,
                "strategy_mode": strategy_mode,
            },
            {
                "market_snapshot": market_snapshot,
                "analysis_timeframe": analysis_timeframe,
                "strategy_profile_binding": strategy_profile_binding,
            },
            {
                "market_snapshot": market_snapshot,
                "analysis_timeframe": analysis_timeframe,
            },
            {
                "market_snapshot": market_snapshot,
            },
            {},
        ]
        last_error: TypeError | None = None
        for kwargs in attempts:
            kwargs = {key: value for key, value in kwargs.items() if value is not None}
            try:
                return self.adapter.analyze_position(candidate, position, **kwargs)
            except TypeError as exc:
                message = str(exc)
                if "unexpected keyword argument" not in message:
                    raise
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        return self.adapter.analyze_position(candidate, position)

    @staticmethod
    def _extract_decision_price(decision: dict | object) -> float:
        if hasattr(decision, "price"):
            try:
                return float(getattr(decision, "price") or 0)
            except (TypeError, ValueError):
                return 0.0
        if isinstance(decision, dict):
            try:
                return float(decision.get("price") or 0)
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    def _sync_watchlist_snapshot(self, stock_code: str, signal: dict, decision_price: float) -> None:
        if not stock_code:
            return
        self.watchlist.update_watch_snapshot(
            stock_code,
            latest_signal=str(signal.get("action") or "").upper() or None,
            latest_price=decision_price if decision_price > 0 else None,
        )
