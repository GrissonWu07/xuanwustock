"""Strategy orchestration for quant simulation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from typing import Any, Optional

from app.db.runtime.registry import DatabaseRuntime
from app.data.analysis_context import StockAnalysisContextRepository
from app.data.analysis_context.refresh import refresh_enabled_by_env, stock_analysis_refresh_queue
from app.quant_kernel.config import StrategyScoringConfig
from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.db import DEFAULT_DB_FILE
from app.quant_sim.dynamic_strategy import (
    DEFAULT_AI_DYNAMIC_LOOKBACK,
    DEFAULT_AI_DYNAMIC_STRENGTH,
    DEFAULT_AI_DYNAMIC_STRATEGY,
    DynamicStrategyController,
)
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.quant_universe_lifecycle import (
    QuantUniverseLifecyclePolicy,
    build_lifecycle_gate,
    is_recovery_probe_active,
)
from app.quant_sim.signal_center_service import SignalCenterService
from app.quant_sim.stockpolicy_adapter import StockPolicyAdapter
from app.watchlist_service import WatchlistService

LIVE_SCAN_QUANT_STATUSES = ("trial", "active", "exit_only")


class QuantSimEngine:
    """Analyze candidates and persist normalized signals."""

    def __init__(
        self,
        db_file: str | Path = DEFAULT_DB_FILE,
        adapter: Optional[StockPolicyAdapter] = None,
        watchlist_service: WatchlistService | None = None,
        stock_analysis_db_file: str | Path | None = None,
        stock_analysis_context_enabled: bool = True,
        stock_analysis_refresh_enabled: bool | None = None,
        db_runtime: DatabaseRuntime | None = None,
    ):
        self.db_file = db_file
        self.db_runtime = db_runtime
        self.stock_analysis_db_file = str(stock_analysis_db_file or db_file)
        self.candidate_pool = CandidatePoolService(db_file=db_file, db_runtime=db_runtime)
        self.signal_center = SignalCenterService(db_file=db_file, db_runtime=db_runtime)
        self.portfolio = PortfolioService(db_file=db_file, db_runtime=db_runtime)
        self.adapter = adapter or StockPolicyAdapter()
        self.watchlist = watchlist_service or WatchlistService(db_file=db_file, db_runtime=db_runtime)
        self.dynamic_strategy = DynamicStrategyController(db_file=db_file, db_runtime=db_runtime)
        self.stock_analysis_context_enabled = bool(stock_analysis_context_enabled)
        self.stock_analysis_refresh_enabled = refresh_enabled_by_env() if stock_analysis_refresh_enabled is None else bool(stock_analysis_refresh_enabled)
        self.stock_analysis_refresh_period = os.getenv("STOCK_ANALYSIS_REFRESH_PERIOD", "1y")
        self.stock_analysis_context = StockAnalysisContextRepository(
            db_path=self.stock_analysis_db_file,
            db_runtime=db_runtime,
        )

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
        current_time: datetime | None = None,
    ) -> dict:
        resolve_kwargs = {
            "strategy_profile_id": strategy_profile_id,
            "ai_dynamic_strategy": ai_dynamic_strategy,
            "ai_dynamic_strength": ai_dynamic_strength,
            "ai_dynamic_lookback": ai_dynamic_lookback,
            "stock_code": str(candidate.get("stock_code") or ""),
            "stock_name": str(candidate.get("stock_name") or ""),
        }
        if current_time is not None:
            resolve_kwargs["as_of"] = current_time
        profile_binding = (
            dict(strategy_profile_binding)
            if isinstance(strategy_profile_binding, dict)
            else self._resolve_strategy_binding(**resolve_kwargs)
        )
        decision = self._evaluate_candidate_decision(
            candidate,
            analysis_timeframe=analysis_timeframe,
            strategy_mode=strategy_mode,
            strategy_profile_binding=profile_binding,
            current_time=current_time,
        )
        decision_price = self._extract_decision_price(decision)
        if decision_price > 0:
            self.candidate_pool.db.update_candidate_latest_price(candidate["stock_code"], decision_price)
        signal = self.signal_center.create_signal(candidate, decision)
        self._sync_watchlist_snapshot(candidate["stock_code"], signal, decision_price)
        return signal

    def build_candidate_review_signal(
        self,
        candidate: dict,
        analysis_timeframe: str = "1d",
        strategy_mode: str = "auto",
        strategy_profile_id: str | None = None,
        strategy_profile_binding: dict | None = None,
        ai_dynamic_strategy: str | None = None,
        ai_dynamic_strength: float | None = None,
        ai_dynamic_lookback: int | None = None,
        current_time: datetime | None = None,
        market_snapshot: dict | None = None,
    ) -> dict[str, Any]:
        resolve_kwargs = {
            "strategy_profile_id": strategy_profile_id,
            "ai_dynamic_strategy": ai_dynamic_strategy,
            "ai_dynamic_strength": ai_dynamic_strength,
            "ai_dynamic_lookback": ai_dynamic_lookback,
            "stock_code": str(candidate.get("stock_code") or ""),
            "stock_name": str(candidate.get("stock_name") or ""),
        }
        if current_time is not None:
            resolve_kwargs["as_of"] = current_time
        profile_binding = (
            dict(strategy_profile_binding)
            if isinstance(strategy_profile_binding, dict)
            else self._resolve_strategy_binding(**resolve_kwargs)
        )
        decision = self._evaluate_candidate_decision(
            candidate,
            market_snapshot=market_snapshot,
            analysis_timeframe=analysis_timeframe,
            strategy_mode=strategy_mode,
            strategy_profile_binding=profile_binding,
            current_time=current_time,
        )
        payload = self.signal_center.build_signal_payload(candidate, decision)
        action = str(payload.get("action") or "HOLD").upper()
        return {
            "id": 0,
            "candidate_id": candidate.get("id"),
            "stock_code": candidate["stock_code"],
            "stock_name": candidate.get("stock_name"),
            "action": action,
            "confidence": int(payload.get("confidence", 0)),
            "reasoning": payload.get("reasoning", ""),
            "position_size_pct": float(payload.get("position_size_pct", 0)),
            "stop_loss_pct": float(payload.get("stop_loss_pct", 5)),
            "take_profit_pct": float(payload.get("take_profit_pct", 12)),
            "decision_type": payload.get("decision_type"),
            "tech_score": float(payload.get("tech_score", 0)),
            "context_score": float(payload.get("context_score", 0)),
            "strategy_profile": payload.get("strategy_profile"),
            "decision_time": self._format_review_decision_time(payload.get("decision_time") or current_time),
            "status": "review",
        }

    @staticmethod
    def _format_review_decision_time(value: Any) -> Any:
        if not isinstance(value, datetime):
            return value
        dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def analyze_active_candidates(
        self,
        analysis_timeframe: str = "1d",
        strategy_mode: str = "auto",
        strategy_profile_id: str | None = None,
        ai_dynamic_strategy: str | None = None,
        ai_dynamic_strength: float | None = None,
        ai_dynamic_lookback: int | None = None,
        exclude_codes: set[str] | None = None,
        candidates_override: list[dict[str, Any]] | None = None,
        current_time: datetime | None = None,
    ) -> list[dict]:
        dynamic_mode = (
            str(ai_dynamic_strategy).strip().lower()
            if ai_dynamic_strategy is not None
            else DEFAULT_AI_DYNAMIC_STRATEGY
        )
        profile_binding = None
        if dynamic_mode == DEFAULT_AI_DYNAMIC_STRATEGY:
            resolve_kwargs = {
                "strategy_profile_id": strategy_profile_id,
                "ai_dynamic_strategy": ai_dynamic_strategy,
                "ai_dynamic_strength": ai_dynamic_strength,
                "ai_dynamic_lookback": ai_dynamic_lookback,
            }
            if current_time is not None:
                resolve_kwargs["as_of"] = current_time
            profile_binding = self._resolve_strategy_binding(**resolve_kwargs)
        signals = []
        blocked = {str(code).strip() for code in (exclude_codes or set()) if str(code).strip()}
        scan_policy = self._quant_lifecycle_policy_from_binding(
            profile_binding if isinstance(profile_binding, dict) else {"profile_id": strategy_profile_id or ""}
        )
        selected_candidates = candidates_override if candidates_override is not None else self.list_live_scan_candidates(
            exclude_codes=blocked,
            policy=scan_policy,
        )
        for candidate in selected_candidates:
            code = str(candidate.get("stock_code") or "").strip()
            candidate_kwargs = {
                "analysis_timeframe": analysis_timeframe,
                "strategy_mode": strategy_mode,
            }
            if current_time is not None:
                candidate_kwargs["current_time"] = current_time
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
        current_time: datetime | None = None,
    ) -> list[dict]:
        dynamic_mode = (
            str(ai_dynamic_strategy).strip().lower()
            if ai_dynamic_strategy is not None
            else DEFAULT_AI_DYNAMIC_STRATEGY
        )
        profile_binding = None
        if dynamic_mode == DEFAULT_AI_DYNAMIC_STRATEGY:
            resolve_kwargs = {
                "strategy_profile_id": strategy_profile_id,
                "ai_dynamic_strategy": ai_dynamic_strategy,
                "ai_dynamic_strength": ai_dynamic_strength,
                "ai_dynamic_lookback": ai_dynamic_lookback,
            }
            if current_time is not None:
                resolve_kwargs["as_of"] = current_time
            profile_binding = self._resolve_strategy_binding(**resolve_kwargs)
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
                resolve_kwargs = {
                    "strategy_profile_id": strategy_profile_id,
                    "ai_dynamic_strategy": ai_dynamic_strategy,
                    "ai_dynamic_strength": ai_dynamic_strength,
                    "ai_dynamic_lookback": ai_dynamic_lookback,
                    "stock_code": str(candidate.get("stock_code") or ""),
                    "stock_name": str(candidate.get("stock_name") or position.get("stock_name") or ""),
                }
                if current_time is not None:
                    resolve_kwargs["as_of"] = current_time
                effective_binding = self._resolve_strategy_binding(**resolve_kwargs)
            decision = self._evaluate_position_decision(
                candidate,
                position,
                analysis_timeframe=analysis_timeframe,
                strategy_mode=strategy_mode,
                strategy_profile_binding=effective_binding,
                current_time=current_time,
            )
            decision_price = self._extract_decision_price(decision)
            if decision_price > 0:
                self.portfolio.db.update_position_market_price(position["stock_code"], decision_price)
                self.candidate_pool.db.update_candidate_latest_price(position["stock_code"], decision_price)
            signal = self.signal_center.create_signal(candidate, decision)
            self._sync_watchlist_snapshot(position["stock_code"], signal, decision_price)
            signals.append(signal)
        return signals

    def list_live_scan_candidates(
        self,
        *,
        exclude_codes: set[str] | None = None,
        policy: QuantUniverseLifecyclePolicy | None = None,
        as_of: datetime | str | None = None,
    ) -> list[dict[str, Any]]:
        lifecycle_policy = policy or QuantUniverseLifecyclePolicy.stable_defaults()
        blocked = {str(code).strip() for code in (exclude_codes or set()) if str(code).strip()}
        normal_candidates = self.candidate_pool.list_candidates(
            status="active",
            quant_statuses=LIVE_SCAN_QUANT_STATUSES,
        )
        normal_candidates = [
            self._with_lifecycle_gate(candidate, lifecycle_policy, as_of=as_of)
            for candidate in normal_candidates
            if str(candidate.get("stock_code") or "").strip() not in blocked
        ]
        normal_candidates.sort(key=self._normal_scan_sort_key)
        needed = max(0, int(lifecycle_policy.min_scan_coverage or 0) - len(normal_candidates))
        if needed <= 0:
            return normal_candidates

        cooling_candidates = self.candidate_pool.list_candidates(status="active", quant_statuses=("cooling",))
        cooling_candidates = [
            self._with_lifecycle_gate(candidate, lifecycle_policy, supplemental=True, as_of=as_of)
            for candidate in cooling_candidates
            if str(candidate.get("stock_code") or "").strip() not in blocked
        ]
        cooling_candidates.sort(key=self._cooling_supplemental_sort_key)
        return [*normal_candidates, *cooling_candidates[:needed]]

    def _with_lifecycle_gate(
        self,
        candidate: dict[str, Any],
        policy: QuantUniverseLifecyclePolicy,
        *,
        supplemental: bool = False,
        as_of: datetime | str | None = None,
    ) -> dict[str, Any]:
        row = dict(candidate)
        code = str(row.get("stock_code") or "").strip()
        state = self.candidate_pool.db.get_quant_universe_state(code) if code else None
        if isinstance(state, dict):
            for key in (
                "quant_status",
                "health_score",
                "candidate_score",
                "last_health_evaluated_at",
                "candidate_confidence",
                "downtrend_streak",
                "weakening_warning_streak",
                "active_since",
                "active_checkpoints",
                "cooling_until",
                "recovery_probe_until",
                "recovery_probe_attempt_count",
                "recent_probe_loss_count",
                "last_recovery_probe_failure_at",
                "recovery_probe_cooldown_until",
                "probe_failure_reason",
                "last_status_changed_at",
            ):
                if state.get(key) not in (None, ""):
                    row[key] = state.get(key)
        row["lifecycle_gate"] = build_lifecycle_gate(
            row.get("quant_status") or "active",
            policy,
            supplemental=supplemental,
            recovery_probe_active=is_recovery_probe_active(state, as_of),
            downtrend_streak=int(row.get("downtrend_streak") or 0),
            recovery_probe_attempt_count=int((state or {}).get("recovery_probe_attempt_count") or 0),
            recent_probe_loss_count=_active_recovery_probe_loss_count(state, policy, as_of),
            recovery_probe_cooldown_active=_is_recovery_probe_cooldown_active(state, as_of),
            probe_failure_reason=str((state or {}).get("probe_failure_reason") or ""),
        )
        return row

    @staticmethod
    def _normal_scan_sort_key(candidate: dict[str, Any]) -> tuple[int, float, str]:
        status_order = {"active": 0, "trial": 1, "exit_only": 2}
        status = str(candidate.get("quant_status") or "").strip().lower()
        health = float(candidate.get("health_score") or 0)
        return (status_order.get(status, 9), -health, str(candidate.get("stock_code") or ""))

    @staticmethod
    def _cooling_supplemental_sort_key(candidate: dict[str, Any]) -> tuple[int, float, float, str, str]:
        score = float(candidate.get("candidate_score") or 0)
        support = 1 if score > 0 else 0
        health = float(candidate.get("health_score") or 0)
        last_eval = str(candidate.get("last_health_evaluated_at") or "")
        return (-support, -score, -health, last_eval, str(candidate.get("stock_code") or ""))

    @staticmethod
    def _quant_lifecycle_policy_from_binding(strategy_profile_binding: dict | None) -> QuantUniverseLifecyclePolicy:
        profile_id = ""
        if isinstance(strategy_profile_binding, dict):
            profile_id = str(strategy_profile_binding.get("profile_id") or "").strip().lower()
        if profile_id == "conservative":
            return QuantUniverseLifecyclePolicy.conservative_defaults()
        if profile_id == "stable":
            return QuantUniverseLifecyclePolicy.stable_defaults()
        if profile_id == "aggressive":
            return QuantUniverseLifecyclePolicy.aggressive_defaults()
        return QuantUniverseLifecyclePolicy.stable_defaults()


    def _resolve_strategy_binding(
        self,
        *,
        strategy_profile_id: str | None,
        ai_dynamic_strategy: str | None = None,
        ai_dynamic_strength: float | None = None,
        ai_dynamic_lookback: int | None = None,
        stock_code: str | None = None,
        stock_name: str | None = None,
        as_of=None,
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
            as_of=as_of,
        )

    def _evaluate_candidate_decision(
        self,
        candidate: dict,
        *,
        market_snapshot: dict | None = None,
        analysis_timeframe: str = "1d",
        strategy_mode: str = "auto",
        strategy_profile_binding: dict | None = None,
        current_time: datetime | None = None,
    ):
        candidate_payload = self._with_account_context(
            candidate,
            profile_kind="candidate",
            stock_analysis_policy=self._stock_analysis_policy_from_binding(
                strategy_profile_binding,
                profile_kind="candidate",
            ),
            current_time=current_time,
        )
        base_attempts = [
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
        attempts = []
        for kwargs in base_attempts:
            if current_time is not None:
                attempts.append({**kwargs, "current_time": current_time})
            attempts.append(kwargs)
        last_error: TypeError | None = None
        for kwargs in attempts:
            kwargs = {key: value for key, value in kwargs.items() if value is not None}
            try:
                return self.adapter.analyze_candidate(candidate_payload, **kwargs)
            except TypeError as exc:
                message = str(exc)
                if "unexpected keyword argument" not in message:
                    raise
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        return self.adapter.analyze_candidate(candidate_payload)

    def _evaluate_position_decision(
        self,
        candidate: dict,
        position: dict,
        *,
        market_snapshot: dict | None = None,
        analysis_timeframe: str = "1d",
        strategy_mode: str = "auto",
        strategy_profile_binding: dict | None = None,
        current_time: datetime | None = None,
    ):
        stock_analysis_policy = self._stock_analysis_policy_from_binding(
            strategy_profile_binding,
            profile_kind="position",
        )
        candidate_payload = self._with_account_context(
            candidate,
            profile_kind="position",
            stock_analysis_policy=stock_analysis_policy,
            current_time=current_time,
        )
        position_payload = self._with_account_context(
            position,
            profile_kind="position",
            stock_analysis_policy=stock_analysis_policy,
            current_time=current_time,
        )
        base_attempts = [
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
        attempts = []
        for kwargs in base_attempts:
            if current_time is not None:
                attempts.append({**kwargs, "current_time": current_time})
            attempts.append(kwargs)
        last_error: TypeError | None = None
        for kwargs in attempts:
            kwargs = {key: value for key, value in kwargs.items() if value is not None}
            try:
                return self.adapter.analyze_position(candidate_payload, position_payload, **kwargs)
            except TypeError as exc:
                message = str(exc)
                if "unexpected keyword argument" not in message:
                    raise
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        return self.adapter.analyze_position(candidate_payload, position_payload)

    def _with_account_context(
        self,
        payload: dict,
        *,
        profile_kind: str = "candidate",
        stock_analysis_policy: dict[str, Any] | None = None,
        current_time: datetime | None = None,
    ) -> dict:
        enriched = dict(payload)
        enriched["_quant_account_context"] = self._build_account_context()
        enriched["_quant_stock_analysis_context"] = self._build_stock_analysis_context(
            payload,
            profile_kind=profile_kind,
            policy=stock_analysis_policy,
            current_time=current_time,
        )
        return enriched

    def _build_stock_analysis_context(
        self,
        payload: dict,
        *,
        profile_kind: str = "candidate",
        policy: dict[str, Any] | None = None,
        current_time: datetime | None = None,
    ) -> dict[str, Any] | None:
        if not self.stock_analysis_context_enabled:
            return None
        resolved_policy = policy or self._default_stock_analysis_policy()
        if not bool(resolved_policy.get("enabled", True)):
            return {
                "used": False,
                "omitted_reason": "disabled_by_profile",
                "profile_kind": profile_kind,
            }
        code = str(payload.get("stock_code") or payload.get("symbol") or "").strip()
        if not code:
            return None
        ttl_hours = self._safe_float(resolved_policy.get("ttl_hours"), 24.0)
        min_confidence = self._safe_float(resolved_policy.get("min_confidence"), 0.45)
        context = self.stock_analysis_context.get_latest_valid(
            code,
            as_of=current_time or datetime.now(),
            mode="realtime",
            ttl_hours=ttl_hours,
            min_confidence=min_confidence,
        )
        if context is not None:
            context["profile_kind"] = profile_kind
            context["policy"] = {
                "ttl_hours": ttl_hours,
                "min_confidence": min_confidence,
                "max_positive_contribution": self._safe_float(resolved_policy.get("max_positive_contribution"), 0.08),
                "max_negative_contribution": self._safe_float(resolved_policy.get("max_negative_contribution"), -0.08),
            }
            return context
        refresh_state = {"enqueued": False, "reason": "disabled"}
        if self.stock_analysis_refresh_enabled:
            refresh_state = stock_analysis_refresh_queue.enqueue(
                symbol=code,
                period=self.stock_analysis_refresh_period,
                db_path=self.stock_analysis_db_file,
                reason="no_valid_recent_stock_analysis",
            )
        return {
            "used": False,
            "omitted_reason": "no_valid_recent_stock_analysis",
            "profile_kind": profile_kind,
            "refresh_enqueued": bool(refresh_state.get("enqueued")),
            "refresh_status": str(refresh_state.get("reason") or ""),
            "policy": {
                "ttl_hours": ttl_hours,
                "min_confidence": min_confidence,
            },
        }

    @staticmethod
    def _default_stock_analysis_policy() -> dict[str, Any]:
        return {
            "enabled": True,
            "ttl_hours": 24.0,
            "min_confidence": 0.45,
            "max_positive_contribution": 0.08,
            "max_negative_contribution": -0.08,
        }

    def _stock_analysis_policy_from_binding(
        self,
        strategy_profile_binding: dict | None,
        *,
        profile_kind: str,
    ) -> dict[str, Any]:
        default_policy = self._default_stock_analysis_policy()
        if not isinstance(strategy_profile_binding, dict):
            return default_policy
        config_payload = strategy_profile_binding.get("config")
        if not isinstance(config_payload, dict):
            return default_policy
        base = config_payload.get("base")
        profiles = config_payload.get("profiles")
        if not isinstance(base, dict) or not isinstance(profiles, dict):
            return default_policy
        try:
            resolved = StrategyScoringConfig(
                schema_version=str(config_payload.get("schema_version") or "quant_explain"),
                base=base,
                profiles=profiles,
            ).resolve(profile_kind)
        except Exception:
            return default_policy
        context_config = resolved.get("context") if isinstance(resolved.get("context"), dict) else {}
        policy = context_config.get("stock_analysis_policy") if isinstance(context_config.get("stock_analysis_policy"), dict) else {}
        return {**default_policy, **policy}

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            parsed = float(value)
            if parsed != parsed:
                return default
            return parsed
        except (TypeError, ValueError):
            return default

    def _build_account_context(self) -> dict[str, Any]:
        try:
            summary = self.portfolio.get_account_summary()
        except Exception:
            return {}
        try:
            available_cash = float(summary.get("available_cash") or 0.0)
            total_equity = float(summary.get("total_equity") or 0.0)
        except (TypeError, ValueError):
            return {}
        cash_ratio = (available_cash / total_equity) if total_equity > 0 else 0.0
        return {
            "available_cash": round(available_cash, 4),
            "total_equity": round(total_equity, 4),
            "cash_ratio": round(max(0.0, min(1.0, cash_ratio)), 6),
            "position_count": int(summary.get("position_count") or 0),
        }

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


def _is_recovery_probe_cooldown_active(state: dict[str, Any] | None, as_of: datetime | str | None) -> bool:
    if not state:
        return False
    value = state.get("recovery_probe_cooldown_until")
    if not value:
        return False
    return is_recovery_probe_active({"recovery_probe_until": value}, as_of)


def _active_recovery_probe_loss_count(
    state: dict[str, Any] | None,
    policy: QuantUniverseLifecyclePolicy,
    as_of: datetime | str | None,
) -> int:
    if not state:
        return 0
    count = int(state.get("recent_probe_loss_count") or 0)
    if count <= 0:
        return 0
    failure_at = state.get("last_recovery_probe_failure_at")
    if not failure_at:
        return count
    try:
        failure_dt = _parse_gate_time(failure_at)
        now_dt = _parse_gate_time(as_of) if as_of is not None else datetime.now(tz=failure_dt.tzinfo)
    except (TypeError, ValueError):
        return count
    if now_dt - failure_dt > timedelta(days=max(int(policy.recovery_probe_failure_lookback_days or 0), 0)):
        return 0
    return count


def _parse_gate_time(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
