"""Artifact-backed BUY/SELL signal outcome scoring.

Outcome scoring is intentionally delayed until a configured horizon has fully
matured. The service only reads ``market_technical_artifact`` rows from the
signal's own domain/run scope; it must not fall back to current live quotes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from app.quant_sim.db import QuantSimDB
from app.quant_sim.market_technical_artifact import (
    MarketTechnicalArtifact,
    MarketTechnicalArtifactData,
)
from app.quant_sim.market_technical_artifact_store import MarketTechnicalArtifactStore
from app.quant_sim.signal_outcome_policy import (
    DEFAULT_OUTCOME_HORIZONS,
    OUTCOME_POLICY_PROFILE_DEFAULTS,
    normalize_signal_outcome_policy,
)
from app.quant_sim.time_utils import format_local_time


logger = logging.getLogger(__name__)

SCORING_VERSION = "signal_outcome_v1"


@dataclass(frozen=True)
class OutcomeRunScope:
    run_id: int
    run_type: str
    domain: str


@dataclass(frozen=True)
class OutcomeScoringRequest:
    signal: dict[str, Any]
    policy: dict[str, Any] | None = None
    run_scope: OutcomeRunScope | None = None
    as_of_checkpoint: str | None = None
    persist: bool = True
    trace_id: str = "NO_TRACE"


@dataclass(frozen=True)
class OutcomeScoreResult:
    signal_id: int
    horizon_checkpoints: int
    status: str
    reason_code: str
    record: dict[str, Any]


@dataclass(frozen=True)
class _PriceWindow:
    source_price: float
    source_checkpoint_at: str
    matured_at: str
    highs: list[float] = field(default_factory=list)
    lows: list[float] = field(default_factory=list)
    closes: list[float] = field(default_factory=list)
    ma20_values: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class _HorizonContext:
    request: OutcomeScoringRequest
    policy: dict[str, Any]
    action: str
    artifact_ref: str | None
    horizon: int


@dataclass(frozen=True)
class _OutcomeRecordContext:
    signal: dict[str, Any]
    scope: OutcomeRunScope | None
    horizon: int
    source: MarketTechnicalArtifact | None
    matured_at: str | None
    status: str
    reason_code: str
    score: float
    metrics: dict[str, Any]
    formula: dict[str, Any]


class SignalOutcomeScoringService:
    """Calculate and persist matured signal outcomes from artifact windows."""

    def __init__(self, db: QuantSimDB, artifact_store: MarketTechnicalArtifactStore):
        self.db = db
        self.artifact_store = artifact_store

    def score_signal(self, request: OutcomeScoringRequest) -> list[OutcomeScoreResult]:
        signal = request.signal
        policy = normalize_signal_outcome_policy(
            request.policy,
            profile_id=_profile_id(signal),
        )
        signal_id = _signal_id(signal)
        action = str(signal.get("action") or "HOLD").upper()
        artifact_ref = _extract_artifact_ref(signal)
        logger.info(
            "signal_outcome_scoring_started",
            extra={
                "trace_id": request.trace_id,
                "run_id": request.run_scope.run_id if request.run_scope else None,
                "run_type": request.run_scope.run_type if request.run_scope else None,
                "signal_id": signal_id,
                "stock_code": signal.get("stock_code"),
                "scoring_version": SCORING_VERSION,
            },
        )
        results = [
            self._score_horizon(_HorizonContext(request, policy, action, artifact_ref, int(horizon)))
            for horizon in policy["outcome_horizons_checkpoints"]
        ]
        logger.info(
            "signal_outcome_scoring_completed",
            extra={
                "trace_id": request.trace_id,
                "run_id": request.run_scope.run_id if request.run_scope else None,
                "run_type": request.run_scope.run_type if request.run_scope else None,
                "signal_id": signal_id,
                "stock_code": signal.get("stock_code"),
                "scoring_version": SCORING_VERSION,
                "outcome_count": len(results),
            },
        )
        return results

    def _score_horizon(self, context: _HorizonContext) -> OutcomeScoreResult:
        request = context.request
        signal = request.signal
        window = self.artifact_store.future_window_by_ref(
            context.artifact_ref,
            horizon_checkpoints=context.horizon,
            as_of_checkpoint=context.request.as_of_checkpoint,
        )
        if not context.artifact_ref:
            record = self._skipped_record(context, "missing_artifact_reference")
        elif window.source is None:
            record = self._skipped_record(context, window.reason_code)
        elif not window.mature:
            record = self._skipped_record(
                context,
                "horizon_not_mature",
                source=window.source,
            )
        elif context.action == "BUY":
            record = self._buy_record(context, window.source, window.window)
        elif context.action == "SELL":
            record = self._sell_record(context, window.source, window.window)
        else:
            record = self._skipped_record(context, "unsupported_action", source=window.source)

        if request.persist:
            if request.run_scope:
                self.db.upsert_sim_run_signal_outcome_score(record)
            else:
                self.db.upsert_signal_outcome_score(record)
        if record["status"] != "mature":
            logger.info(
                "signal_outcome_scoring_skipped",
                extra={
                    "trace_id": request.trace_id,
                    "run_id": request.run_scope.run_id if request.run_scope else None,
                    "run_type": request.run_scope.run_type if request.run_scope else None,
                    "signal_id": _signal_id(signal),
                    "stock_code": signal.get("stock_code"),
                    "horizon_key": context.horizon,
                    "matured_at": record.get("matured_at"),
                    "scoring_version": SCORING_VERSION,
                    "reason_code": record["reason_code"],
                },
            )
        return OutcomeScoreResult(
            signal_id=_signal_id(signal),
            horizon_checkpoints=context.horizon,
            status=record["status"],
            reason_code=record["reason_code"],
            record=record,
        )

    def _buy_record(
        self,
        context: _HorizonContext,
        source: MarketTechnicalArtifact,
        artifacts: list[MarketTechnicalArtifact],
    ) -> dict[str, Any]:
        prices = _price_window(source, artifacts)
        if prices is None:
            return self._skipped_record(context, "incomplete_artifact", source=source)
        mfe_pct = (max(prices.highs) / prices.source_price - 1.0) * 100.0
        mae_pct = (min(prices.lows) / prices.source_price - 1.0) * 100.0
        final_return_pct = (prices.closes[-1] / prices.source_price - 1.0) * 100.0
        first_return_pct = (prices.closes[0] / prices.source_price - 1.0) * 100.0
        target_hit = mfe_pct >= float(context.policy["buy_target_pct"])
        invalidation_hit = mae_pct <= float(context.policy["buy_invalidation_mae_pct"])
        ma20_break = any(close < ma20 for close, ma20 in zip(prices.closes, prices.ma20_values) if ma20 > 0)
        t1_loss_amplified = first_return_pct <= float(context.policy["buy_invalidation_mae_pct"]) * 0.5
        delay_cost_pct = max(0.0, first_return_pct)
        market_alignment = "aligned" if final_return_pct >= 0 else "against"
        raw_score = (
            50.0
            + min(25.0, max(0.0, mfe_pct) / float(context.policy["buy_target_pct"]) * 25.0)
            - min(25.0, abs(min(0.0, mae_pct)) / abs(float(context.policy["buy_invalidation_mae_pct"])) * 25.0)
            + (10.0 if target_hit else 0.0)
            - (20.0 if invalidation_hit else 0.0)
            - (10.0 if ma20_break else 0.0)
            - (8.0 if t1_loss_amplified else 0.0)
            - min(10.0, delay_cost_pct * 2.0)
            + (5.0 if market_alignment == "aligned" else -5.0)
        )
        metrics = {
            "mfe_pct": round(mfe_pct, 4),
            "mae_pct": round(mae_pct, 4),
            "target_hit": target_hit,
            "invalidation_hit": invalidation_hit,
            "ma20_break_after_buy": ma20_break,
            "t1_loss_amplified": t1_loss_amplified,
            "delay_cost_pct": round(delay_cost_pct, 4),
            "market_alignment": market_alignment,
            "final_return_pct": round(final_return_pct, 4),
        }
        return self._base_record(_OutcomeRecordContext(
            signal=context.request.signal,
            scope=context.request.run_scope,
            horizon=context.horizon,
            source=source,
            matured_at=prices.matured_at,
            status="mature",
            reason_code="ok",
            score=_clamp(raw_score, 0.0, 100.0),
            metrics=metrics,
            formula=_formula("BUY", context.policy, metrics),
        ))

    def _sell_record(
        self,
        context: _HorizonContext,
        source: MarketTechnicalArtifact,
        artifacts: list[MarketTechnicalArtifact],
    ) -> dict[str, Any]:
        prices = _price_window(source, artifacts)
        if prices is None:
            return self._skipped_record(context, "incomplete_artifact", source=source)
        avoided_drawdown_pct = (prices.source_price / min(prices.lows) - 1.0) * 100.0 if min(prices.lows) > 0 else 0.0
        missed_upside_pct = (max(prices.highs) / prices.source_price - 1.0) * 100.0
        final_return_pct = (prices.closes[-1] / prices.source_price - 1.0) * 100.0
        target_hit = avoided_drawdown_pct >= float(context.policy["sell_validation_drawdown_pct"])
        sell_validated = target_hit or final_return_pct <= 0
        quick_rebuy_after_sell = missed_upside_pct >= float(context.policy["missed_upside_penalty_pct"]) and final_return_pct > 0
        market_alignment = "aligned" if final_return_pct <= 0 else "against"
        raw_score = (
            50.0
            + min(25.0, max(0.0, avoided_drawdown_pct) / float(context.policy["sell_validation_drawdown_pct"]) * 25.0)
            - min(20.0, max(0.0, missed_upside_pct) / float(context.policy["missed_upside_penalty_pct"]) * 20.0)
            + (10.0 if target_hit else 0.0)
            + (5.0 if sell_validated else -5.0)
            - (15.0 if quick_rebuy_after_sell else 0.0)
            + (5.0 if market_alignment == "aligned" else -5.0)
        )
        metrics = {
            "avoided_drawdown_pct": round(avoided_drawdown_pct, 4),
            "missed_upside_pct": round(missed_upside_pct, 4),
            "target_hit": target_hit,
            "sell_validated": sell_validated,
            "quick_rebuy_after_sell": quick_rebuy_after_sell,
            "market_alignment": market_alignment,
            "final_return_pct": round(final_return_pct, 4),
            "sell_intent": _sell_intent(context.request.signal),
        }
        return self._base_record(_OutcomeRecordContext(
            signal=context.request.signal,
            scope=context.request.run_scope,
            horizon=context.horizon,
            source=source,
            matured_at=prices.matured_at,
            status="mature",
            reason_code="ok",
            score=_clamp(raw_score, 0.0, 100.0),
            metrics=metrics,
            formula=_formula("SELL", context.policy, metrics),
        ))

    def _skipped_record(
        self,
        context: _HorizonContext,
        reason_code: str,
        *,
        source: MarketTechnicalArtifact | None = None,
    ) -> dict[str, Any]:
        return self._base_record(_OutcomeRecordContext(
            signal=context.request.signal,
            scope=context.request.run_scope,
            horizon=context.horizon,
            source=source,
            matured_at=None,
            status="skipped",
            reason_code=reason_code,
            score=0.0,
            metrics={"reason_code": reason_code},
            formula={"scoring_version": SCORING_VERSION, "reason_code": reason_code},
        ))

    def _base_record(self, context: _OutcomeRecordContext) -> dict[str, Any]:
        record = {
            "domain": context.scope.domain if context.scope else "live",
            "signal_id": _signal_id(context.signal),
            "stock_code": str(context.signal.get("stock_code") or "").strip(),
            "action": str(context.signal.get("action") or "HOLD").upper(),
            "horizon_checkpoints": context.horizon,
            "signal_checkpoint_at": _signal_checkpoint_at(context.signal, context.source),
            "matured_at": context.matured_at,
            "source_artifact_ref": context.source.artifact_ref if context.source else _extract_artifact_ref(context.signal),
            "outcome_score": round(context.score, 4),
            "status": context.status,
            "reason_code": context.reason_code,
            "metrics": context.metrics,
            "formula": context.formula,
            "updated_at": format_local_time(),
        }
        if context.scope:
            record["run_id"] = context.scope.run_id
            record["run_type"] = context.scope.run_type
        return record


def _price_window(
    source: MarketTechnicalArtifact,
    artifacts: list[MarketTechnicalArtifact],
) -> _PriceWindow | None:
    source_price = _price(source.data)
    if source_price is None or source_price <= 0 or not artifacts:
        return None
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    ma20_values: list[float] = []
    for artifact in artifacts:
        close = _price(artifact.data)
        high = _float_or_none(artifact.data.high) or close
        low = _float_or_none(artifact.data.low) or close
        ma20 = _float_or_none(artifact.data.ma20) or 0.0
        if close is None or high is None or low is None:
            return None
        highs.append(max(high, close))
        lows.append(min(low, close))
        closes.append(close)
        ma20_values.append(ma20)
    return _PriceWindow(
        source_price=source_price,
        source_checkpoint_at=source.ref.checkpoint_at,
        matured_at=artifacts[-1].ref.checkpoint_at,
        highs=highs,
        lows=lows,
        closes=closes,
        ma20_values=ma20_values,
    )


def _formula(action: str, policy: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "scoring_version": SCORING_VERSION,
        "action": action,
        "policy": {
            "buy_target_pct": policy.get("buy_target_pct"),
            "buy_invalidation_mae_pct": policy.get("buy_invalidation_mae_pct"),
            "sell_validation_drawdown_pct": policy.get("sell_validation_drawdown_pct"),
            "missed_upside_penalty_pct": policy.get("missed_upside_penalty_pct"),
        },
        "metrics_used": metrics,
    }


def _extract_artifact_ref(signal: dict[str, Any]) -> str | None:
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    explainability = profile.get("explainability") if isinstance(profile.get("explainability"), dict) else {}
    for payload in (
        profile.get("market_snapshot") if isinstance(profile.get("market_snapshot"), dict) else {},
        explainability.get("market_snapshot") if isinstance(explainability.get("market_snapshot"), dict) else {},
        profile,
        signal.get("market_snapshot") if isinstance(signal.get("market_snapshot"), dict) else {},
        signal,
    ):
        artifact_ref = str(payload.get("artifact_ref") or "").strip() if isinstance(payload, dict) else ""
        if artifact_ref:
            return artifact_ref
    diagnostics = signal.get("execution_diagnostics")
    if isinstance(diagnostics, dict) and diagnostics.get("artifact_ref"):
        return str(diagnostics["artifact_ref"]).strip()
    return None


def _signal_checkpoint_at(signal: dict[str, Any], source: MarketTechnicalArtifact | None) -> str | None:
    if source:
        return source.ref.checkpoint_at
    value = signal.get("checkpoint_at") or signal.get("decision_time") or signal.get("created_at")
    return str(value) if value else None


def _signal_id(signal: dict[str, Any]) -> int:
    return int(signal.get("id") or signal.get("signal_id") or signal.get("source_signal_id") or 0)


def _profile_id(signal: dict[str, Any]) -> str | None:
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    selected = profile.get("selected_strategy_profile") if isinstance(profile.get("selected_strategy_profile"), dict) else {}
    return (
        str(selected.get("id") or "").strip()
        or str(profile.get("strategy_profile_id") or profile.get("profile_id") or "").strip()
        or None
    )


def _sell_intent(signal: dict[str, Any]) -> str:
    decision_type = str(signal.get("decision_type") or "").strip()
    if decision_type:
        return decision_type
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    return str(profile.get("execution_intent") or "unknown")


def _price(data: MarketTechnicalArtifactData) -> float | None:
    return _float_or_none(data.latest_price) or _float_or_none(data.close)


def _float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any, default: float) -> float:
    parsed = _float_or_none(value)
    return default if parsed is None else parsed


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
