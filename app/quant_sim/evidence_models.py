"""Shared request objects for quant evidence and provenance builders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PreparedEvidenceInput:
    """Input for building a prepared discovery candidate evidence payload."""

    row: dict[str, Any]
    run_id: str = ""
    source_type: str = "discover"
    profile_id: str | None = None
    evaluated_at: str = ""


@dataclass(frozen=True)
class CandidateReevaluationRequest:
    """Input for refresh-triggered candidate lifecycle re-evaluation."""

    context: Any
    run_reason: str = "refresh"
    evaluated_at: str = ""


@dataclass(frozen=True)
class DecisionProvenanceInput:
    """Input for user-facing signal decision provenance."""

    decision: dict[str, Any]
    signal: dict[str, Any]
    strategy_profile: dict[str, Any]
    source: str
    technical_indicators: list[dict[str, Any]]
    replay_run: dict[str, Any] | None = None
