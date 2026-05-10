"""Historical replay orchestration for quant simulation."""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from app.db.runtime.registry import DatabaseRuntime
from app.data_source_manager import data_source_manager
from app.quant_kernel import ReplayTimepointGenerator
from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.capital_slots import DEFAULT_CAPITAL_SLOT_CONFIG
from app.quant_sim.corporate_actions import AkshareCorporateActionProvider
from app.quant_sim.db import DEFAULT_DB_FILE, DEFAULT_REPLAY_DB_FILE, QuantSimDB, QuantSimReplayDB
from app.quant_sim.dynamic_strategy import (
    DEFAULT_AI_DYNAMIC_LOOKBACK,
    DEFAULT_AI_DYNAMIC_STRENGTH,
    DEFAULT_AI_DYNAMIC_STRATEGY,
)
from app.quant_sim.engine import QuantSimEngine
from app.quant_sim.live_quant_drill_candidates import (
    CandidateGenerationConfig,
    CandidateSourceAvailability,
    estimate_candidate_generation,
    should_generate_candidates,
    should_skip_candidate_event_due_to_dedup,
    source_availability_for_checkpoint,
)
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.quant_universe_lifecycle import QuantUniverseManager
from app.quant_sim.replay_runner import get_quant_sim_replay_runner
from app.quant_sim.scheduler import get_quant_sim_scheduler
from app.quant_sim.signal_center_service import SignalCenterService
from app.quant_sim.stockpolicy_adapter import StockPolicyAdapter
from app.quant_sim.time_utils import format_utc_iso_z, market_timezone, market_timezone_name
from app.quant_kernel.models import Decision
from app.smart_monitor_tdx_data import SmartMonitorTDXDataFetcher


