"""Historical replay execution mixin for quant replay service."""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.quant_kernel.models import Decision
from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.db import QuantSimDB
from app.quant_sim.dynamic_strategy import DEFAULT_AI_DYNAMIC_LOOKBACK, DEFAULT_AI_DYNAMIC_STRENGTH, DEFAULT_AI_DYNAMIC_STRATEGY
from app.quant_sim.engine import QuantSimEngine
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.replay_artifact_adapter import (
    RunArtifactContext,
    read_run_artifact,
    write_missing_run_artifact,
    write_run_artifact_from_snapshot,
)
from app.quant_sim.signal_center_service import SignalCenterService
from app.quant_sim.time_utils import format_utc_iso_z, market_timezone


class HistoricalReplayMixin:
    """Execute historical replay checkpoints and shared replay helpers."""
    def _execute_prepared_replay(
        self,
        *,
        run_id: int,
        mode: str,
        handoff_to_live: bool,
        context: dict,
        auto_start_scheduler: bool,
    ) -> dict:
        if handoff_to_live:
            raise ValueError("接续到实时模拟账户已停用，请使用历史回放查看独立回放结果。")
        del auto_start_scheduler

        start_dt = context["start_dt"]
        end_dt = context["end_dt"]
        timeframe = context["timeframe"]
        market = context["market"]
        strategy_mode = context["strategy_mode"]
        strategy_profile_binding = context.get("strategy_profile_binding") if isinstance(context.get("strategy_profile_binding"), dict) else {}
        ai_dynamic_strategy = str(context.get("ai_dynamic_strategy") or DEFAULT_AI_DYNAMIC_STRATEGY).strip().lower()
        ai_dynamic_strength = float(context.get("ai_dynamic_strength") or DEFAULT_AI_DYNAMIC_STRENGTH)
        ai_dynamic_lookback = int(context.get("ai_dynamic_lookback") or DEFAULT_AI_DYNAMIC_LOOKBACK)
        commission_rate = float(context.get("commission_rate") or 0)
        sell_tax_rate = float(context.get("sell_tax_rate") or 0)
        candidates = context["candidates"]
        stock_codes = context["stock_codes"]
        checkpoints = context["checkpoints"]
        account_summary = context["account_summary"]

        self.db.update_sim_run_progress(
            run_id,
            status="running",
            progress_total=len(checkpoints),
            status_message="正在准备历史行情数据",
        )
        self.db.append_sim_run_event(run_id, "回放任务已开始，正在准备历史行情数据。")

        temp_dir = Path(tempfile.mkdtemp(prefix="quant_replay_"))
        temp_db_file = temp_dir / "quant_replay.db"

        try:
            temp_candidate_service = CandidatePoolService(db_file=temp_db_file)
            temp_portfolio = PortfolioService(db_file=temp_db_file)
            temp_engine = QuantSimEngine(
                db_file=temp_db_file,
                adapter=self.adapter,
                stock_analysis_context_enabled=False,
            )
            temp_signal_service = SignalCenterService(db_file=temp_db_file)
            temp_db = QuantSimDB(temp_db_file)
            last_checkpoint_index = 0
            last_checkpoint_text = ""

            temp_portfolio.configure_account(float(account_summary["initial_cash"]))
            temp_db.update_scheduler_config(
                commission_rate=commission_rate,
                sell_tax_rate=sell_tax_rate,
                strategy_profile_id=str(strategy_profile_binding.get("profile_id") or "") or None,
                ai_dynamic_strategy=ai_dynamic_strategy,
                ai_dynamic_strength=ai_dynamic_strength,
                ai_dynamic_lookback=ai_dynamic_lookback,
                capital_slot_enabled=bool((context.get("scheduler_config") or {}).get("capital_slot_enabled", True)),
                capital_pool_min_cash=float((context.get("scheduler_config") or {}).get("capital_pool_min_cash") or 0),
                capital_pool_max_cash=float((context.get("scheduler_config") or {}).get("capital_pool_max_cash") or 0),
                capital_slot_min_cash=float((context.get("scheduler_config") or {}).get("capital_slot_min_cash") or 0),
                capital_max_slots=int((context.get("scheduler_config") or {}).get("capital_max_slots") or 1),
                capital_min_buy_slot_fraction=float((context.get("scheduler_config") or {}).get("capital_min_buy_slot_fraction") or 0.25),
                capital_full_buy_edge=float((context.get("scheduler_config") or {}).get("capital_full_buy_edge") or 0.25),
                capital_confidence_weight=float((context.get("scheduler_config") or {}).get("capital_confidence_weight") or 0.35),
                capital_high_price_threshold=float((context.get("scheduler_config") or {}).get("capital_high_price_threshold") or 100),
                capital_high_price_max_slot_units=float((context.get("scheduler_config") or {}).get("capital_high_price_max_slot_units") or 2),
                capital_sell_cash_reuse_policy=str((context.get("scheduler_config") or {}).get("capital_sell_cash_reuse_policy") or "next_batch"),
            )
            for candidate in candidates:
                temp_candidate_service.add_candidate(
                    stock_code=str(candidate["stock_code"]),
                    stock_name=str(candidate.get("stock_name") or ""),
                    source=str(candidate.get("source") or "manual"),
                    latest_price=float(candidate.get("latest_price") or 0),
                    notes=candidate.get("notes"),
                    metadata=candidate.get("metadata") or {},
                    status="active",
                )

            self.snapshot_provider.prepare(stock_codes, start_dt, end_dt, timeframe)
            prepare_report = getattr(self.snapshot_provider, "prepare_report", None)
            if isinstance(prepare_report, dict):
                self.db.append_sim_run_event(
                    run_id,
                    (
                        "历史数据准备完成："
                        f"股票批次 {len(prepare_report.get('stock_batches') or [])}，"
                        f"时间分段 {int(prepare_report.get('segment_count') or 0)}，"
                        f"成功 {int(prepare_report.get('prepared') or 0)}，"
                        f"失败 {int(prepare_report.get('failed') or 0)}。"
                    ),
                    level="warning" if int(prepare_report.get("failed") or 0) > 0 else "info",
                )
                if int(prepare_report.get("prepared") or 0) <= 0 and stock_codes:
                    raise ValueError("历史数据准备失败：所有股票都没有可用行情数据")
            self.db.append_sim_run_event(
                run_id,
                f"已准备 {len(stock_codes)} 只股票的历史数据，共 {len(checkpoints)} 个检查点。",
            )

            cancelled = False

            for checkpoint_index, checkpoint in enumerate(checkpoints, start=1):
                last_checkpoint_index = checkpoint_index
                if self.db.is_sim_run_cancel_requested(run_id):
                    cancelled = True
                    self.db.append_sim_run_event(run_id, "检测到取消请求，正在停止回放。", level="warning")
                    break

                checkpoint_text = self._format_datetime(checkpoint)
                last_checkpoint_text = checkpoint_text
                self.db.update_sim_run_progress(
                    run_id,
                    status="running",
                    progress_current=checkpoint_index - 1,
                    progress_total=len(checkpoints),
                    latest_checkpoint_at=checkpoint_text,
                    status_message=f"正在执行第 {checkpoint_index}/{len(checkpoints)} 个检查点：{checkpoint_text}",
                )
                self._apply_due_corporate_actions(
                    temp_db=temp_db,
                    checkpoint=checkpoint,
                    market=context["market"],
                    start_dt=start_dt,
                    end_dt=end_dt,
                )
                checkpoint_summary = self._run_checkpoint(
                    run_id=run_id,
                    checkpoint=checkpoint,
                    timeframe=timeframe,
                    market=context["market"],
                    strategy_mode=strategy_mode,
                    strategy_profile_binding=strategy_profile_binding,
                    ai_dynamic_strategy=ai_dynamic_strategy,
                    ai_dynamic_strength=ai_dynamic_strength,
                    ai_dynamic_lookback=ai_dynamic_lookback,
                    engine=temp_engine,
                    portfolio=temp_portfolio,
                    signal_service=temp_signal_service,
                )
                with self.db.write_batch():
                    if checkpoint_summary.get("cancelled"):
                        cancelled = True
                        self.db.append_sim_run_event(
                            run_id,
                            f"已在第 {checkpoint_index}/{len(checkpoints)} 个检查点内响应取消请求。",
                            level="warning",
                        )
                        break
                    checkpoint_signals = checkpoint_summary.get("signals") or []
                    if checkpoint_signals:
                        self.db.upsert_sim_run_signals(run_id, checkpoint_signals)
                    if int(checkpoint_summary.get("auto_executed") or 0) > 0:
                        incremental_trades = temp_db.get_trade_history(limit=10000)
                        incremental_snapshots = self._sort_snapshots_chronologically(
                            [
                                snapshot
                                for snapshot in temp_db.get_account_snapshots(limit=10000)
                                if str(snapshot.get("run_reason") or "").startswith("historical_range@")
                            ]
                        )
                        self.db.replace_sim_run_runtime_results(
                            run_id,
                            trades=incremental_trades,
                            snapshots=incremental_snapshots,
                            positions=temp_portfolio.list_positions(),
                        )
                    self.db.add_sim_run_checkpoint(
                        run_id,
                        checkpoint_at=checkpoint_text,
                        candidates_scanned=int(checkpoint_summary["candidates_scanned"]),
                        positions_checked=int(checkpoint_summary["positions_checked"]),
                        signals_created=int(checkpoint_summary["signals_created"]),
                        auto_executed=int(checkpoint_summary["auto_executed"]),
                        available_cash=float(checkpoint_summary["available_cash"]),
                        market_value=float(checkpoint_summary["market_value"]),
                        total_equity=float(checkpoint_summary["total_equity"]),
                        metadata={
                            "positions": checkpoint_summary.get("positions") or [],
                            "realized_pnl": checkpoint_summary.get("realized_pnl") or 0,
                            "unrealized_pnl": checkpoint_summary.get("unrealized_pnl") or 0,
                            "slot_summary": checkpoint_summary.get("slot_summary") or {},
                        },
                    )
                    self.db.update_sim_run_progress(
                        run_id,
                        progress_current=checkpoint_index,
                        progress_total=len(checkpoints),
                        latest_checkpoint_at=checkpoint_text,
                        status_message=f"已完成第 {checkpoint_index}/{len(checkpoints)} 个检查点",
                    )
                    self.db.append_sim_run_event(
                        run_id,
                        f"已完成第 {checkpoint_index}/{len(checkpoints)} 个检查点，当前总权益 {float(checkpoint_summary['total_equity']):.2f}。",
                    )

            trades = temp_db.get_trade_history(limit=10000)
            snapshots = self._sort_snapshots_chronologically(
                [
                    snapshot
                    for snapshot in temp_db.get_account_snapshots(limit=10000)
                    if str(snapshot.get("run_reason") or "").startswith("historical_range@")
                ]
            )
            positions = temp_portfolio.list_positions()
            metrics = self._calculate_run_metrics(account_summary["initial_cash"], trades, snapshots)
            final_slot_summary = self._collect_slot_summary(temp_db)

            if cancelled:
                completed_checkpoints = len(self.db.get_sim_run_checkpoints(run_id))
                with self.db.write_batch():
                    self.db.replace_sim_run_runtime_results(
                        run_id,
                        trades=trades,
                        snapshots=snapshots,
                        positions=positions,
                    )
                    self.db.finalize_sim_run(
                        run_id,
                        status="cancelled",
                        final_equity=float(metrics["final_equity"]),
                        total_return_pct=float(metrics["total_return_pct"]),
                        max_drawdown_pct=float(metrics["max_drawdown_pct"]),
                        win_rate=float(metrics["win_rate"]),
                        trade_count=len(trades),
                        status_message="回放任务已取消",
                        metadata={"checkpoint_count": completed_checkpoints, "final_slot_summary": final_slot_summary},
                    )
                    self.db.append_sim_run_event(run_id, "回放任务已取消。", level="warning")
                return {
                    "run_id": run_id,
                    "status": "cancelled",
                    "checkpoint_count": completed_checkpoints,
                    "trade_count": len(trades),
                    "final_equity": metrics["final_equity"],
                    "total_return_pct": metrics["total_return_pct"],
                    "max_drawdown_pct": metrics["max_drawdown_pct"],
                    "win_rate": metrics["win_rate"],
                    "handoff_to_live": False,
                }

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
                    status_message="回放任务已完成",
                    metadata={"checkpoint_count": len(checkpoints), "final_slot_summary": final_slot_summary},
                )
                self.db.append_sim_run_event(run_id, f"回放任务已完成，共生成 {len(trades)} 笔交易。", level="success")

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
            partial_trades: list[dict] = []
            partial_snapshots: list[dict] = []
            partial_positions: list[dict] = []
            partial_slot_summary: dict = {}
            if "temp_db" in locals() and "temp_portfolio" in locals():
                partial_trades = temp_db.get_trade_history(limit=10000)
                partial_snapshots = self._sort_snapshots_chronologically(
                    [
                        snapshot
                        for snapshot in temp_db.get_account_snapshots(limit=10000)
                        if str(snapshot.get("run_reason") or "").startswith("historical_range@")
                    ]
                )
                partial_positions = temp_portfolio.list_positions()
                partial_slot_summary = self._collect_slot_summary(temp_db)

            metrics = self._calculate_run_metrics(account_summary["initial_cash"], partial_trades, partial_snapshots)
            failure_context = ""
            if "last_checkpoint_index" in locals() and last_checkpoint_index > 0:
                failure_context = f"第 {last_checkpoint_index}/{len(checkpoints)} 个检查点"
                if last_checkpoint_text:
                    failure_context = f"{failure_context}（{last_checkpoint_text}）"
                failure_context = f"{failure_context} 失败："
            status_message = f"{failure_context}{exc}" if failure_context else f"回放任务失败：{exc}"
            with self.db.write_batch():
                if partial_trades or partial_snapshots or partial_positions:
                    self.db.replace_sim_run_runtime_results(
                        run_id,
                        trades=partial_trades,
                        snapshots=partial_snapshots,
                        positions=partial_positions,
                    )
                self.db.finalize_sim_run(
                    run_id,
                    status="failed",
                    final_equity=float(metrics["final_equity"]),
                    total_return_pct=float(metrics["total_return_pct"]),
                    max_drawdown_pct=float(metrics["max_drawdown_pct"]),
                    win_rate=float(metrics["win_rate"]),
                    trade_count=len(partial_trades),
                    status_message=status_message,
                    metadata={
                        "error": str(exc),
                        "failed_checkpoint_index": locals().get("last_checkpoint_index", 0),
                        "failed_checkpoint_at": locals().get("last_checkpoint_text", ""),
                        "final_slot_summary": partial_slot_summary,
                    },
                )
                self.db.append_sim_run_event(run_id, status_message, level="error")
            raise
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _run_checkpoint(
        self,
        *,
        run_id: int | None = None,
        run_type: str = "historical_replay",
        checkpoint: datetime,
        timeframe: str,
        market: str = "CN",
        strategy_mode: str = "auto",
        strategy_profile_binding: dict | None = None,
        ai_dynamic_strategy: str = DEFAULT_AI_DYNAMIC_STRATEGY,
        ai_dynamic_strength: float = DEFAULT_AI_DYNAMIC_STRENGTH,
        ai_dynamic_lookback: int = DEFAULT_AI_DYNAMIC_LOOKBACK,
        engine: QuantSimEngine,
        portfolio: PortfolioService,
        signal_service: SignalCenterService,
        candidate_quant_statuses: tuple[str, ...] | list[str] | None = None,
        candidates_override: list[dict[str, Any]] | None = None,
        auto_execute_signals: bool = True,
        auto_execute_note: str = "历史回放自动执行",
        account_snapshot_reason_prefix: str | None = "historical_range",
    ) -> dict:
        positions = portfolio.list_positions()
        held_codes = {
            str(item.get("stock_code") or "").strip()
            for item in positions
            if str(item.get("stock_code") or "").strip()
        }
        raw_candidates = candidates_override if candidates_override is not None else engine.candidate_pool.list_candidates(
            status="active",
            quant_statuses=candidate_quant_statuses,
        )
        candidates = [
            item
            for item in raw_candidates
            if str(item.get("stock_code") or "").strip() not in held_codes
        ]
        signals_created = 0
        candidates_scanned = 0
        positions_checked = 0
        checkpoint_signals: list[dict] = []
        checkpoint_text = self._format_datetime(checkpoint)
        checkpoint_utc = self._market_time_to_utc(checkpoint, market)
        base_profile_id = (
            str(strategy_profile_binding.get("profile_id") or "").strip()
            if isinstance(strategy_profile_binding, dict)
            else None
        )
        dynamic_mode = (
            str(ai_dynamic_strategy).strip().lower()
            if ai_dynamic_strategy is not None
            else DEFAULT_AI_DYNAMIC_STRATEGY
        )
        effective_strategy_profile_binding = None
        if dynamic_mode == DEFAULT_AI_DYNAMIC_STRATEGY:
            effective_strategy_profile_binding = engine._resolve_strategy_binding(
                strategy_profile_id=base_profile_id,
                ai_dynamic_strategy=ai_dynamic_strategy,
                ai_dynamic_strength=ai_dynamic_strength,
                ai_dynamic_lookback=ai_dynamic_lookback,
            )

        for candidate in candidates:
            if run_id is not None and self.db.is_sim_run_cancel_requested(run_id):
                return {
                    "cancelled": True,
                    "candidates_scanned": candidates_scanned,
                    "positions_checked": positions_checked,
                    "signals_created": signals_created,
                    "auto_executed": 0,
                    "available_cash": portfolio.get_account_summary()["available_cash"],
                    "market_value": portfolio.get_account_summary()["market_value"],
                    "total_equity": portfolio.get_account_summary()["total_equity"],
                    "signals": checkpoint_signals,
                }

            candidates_scanned += 1
            snapshot = self.snapshot_provider.get_snapshot(
                candidate["stock_code"],
                checkpoint,
                timeframe,
                stock_name=candidate.get("stock_name"),
            )
            if not snapshot:
                self._record_missing_run_market_artifact(
                    run_id=run_id,
                    run_type=run_type,
                    stock_code=str(candidate["stock_code"]),
                    checkpoint=checkpoint,
                    timeframe=timeframe,
                    market=market,
                )
                continue
            snapshot = self._attach_run_market_artifact(
                run_id=run_id,
                run_type=run_type,
                stock_code=str(candidate["stock_code"]),
                checkpoint=checkpoint,
                timeframe=timeframe,
                market=market,
                snapshot=snapshot,
            )
            candidate_binding = effective_strategy_profile_binding
            if dynamic_mode != DEFAULT_AI_DYNAMIC_STRATEGY:
                candidate_binding = engine._resolve_strategy_binding(
                    strategy_profile_id=base_profile_id,
                    ai_dynamic_strategy=ai_dynamic_strategy,
                    ai_dynamic_strength=ai_dynamic_strength,
                    ai_dynamic_lookback=ai_dynamic_lookback,
                    stock_code=str(candidate.get("stock_code") or ""),
                    stock_name=str(candidate.get("stock_name") or ""),
                    as_of=checkpoint,
                )
            decision = engine._evaluate_candidate_decision(
                candidate,
                market_snapshot=snapshot,
                analysis_timeframe=timeframe,
                strategy_mode=strategy_mode,
                strategy_profile_binding=candidate_binding,
                current_time=checkpoint,
            )
            decision = self._with_replay_decision_time(decision, checkpoint)
            decision_price = engine._extract_decision_price(decision)
            if decision_price > 0:
                engine.candidate_pool.db.update_candidate_latest_price(candidate["stock_code"], decision_price)
            signal = signal_service.create_signal(candidate, decision, notify=False, mirror_to_ai=False, dedupe_pending=False)
            signal["checkpoint_at"] = self._format_datetime(checkpoint)
            checkpoint_signals.append(signal)
            signals_created += 1

        for position in positions:
            candidate = engine.candidate_pool.db.get_candidate(position["stock_code"]) or {
                "stock_code": position["stock_code"],
                "stock_name": position.get("stock_name"),
                "source": "manual",
                "sources": ["manual"],
            }
            if run_id is not None and self.db.is_sim_run_cancel_requested(run_id):
                return {
                    "cancelled": True,
                    "candidates_scanned": candidates_scanned,
                    "positions_checked": positions_checked,
                    "signals_created": signals_created,
                    "auto_executed": 0,
                    "available_cash": portfolio.get_account_summary()["available_cash"],
                    "market_value": portfolio.get_account_summary()["market_value"],
                    "total_equity": portfolio.get_account_summary()["total_equity"],
                    "signals": checkpoint_signals,
                }

            positions_checked += 1
            snapshot = self.snapshot_provider.get_snapshot(
                position["stock_code"],
                checkpoint,
                timeframe,
                stock_name=candidate.get("stock_name") or position.get("stock_name"),
            )
            if not snapshot:
                snapshot = self._record_missing_run_market_artifact(
                    run_id=run_id,
                    run_type=run_type,
                    stock_code=str(position["stock_code"]),
                    checkpoint=checkpoint,
                    timeframe=timeframe,
                    market=market,
                )
            else:
                snapshot = self._attach_run_market_artifact(
                    run_id=run_id,
                    run_type=run_type,
                    stock_code=str(position["stock_code"]),
                    checkpoint=checkpoint,
                    timeframe=timeframe,
                    market=market,
                    snapshot=snapshot,
                )
            position_binding = effective_strategy_profile_binding
            if dynamic_mode != DEFAULT_AI_DYNAMIC_STRATEGY:
                position_binding = engine._resolve_strategy_binding(
                    strategy_profile_id=base_profile_id,
                    ai_dynamic_strategy=ai_dynamic_strategy,
                    ai_dynamic_strength=ai_dynamic_strength,
                    ai_dynamic_lookback=ai_dynamic_lookback,
                    stock_code=str(candidate.get("stock_code") or position.get("stock_code") or ""),
                    stock_name=str(candidate.get("stock_name") or position.get("stock_name") or ""),
                    as_of=checkpoint,
                )
            decision = engine._evaluate_position_decision(
                candidate,
                position,
                market_snapshot=snapshot,
                analysis_timeframe=timeframe,
                strategy_mode=strategy_mode,
                strategy_profile_binding=position_binding,
                current_time=checkpoint,
            )
            decision = self._with_replay_decision_time(decision, checkpoint)
            decision_price = engine._extract_decision_price(decision)
            if decision_price > 0:
                portfolio.db.update_position_market_price(position["stock_code"], decision_price)
                portfolio.db.update_candidate_latest_price(position["stock_code"], decision_price)
            signal = signal_service.create_signal(candidate, decision, notify=False, mirror_to_ai=False, dedupe_pending=False)
            signal["checkpoint_at"] = self._format_datetime(checkpoint)
            checkpoint_signals.append(signal)
            signals_created += 1

        pending_signals = [
            signal
            for signal in checkpoint_signals
            if str(signal.get("status") or "").lower() == "pending"
            and str(signal.get("action") or "").upper() in {"BUY", "SELL"}
        ]
        auto_executed = 0
        if auto_execute_signals:
            try:
                auto_executed = portfolio.auto_execute_pending_signals(
                    pending_signals,
                    note=auto_execute_note,
                    executed_at=checkpoint_utc,
                )
            except Exception as exc:
                if run_id is not None:
                    self.db.append_sim_run_event(
                        run_id,
                        f"检查点 {self._format_datetime(checkpoint)} 自动执行批量信号失败：{exc}",
                        level="error",
                    )

        checkpoint_signals = self._finalize_checkpoint_signals(
            signal_service.db,
            checkpoint_signals,
            checkpoint_at=checkpoint_text,
        )
        if account_snapshot_reason_prefix:
            portfolio.db.add_account_snapshot(run_reason=f"{account_snapshot_reason_prefix}@{self._format_datetime(checkpoint)}")
        account_summary = portfolio.get_account_summary()
        positions = portfolio.list_positions()
        return {
            "cancelled": False,
            "candidates_scanned": candidates_scanned,
            "positions_checked": positions_checked,
            "signals_created": signals_created,
            "auto_executed": auto_executed,
            "available_cash": account_summary["available_cash"],
            "market_value": account_summary["market_value"],
            "total_equity": account_summary["total_equity"],
            "realized_pnl": account_summary.get("realized_pnl", 0),
            "unrealized_pnl": account_summary.get("unrealized_pnl", 0),
            "positions": self._collect_position_snapshot(positions),
            "slot_summary": self._collect_slot_summary(portfolio.db),
            "signals": checkpoint_signals,
        }

    def _attach_run_market_artifact(
        self,
        *,
        run_id: int | None,
        run_type: str,
        stock_code: str,
        checkpoint: datetime,
        timeframe: str,
        market: str,
        snapshot: dict,
    ) -> dict:
        """Persist the run-scoped artifact and attach its ref to the decision facts."""

        if run_id is None:
            return snapshot
        write_run_artifact_from_snapshot(
            RunArtifactContext(
                db_file=self.replay_db_file,
                run_id=run_id,
                run_type=run_type,
                market=market,
                timeframe=timeframe,
                trace_id=f"{run_type}:{run_id}",
            ),
            stock_code=stock_code,
            checkpoint=checkpoint,
            snapshot=snapshot,
        )
        artifact_payload = read_run_artifact(
            RunArtifactContext(
                db_file=self.replay_db_file,
                run_id=run_id,
                run_type=run_type,
                market=market,
                timeframe=timeframe,
                trace_id=f"{run_type}:{run_id}",
            ),
            stock_code=stock_code,
            checkpoint=checkpoint,
        )
        return dict(artifact_payload)

    def _record_missing_run_market_artifact(
        self,
        *,
        run_id: int | None,
        run_type: str,
        stock_code: str,
        checkpoint: datetime,
        timeframe: str,
        market: str,
    ) -> dict[str, Any]:
        """Persist a run-scoped missing artifact so skipped snapshots remain auditable."""

        if run_id is None:
            return {"source_status": "missing", "reason_code": "missing_artifact"}
        return write_missing_run_artifact(
            RunArtifactContext(
                db_file=self.replay_db_file,
                run_id=run_id,
                run_type=run_type,
                market=market,
                timeframe=timeframe,
                trace_id=f"{run_type}:{run_id}",
            ),
            stock_code=stock_code,
            checkpoint=checkpoint,
        )

    @staticmethod
    def _finalize_checkpoint_signals(
        db: QuantSimDB,
        checkpoint_signals: list[dict],
        *,
        checkpoint_at: str,
    ) -> list[dict]:
        refreshed: list[dict] = []
        for signal in checkpoint_signals:
            signal_id = signal.get("id")
            current = db.get_signal(int(signal_id)) if signal_id not in (None, "") else None
            if current is None:
                current = dict(signal)
            if str(current.get("status") or "").lower() == "pending":
                note = str(current.get("execution_note") or "").strip()
                if not note:
                    note = "历史回放本检查点未执行，信号已过期。"
                db.update_signal_state(int(current["id"]), status="ignored", execution_note=note)
                current = db.get_signal(int(current["id"])) or current
            current["checkpoint_at"] = checkpoint_at
            refreshed.append(current)
        return refreshed

    def _with_replay_decision_time(self, decision: dict | Decision, checkpoint: datetime) -> dict | Decision:
        if isinstance(decision, Decision):
            decision.timestamp = checkpoint
            return decision
        if isinstance(decision, dict):
            stamped = dict(decision)
            stamped["timestamp"] = checkpoint
            stamped["decision_time"] = checkpoint
            stamped["checkpoint_at"] = self._format_datetime(checkpoint)
            return stamped
        return decision

    def _apply_due_corporate_actions(
        self,
        *,
        temp_db: QuantSimDB,
        checkpoint: datetime,
        market: str = "CN",
        start_dt: datetime,
        end_dt: datetime,
    ) -> None:
        positions = temp_db.get_positions(as_of=checkpoint)
        if not positions:
            return
        checkpoint_text = format_utc_iso_z(self._market_time_to_utc(checkpoint, market))
        ex_date = checkpoint.date().isoformat()
        actions: list[dict] = []
        for position in positions:
            stock_code = str(position.get("stock_code") or "").strip()
            if not stock_code:
                continue
            try:
                stock_actions = self.corporate_action_provider.get_actions(stock_code, start_dt, end_dt)
            except Exception:
                stock_actions = []
            actions.extend(
                {**action, "stock_code": stock_code}
                for action in stock_actions
                if str(action.get("ex_date") or "").strip() == ex_date
            )
        for action in actions:
            temp_db.apply_corporate_action(
                stock_code=str(action.get("stock_code") or ""),
                ex_date=str(action.get("ex_date") or checkpoint.date().isoformat()),
                record_date=str(action.get("record_date") or "") or None,
                bonus_share_ratio=float(action.get("bonus_share_ratio") or 0.0),
                cash_dividend_per_share=float(action.get("cash_dividend_per_share") or 0.0),
                description=str(action.get("description") or ""),
                applied_at=checkpoint_text,
            )

    @staticmethod
    def _collect_open_lots(temp_db: QuantSimDB, positions: list[dict], *, as_of: datetime) -> list[dict]:
        lots: list[dict] = []
        for position in positions:
            stock_code = str(position.get("stock_code") or "")
            if not stock_code:
                continue
            lots.extend(temp_db.get_position_lots(stock_code, as_of=as_of))
        return lots

    @staticmethod
    def _collect_position_snapshot(positions: list[dict]) -> list[dict]:
        snapshot: list[dict] = []
        for position in positions:
            stock_code = str(position.get("stock_code") or "").strip()
            quantity = int(position.get("quantity") or 0)
            if not stock_code or quantity <= 0:
                continue
            snapshot.append(
                {
                    "stock_code": stock_code,
                    "stock_name": str(position.get("stock_name") or stock_code),
                    "quantity": quantity,
                    "avg_price": float(position.get("avg_price") or 0),
                    "latest_price": float(position.get("latest_price") or 0),
                    "market_value": float(position.get("market_value") or 0),
                    "unrealized_pnl": float(position.get("unrealized_pnl") or 0),
                    "sellable_quantity": int(position.get("sellable_quantity") or 0),
                    "locked_quantity": int(position.get("locked_quantity") or 0),
                }
            )
        return snapshot

    @staticmethod
    def _collect_slot_summary(temp_db: QuantSimDB) -> dict:
        slots = temp_db.get_capital_slots()
        if not slots:
            return {}
        slot_count = len(slots)
        total_budget = sum(float(slot.get("budget_cash") or 0) for slot in slots)
        return {
            "slot_count": slot_count,
            "slot_budget": round(total_budget / slot_count, 4) if slot_count else 0.0,
            "available_cash": round(sum(float(slot.get("available_cash") or 0) for slot in slots), 4),
            "occupied_cash": round(sum(float(slot.get("occupied_cash") or 0) for slot in slots), 4),
            "settling_cash": round(sum(float(slot.get("settling_cash") or 0) for slot in slots), 4),
        }

    @staticmethod
    def _calculate_run_metrics(initial_cash: float, trades: list[dict], snapshots: list[dict]) -> dict:
        snapshot_equity_curve = [float(snapshot.get("total_equity") or 0) for snapshot in snapshots]
        final_equity = snapshot_equity_curve[-1] if snapshot_equity_curve else float(initial_cash)

        peak = float(initial_cash)
        max_drawdown_pct = 0.0
        for equity in snapshot_equity_curve:
            peak = max(peak, equity)
            if peak <= 0:
                continue
            drawdown_pct = (peak - equity) / peak * 100
            max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

        closed_trades = [trade for trade in trades if str(trade.get("action")).upper() == "SELL"]
        profitable_trades = [trade for trade in closed_trades if float(trade.get("realized_pnl") or 0) > 0]
        win_rate = (len(profitable_trades) / len(closed_trades) * 100) if closed_trades else 0.0

        return {
            "final_equity": round(final_equity, 4),
            "total_return_pct": round(((final_equity - initial_cash) / initial_cash * 100) if initial_cash > 0 else 0.0, 4),
            "max_drawdown_pct": round(max_drawdown_pct, 4),
            "win_rate": round(win_rate, 4),
        }

    @staticmethod
    def _to_datetime(value: datetime | str) -> datetime:
        if isinstance(value, datetime):
            return value.replace(microsecond=0)
        return datetime.fromisoformat(str(value).replace("T", " ")).replace(microsecond=0)

    @classmethod
    def _parse_optional_naive_utc(cls, value: Any) -> datetime | None:
        try:
            return cls._to_naive_utc(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_naive_utc(value: Any) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        else:
            text = str(value or "").strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed.replace(microsecond=0)

    def _resolve_end_datetime(self, value: datetime | str | None) -> datetime:
        if value is None:
            return self._current_time()
        return self._to_datetime(value)

    def _current_time(self) -> datetime:
        return datetime.now().replace(microsecond=0)

    def _sort_snapshots_chronologically(self, snapshots: list[dict]) -> list[dict]:
        return sorted(
            snapshots,
            key=lambda snapshot: (
                self._extract_snapshot_checkpoint_time(snapshot),
                int(snapshot.get("id") or 0),
            ),
        )

    def _extract_snapshot_checkpoint_time(self, snapshot: dict) -> datetime:
        run_reason = str(snapshot.get("run_reason") or "")
        if "@" in run_reason:
            _, _, suffix = run_reason.partition("@")
            try:
                return self._to_datetime(suffix)
            except ValueError:
                pass
        created_at = snapshot.get("created_at")
        if created_at:
            try:
                return self._to_datetime(str(created_at))
            except ValueError:
                pass
        return datetime.min

    @staticmethod
    def _format_datetime(value: datetime) -> str:
        return value.replace(microsecond=0).isoformat(sep=" ")

    @staticmethod
    def _market_time_to_utc(value: datetime, market: str = "CN") -> datetime:
        local_value = (
            value.replace(tzinfo=market_timezone(market))
            if value.tzinfo is None
            else value.astimezone(market_timezone(market))
        )
        return local_value.astimezone(timezone.utc).replace(microsecond=0)
