"""Lightweight data models for quant simulation."""

from dataclasses import dataclass


@dataclass
class QuantDecision:
    """Normalized strategy output used by the quant simulation pipeline."""

    action: str
    confidence: int
    reasoning: str
    position_size_pct: float = 0.0
    stop_loss_pct: float = 5.0
    take_profit_pct: float = 12.0
    tech_score: float = 0.0
    context_score: float = 0.0
