"""Historical replay orchestration for quant simulation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from app.data_source_manager import data_source_manager
from app.db.runtime.registry import DatabaseRuntime
from app.quant_kernel import TradingTimeUtils
from app.quant_sim.corporate_actions import AkshareCorporateActionProvider
from app.quant_sim.dynamic_strategy import DEFAULT_AI_DYNAMIC_LOOKBACK, DEFAULT_AI_DYNAMIC_STRENGTH, DEFAULT_AI_DYNAMIC_STRATEGY
from app.quant_sim.live_quant_drill_candidates import estimate_candidate_generation
from app.quant_sim.replay_runner import get_quant_sim_replay_runner
from app.quant_sim.stockpolicy_adapter import StockPolicyAdapter
from app.quant_sim.replay_service_base import MainProjectHistoricalSnapshotProvider, QuantSimReplayServiceBase
from app.quant_sim.replay_service_drill import LiveQuantDrillMixin
from app.quant_sim.replay_service_drill_candidates import LiveQuantDrillCandidateMixin
from app.quant_sim.replay_service_historical import HistoricalReplayMixin


class QuantSimReplayService(
    LiveQuantDrillMixin,
    LiveQuantDrillCandidateMixin,
    HistoricalReplayMixin,
    QuantSimReplayServiceBase,
):
    """Execute historical replay and live-quant drill runs."""

    @staticmethod
    def _estimate_candidate_generation(**kwargs):
        return estimate_candidate_generation(**kwargs)
    def run_historical_range(
        self,
        *,
        start_datetime: datetime | str,
        end_datetime: datetime | str | None,
        timeframe: str,
        market: str,
        strategy_mode: str = "auto",
        strategy_profile_id: str | None = None,
        initial_cash: float | None = None,
        ai_dynamic_strategy: str = DEFAULT_AI_DYNAMIC_STRATEGY,
        ai_dynamic_strength: float = DEFAULT_AI_DYNAMIC_STRENGTH,
        ai_dynamic_lookback: int = DEFAULT_AI_DYNAMIC_LOOKBACK,
        commission_rate: float | None = None,
        sell_tax_rate: float | None = None,
    ) -> dict:
        context = self._prepare_replay_context(
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            timeframe=timeframe,
            market=market,
            strategy_mode=strategy_mode,
            strategy_profile_id=strategy_profile_id,
            initial_cash=initial_cash,
            ai_dynamic_strategy=ai_dynamic_strategy,
            ai_dynamic_strength=ai_dynamic_strength,
            ai_dynamic_lookback=ai_dynamic_lookback,
            commission_rate=commission_rate,
            sell_tax_rate=sell_tax_rate,
        )
        if hasattr(self.adapter, "set_market"):
            self.adapter.set_market(market)
        run_id = self._create_replay_run(
            mode="historical_range",
            handoff_to_live=False,
            timeframe=timeframe,
            market=market,
            context=context,
            status="running",
            status_message="正在同步执行历史回放",
        )
        return self._execute_prepared_replay(
            run_id=run_id,
            mode="historical_range",
            handoff_to_live=False,
            context=context,
            auto_start_scheduler=False,
        )

    def run_past_to_live(
        self,
        *,
        start_datetime: datetime | str,
        end_datetime: datetime | str | None,
        timeframe: str,
        market: str,
        strategy_mode: str = "auto",
        strategy_profile_id: str | None = None,
        initial_cash: float | None = None,
        ai_dynamic_strategy: str = DEFAULT_AI_DYNAMIC_STRATEGY,
        ai_dynamic_strength: float = DEFAULT_AI_DYNAMIC_STRENGTH,
        ai_dynamic_lookback: int = DEFAULT_AI_DYNAMIC_LOOKBACK,
        commission_rate: float | None = None,
        sell_tax_rate: float | None = None,
        overwrite_live: bool = False,
        auto_start_scheduler: bool = True,
    ) -> dict:
        del (
            start_datetime,
            end_datetime,
            timeframe,
            market,
            strategy_mode,
            strategy_profile_id,
            initial_cash,
            ai_dynamic_strategy,
            ai_dynamic_strength,
            ai_dynamic_lookback,
            commission_rate,
            sell_tax_rate,
            overwrite_live,
            auto_start_scheduler,
        )
        raise ValueError("接续到实时模拟账户已停用，请使用历史回放查看独立回放结果。")

    def enqueue_historical_range(
        self,
        *,
        start_datetime: datetime | str,
        end_datetime: datetime | str | None,
        timeframe: str,
        market: str,
        strategy_mode: str = "auto",
        strategy_profile_id: str | None = None,
        initial_cash: float | None = None,
        ai_dynamic_strategy: str = DEFAULT_AI_DYNAMIC_STRATEGY,
        ai_dynamic_strength: float = DEFAULT_AI_DYNAMIC_STRENGTH,
        ai_dynamic_lookback: int = DEFAULT_AI_DYNAMIC_LOOKBACK,
        commission_rate: float | None = None,
        sell_tax_rate: float | None = None,
    ) -> int:
        self._ensure_no_active_replay()
        context = self._prepare_replay_context(
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            timeframe=timeframe,
            market=market,
            strategy_mode=strategy_mode,
            strategy_profile_id=strategy_profile_id,
            initial_cash=initial_cash,
            ai_dynamic_strategy=ai_dynamic_strategy,
            ai_dynamic_strength=ai_dynamic_strength,
            ai_dynamic_lookback=ai_dynamic_lookback,
            commission_rate=commission_rate,
            sell_tax_rate=sell_tax_rate,
        )
        run_id = self._create_replay_run(
            mode="historical_range",
            handoff_to_live=False,
            timeframe=timeframe,
            market=market,
            context=context,
            status="queued",
            status_message="等待后台任务启动",
        )
        if self.db_runtime is None:
            runner = get_quant_sim_replay_runner(db_file=self.replay_db_file)
        else:
            runner = get_quant_sim_replay_runner(db_file=self.replay_db_file, db_runtime=self.db_runtime)
        started = runner.start_run(
            run_id,
            execute_prepared_replay_worker,
            self.db_file,
            self.replay_db_file,
            run_id,
            "historical_range",
            False,
            context,
            False,
        )
        if not started:
            self.db.finalize_sim_run(
                run_id,
                status="failed",
                final_equity=float(context["account_summary"]["initial_cash"]),
                total_return_pct=0.0,
                max_drawdown_pct=0.0,
                win_rate=0.0,
                trade_count=0,
                status_message="后台回放任务启动失败",
                metadata={"error": "background replay start failed"},
            )
            raise RuntimeError("后台回放任务启动失败")
        return run_id

    def enqueue_live_quant_drill(
        self,
        *,
        start_datetime: datetime | str,
        end_datetime: datetime | str | None,
        timeframe: str,
        market: str,
        strategy_profile_id: str | None = None,
        initial_cash: float | None = None,
        ai_dynamic_strategy: str = DEFAULT_AI_DYNAMIC_STRATEGY,
        ai_dynamic_strength: float = DEFAULT_AI_DYNAMIC_STRENGTH,
        ai_dynamic_lookback: int = DEFAULT_AI_DYNAMIC_LOOKBACK,
        auto_entry_enabled: bool = True,
        auto_exit_enabled: bool = True,
        execute_trades: bool = True,
        liquidate_at_end: bool = True,
        seed_current_quant_universe: bool = True,
        generate_historical_candidate_events: bool = True,
        candidate_generation_frequency: str = "daily_first_checkpoint",
        candidate_generation_checkpoint_interval: int = 8,
        confirm_long_running: bool = False,
    ) -> int:
        self._ensure_no_active_replay()
        context = self._prepare_live_quant_drill_context(
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            timeframe=timeframe,
            market=market,
            strategy_profile_id=strategy_profile_id,
            initial_cash=initial_cash,
            ai_dynamic_strategy=ai_dynamic_strategy,
            ai_dynamic_strength=ai_dynamic_strength,
            ai_dynamic_lookback=ai_dynamic_lookback,
            auto_entry_enabled=auto_entry_enabled,
            auto_exit_enabled=auto_exit_enabled,
            execute_trades=execute_trades,
            liquidate_at_end=liquidate_at_end,
            seed_current_quant_universe=seed_current_quant_universe,
            generate_historical_candidate_events=generate_historical_candidate_events,
            candidate_generation_frequency=candidate_generation_frequency,
            candidate_generation_checkpoint_interval=candidate_generation_checkpoint_interval,
        )
        estimated_invocations = int((context.get("candidate_generation") or {}).get("estimated_strategy_invocations") or 0)
        if estimated_invocations > self.LIVE_QUANT_DRILL_LONG_RUNNING_INVOCATION_LIMIT and not confirm_long_running:
            raise ValueError("Long running drill requires confirmation")

        run_id = self._create_replay_run(
            mode="live_quant_drill",
            handoff_to_live=False,
            timeframe=timeframe,
            market=market,
            context=context,
            status="queued",
            status_message="等待后台实时量化演练任务启动",
        )
        if self.db_runtime is None:
            runner = get_quant_sim_replay_runner(db_file=self.replay_db_file)
        else:
            runner = get_quant_sim_replay_runner(db_file=self.replay_db_file, db_runtime=self.db_runtime)
        started = runner.start_run(
            run_id,
            execute_live_quant_drill_worker,
            self.db_file,
            self.replay_db_file,
            run_id,
            context,
        )
        if not started:
            self.db.finalize_sim_run(
                run_id,
                status="failed",
                final_equity=float(context["account_summary"]["initial_cash"]),
                total_return_pct=0.0,
                max_drawdown_pct=0.0,
                win_rate=0.0,
                trade_count=0,
                status_message="后台实时量化演练任务启动失败",
                metadata={"error": "background live quant drill start failed"},
            )
            raise RuntimeError("后台实时量化演练任务启动失败")
        return run_id

    def run_live_quant_drill(
        self,
        *,
        start_datetime: datetime | str,
        end_datetime: datetime | str | None,
        timeframe: str,
        market: str,
        strategy_profile_id: str | None = None,
        initial_cash: float | None = None,
        ai_dynamic_strategy: str = DEFAULT_AI_DYNAMIC_STRATEGY,
        ai_dynamic_strength: float = DEFAULT_AI_DYNAMIC_STRENGTH,
        ai_dynamic_lookback: int = DEFAULT_AI_DYNAMIC_LOOKBACK,
        auto_entry_enabled: bool = True,
        auto_exit_enabled: bool = True,
        execute_trades: bool = True,
        liquidate_at_end: bool = True,
        seed_current_quant_universe: bool = True,
        generate_historical_candidate_events: bool = True,
        candidate_generation_frequency: str = "daily_first_checkpoint",
        candidate_generation_checkpoint_interval: int = 8,
    ) -> dict:
        self._ensure_no_active_replay()
        context = self._prepare_live_quant_drill_context(
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            timeframe=timeframe,
            market=market,
            strategy_profile_id=strategy_profile_id,
            initial_cash=initial_cash,
            ai_dynamic_strategy=ai_dynamic_strategy,
            ai_dynamic_strength=ai_dynamic_strength,
            ai_dynamic_lookback=ai_dynamic_lookback,
            auto_entry_enabled=auto_entry_enabled,
            auto_exit_enabled=auto_exit_enabled,
            execute_trades=execute_trades,
            liquidate_at_end=liquidate_at_end,
            seed_current_quant_universe=seed_current_quant_universe,
            generate_historical_candidate_events=generate_historical_candidate_events,
            candidate_generation_frequency=candidate_generation_frequency,
            candidate_generation_checkpoint_interval=candidate_generation_checkpoint_interval,
        )
        run_id = self._create_replay_run(
            mode="live_quant_drill",
            handoff_to_live=False,
            timeframe=timeframe,
            market=market,
            context=context,
            status="running",
            status_message="正在同步执行实时量化演练",
        )
        return self._execute_live_quant_drill(run_id=run_id, context=context)

    def enqueue_past_to_live(
        self,
        *,
        start_datetime: datetime | str,
        end_datetime: datetime | str | None,
        timeframe: str,
        market: str,
        strategy_mode: str = "auto",
        strategy_profile_id: str | None = None,
        initial_cash: float | None = None,
        ai_dynamic_strategy: str = DEFAULT_AI_DYNAMIC_STRATEGY,
        ai_dynamic_strength: float = DEFAULT_AI_DYNAMIC_STRENGTH,
        ai_dynamic_lookback: int = DEFAULT_AI_DYNAMIC_LOOKBACK,
        commission_rate: float | None = None,
        sell_tax_rate: float | None = None,
        overwrite_live: bool = False,
        auto_start_scheduler: bool = True,
    ) -> int:
        del (
            start_datetime,
            end_datetime,
            timeframe,
            market,
            strategy_mode,
            strategy_profile_id,
            initial_cash,
            ai_dynamic_strategy,
            ai_dynamic_strength,
            ai_dynamic_lookback,
            commission_rate,
            sell_tax_rate,
            overwrite_live,
            auto_start_scheduler,
        )
        raise ValueError("接续到实时模拟账户已停用，请使用历史回放查看独立回放结果。")


def execute_prepared_replay_worker(
    db_file: str,
    replay_db_file: str,
    run_id: int,
    mode: str,
    handoff_to_live: bool,
    context: dict,
    auto_start_scheduler: bool,
) -> None:
    service = QuantSimReplayService(db_file=db_file, replay_db_file=replay_db_file)
    service._execute_prepared_replay(
        run_id=run_id,
        mode=mode,
        handoff_to_live=handoff_to_live,
        context=context,
        auto_start_scheduler=auto_start_scheduler,
    )


def execute_live_quant_drill_worker(
    db_file: str,
    replay_db_file: str,
    run_id: int,
    context: dict,
) -> None:
    service = QuantSimReplayService(db_file=db_file, replay_db_file=replay_db_file)
    service._execute_live_quant_drill(run_id=run_id, context=context)
