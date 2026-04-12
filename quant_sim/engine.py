"""Strategy orchestration for quant simulation."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from quant_sim.candidate_pool_service import CandidatePoolService
from quant_sim.db import DEFAULT_DB_FILE
from quant_sim.portfolio_service import PortfolioService
from quant_sim.signal_center_service import SignalCenterService
from quant_sim.stockpolicy_adapter import StockPolicyAdapter
from watchlist_service import WatchlistService


class QuantSimEngine:
    """Analyze candidates and persist normalized signals."""

    def __init__(
        self,
        db_file: str | Path = DEFAULT_DB_FILE,
        adapter: Optional[StockPolicyAdapter] = None,
        watchlist_db_file: str | Path = "watchlist.db",
        watchlist_service: WatchlistService | None = None,
    ):
        self.db_file = db_file
        self.candidate_pool = CandidatePoolService(db_file=db_file)
        self.signal_center = SignalCenterService(db_file=db_file)
        self.portfolio = PortfolioService(db_file=db_file)
        self.adapter = adapter or StockPolicyAdapter()
        self.watchlist = watchlist_service or WatchlistService(db_file=watchlist_db_file)

    def analyze_candidate(self, candidate: dict, analysis_timeframe: str = "1d", strategy_mode: str = "auto") -> dict:
        decision = self._evaluate_candidate_decision(
            candidate,
            analysis_timeframe=analysis_timeframe,
            strategy_mode=strategy_mode,
        )
        decision_price = self._extract_decision_price(decision)
        if decision_price > 0:
            self.candidate_pool.db.update_candidate_latest_price(candidate["stock_code"], decision_price)
        signal = self.signal_center.create_signal(candidate, decision)
        self._sync_watchlist_snapshot(candidate["stock_code"], signal, decision_price)
        return signal

    def analyze_active_candidates(self, analysis_timeframe: str = "1d", strategy_mode: str = "auto") -> list[dict]:
        signals = []
        for candidate in self.candidate_pool.list_candidates(status="active"):
            signals.append(self.analyze_candidate(candidate, analysis_timeframe=analysis_timeframe, strategy_mode=strategy_mode))
        return signals

    def analyze_positions(self, analysis_timeframe: str = "1d", strategy_mode: str = "auto") -> list[dict]:
        signals = []
        for position in self.portfolio.list_positions():
            candidate = self.candidate_pool.db.get_candidate(position["stock_code"]) or {
                "stock_code": position["stock_code"],
                "stock_name": position.get("stock_name"),
                "source": "manual",
                "sources": ["manual"],
            }
            decision = self._evaluate_position_decision(
                candidate,
                position,
                analysis_timeframe=analysis_timeframe,
                strategy_mode=strategy_mode,
            )
            decision_price = self._extract_decision_price(decision)
            if decision_price > 0:
                self.portfolio.db.update_position_market_price(position["stock_code"], decision_price)
                self.candidate_pool.db.update_candidate_latest_price(position["stock_code"], decision_price)
            signal = self.signal_center.create_signal(candidate, decision)
            self._sync_watchlist_snapshot(position["stock_code"], signal, decision_price)
            signals.append(signal)
        return signals

    def _evaluate_candidate_decision(
        self,
        candidate: dict,
        *,
        market_snapshot: dict | None = None,
        analysis_timeframe: str = "1d",
        strategy_mode: str = "auto",
    ):
        try:
            return self.adapter.analyze_candidate(
                candidate,
                market_snapshot=market_snapshot,
                analysis_timeframe=analysis_timeframe,
                strategy_mode=strategy_mode,
            )
        except TypeError as exc:
            first_message = str(exc)
            if "analysis_timeframe" not in first_message and "strategy_mode" not in first_message:
                raise
            try:
                return self.adapter.analyze_candidate(
                    candidate,
                    market_snapshot=market_snapshot,
                    analysis_timeframe=analysis_timeframe,
                )
            except TypeError as retry_exc:
                retry_message = str(retry_exc)
                if "analysis_timeframe" not in retry_message:
                    raise
                return self.adapter.analyze_candidate(candidate, market_snapshot=market_snapshot)

    def _evaluate_position_decision(
        self,
        candidate: dict,
        position: dict,
        *,
        market_snapshot: dict | None = None,
        analysis_timeframe: str = "1d",
        strategy_mode: str = "auto",
    ):
        try:
            return self.adapter.analyze_position(
                candidate,
                position,
                market_snapshot=market_snapshot,
                analysis_timeframe=analysis_timeframe,
                strategy_mode=strategy_mode,
            )
        except TypeError as exc:
            first_message = str(exc)
            if "analysis_timeframe" not in first_message and "strategy_mode" not in first_message:
                raise
            try:
                return self.adapter.analyze_position(
                    candidate,
                    position,
                    market_snapshot=market_snapshot,
                    analysis_timeframe=analysis_timeframe,
                )
            except TypeError as retry_exc:
                retry_message = str(retry_exc)
                if "analysis_timeframe" not in retry_message:
                    raise
                return self.adapter.analyze_position(candidate, position, market_snapshot=market_snapshot)

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