class MainProjectHistoricalSnapshotProvider:
    """Build replay snapshots using the main project's market-data stack."""

    DAILY_LOOKBACK_DAYS = 180
    INTRADAY_LOOKBACK_DAYS = 45
    DEFAULT_STOCK_BATCH_SIZE = max(1, int(os.getenv("REPLAY_DATA_STOCK_BATCH_SIZE", "20")))
    DEFAULT_DAILY_SEGMENT_DAYS = max(1, int(os.getenv("REPLAY_DATA_DAILY_SEGMENT_DAYS", "120")))
    DEFAULT_INTRADAY_SEGMENT_DAYS = max(1, int(os.getenv("REPLAY_DATA_INTRADAY_SEGMENT_DAYS", "90")))

    def __init__(
        self,
        *,
        tdx_fetcher: Optional[SmartMonitorTDXDataFetcher] = None,
        stock_batch_size: int | None = None,
        daily_segment_days: int | None = None,
        intraday_segment_days: int | None = None,
    ):
        self.tdx_fetcher = tdx_fetcher or SmartMonitorTDXDataFetcher()
        self.cache: dict[tuple[str, str], pd.DataFrame] = {}
        self.indicator_cache: dict[tuple[str, str], pd.DataFrame] = {}
        self.stock_batch_size = max(1, int(stock_batch_size or self.DEFAULT_STOCK_BATCH_SIZE))
        self.daily_segment_days = max(1, int(daily_segment_days or self.DEFAULT_DAILY_SEGMENT_DAYS))
        self.intraday_segment_days = max(1, int(intraday_segment_days or self.DEFAULT_INTRADAY_SEGMENT_DAYS))
        self.prepare_report: dict[str, object] = {
            "stock_batches": [],
            "segment_count": 0,
            "prepared": 0,
            "failed": 0,
            "failures": [],
        }

    def prepare(
        self,
        stock_codes: list[str],
        start_datetime: datetime,
        end_datetime: datetime,
        timeframe: str,
    ) -> None:
        data_timeframe = self._normalize_data_timeframe(timeframe)
        segments = self._build_segments(start_datetime, end_datetime, timeframe=data_timeframe)
        stock_batches = [stock_codes[index : index + self.stock_batch_size] for index in range(0, len(stock_codes), self.stock_batch_size)]
        failures: list[dict[str, str]] = []
        prepared = 0
        for batch in stock_batches:
            for stock_code in batch:
                try:
                    history = self._load_history_segments(
                        stock_code,
                        segments=segments,
                        timeframe=data_timeframe,
                    )
                    self.cache[(stock_code, timeframe)] = history
                    if history is None or history.empty:
                        failures.append({"stock_code": stock_code, "reason": "empty_history"})
                        continue
                    indicators = self.tdx_fetcher.build_indicator_history(stock_code, history, timeframe=data_timeframe)
                    if indicators is not None and not indicators.empty:
                        self.indicator_cache[(stock_code, timeframe)] = indicators
                    prepared += 1
                except Exception as exc:
                    failures.append({"stock_code": stock_code, "reason": f"{type(exc).__name__}: {exc}"})
                    self.cache[(stock_code, timeframe)] = pd.DataFrame(columns=["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"])
        self.prepare_report = {
            "stock_batches": [list(batch) for batch in stock_batches],
            "segment_count": len(segments),
            "prepared": prepared,
            "failed": len(failures),
            "failures": failures,
        }

    def get_snapshot(
        self,
        stock_code: str,
        checkpoint: datetime,
        timeframe: str,
        *,
        stock_name: Optional[str] = None,
    ) -> Optional[dict]:
        history = self.cache.get((stock_code, timeframe))
        if history is None or history.empty:
            return None

        window = history[history["日期"] <= pd.Timestamp(checkpoint)]
        if window.empty:
            return None

        snapshot_window = window.tail(240).reset_index(drop=True)
        indicator_frame = self.indicator_cache.get((stock_code, timeframe))
        resolved_name = stock_name if stock_name not in (None, "") else stock_code
        try:
            return self.tdx_fetcher.build_snapshot_from_history(
                stock_code,
                snapshot_window,
                stock_name=resolved_name,
                indicator_frame=indicator_frame,
            )
        except TypeError as exc:
            if "indicator_frame" not in str(exc):
                raise
            return self.tdx_fetcher.build_snapshot_from_history(
                stock_code,
                snapshot_window,
                stock_name=resolved_name,
            )

    def _load_history(
        self,
        stock_code: str,
        *,
        start_datetime: datetime,
        end_datetime: datetime,
        timeframe: str,
        include_lookback: bool = True,
    ) -> pd.DataFrame:
        normalized = self._normalize_data_timeframe(timeframe)
        if normalized in {"1d", "day", "daily"}:
            start_date = (start_datetime - timedelta(days=self.DAILY_LOOKBACK_DAYS) if include_lookback else start_datetime).strftime("%Y%m%d")
            end_date = end_datetime.strftime("%Y%m%d")
            df = data_source_manager.get_stock_hist_data(stock_code, start_date=start_date, end_date=end_date, adjust="")
            return self._normalize_daily_history(df)

        if normalized in {"30m", "30min", "minute30"}:
            intraday_history = self.tdx_fetcher.get_kline_data_range(
                stock_code,
                kline_type="minute30",
                start_datetime=start_datetime - timedelta(days=self.INTRADAY_LOOKBACK_DAYS) if include_lookback else start_datetime,
                end_datetime=end_datetime,
                max_bars=3200,
            )
            if isinstance(intraday_history, pd.DataFrame):
                return intraday_history
            if intraday_history is None:
                return pd.DataFrame(columns=["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"])
            frame = pd.DataFrame(intraday_history)
            if frame.empty:
                return pd.DataFrame(columns=["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"])
            return frame

        raise ValueError(f"Unsupported replay timeframe: {timeframe}")

    def _load_history_segments(
        self,
        stock_code: str,
        *,
        segments: list[tuple[datetime, datetime]],
        timeframe: str,
    ) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for segment_start, segment_end in segments:
            frame = self._load_history(
                stock_code,
                start_datetime=segment_start,
                end_datetime=segment_end,
                timeframe=timeframe,
                include_lookback=False,
            )
            if isinstance(frame, pd.DataFrame) and not frame.empty:
                frames.append(frame)
        if not frames:
            return pd.DataFrame(columns=["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"])
        merged = pd.concat(frames, ignore_index=True)
        if "日期" in merged.columns:
            merged["日期"] = pd.to_datetime(merged["日期"])
            merged = merged.drop_duplicates(subset=["日期"], keep="last").sort_values("日期").reset_index(drop=True)
        return merged

    def _build_segments(self, start_datetime: datetime, end_datetime: datetime, *, timeframe: str) -> list[tuple[datetime, datetime]]:
        normalized = self._normalize_data_timeframe(timeframe)
        if normalized in {"1d", "day", "daily"}:
            range_start = start_datetime - timedelta(days=self.DAILY_LOOKBACK_DAYS)
            segment_days = self.daily_segment_days
        elif normalized in {"30m", "30min", "minute30"}:
            range_start = start_datetime - timedelta(days=self.INTRADAY_LOOKBACK_DAYS)
            segment_days = self.intraday_segment_days
        else:
            raise ValueError(f"Unsupported replay timeframe: {timeframe}")

        segments: list[tuple[datetime, datetime]] = []
        current = range_start
        while current <= end_datetime:
            segment_end = min(current + timedelta(days=segment_days), end_datetime)
            segments.append((current, segment_end))
            current = segment_end + timedelta(microseconds=1)
        return segments

    @staticmethod
    def _normalize_data_timeframe(timeframe: str) -> str:
        normalized = str(timeframe).lower()
        if normalized == "1d+30m":
            return "30m"
        return normalized

    @staticmethod
    def _normalize_daily_history(df) -> pd.DataFrame:
        if df is None or isinstance(df, dict) or len(df) == 0:
            return pd.DataFrame(columns=["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"])

        frame = pd.DataFrame(df).copy()
        rename_map = {
            "date": "日期",
            "open": "开盘",
            "close": "收盘",
            "high": "最高",
            "low": "最低",
            "volume": "成交量",
            "amount": "成交额",
        }
        frame = frame.rename(columns=rename_map)
        required = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"]
        missing = [column for column in required if column not in frame.columns]
        for column in missing:
            frame[column] = 0
        frame["日期"] = pd.to_datetime(frame["日期"])
        return frame[required].sort_values("日期").reset_index(drop=True)


