"""Candidate event generation for live quant drill replay service."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.quant_sim.db import QuantSimDB
from app.quant_sim.live_quant_drill_candidates import (
    CandidateGenerationConfig,
    CandidateSourceAvailability,
    should_generate_candidates,
    should_skip_candidate_event_due_to_dedup,
    source_availability_for_checkpoint,
)
from app.quant_sim.quant_universe_lifecycle import QuantUniverseManager


class LiveQuantDrillCandidateMixin:
    """Generate and normalize drill candidate events."""
    def _process_live_quant_drill_candidate_events(
        self,
        *,
        run_id: int,
        checkpoint: datetime,
        checkpoint_index: int,
        context: dict,
        temp_db: QuantSimDB,
        manager: QuantUniverseManager,
    ) -> dict[str, Any]:
        if not bool(context.get("generate_historical_candidate_events", True)):
            return {"candidate_event_count": 0, "auto_promoted_count": 0, "consumed_count": 0}
        config = CandidateGenerationConfig(
            frequency=str(context.get("candidate_generation_frequency") or "daily_first_checkpoint"),
            checkpoint_interval=int(context.get("candidate_generation_checkpoint_interval") or 8),
            candidate_event_dedup_days=int(context.get("candidate_event_dedup_days") or 5),
        )
        checkpoints = context.get("checkpoints") if isinstance(context.get("checkpoints"), list) else []
        event_index = max(0, int(checkpoint_index) - 1)
        if not should_generate_candidates(config, checkpoints, event_index):
            return {"candidate_event_count": 0, "auto_promoted_count": 0, "consumed_count": 0}

        raw_events = self._generate_live_quant_drill_candidate_events(
            run_id=run_id,
            checkpoint=checkpoint,
            context=context,
            temp_db=temp_db,
        )
        normalized_events = [
            self._normalize_live_quant_drill_candidate_event(event, checkpoint=checkpoint, context=context)
            for event in raw_events
            if str(event.get("stock_code") or "").strip()
        ]
        previous_events = self.db.list_sim_run_candidate_events(run_id, page_size=100000).get("items") or []
        deduped_events: list[dict[str, Any]] = []
        seen_event_keys: set[tuple[str, str, str]] = set()
        for event in normalized_events:
            event_key = (
                str(event.get("stock_code") or ""),
                str(event.get("source_type") or ""),
                str(event.get("checkpoint_at") or ""),
            )
            if event_key in seen_event_keys:
                continue
            seen_event_keys.add(event_key)
            if should_skip_candidate_event_due_to_dedup(
                config=config,
                stock_code=event["stock_code"],
                source_type=event["source_type"],
                checkpoint=checkpoint,
                previous_events=previous_events,
            ):
                continue
            deduped_events.append(event)
        normalized_events = deduped_events
        if not normalized_events:
            return {"candidate_event_count": 0, "auto_promoted_count": 0, "consumed_count": 0}
        self.db.add_sim_run_candidate_events(run_id, normalized_events)

        promoted = 0
        consumed = 0
        checkpoint_at = normalized_events[0]["checkpoint_at"]
        for event in normalized_events:
            manager_result = manager.ingest_candidate_event(
                {
                    "stock_code": event["stock_code"],
                    "stock_name": event.get("stock_name"),
                    "source_type": event["source_type"],
                    "source_key": event.get("source_key"),
                    "source_score": event.get("candidate_score"),
                    "confidence": event.get("confidence"),
                    "trend": event.get("trend"),
                    "event_weight": 1,
                    "reason_text": event.get("reason_text"),
                    "occurred_at": event.get("occurred_at") or event["checkpoint_at"],
                    "payload_json": event.get("evidence_json") or {},
                    "status": "active",
                },
                capacity_at=checkpoint,
            )
            self.db.update_sim_run_candidate_event_evaluation(
                run_id,
                stock_code=event["stock_code"],
                source_type=event["source_type"],
                checkpoint_at=event["checkpoint_at"],
                evaluation=manager_result,
            )
            if str(manager_result.get("decision") or "") == "cooling_review_queued":
                self._queue_live_quant_drill_cooling_review(context, event["stock_code"])
            if str(manager_result.get("decision") or "") == "promoted_to_trial":
                promoted += 1
                consumed += self.db.mark_sim_run_candidate_events_consumed(
                    run_id,
                    stock_code=event["stock_code"],
                    source_type=event["source_type"],
                    checkpoint_at_lte=checkpoint_at,
                )
        return {
            "candidate_event_count": len(normalized_events),
            "auto_promoted_count": promoted,
            "consumed_count": consumed,
        }

    @staticmethod
    def _queue_live_quant_drill_cooling_review(context: dict, stock_code: str) -> None:
        code = str(stock_code or "").strip().upper()
        if not code:
            return
        queued = context.setdefault("_live_quant_drill_forced_cooling_review_codes", set())
        if not isinstance(queued, set):
            queued = set(queued or [])
            context["_live_quant_drill_forced_cooling_review_codes"] = queued
        queued.add(code)

    def _generate_live_quant_drill_candidate_events(
        self,
        *,
        run_id: int,
        checkpoint: datetime,
        context: dict,
        temp_db: QuantSimDB,
    ) -> list[dict]:
        for source in self.LIVE_QUANT_DRILL_DISABLED_CANDIDATE_SOURCES:
            self._mark_live_quant_drill_candidate_source_disabled(context, source)
        timeframe = str(context.get("timeframe") or "30m")
        candidates = context.get("candidates") if isinstance(context.get("candidates"), list) else []
        events: list[dict[str, Any]] = []
        for candidate in candidates:
            stock_code = str(candidate.get("stock_code") or "").strip().upper()
            if not stock_code:
                continue
            state = temp_db.get_quant_universe_state(stock_code) or {}
            quant_status = str(state.get("quant_status") or "inactive").strip()
            if quant_status in {"trial", "active", "exit_only", "manual_paused"}:
                continue
            snapshot = self.snapshot_provider.get_snapshot(
                stock_code,
                checkpoint,
                timeframe,
                stock_name=candidate.get("stock_name") or stock_code,
            )
            if not snapshot:
                self._record_missing_run_market_artifact(
                    run_id=run_id,
                    run_type="live_quant_drill",
                    stock_code=stock_code,
                    checkpoint=checkpoint,
                    timeframe=timeframe,
                    market=str(context.get("market") or "CN"),
                )
                continue
            snapshot = self._attach_run_market_artifact(
                run_id=run_id,
                run_type="live_quant_drill",
                stock_code=stock_code,
                checkpoint=checkpoint,
                timeframe=timeframe,
                market=str(context.get("market") or "CN"),
                snapshot=snapshot,
            )
            source_event = self._build_live_quant_drill_low_price_event(
                candidate=candidate,
                checkpoint=checkpoint,
                snapshot=snapshot,
            )
            if source_event is not None:
                events.append(source_event)

        for source in self.LIVE_QUANT_DRILL_CANDIDATE_SOURCES:
            if source == "low_price":
                continue
            self._mark_live_quant_drill_candidate_source_disabled(context, source)
        return events

    def _build_live_quant_drill_low_price_event(
        self,
        *,
        candidate: dict[str, Any],
        checkpoint: datetime,
        snapshot: dict[str, Any],
    ) -> dict[str, Any] | None:
        available_fields = {
            "ohlcv": True,
            "price": self._snapshot_float(snapshot, "current_price", "latest_price", "close") > 0,
            "volume": self._snapshot_float(snapshot, "volume", "成交量", "volume_ratio") > 0,
        }
        availability = source_availability_for_checkpoint(
            source_type="low_price",
            checkpoint=checkpoint,
            available_fields=available_fields,
        )
        if availability != CandidateSourceAvailability.ENABLED:
            return None
        price = self._snapshot_float(snapshot, "current_price", "latest_price", "close")
        if price <= 0 or price > 18:
            return None
        ma5 = self._snapshot_float(snapshot, "ma5", "MA5")
        ma10 = self._snapshot_float(snapshot, "ma10", "MA10")
        ma20 = self._snapshot_float(snapshot, "ma20", "MA20")
        ma20_slope = self._snapshot_float(snapshot, "ma20_slope", "MA20_slope", "ma20Slope")
        ma60 = self._snapshot_float(snapshot, "ma60", "MA60")
        macd = self._snapshot_float(snapshot, "macd", "MACD")
        rsi = self._snapshot_float(snapshot, "rsi12", "rsi", "RSI")
        volume_ratio = self._snapshot_float(snapshot, "volume_ratio", "量比")
        amount = self._snapshot_float(snapshot, "amount", "turnover", "成交额")
        score = 0.48
        if price <= 12:
            score += 0.08
        if price <= 8:
            score += 0.06
        if ma20 > 0 and price >= ma20:
            score += 0.08
        if ma5 > 0 and ma10 > 0 and ma20 > 0 and ma5 >= ma10 >= ma20:
            score += 0.08
        if macd > 0:
            score += 0.05
        if volume_ratio >= 1.2:
            score += 0.07
        if 45 <= rsi <= 78:
            score += 0.05
        source_score = max(0.0, min(score, 0.95))
        if source_score < 0.50:
            return None
        stock_code = str(candidate.get("stock_code") or "").strip().upper()
        stock_name = str(candidate.get("stock_name") or stock_code).strip() or stock_code
        return {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "source_type": "low_price",
            "source_key": f"low_price:{checkpoint.date().isoformat()}",
            "candidate_score": round(source_score, 4),
            "confidence": round(0.68 + min(max(volume_ratio, 0.0), 3.0) * 0.04, 4),
            "trend": "up" if (ma20 > 0 and price >= ma20) or (ma5 > 0 and ma10 > 0 and ma5 >= ma10) else "neutral",
            "reason_text": f"历史低价动量候选：价格 {price:.2f}，量比 {volume_ratio:.2f}",
            "evidence_json": {
                "technical_snapshot_ready": snapshot.get("source_status") == "ready",
                "technical_snapshot_status": "ready" if snapshot.get("source_status") == "ready" else snapshot.get("reason_code"),
                "technical_snapshot_missing_fields": list(snapshot.get("technical_snapshot_missing_fields") or []),
                "technical_snapshot_timeframe": str(candidate.get("timeframe") or "30m"),
                "technical_snapshot_provider": snapshot.get("technical_snapshot_provider") or "historical_snapshot",
                "technical_snapshot_at": snapshot.get("technical_snapshot_at") or self._format_datetime(checkpoint),
                "technical_snapshot_prepared_at": snapshot.get("technical_snapshot_prepared_at") or self._format_datetime(checkpoint),
                "technical_snapshot_row_count": snapshot.get("row_count") or snapshot.get("technical_snapshot_row_count") or 120,
                "technical_snapshot_indicator_version": snapshot.get("technical_snapshot_indicator_version")
                or "live-quant-drill-v1",
                "score_basis": "artifact_as_of_price_volume_trend",
                "artifact_ref": snapshot.get("artifact_ref"),
                "source_status": snapshot.get("source_status"),
                "reason_code": snapshot.get("reason_code"),
            },
        }

    @staticmethod
    def _snapshot_float(snapshot: dict[str, Any], *keys: str) -> float:
        for key in keys:
            value = snapshot.get(key)
            if value in (None, ""):
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0

    @staticmethod
    def _mark_live_quant_drill_candidate_source_disabled(context: dict[str, Any], source: str) -> None:
        disabled = context.setdefault("disabled_candidate_sources", [])
        source_text = str(source or "").strip()
        if source_text and source_text not in disabled:
            disabled.append(source_text)

    def _normalize_live_quant_drill_candidate_event(
        self,
        event: dict[str, Any],
        *,
        checkpoint: datetime,
        context: dict,
    ) -> dict[str, Any]:
        market = str(context.get("market") or "CN")
        checkpoint_at = self._format_datetime(checkpoint)
        score = event.get("candidate_score")
        if score is None:
            score = event.get("source_score")
        return {
            "checkpoint_at": checkpoint_at,
            "stock_code": str(event.get("stock_code") or "").strip().upper(),
            "stock_name": str(event.get("stock_name") or event.get("stock_code") or "").strip(),
            "source_type": str(event.get("source_type") or "historical_candidate").strip(),
            "source_key": event.get("source_key"),
            "candidate_score": float(score or 0),
            "confidence": float(event.get("confidence") or 0),
            "trend": event.get("trend") or "up",
            "reason_text": event.get("reason_text"),
            "evidence_json": event.get("evidence_json") or event.get("payload_json") or {},
            "occurred_at": event.get("occurred_at") or checkpoint_at,
            "status": event.get("status") or "active",
        }
