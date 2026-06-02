"""Live quant drill execution mixin for quant replay service."""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from app.quant_sim.db import QuantSimDB
from app.quant_sim.dynamic_strategy import DEFAULT_AI_DYNAMIC_LOOKBACK, DEFAULT_AI_DYNAMIC_STRENGTH, DEFAULT_AI_DYNAMIC_STRATEGY
from app.quant_sim.engine import QuantSimEngine
from app.quant_sim.market_technical_artifact_store import MarketTechnicalArtifactStore
from app.quant_sim.outcome_scoring_entrypoints import OutcomeBatchRequest, OutcomeBatchScope, score_signal_batch
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.quant_universe_artifact_db import ArtifactBackedCandidateEventDB
from app.quant_sim.quant_universe_lifecycle import QuantUniverseManager
from app.quant_sim.time_utils import parse_system_datetime


class LiveQuantDrillMixin:
    """Execute live quant drill checkpoints against run-local state."""
    def _execute_live_quant_drill(self, *, run_id: int, context: dict) -> dict:
        checkpoints = context["checkpoints"]
        account_summary = context["account_summary"]
        temp_dir = Path(tempfile.mkdtemp(prefix="quant_live_drill_"))
        temp_db_file = temp_dir / "quant_live_drill.db"
        last_checkpoint_index = 0
        last_checkpoint_text = ""
        try:
            temp_db = self._create_live_quant_drill_temp_db(context, temp_db_file)
            temp_engine = QuantSimEngine(
                db_file=temp_db_file,
                adapter=self.adapter,
                stock_analysis_context_enabled=False,
            )
            temp_portfolio = PortfolioService(db_file=temp_db_file)
            strategy_profile_binding = context.get("strategy_profile_binding") if isinstance(context.get("strategy_profile_binding"), dict) else {}
            policy = temp_engine._quant_lifecycle_policy_from_binding(strategy_profile_binding)
            manager = QuantUniverseManager(
                db=ArtifactBackedCandidateEventDB(temp_db, artifact_db_file=self.replay_db_file),
                profile_id=str(strategy_profile_binding.get("profile_id") or "stable"),
                policy=policy,
                drill_mode=True,
            )
            self.db.update_sim_run_progress(
                run_id,
                status="running",
                progress_total=len(checkpoints),
                status_message="实时量化演练任务已开始",
            )
            self.db.append_sim_run_event(run_id, "实时量化演练任务已开始。")
            stock_codes = [
                str(code).strip()
                for code in (context.get("stock_codes") if isinstance(context.get("stock_codes"), list) else [])
                if str(code).strip()
            ]
            self.snapshot_provider.prepare(
                stock_codes,
                context["start_dt"],
                context["end_dt"],
                str(context.get("timeframe") or "30m"),
            )
            prepare_report = getattr(self.snapshot_provider, "prepare_report", None)
            if isinstance(prepare_report, dict):
                self.db.append_sim_run_event(
                    run_id,
                    (
                        "实时量化演练历史数据准备完成："
                        f"股票批次 {len(prepare_report.get('stock_batches') or [])}，"
                        f"时间分段 {int(prepare_report.get('segment_count') or 0)}，"
                        f"成功 {int(prepare_report.get('prepared') or 0)}，"
                        f"失败 {int(prepare_report.get('failed') or 0)}。"
                    ),
                )

            for checkpoint_index, checkpoint in enumerate(checkpoints, start=1):
                last_checkpoint_index = checkpoint_index
                last_checkpoint_text = self._format_datetime(checkpoint)
                if self.db.is_sim_run_cancel_requested(run_id):
                    raise RuntimeError("实时量化演练任务已取消")
                self.db.update_sim_run_progress(
                    run_id,
                    status="running",
                    progress_current=checkpoint_index - 1,
                    progress_total=len(checkpoints),
                    latest_checkpoint_at=last_checkpoint_text,
                    status_message=f"正在执行第 {checkpoint_index}/{len(checkpoints)} 个检查点：{last_checkpoint_text}",
                )
                checkpoint_summary = self._run_live_quant_drill_checkpoint(
                    run_id=run_id,
                    checkpoint=checkpoint,
                    checkpoint_index=checkpoint_index,
                    context=context,
                    temp_db=temp_db,
                    engine=temp_engine,
                    portfolio=temp_portfolio,
                    manager=manager,
                )
                checkpoint_signals = checkpoint_summary.get("signals") or []
                if checkpoint_signals:
                    self.db.upsert_sim_run_signals(run_id, checkpoint_signals)
                self.db.add_sim_run_checkpoint(
                    run_id,
                    checkpoint_at=last_checkpoint_text,
                    candidates_scanned=int(checkpoint_summary.get("candidates_scanned") or 0),
                    positions_checked=int(checkpoint_summary.get("positions_checked") or 0),
                    signals_created=int(checkpoint_summary.get("signals_created") or 0),
                    auto_executed=int(checkpoint_summary.get("auto_executed") or 0),
                    available_cash=float(checkpoint_summary.get("available_cash") or 0),
                    market_value=float(checkpoint_summary.get("market_value") or 0),
                    total_equity=float(checkpoint_summary.get("total_equity") or 0),
                    metadata={
                        "positions": checkpoint_summary.get("positions") or [],
                        "slot_summary": checkpoint_summary.get("slot_summary") or {},
                        "cooling_review": checkpoint_summary.get("cooling_review") or {},
                    },
                )
                self.db.update_sim_run_progress(
                    run_id,
                    progress_current=checkpoint_index,
                    progress_total=len(checkpoints),
                    latest_checkpoint_at=last_checkpoint_text,
                    status_message=f"已完成第 {checkpoint_index}/{len(checkpoints)} 个检查点",
                )

            trades = temp_db.get_trade_history(limit=10000)
            snapshots = self._sort_snapshots_chronologically(
                [
                    snapshot
                    for snapshot in temp_db.get_account_snapshots(limit=10000)
                    if str(snapshot.get("run_reason") or "").startswith("live_quant_drill@")
                ]
            )
            positions = temp_portfolio.list_positions()
            metrics = self._calculate_run_metrics(float(account_summary["initial_cash"]), trades, snapshots)
            outcome_batch = score_signal_batch(
                OutcomeBatchRequest(
                    db=self.db,
                    artifact_store=MarketTechnicalArtifactStore(self.replay_db_file),
                    scope=OutcomeBatchScope(run_id=run_id, run_type="live_quant_drill", domain="drill"),
                    as_of_checkpoint=last_checkpoint_text or None,
                    limit=5000,
                    trace_id=f"live_quant_drill_{run_id}",
                )
            )
            with self.db.write_batch():
                self.db.replace_sim_run_runtime_results(
                    run_id,
                    trades=trades,
                    snapshots=snapshots,
                    positions=positions,
                )
                self.db.finalize_sim_run(
                    run_id,
                    status="completed",
                    final_equity=float(metrics["final_equity"]),
                    total_return_pct=float(metrics["total_return_pct"]),
                    max_drawdown_pct=float(metrics["max_drawdown_pct"]),
                    win_rate=float(metrics["win_rate"]),
                    trade_count=len(trades),
                    status_message="实时量化演练任务已完成",
                    metadata={
                        "checkpoint_count": len(checkpoints),
                        "configured_candidate_sources": context.get("configured_candidate_sources") or [],
                        "historical_executable_candidate_sources": context.get("historical_executable_candidate_sources") or [],
                        "disabled_candidate_sources": context.get("disabled_candidate_sources") or [],
                        "data_warnings": context.get("data_warnings") or [],
                        "final_slot_summary": self._collect_slot_summary(temp_db),
                        "outcome_summary": outcome_batch.get("summary") or {},
                    },
                )
                self.db.append_sim_run_event(run_id, "实时量化演练任务已完成。", level="success")
            return {
                "run_id": run_id,
                "status": "completed",
                "checkpoint_count": len(checkpoints),
                "trade_count": len(trades),
                "final_equity": metrics["final_equity"],
                "total_return_pct": metrics["total_return_pct"],
                "max_drawdown_pct": metrics["max_drawdown_pct"],
                "win_rate": metrics["win_rate"],
                "handoff_to_live": False,
            }
        except Exception as exc:
            status_message = f"实时量化演练任务失败：{exc}"
            if last_checkpoint_index > 0:
                status_message = f"第 {last_checkpoint_index}/{len(checkpoints)} 个检查点（{last_checkpoint_text}）失败：{exc}"
            with self.db.write_batch():
                self.db.finalize_sim_run(
                    run_id,
                    status="failed",
                    final_equity=float(account_summary["initial_cash"]),
                    total_return_pct=0.0,
                    max_drawdown_pct=0.0,
                    win_rate=0.0,
                    trade_count=0,
                    status_message=status_message,
                    metadata={
                        "error": str(exc),
                        "failed_checkpoint_index": last_checkpoint_index,
                        "failed_checkpoint_at": last_checkpoint_text,
                    },
                )
                self.db.append_sim_run_event(run_id, status_message, level="error")
            raise
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _run_live_quant_drill_checkpoint(
        self,
        *,
        run_id: int,
        checkpoint: datetime,
        checkpoint_index: int,
        context: dict,
        temp_db: QuantSimDB,
        engine: QuantSimEngine,
        portfolio: PortfolioService,
        manager: QuantUniverseManager,
    ) -> dict:
        self._apply_due_corporate_actions(
            temp_db=temp_db,
            checkpoint=checkpoint,
            market=str(context.get("market") or "CN"),
            start_dt=context.get("start_dt") or checkpoint,
            end_dt=context.get("end_dt") or checkpoint,
            run_id=run_id,
            scope_type="live_quant_drill",
        )
        candidate_processing = self._process_live_quant_drill_candidate_events(
            run_id=run_id,
            checkpoint=checkpoint,
            checkpoint_index=checkpoint_index,
            context=context,
            temp_db=temp_db,
            manager=manager,
        )
        cooling_review = self._run_live_quant_drill_cooling_review(
            run_id=run_id,
            checkpoint=checkpoint,
            context=context,
            temp_db=temp_db,
            engine=engine,
            portfolio=portfolio,
            manager=manager,
        )
        main_scan = self._run_live_quant_drill_main_scan(
            run_id=run_id,
            checkpoint=checkpoint,
            context=context,
            temp_db=temp_db,
            engine=engine,
            portfolio=portfolio,
            manager=manager,
        )
        cooling_diagnostics = list(cooling_review.get("diagnostics") or [])
        cooling_review_summary = {key: value for key, value in cooling_review.items() if key != "diagnostics"}
        cooling_review_summary["diagnostic_count"] = len(cooling_diagnostics)
        temp_db.add_account_snapshot(run_reason=f"live_quant_drill@{self._format_datetime(checkpoint)}")
        self._persist_live_quant_drill_quant_snapshot(
            run_id=run_id,
            checkpoint=checkpoint,
            context=context,
            temp_db=temp_db,
            checkpoint_metadata={
                "candidate_event_count": int(candidate_processing.get("candidate_event_count") or 0),
                "auto_promoted_count": int(candidate_processing.get("auto_promoted_count") or 0),
                "auto_exited_count": int(main_scan.get("auto_exited_count") or 0),
                "cooling_review": cooling_review_summary,
            },
        )
        account = temp_db.get_account_summary()
        positions = portfolio.list_positions() if hasattr(portfolio, "list_positions") else []
        signals = list(main_scan.get("signals") or [])
        return {
            "signals": signals,
            "candidates_scanned": int(main_scan.get("candidates_scanned") or 0),
            "positions_checked": len(positions),
            "signals_created": len(signals),
            "auto_executed": int(main_scan.get("auto_executed") or 0),
            "available_cash": float(account.get("available_cash") or 0),
            "market_value": float(account.get("market_value") or 0),
            "total_equity": float(account.get("total_equity") or 0),
            "positions": self._collect_position_snapshot(positions),
            "slot_summary": self._collect_slot_summary(temp_db),
            "cooling_review": cooling_review_summary,
            "candidate_processing": candidate_processing,
        }

    def _persist_live_quant_drill_quant_snapshot(
        self,
        *,
        run_id: int,
        checkpoint: datetime,
        context: dict,
        temp_db: QuantSimDB,
        checkpoint_metadata: dict[str, Any],
    ) -> None:
        market = str(context.get("market") or "CN")
        checkpoint_at = self._format_datetime(checkpoint)
        response = temp_db.list_quant_universe_state(limit=100000)
        states = list(response.get("items") or [])
        status_counts: dict[str, int] = {}
        for state in states:
            status = str(state.get("quant_status") or "inactive")
            status_counts[status] = status_counts.get(status, 0) + 1
            state["market"] = market
            state["latest_reason"] = state.get("retire_reason") or state.get("quant_manual_override") or ""
        self.db.upsert_sim_run_quant_states(
            run_id,
            checkpoint_at=checkpoint_at,
            states=states,
        )
        persisted_event_ids = context.setdefault("_persisted_quant_event_ids", set())
        if not isinstance(persisted_event_ids, set):
            persisted_event_ids = set(persisted_event_ids or [])
            context["_persisted_quant_event_ids"] = persisted_event_ids
        quant_events = sorted(temp_db.list_quant_universe_events(limit=1000), key=lambda item: int(item.get("id") or 0))
        replay_events: list[dict[str, Any]] = []
        for event in quant_events:
            event_id = int(event.get("id") or 0)
            if event_id in persisted_event_ids:
                continue
            persisted_event_ids.add(event_id)
            replay_events.append(
                {
                    "checkpoint_at": checkpoint_at,
                    "stock_code": event.get("stock_code"),
                    "stock_name": event.get("stock_name") or event.get("stock_code"),
                    "event_type": event.get("event_type"),
                    "from_status": event.get("from_status"),
                    "to_status": event.get("to_status"),
                    "reason_code": event.get("reason_code"),
                    "reason_text": event.get("reason_text"),
                    "health_score_before": event.get("health_score_before"),
                    "health_score_after": event.get("health_score_after"),
                    "candidate_score": event.get("candidate_score"),
                    "reason_json": {"trigger_source": event.get("trigger_source")},
                    "evidence_json": event.get("evidence_json") or {},
                    "created_at": event.get("created_at"),
                }
            )
        self.db.add_sim_run_quant_events(run_id, replay_events)
        data_warnings = context.get("data_warnings") if isinstance(context.get("data_warnings"), list) else []
        self.db.upsert_sim_run_quant_summary(
            run_id,
            {
                "checkpoint_at": checkpoint_at,
                "inactive_count": status_counts.get("inactive", 0),
                "trial_count": status_counts.get("trial", 0),
                "active_count": status_counts.get("active", 0),
                "exit_only_count": status_counts.get("exit_only", 0),
                "cooling_count": status_counts.get("cooling", 0),
                "retired_count": status_counts.get("retired", 0),
                "manual_paused_count": status_counts.get("manual_paused", 0),
                "auto_promoted_count": int(checkpoint_metadata.get("auto_promoted_count") or 0),
                "auto_exited_count": int(checkpoint_metadata.get("auto_exited_count") or 0),
                "candidate_event_count": int(checkpoint_metadata.get("candidate_event_count") or 0),
                "data_warning_count": len(data_warnings),
                "metadata_json": checkpoint_metadata,
            },
        )

    def _run_live_quant_drill_main_scan(
        self,
        *,
        run_id: int | None = None,
        checkpoint: datetime,
        context: dict,
        temp_db: QuantSimDB,
        engine: QuantSimEngine,
        portfolio: PortfolioService,
        manager: QuantUniverseManager,
    ) -> dict:
        held_codes = {
            str(item.get("stock_code") or "").strip()
            for item in portfolio.list_positions()
            if str(item.get("stock_code") or "").strip()
        }
        scan_candidates = engine.list_live_scan_candidates(exclude_codes=held_codes, policy=manager.policy, as_of=checkpoint)
        summary = self._run_checkpoint(
            run_id=run_id,
            run_type="live_quant_drill",
            checkpoint=checkpoint,
            timeframe=str(context.get("timeframe") or "30m"),
            market=str(context.get("market") or "CN"),
            strategy_mode=str(context.get("strategy_mode") or "live_quant_drill"),
            strategy_profile_binding=context.get("strategy_profile_binding")
            if isinstance(context.get("strategy_profile_binding"), dict)
            else None,
            ai_dynamic_strategy=str(context.get("ai_dynamic_strategy") or DEFAULT_AI_DYNAMIC_STRATEGY),
            ai_dynamic_strength=float(context.get("ai_dynamic_strength") or DEFAULT_AI_DYNAMIC_STRENGTH),
            ai_dynamic_lookback=int(context.get("ai_dynamic_lookback") or DEFAULT_AI_DYNAMIC_LOOKBACK),
            engine=engine,
            portfolio=portfolio,
            signal_service=engine.signal_center,
            candidate_quant_statuses=self.LIVE_QUANT_DRILL_SCAN_STATUSES,
            candidates_override=scan_candidates,
            auto_execute_signals=bool(context.get("execute_trades", True)),
            auto_execute_note="实时量化演练自动执行",
            account_snapshot_reason_prefix=None,
        )
        summary["auto_exited_count"] = self._apply_live_quant_drill_lifecycle_updates(
            temp_db=temp_db,
            engine=engine,
            portfolio=portfolio,
            manager=manager,
            signals=list(summary.get("signals") or []),
        )
        return summary

    def _apply_live_quant_drill_lifecycle_updates(
        self,
        *,
        temp_db: QuantSimDB,
        engine: QuantSimEngine,
        portfolio: PortfolioService,
        manager: QuantUniverseManager,
        signals: list[dict[str, Any]],
    ) -> int:
        if not signals:
            return 0
        positions_by_code = {
            str(position.get("stock_code") or "").strip().upper(): position
            for position in portfolio.list_positions()
            if str(position.get("stock_code") or "").strip()
        }
        auto_exited_count = 0
        lookback = max(1, int(manager.policy.health_score_lookback_checkpoints or 1))
        for signal in signals:
            code = str(signal.get("stock_code") or "").strip().upper()
            if not code:
                continue
            previous_state = temp_db.get_quant_universe_state(code) or {}
            previous_status = str(previous_state.get("quant_status") or "inactive")
            signal_id = int(signal.get("id") or 0)
            recent_signals = [
                signal,
                *[
                    item
                    for item in engine.signal_center.list_signals(stock_code=code, limit=lookback)
                    if int(item.get("id") or 0) != signal_id
                ],
            ][:lookback]
            update = manager.update_after_signal(code, signal, recent_signals, positions_by_code.get(code))
            next_status = str(update.get("new_status") or previous_status)
            if (
                bool(update.get("status_changed"))
                and next_status in {"exit_only", "cooling", "retired"}
                and previous_status != next_status
            ):
                auto_exited_count += 1
        return auto_exited_count

    def _run_live_quant_drill_cooling_review(
        self,
        *,
        run_id: int | None = None,
        checkpoint: datetime,
        context: dict,
        temp_db: QuantSimDB,
        engine: QuantSimEngine,
        portfolio: PortfolioService,
        manager: QuantUniverseManager,
    ) -> dict:
        cooling = temp_db.list_quant_universe_state(statuses=["cooling"], limit=1000).get("items") or []
        interval_minutes = max(1, int(manager.policy.cooling_review_interval_minutes or 1))
        forced_codes = context.pop("_live_quant_drill_forced_cooling_review_codes", set())
        if not isinstance(forced_codes, set):
            forced_codes = set(forced_codes or [])
        forced_codes = {str(code or "").strip().upper() for code in forced_codes if str(code or "").strip()}
        due_cooling = [
            item
            for item in cooling
            if self._is_live_quant_drill_cooling_review_due(item, checkpoint=checkpoint, interval_minutes=interval_minutes)
        ]
        forced_cooling = [
            item
            for item in cooling
            if str(item.get("stock_code") or "").strip().upper() in forced_codes
        ]
        cooling_by_code: dict[str, dict[str, Any]] = {}
        for item in [*forced_cooling, *due_cooling]:
            code = str(item.get("stock_code") or "").strip().upper()
            if code:
                cooling_by_code[code] = item
        cooling = list(cooling_by_code.values())
        cooling.sort(
            key=lambda item: (
                0 if str(item.get("stock_code") or "").strip().upper() in forced_codes else 1,
                -float(item.get("candidate_score") or 0),
                str(item.get("last_health_evaluated_at") or ""),
                -float(item.get("health_score") or 0),
                str(item.get("stock_code") or ""),
            )
        )
        if self._should_full_review_live_quant_drill_cooling(context, checkpoint):
            selected = cooling
        else:
            batch_size = max(1, int(manager.policy.cooling_review_batch_size or 1))
            forced_selected = [
                item
                for item in cooling
                if str(item.get("stock_code") or "").strip().upper() in forced_codes
            ]
            forced_selected_codes = {
                str(item.get("stock_code") or "").strip().upper()
                for item in forced_selected
                if str(item.get("stock_code") or "").strip()
            }
            remainder = [
                item
                for item in cooling
                if str(item.get("stock_code") or "").strip().upper() not in forced_selected_codes
            ]
            selected = [*forced_selected, *remainder[: max(0, batch_size - len(forced_selected))]]
        if not selected:
            return {"reviewed": 0, "restored": 0, "retired": 0}
        positions_by_code = {
            str(position.get("stock_code") or "").strip().upper(): position
            for position in portfolio.list_positions()
            if str(position.get("stock_code") or "").strip()
        }
        lookback = max(1, int(manager.policy.health_score_lookback_checkpoints or 1))
        restored = 0
        retired = 0
        reviewed = 0
        diagnostics: list[dict[str, Any]] = []
        timeframe = str(context.get("timeframe") or "30m")
        for item in selected:
            code = str(item.get("stock_code") or "").strip().upper()
            if not code:
                continue
            candidate = engine.candidate_pool.db.get_candidate(code) or {
                "stock_code": code,
                "stock_name": item.get("stock_name") or code,
                "source": "cooling_review",
                "sources": ["cooling_review"],
            }
            snapshot = self.snapshot_provider.get_snapshot(
                code,
                checkpoint,
                timeframe,
                stock_name=candidate.get("stock_name") or code,
            )
            if not snapshot:
                self._record_missing_run_market_artifact(
                    run_id=run_id,
                    run_type="live_quant_drill",
                    stock_code=code,
                    checkpoint=checkpoint,
                    timeframe=timeframe,
                    market=str(context.get("market") or "CN"),
                )
                continue
            snapshot = self._attach_run_market_artifact(
                run_id=run_id,
                run_type="live_quant_drill",
                stock_code=code,
                checkpoint=checkpoint,
                timeframe=timeframe,
                market=str(context.get("market") or "CN"),
                snapshot=snapshot,
            )
            reviewed += 1
            review_signal = engine.build_candidate_review_signal(
                candidate,
                analysis_timeframe=timeframe,
                strategy_mode=str(context.get("strategy_mode") or "live_quant_drill"),
                strategy_profile_binding=context.get("strategy_profile_binding")
                if isinstance(context.get("strategy_profile_binding"), dict)
                else None,
                ai_dynamic_strategy=str(context.get("ai_dynamic_strategy") or DEFAULT_AI_DYNAMIC_STRATEGY),
                ai_dynamic_strength=float(context.get("ai_dynamic_strength") or DEFAULT_AI_DYNAMIC_STRENGTH),
                ai_dynamic_lookback=int(context.get("ai_dynamic_lookback") or DEFAULT_AI_DYNAMIC_LOOKBACK),
                current_time=checkpoint,
                market_snapshot=snapshot,
            )
            recent_signals = [
                review_signal,
                *[
                    signal
                    for signal in engine.signal_center.list_signals(stock_code=code, limit=max(0, lookback - 1))
                    if int(signal.get("id") or 0) != int(review_signal.get("id") or 0)
                ],
            ][:lookback]
            previous_status = str((temp_db.get_quant_universe_state(code) or {}).get("quant_status") or "cooling")
            previous_state = temp_db.get_quant_universe_state(code) or {}
            forced_review = code in forced_codes
            update = manager.update_after_signal(
                code,
                review_signal,
                recent_signals,
                positions_by_code.get(code),
                ignore_cooling_min_dwell=forced_review,
            )
            next_status = str(update.get("new_status") or previous_status)
            if previous_status == "cooling" and next_status == "trial":
                restored += 1
            elif previous_status == "cooling" and next_status == "retired":
                retired += 1
            elif previous_status == "cooling" and next_status == "cooling":
                latest_state = temp_db.get_quant_universe_state(code) or {}
                profile = (
                    review_signal.get("strategy_profile")
                    if isinstance(review_signal.get("strategy_profile"), dict)
                    else {}
                )
                gate = (
                    profile.get("lifecycle_gate")
                    if isinstance(profile.get("lifecycle_gate"), dict)
                    else {}
                )
                plan = (
                    profile.get("execution_sizing_plan")
                    if isinstance(profile.get("execution_sizing_plan"), dict)
                    else {}
                )
                guard = (
                    profile.get("portfolio_execution_guard")
                    if isinstance(profile.get("portfolio_execution_guard"), dict)
                    else {}
                )
                diagnostics.append(
                    {
                        "stock_code": code,
                        "stock_name": candidate.get("stock_name") or code,
                        "from_status": previous_status,
                        "to_status": next_status,
                        "reason_code": update.get("reason_code") or "cooling_recovery_not_confirmed",
                        "reason_text": update.get("reason_text") or "冷却复评未满足恢复条件",
                        "health_score_before": previous_state.get("health_score"),
                        "health_score_after": latest_state.get("health_score") or update.get("health_score"),
                        "candidate_score": latest_state.get("candidate_score") or previous_state.get("candidate_score") or 0,
                        "reason_json": {
                            "downtrend_hit": bool(update.get("downtrend_hit")),
                            "weakening_warning_hit": bool(update.get("weakening_warning_hit")),
                        },
                        "evidence_json": {
                            "review_signal_action": review_signal.get("action"),
                            "decision_type": review_signal.get("decision_type"),
                            "buy_tier": plan.get("buy_tier") or guard.get("buy_tier"),
                            "buy_strength_score": guard.get("buy_strength_score"),
                            "execution_skip_reason": plan.get("skip_reason"),
                            "lifecycle_gate_mode": gate.get("mode"),
                            "lifecycle_gate_reason_code": gate.get("reason_code"),
                            "health_breakdown": update.get("health_breakdown") or {},
                        },
                    }
                )
                reason_code = update.get("reason_code") or "cooling_recovery_not_confirmed"
                if self._should_record_live_quant_drill_cooling_diagnostic(context, checkpoint, code, reason_code):
                    temp_db.record_quant_universe_event(
                        {
                            "stock_code": code,
                            "event_type": "cooling_review_not_restored",
                            "from_status": previous_status,
                            "to_status": next_status,
                            "trigger_source": "cooling_review",
                            "reason_code": reason_code,
                            "reason_text": update.get("reason_text") or "冷却复评未满足恢复条件",
                            "health_score_before": previous_state.get("health_score"),
                            "health_score_after": latest_state.get("health_score") or update.get("health_score"),
                            "candidate_score": latest_state.get("candidate_score") or previous_state.get("candidate_score") or 0,
                            "evidence_json": diagnostics[-1]["evidence_json"],
                        }
                    )
        return {"reviewed": reviewed, "restored": restored, "retired": retired, "diagnostics": diagnostics}

    @staticmethod
    def _should_record_live_quant_drill_cooling_diagnostic(
        context: dict,
        checkpoint: datetime,
        stock_code: str,
        reason_code: str,
    ) -> bool:
        code = str(stock_code or "").strip().upper()
        reason = str(reason_code or "").strip()
        count_key = (code, reason)
        counts = context.setdefault("_live_quant_drill_cooling_diagnostic_counts", {})
        if not isinstance(counts, dict):
            counts = {}
            context["_live_quant_drill_cooling_diagnostic_counts"] = counts
        counts[count_key] = int(counts.get(count_key) or 0) + 1

        recorded = context.setdefault("_live_quant_drill_cooling_diagnostic_keys", set())
        if not isinstance(recorded, set):
            recorded = set(recorded or [])
            context["_live_quant_drill_cooling_diagnostic_keys"] = recorded
        key = (code, reason)
        if key in recorded:
            return False
        recorded.add(key)
        return True

    @staticmethod
    def _should_full_review_live_quant_drill_cooling(context: dict, checkpoint: datetime) -> bool:
        reviewed_dates = context.setdefault("_live_quant_drill_full_cooling_review_dates", set())
        if not isinstance(reviewed_dates, set):
            reviewed_dates = set(reviewed_dates or [])
            context["_live_quant_drill_full_cooling_review_dates"] = reviewed_dates
        day_key = checkpoint.date().isoformat()
        if day_key in reviewed_dates:
            return False
        reviewed_dates.add(day_key)
        return True

    def _is_live_quant_drill_cooling_review_due(
        self,
        item: dict[str, Any],
        *,
        checkpoint: datetime,
        interval_minutes: int,
    ) -> bool:
        current = parse_system_datetime(checkpoint)
        cooling_until = item.get("cooling_until")
        if cooling_until:
            cooling_dt = self._parse_optional_local_time(cooling_until)
            if cooling_dt is not None and cooling_dt > current:
                return False
        last_eval = item.get("last_health_evaluated_at")
        if not last_eval:
            return True
        last_dt = self._parse_optional_local_time(last_eval)
        if last_dt is None:
            return True
        if last_dt > current:
            return True
        return (current - last_dt).total_seconds() >= interval_minutes * 60

    @staticmethod
    def _parse_optional_local_time(value: Any) -> datetime | None:
        try:
            return parse_system_datetime(value)
        except (TypeError, ValueError):
            return None
