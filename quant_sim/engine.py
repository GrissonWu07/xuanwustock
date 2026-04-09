"""Strategy orchestration for quant simulation."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from quant_sim.candidate_pool_service import CandidatePoolService
from quant_sim.db import DEFAULT_DB_FILE
from quant_sim.portfolio_service import PortfolioService
from quant_sim.signal_center_service import SignalCenterService
from quant_sim.stockpolicy_adapter import StockPolicyAdapter


class QuantSimEngine:
    """Analyze candidates and persist normalized signals."""

    def __init__(
        self,
        db_file: str | Path = DEFAULT_DB_FILE,
        adapter: Optional[StockPolicyAdapter] = None,
    ):
        self.db_file = db_file
        self.candidate_pool = CandidatePoolService(db_file=db_file)
        self.signal_center = SignalCenterService(db_file=db_file)
        self.portfolio = PortfolioService(db_file=db_file)
        self.adapter = adapter or StockPolicyAdapter()

    def analyze_candidate(self, candidate: dict) -> dict:
        decision = self.adapter.analyze_candidate(candidate)
        decision_price = self._extract_decision_price(decision)
        if decision_price > 0:
            self.candidate_pool.db.update_candidate_latest_price(candidate["stock_code"], decision_price)
        return self.signal_center.create_signal(candidate, decision)

    def analyze_active_candidates(self) -> list[dict]:
        signals = []
        for candidate in self.candidate_pool.list_candidates(status="active"):
            signals.append(self.analyze_candidate(candidate))
        return signals

    def analyze_positions(self) -> list[dict]:
        signals = []
        for position in self.portfolio.list_positions():
            candidate = self.candidate_pool.db.get_candidate(position["stock_code"]) or {
                "stock_code": position["stock_code"],
                "stock_name": position.get("stock_name"),
                "source": "manual",
                "sources": ["manual"],
            }
            decision = self.adapter.analyze_position(candidate, position)
            decision_price = self._extract_decision_price(decision)
            if decision_price > 0:
                self.portfolio.db.update_position_market_price(position["stock_code"], decision_price)
            signals.append(self.signal_center.create_signal(candidate, decision))
        return signals

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