class QuantSimReplayService:
    """Execute historical-range replay runs and persist their artifacts."""

    LIVE_QUANT_DRILL_CANDIDATE_SOURCES = (
        "low_price",
        "small_cap",
        "low_valuation",
        "profit_growth",
        "main_force",
        "historical_research",
    )
    LIVE_QUANT_DRILL_HISTORICAL_EXECUTABLE_CANDIDATE_SOURCES = ("low_price",)
    LIVE_QUANT_DRILL_DISABLED_CANDIDATE_SOURCES = (
        "current_ai_analysis",
        "current_discover_result",
        "current_research_summary",
    )
    LIVE_QUANT_DRILL_SCAN_STATUSES = ("trial", "active", "exit_only")
    LIVE_QUANT_DRILL_LONG_RUNNING_INVOCATION_LIMIT = 3000

    def __init__(
        self,
        db_file: str | Path | None = None,
        *,
        db_runtime: DatabaseRuntime | None = None,
        replay_db_file: str | Path | None = None,
        snapshot_provider: Optional[MainProjectHistoricalSnapshotProvider] = None,
        adapter: Optional[StockPolicyAdapter] = None,
        timepoint_generator: Optional[ReplayTimepointGenerator] = None,
        corporate_action_provider: Optional[AkshareCorporateActionProvider] = None,
    ):
        self.db_runtime = db_runtime
        self.shared_db = QuantSimDB(db_file, db_runtime=db_runtime)
        self.db_file = self.shared_db.db_file
        if replay_db_file is None:
            replay_db_file = None if db_runtime is not None else (DEFAULT_REPLAY_DB_FILE if self.db_file == str(DEFAULT_DB_FILE) else Path(self.db_file).with_name("xuanwu_stock_replay.db"))
        self.db = QuantSimReplayDB(replay_db_file, db_runtime=db_runtime, pin_connection=True)
        self.replay_db_file = self.db.db_file
        self.snapshot_provider = snapshot_provider or MainProjectHistoricalSnapshotProvider()
        self.adapter = adapter or StockPolicyAdapter()
        self.timepoint_generator = timepoint_generator or ReplayTimepointGenerator()
        self.corporate_action_provider = corporate_action_provider or AkshareCorporateActionProvider()

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
            ai_dynamic_strategy=DEFAULT_AI_DYNAMIC_STRATEGY,
            ai_dynamic_strength=DEFAULT_AI_DYNAMIC_STRENGTH,
            ai_dynamic_lookback=DEFAULT_AI_DYNAMIC_LOOKBACK,
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

    def _prepare_live_quant_drill_context(
        self,
        *,
        start_datetime: datetime | str,
        end_datetime: datetime | str | None,
        timeframe: str,
        market: str,
        strategy_profile_id: str | None,
        initial_cash: float | None,
        ai_dynamic_strategy: str,
        ai_dynamic_strength: float,
        ai_dynamic_lookback: int,
        auto_entry_enabled: bool,
        auto_exit_enabled: bool,
        execute_trades: bool,
        liquidate_at_end: bool,
        seed_current_quant_universe: bool,
        generate_historical_candidate_events: bool,
        candidate_generation_frequency: str,
        candidate_generation_checkpoint_interval: int,
    ) -> dict:
        if not seed_current_quant_universe and not generate_historical_candidate_events:
            raise ValueError("No quant universe source selected")

        start_dt = self._to_datetime(start_datetime)
        end_dt = self._resolve_end_datetime(end_datetime)
        if start_dt >= end_dt:
            raise ValueError("start_datetime must be before end_datetime")
        checkpoints = self.timepoint_generator.generate(start_dt, end_dt, timeframe)
        if not checkpoints:
            raise ValueError("指定区间内没有可用的交易检查点")

        account_summary = self.shared_db.get_account_summary()
        try:
            resolved_initial_cash = float(initial_cash) if initial_cash is not None else float(account_summary["initial_cash"])
        except (TypeError, ValueError):
            resolved_initial_cash = float(account_summary["initial_cash"])
        if resolved_initial_cash <= 0:
            resolved_initial_cash = float(account_summary["initial_cash"])
        account_summary = {
            **account_summary,
            "initial_cash": resolved_initial_cash,
            "available_cash": resolved_initial_cash,
            "market_value": 0.0,
            "total_equity": resolved_initial_cash,
        }

        scheduler_config = {
            **self.shared_db.get_scheduler_config(),
            "capital_slot_enabled": True,
            "capital_pool_min_cash": float(DEFAULT_CAPITAL_SLOT_CONFIG["capital_pool_min_cash"]),
            "capital_pool_max_cash": 1_000_000_000_000.0,
            "capital_slot_min_cash": float(DEFAULT_CAPITAL_SLOT_CONFIG["capital_slot_min_cash"]),
            "capital_sell_cash_reuse_policy": str(DEFAULT_CAPITAL_SLOT_CONFIG["capital_sell_cash_reuse_policy"]),
        }
        selected_profile_id = str(
            strategy_profile_id
            if strategy_profile_id not in (None, "")
            else scheduler_config.get("strategy_profile_id")
        ).strip() or None
        strategy_profile_binding = self.shared_db.resolve_strategy_profile_binding(selected_profile_id)
        dynamic_strategy_mode = str(
            ai_dynamic_strategy if ai_dynamic_strategy not in (None, "") else scheduler_config.get("ai_dynamic_strategy")
        ).strip().lower() or DEFAULT_AI_DYNAMIC_STRATEGY
        try:
            dynamic_strength = float(
                ai_dynamic_strength
                if ai_dynamic_strength is not None
                else scheduler_config.get("ai_dynamic_strength", DEFAULT_AI_DYNAMIC_STRENGTH)
            )
        except (TypeError, ValueError):
            dynamic_strength = DEFAULT_AI_DYNAMIC_STRENGTH
        dynamic_strength = max(0.0, min(1.0, dynamic_strength))
        try:
            dynamic_lookback = int(
                ai_dynamic_lookback
                if ai_dynamic_lookback is not None
                else scheduler_config.get("ai_dynamic_lookback", DEFAULT_AI_DYNAMIC_LOOKBACK)
            )
        except (TypeError, ValueError):
            dynamic_lookback = DEFAULT_AI_DYNAMIC_LOOKBACK
        dynamic_lookback = max(6, min(336, dynamic_lookback))

        quant_state_response = self.shared_db.list_quant_universe_state(limit=100000) if seed_current_quant_universe else {"items": []}
        initial_quant_universe_snapshot = list(quant_state_response.get("items") or [])
        candidates = [
            {
                "stock_code": str(item.get("stock_code") or "").strip(),
                "stock_name": str(item.get("stock_name") or item.get("stock_code") or "").strip(),
                "source": str(item.get("quant_entry_source") or "quant_universe_seed"),
                "latest_price": 0.0,
                "notes": "live_quant_drill_seed",
                "metadata": {
                    "quant_status": item.get("quant_status"),
                    "health_score": item.get("health_score"),
                    "candidate_score": item.get("candidate_score"),
                    "candidate_confidence": item.get("candidate_confidence"),
                },
            }
            for item in initial_quant_universe_snapshot
            if str(item.get("stock_code") or "").strip()
        ]
        stock_codes = [str(candidate["stock_code"]) for candidate in candidates]
        configured_candidate_sources = list(self.LIVE_QUANT_DRILL_CANDIDATE_SOURCES) if generate_historical_candidate_events else []
        enabled_candidate_sources = (
            list(self.LIVE_QUANT_DRILL_HISTORICAL_EXECUTABLE_CANDIDATE_SOURCES)
            if generate_historical_candidate_events
            else []
        )
        disabled_candidate_sources = sorted(
            set(self.LIVE_QUANT_DRILL_DISABLED_CANDIDATE_SOURCES)
            | (set(configured_candidate_sources) - set(enabled_candidate_sources))
        )
        candidate_generation_config = CandidateGenerationConfig(
            frequency=candidate_generation_frequency,
            checkpoint_interval=candidate_generation_checkpoint_interval,
        )
        candidate_generation = estimate_candidate_generation(
            checkpoints=checkpoints,
            config=candidate_generation_config,
            enabled_sources=enabled_candidate_sources,
        )
        lifecycle_settings_snapshot = self.shared_db.get_quant_universe_settings()

        return {
            "start_dt": start_dt,
            "end_dt": end_dt,
            "timeframe": timeframe,
            "market": market,
            "strategy_mode": "live_quant_drill",
            "strategy_profile_binding": strategy_profile_binding,
            "ai_dynamic_strategy": dynamic_strategy_mode,
            "ai_dynamic_strength": dynamic_strength,
            "ai_dynamic_lookback": dynamic_lookback,
            "commission_rate": float(scheduler_config.get("commission_rate") or 0),
            "sell_tax_rate": float(scheduler_config.get("sell_tax_rate") or 0),
            "scheduler_config": scheduler_config,
            "candidates": candidates,
            "stock_codes": stock_codes,
            "checkpoints": checkpoints,
            "account_summary": account_summary,
            "initial_quant_universe_snapshot": initial_quant_universe_snapshot,
            "lifecycle_settings_snapshot": lifecycle_settings_snapshot,
            "candidate_generation": candidate_generation,
            "configured_candidate_sources": configured_candidate_sources,
            "historical_executable_candidate_sources": enabled_candidate_sources,
            "disabled_candidate_sources": disabled_candidate_sources,
            "data_warnings": [],
            "candidate_event_dedup_days": int(candidate_generation_config.candidate_event_dedup_days),
            "auto_entry_enabled": bool(auto_entry_enabled),
            "auto_exit_enabled": bool(auto_exit_enabled),
            "execute_trades": bool(execute_trades),
            "liquidate_at_end": bool(liquidate_at_end),
            "seed_current_quant_universe": bool(seed_current_quant_universe),
            "generate_historical_candidate_events": bool(generate_historical_candidate_events),
            "candidate_generation_frequency": candidate_generation_frequency,
            "candidate_generation_checkpoint_interval": int(candidate_generation_checkpoint_interval),
        }

    def _create_live_quant_drill_temp_db(self, context: dict, temp_db_file: str | Path) -> QuantSimDB:
        temp_db_path = Path(temp_db_file)
        temp_db_path.parent.mkdir(parents=True, exist_ok=True)
        temp_db = QuantSimDB(temp_db_path)
        temp_db.configure_account(float(context["account_summary"]["initial_cash"]))
        scheduler_config = context.get("scheduler_config") if isinstance(context.get("scheduler_config"), dict) else {}
        strategy_profile_binding = context.get("strategy_profile_binding") if isinstance(context.get("strategy_profile_binding"), dict) else {}
        temp_db.update_scheduler_config(
            enabled=False,
            auto_execute=bool(context.get("execute_trades", True)),
            interval_minutes=int(scheduler_config.get("interval_minutes") or 10),
            trading_hours_only=True,
            analysis_timeframe=str(context.get("timeframe") or scheduler_config.get("analysis_timeframe") or "30m"),
            strategy_mode=str(scheduler_config.get("strategy_mode") or "auto"),
            strategy_profile_id=str(strategy_profile_binding.get("profile_id") or "") or None,
            ai_dynamic_strategy=str(context.get("ai_dynamic_strategy") or DEFAULT_AI_DYNAMIC_STRATEGY),
            ai_dynamic_strength=float(context.get("ai_dynamic_strength") or 0),
            ai_dynamic_lookback=int(context.get("ai_dynamic_lookback") or DEFAULT_AI_DYNAMIC_LOOKBACK),
            market=str(context.get("market") or scheduler_config.get("market") or "CN"),
            commission_rate=float(context.get("commission_rate") or scheduler_config.get("commission_rate") or 0),
            sell_tax_rate=float(context.get("sell_tax_rate") or scheduler_config.get("sell_tax_rate") or 0),
            capital_slot_enabled=bool(scheduler_config.get("capital_slot_enabled", True)),
            capital_pool_min_cash=float(scheduler_config.get("capital_pool_min_cash") or 0),
            capital_pool_max_cash=float(scheduler_config.get("capital_pool_max_cash") or 0),
            capital_slot_min_cash=float(scheduler_config.get("capital_slot_min_cash") or 0),
            capital_max_slots=int(scheduler_config.get("capital_max_slots") or 1),
            capital_min_buy_slot_fraction=float(scheduler_config.get("capital_min_buy_slot_fraction") or 0.25),
            capital_full_buy_edge=float(scheduler_config.get("capital_full_buy_edge") or 0.25),
            capital_confidence_weight=float(scheduler_config.get("capital_confidence_weight") or 0.35),
            capital_high_price_threshold=float(scheduler_config.get("capital_high_price_threshold") or 100),
            capital_high_price_max_slot_units=float(scheduler_config.get("capital_high_price_max_slot_units") or 2),
            capital_sell_cash_reuse_policy=str(scheduler_config.get("capital_sell_cash_reuse_policy") or "next_batch"),
        )
        temp_db.update_quant_universe_settings(
            {
                "quant_universe_lifecycle_enabled": True,
                "auto_exit_enabled": bool(context.get("auto_exit_enabled", True)),
                "auto_entry_mode": "auto_trial" if bool(context.get("auto_entry_enabled", True)) else "confirm_first",
            }
        )
        for row in context.get("initial_quant_universe_snapshot") or []:
            stock_code = str(row.get("stock_code") or "").strip()
            if not stock_code:
                continue
            stock_name = str(row.get("stock_name") or stock_code).strip() or stock_code
            quant_status = str(row.get("quant_status") or "inactive").strip()
            source = str(row.get("quant_entry_source") or "seed_current_quant_universe")
            temp_db.add_watch(
                stock_code=stock_code,
                stock_name=stock_name,
                source=source,
                metadata={"live_quant_drill_seed": True},
            )
            if quant_status in self.LIVE_QUANT_DRILL_SCAN_STATUSES:
                temp_db.add_candidate(
                    {
                        "stock_code": stock_code,
                        "stock_name": stock_name,
                        "source": source,
                        "latest_price": 0,
                        "notes": "live_quant_drill_seed",
                        "metadata": {"live_quant_drill_seed": True},
                        "status": "active",
                    }
                )
            temp_db.upsert_quant_universe_state(
                stock_code,
                {
                    "stock_name": stock_name,
                    "quant_status": quant_status,
                    "quant_entry_source": source,
                    "quant_entry_at": row.get("quant_entry_at"),
                    "candidate_score": row.get("candidate_score"),
                    "candidate_confidence": row.get("candidate_confidence"),
                    "health_score": float(row.get("health_score") if row.get("health_score") is not None else 100.0),
                    "downtrend_streak": row.get("downtrend_streak"),
                    "weakening_warning_streak": row.get("weakening_warning_streak"),
                    "blocked_streak": row.get("blocked_streak"),
                    "no_buy_days": row.get("no_buy_days"),
                    "cooling_until": row.get("cooling_until"),
                    "retired_at": row.get("retired_at"),
                    "retire_reason": row.get("retire_reason"),
                    "reentry_watch_until": row.get("reentry_watch_until"),
                    "last_status_changed_at": row.get("last_status_changed_at"),
                    "last_health_evaluated_at": row.get("last_health_evaluated_at"),
                    "snapshot": row.get("snapshot") or row.get("snapshot_json"),
                },
            )
        return temp_db

    def _prepare_replay_context(
        self,
        *,
        start_datetime: datetime | str,
        end_datetime: datetime | str | None,
        timeframe: str,
        market: str,
        strategy_mode: str,
        strategy_profile_id: str | None,
        initial_cash: float | None = None,
        ai_dynamic_strategy: str = DEFAULT_AI_DYNAMIC_STRATEGY,
        ai_dynamic_strength: float = DEFAULT_AI_DYNAMIC_STRENGTH,
        ai_dynamic_lookback: int = DEFAULT_AI_DYNAMIC_LOOKBACK,
        commission_rate: float | None = None,
        sell_tax_rate: float | None = None,
    ) -> dict:
        start_dt = self._to_datetime(start_datetime)
        end_dt = self._resolve_end_datetime(end_datetime)
        if start_dt >= end_dt:
            raise ValueError("start_datetime must be before end_datetime")

        candidates = CandidatePoolService(db_file=self.db_file).list_candidates(status="active")
        if not candidates:
            raise ValueError("候选池为空，无法执行历史区间模拟")

        stock_codes = [str(candidate["stock_code"]) for candidate in candidates]
        checkpoints = self.timepoint_generator.generate(start_dt, end_dt, timeframe)
        if not checkpoints:
            raise ValueError("指定区间内没有可用的交易检查点")
        account_summary = self.shared_db.get_account_summary()
        try:
            resolved_initial_cash = float(initial_cash) if initial_cash is not None else float(account_summary["initial_cash"])
        except (TypeError, ValueError):
            resolved_initial_cash = float(account_summary["initial_cash"])
        if resolved_initial_cash <= 0:
            resolved_initial_cash = float(account_summary["initial_cash"])
        account_summary = {
            **account_summary,
            "initial_cash": resolved_initial_cash,
            "available_cash": resolved_initial_cash,
            "market_value": 0.0,
            "total_equity": resolved_initial_cash,
        }
        scheduler_config = {
            **self.shared_db.get_scheduler_config(),
            "capital_slot_enabled": True,
            "capital_pool_min_cash": float(DEFAULT_CAPITAL_SLOT_CONFIG["capital_pool_min_cash"]),
            "capital_pool_max_cash": 1_000_000_000_000.0,
            "capital_slot_min_cash": float(DEFAULT_CAPITAL_SLOT_CONFIG["capital_slot_min_cash"]),
            "capital_sell_cash_reuse_policy": str(DEFAULT_CAPITAL_SLOT_CONFIG["capital_sell_cash_reuse_policy"]),
        }
        selected_profile_id = str(
            strategy_profile_id
            if strategy_profile_id not in (None, "")
            else scheduler_config.get("strategy_profile_id")
        ).strip() or None
        strategy_profile_binding = self.shared_db.resolve_strategy_profile_binding(selected_profile_id)
        dynamic_strategy_mode = str(
            ai_dynamic_strategy if ai_dynamic_strategy not in (None, "") else scheduler_config.get("ai_dynamic_strategy")
        ).strip().lower() or DEFAULT_AI_DYNAMIC_STRATEGY
        try:
            dynamic_strength = float(
                ai_dynamic_strength
                if ai_dynamic_strength is not None
                else scheduler_config.get("ai_dynamic_strength", DEFAULT_AI_DYNAMIC_STRENGTH)
            )
        except (TypeError, ValueError):
            dynamic_strength = DEFAULT_AI_DYNAMIC_STRENGTH
        dynamic_strength = max(0.0, min(1.0, dynamic_strength))
        try:
            dynamic_lookback = int(
                ai_dynamic_lookback
                if ai_dynamic_lookback is not None
                else scheduler_config.get("ai_dynamic_lookback", DEFAULT_AI_DYNAMIC_LOOKBACK)
            )
        except (TypeError, ValueError):
            dynamic_lookback = DEFAULT_AI_DYNAMIC_LOOKBACK
        dynamic_lookback = max(6, min(336, dynamic_lookback))
        resolved_commission_rate = float(commission_rate if commission_rate is not None else 0.0)
        resolved_sell_tax_rate = float(sell_tax_rate if sell_tax_rate is not None else 0.0)

        return {
            "start_dt": start_dt,
            "end_dt": end_dt,
            "timeframe": timeframe,
            "market": market,
            "strategy_mode": strategy_mode,
            "strategy_profile_binding": strategy_profile_binding,
            "ai_dynamic_strategy": dynamic_strategy_mode,
            "ai_dynamic_strength": dynamic_strength,
            "ai_dynamic_lookback": dynamic_lookback,
            "commission_rate": resolved_commission_rate,
            "sell_tax_rate": resolved_sell_tax_rate,
            "scheduler_config": scheduler_config,
            "candidates": candidates,
            "stock_codes": stock_codes,
            "checkpoints": checkpoints,
            "account_summary": account_summary,
        }

    def _create_replay_run(
        self,
        *,
        mode: str,
        handoff_to_live: bool,
        timeframe: str,
        market: str,
        context: dict,
        status: str,
        status_message: str,
    ) -> int:
        profile_binding = context.get("strategy_profile_binding") if isinstance(context.get("strategy_profile_binding"), dict) else {}
        stock_codes = [
            str(code).strip()
            for code in (context.get("stock_codes") if isinstance(context.get("stock_codes"), list) else [])
            if str(code).strip()
        ]
        candidates = context.get("candidates") if isinstance(context.get("candidates"), list) else []
        metadata = {
            "candidate_count": len(context["candidates"]),
            "stock_codes": stock_codes,
            "candidate_scope": [
                {
                    "stock_code": str(candidate.get("stock_code") or "").strip(),
                    "stock_name": str(candidate.get("stock_name") or candidate.get("stock_code") or "").strip(),
                }
                for candidate in candidates
                if str(candidate.get("stock_code") or "").strip()
            ],
            "strategy_mode": context["strategy_mode"],
            "checkpoint_market": market,
            "checkpoint_timezone": market_timezone_name(market),
            "strategy_profile_id": str(profile_binding.get("profile_id") or ""),
            "strategy_profile_name": str(profile_binding.get("profile_name") or ""),
            "strategy_profile_version_id": int(profile_binding["version_id"]) if profile_binding.get("version_id") is not None else None,
            "strategy_profile_version": int(profile_binding["version"]) if profile_binding.get("version") is not None else None,
            "ai_dynamic_strategy": context.get("ai_dynamic_strategy"),
            "ai_dynamic_strength": context.get("ai_dynamic_strength"),
            "ai_dynamic_lookback": context.get("ai_dynamic_lookback"),
            "commission_rate": float(context.get("commission_rate") or 0),
            "sell_tax_rate": float(context.get("sell_tax_rate") or 0),
            "capital_slot_enabled": bool((context.get("scheduler_config") or {}).get("capital_slot_enabled", True)),
            "capital_pool_min_cash": float((context.get("scheduler_config") or {}).get("capital_pool_min_cash") or 0),
            "capital_pool_max_cash": float((context.get("scheduler_config") or {}).get("capital_pool_max_cash") or 0),
            "capital_slot_min_cash": float((context.get("scheduler_config") or {}).get("capital_slot_min_cash") or 0),
            "capital_max_slots": int((context.get("scheduler_config") or {}).get("capital_max_slots") or 0),
            "capital_min_buy_slot_fraction": float((context.get("scheduler_config") or {}).get("capital_min_buy_slot_fraction") or 0),
            "capital_full_buy_edge": float((context.get("scheduler_config") or {}).get("capital_full_buy_edge") or 0),
            "capital_confidence_weight": float((context.get("scheduler_config") or {}).get("capital_confidence_weight") or 0),
            "capital_high_price_threshold": float((context.get("scheduler_config") or {}).get("capital_high_price_threshold") or 0),
            "capital_high_price_max_slot_units": float((context.get("scheduler_config") or {}).get("capital_high_price_max_slot_units") or 0),
            "capital_sell_cash_reuse_policy": str((context.get("scheduler_config") or {}).get("capital_sell_cash_reuse_policy") or "next_batch"),
        }
        if mode == "live_quant_drill":
            candidate_generation = context.get("candidate_generation") if isinstance(context.get("candidate_generation"), dict) else {}
            metadata.update(
                {
                    "run_type": "live_quant_drill",
                    "seed_current_quant_universe": bool(context.get("seed_current_quant_universe", True)),
                    "generate_historical_candidate_events": bool(context.get("generate_historical_candidate_events", True)),
                    "auto_entry_enabled": bool(context.get("auto_entry_enabled", True)),
                    "auto_exit_enabled": bool(context.get("auto_exit_enabled", True)),
                    "execute_trades": bool(context.get("execute_trades", True)),
                    "liquidate_at_end": bool(context.get("liquidate_at_end", True)),
                    "initial_quant_universe_snapshot": context.get("initial_quant_universe_snapshot") or [],
                    "lifecycle_settings_snapshot": context.get("lifecycle_settings_snapshot") or {},
                    "strategy_profile_snapshot": profile_binding.get("config") if isinstance(profile_binding.get("config"), dict) else {},
                    "candidate_generation": context.get("candidate_generation") or {},
                    "configured_candidate_sources": context.get("configured_candidate_sources") or [],
                    "historical_executable_candidate_sources": context.get("historical_executable_candidate_sources") or [],
                    "disabled_candidate_sources": context.get("disabled_candidate_sources") or [],
                    "data_warnings": context.get("data_warnings") or [],
                    "candidate_generation_frequency": context.get("candidate_generation_frequency"),
                    "candidate_generation_checkpoint_interval": context.get("candidate_generation_checkpoint_interval"),
                    "candidate_event_dedup_days": context.get("candidate_event_dedup_days"),
                    "estimated_candidate_generation_runs": int(candidate_generation.get("estimated_candidate_generation_runs") or 0),
                    "enabled_candidate_sources": candidate_generation.get("enabled_candidate_sources") or [],
                    "estimated_strategy_invocations": int(candidate_generation.get("estimated_strategy_invocations") or 0),
                }
            )
        return self.db.create_sim_run(
            mode=mode,
            timeframe=timeframe,
            market=market,
            start_datetime=self._format_datetime(context["start_dt"]),
            end_datetime=self._format_datetime(context["end_dt"]),
            initial_cash=float(context["account_summary"]["initial_cash"]),
            status=status,
            auto_execute=True,
            handoff_to_live=handoff_to_live,
            progress_current=0,
            progress_total=len(context["checkpoints"]),
            status_message=status_message,
            selected_strategy_profile_id=str(profile_binding.get("profile_id") or ""),
            selected_strategy_profile_name=str(profile_binding.get("profile_name") or ""),
            selected_strategy_profile_version_id=int(profile_binding["version_id"]) if profile_binding.get("version_id") is not None else None,
            strategy_profile_snapshot=profile_binding.get("config") if isinstance(profile_binding.get("config"), dict) else None,
            metadata=metadata,
        )

    def _ensure_no_active_replay(self) -> None:
        active_run = self.db.get_active_sim_run()
        if active_run is not None:
            raise ValueError(f"已有回放任务运行中（#{active_run['id']}），请先等待完成或取消")

    def _execute_live_quant_drill(self, *, run_id: int, context: dict) -> dict:
        checkpoints = context["checkpoints"]
        account_summary = context["account_summary"]
        temp_dir = Path(tempfile.mkdtemp(prefix="quant_live_drill_"))
        temp_db_file = temp_dir / "quant_live_drill.db"
        replay_signals: list[dict] = []
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
                db=temp_db,
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
                replay_signals.extend(checkpoint_signals)
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
            with self.db.write_batch():
                self.db.replace_sim_run_results(
                    run_id,
                    trades=trades,
                    snapshots=snapshots,
                    positions=positions,
                    signals=replay_signals,
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
        )
        candidate_processing = self._process_live_quant_drill_candidate_events(
            run_id=run_id,
            checkpoint=checkpoint,
            checkpoint_index=checkpoint_index,
            context=context,
            temp_db=temp_db,
            manager=manager,
        )
        main_scan = self._run_live_quant_drill_main_scan(
            checkpoint=checkpoint,
            context=context,
            temp_db=temp_db,
            engine=engine,
            portfolio=portfolio,
            manager=manager,
        )
        cooling_review = self._run_live_quant_drill_cooling_review(
            checkpoint=checkpoint,
            context=context,
            temp_db=temp_db,
            engine=engine,
            portfolio=portfolio,
            manager=manager,
        )
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
                "cooling_review": cooling_review,
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
            "cooling_review": cooling_review,
            "candidate_processing": candidate_processing,
        }

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
                str(event.get("checkpoint_at_utc") or event.get("checkpoint_at") or ""),
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
        checkpoint_at_utc = normalized_events[0]["checkpoint_at_utc"]
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
                    "occurred_at": event.get("occurred_at") or event["checkpoint_at_utc"],
                    "payload_json": event.get("evidence_json") or {},
                    "status": "active",
                },
                capacity_at=checkpoint,
            )
            self.db.update_sim_run_candidate_event_evaluation(
                run_id,
                stock_code=event["stock_code"],
                source_type=event["source_type"],
                checkpoint_at_utc=event["checkpoint_at_utc"],
                evaluation=manager_result,
            )
            if str(manager_result.get("decision") or "") == "promoted_to_trial":
                promoted += 1
                consumed += self.db.mark_sim_run_candidate_events_consumed(
                    run_id,
                    stock_code=event["stock_code"],
                    source_type=event["source_type"],
                    checkpoint_at_utc_lte=checkpoint_at_utc,
                )
        return {
            "candidate_event_count": len(normalized_events),
            "auto_promoted_count": promoted,
            "consumed_count": consumed,
        }

    def _generate_live_quant_drill_candidate_events(
        self,
        *,
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
                continue
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
        macd = self._snapshot_float(snapshot, "macd", "MACD")
        rsi = self._snapshot_float(snapshot, "rsi12", "rsi", "RSI")
        volume_ratio = self._snapshot_float(snapshot, "volume_ratio", "量比")
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
                "price": price,
                "ma5": ma5,
                "ma10": ma10,
                "ma20": ma20,
                "macd": macd,
                "rsi": rsi,
                "volume_ratio": volume_ratio,
                "score_basis": "as_of_price_volume_trend",
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
        checkpoint_at_utc = format_utc_iso_z(self._market_time_to_utc(checkpoint, market))
        score = event.get("candidate_score")
        if score is None:
            score = event.get("source_score")
        return {
            "checkpoint_at": checkpoint_at,
            "checkpoint_at_utc": checkpoint_at_utc,
            "stock_code": str(event.get("stock_code") or "").strip().upper(),
            "stock_name": str(event.get("stock_name") or event.get("stock_code") or "").strip(),
            "source_type": str(event.get("source_type") or "historical_candidate").strip(),
            "source_key": event.get("source_key"),
            "candidate_score": float(score or 0),
            "confidence": float(event.get("confidence") or 0),
            "trend": event.get("trend") or "up",
            "reason_text": event.get("reason_text"),
            "evidence_json": event.get("evidence_json") or event.get("payload_json") or {},
            "occurred_at": event.get("occurred_at") or checkpoint_at_utc,
            "status": event.get("status") or "active",
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
        checkpoint_at_utc = format_utc_iso_z(self._market_time_to_utc(checkpoint, market))
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
            checkpoint_at_utc=checkpoint_at_utc,
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
                    "checkpoint_at_utc": checkpoint_at_utc,
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
                "checkpoint_at_utc": checkpoint_at_utc,
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
        checkpoint: datetime,
        context: dict,
        temp_db: QuantSimDB,
        engine: QuantSimEngine,
        portfolio: PortfolioService,
        manager: QuantUniverseManager,
    ) -> dict:
        summary = self._run_checkpoint(
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
        checkpoint: datetime,
        context: dict,
        temp_db: QuantSimDB,
        engine: QuantSimEngine,
        portfolio: PortfolioService,
        manager: QuantUniverseManager,
    ) -> dict:
        cooling = temp_db.list_quant_universe_state(statuses=["cooling"], limit=1000).get("items") or []
        interval_minutes = max(1, int(manager.policy.cooling_review_interval_minutes or 1))
        cooling = [
            item
            for item in cooling
            if self._is_live_quant_drill_cooling_review_due(item, checkpoint=checkpoint, interval_minutes=interval_minutes)
        ]
        cooling.sort(
            key=lambda item: (
                str(item.get("last_health_evaluated_at") or ""),
                -float(item.get("health_score") or 0),
                str(item.get("stock_code") or ""),
            )
        )
        if self._should_full_review_live_quant_drill_cooling(context, checkpoint):
            selected = cooling
        else:
            batch_size = max(1, int(manager.policy.cooling_review_batch_size or 1))
            selected = cooling[: min(batch_size, len(cooling))]
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
                continue
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
            update = manager.update_after_signal(code, review_signal, recent_signals, positions_by_code.get(code))
            next_status = str(update.get("new_status") or previous_status)
            if previous_status == "cooling" and next_status == "trial":
                restored += 1
            elif previous_status == "cooling" and next_status == "retired":
                retired += 1
        return {"reviewed": reviewed, "restored": restored, "retired": retired}

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
        current = self._to_naive_utc(checkpoint)
        cooling_until = item.get("cooling_until")
        if cooling_until:
            cooling_dt = self._parse_optional_naive_utc(cooling_until)
            if cooling_dt is not None and cooling_dt > current:
                return False
        last_eval = item.get("last_health_evaluated_at")
        if not last_eval:
            return True
        last_dt = self._parse_optional_naive_utc(last_eval)
        if last_dt is None:
            return True
        if last_dt > current:
            return True
        return (current - last_dt).total_seconds() >= interval_minutes * 60

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
            replay_signals: list[dict] = []

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
                    replay_signals.extend(checkpoint_signals)
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
            partial_signals: list[dict] = list(locals().get("replay_signals", []))
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
                if partial_trades or partial_snapshots or partial_positions or partial_signals:
                    self.db.replace_sim_run_results(
                        run_id,
                        trades=partial_trades,
                        snapshots=partial_snapshots,
                        positions=partial_positions,
                        signals=partial_signals,
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
        candidates = [
            item
            for item in engine.candidate_pool.list_candidates(
                status="active",
                quant_statuses=candidate_quant_statuses,
            )
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
                continue
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
                continue
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
