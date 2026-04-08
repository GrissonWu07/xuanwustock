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
        return self.signal_center.create_signal(candidate, decision)

    def analyze_active_candidates(self) -> list[dict]:
        signals = []
        for candidate in self.candidate_pool.list_candidates(status="active"):
            signals.append(self.analyze_candidate(candidate))
        return signals
