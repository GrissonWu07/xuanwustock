"""Base context and data provider pieces for quant replay service."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from app.db.runtime.registry import DatabaseRuntime
from app.data_source_manager import data_source_manager
from app.quant_kernel import TradingTimeUtils
from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.capital_slots import DEFAULT_CAPITAL_SLOT_CONFIG
from app.quant_sim.corporate_actions import AkshareCorporateActionProvider
from app.quant_sim.db import DEFAULT_COMMISSION_RATE, DEFAULT_DB_FILE, DEFAULT_REPLAY_DB_FILE, DEFAULT_SELL_TAX_RATE, QuantSimDB, QuantSimReplayDB
from app.quant_sim.dynamic_strategy import DEFAULT_AI_DYNAMIC_LOOKBACK, DEFAULT_AI_DYNAMIC_STRENGTH, DEFAULT_AI_DYNAMIC_STRATEGY
from app.quant_sim.live_quant_drill_candidates import CandidateGenerationConfig, estimate_candidate_generation
from app.quant_sim.market_technical_artifact_store import MarketTechnicalArtifactStore
from app.quant_sim.outcome_scoring_entrypoints import OutcomeBatchRequest, OutcomeBatchScope, score_signal_batch
from app.quant_sim.stockpolicy_adapter import StockPolicyAdapter
from app.quant_sim.time_utils import market_timezone_name
from app.smart_monitor_tdx_data import SmartMonitorTDXDataFetcher


from app.quant_sim.replay_runner import get_quant_sim_replay_runner
from app.quant_sim.scheduler import get_quant_sim_scheduler
from app.quant_sim.signal_center_service import SignalCenterService
from app.quant_sim.stockpolicy_adapter import StockPolicyAdapter
from app.quant_sim.time_utils import market_timezone_name
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



class QuantSimReplayServiceBase:
    """Shared setup and context construction for replay service mixins."""

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
        timepoint_generator: Optional[TradingTimeUtils] = None,
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
        self.timepoint_generator = timepoint_generator or TradingTimeUtils()
        self.corporate_action_provider = corporate_action_provider or AkshareCorporateActionProvider()

    def _score_run_outcomes_for_checkpoint(
        self,
        *,
        run_id: int,
        run_type: str,
        domain: str,
        checkpoint_at: str,
        temp_db: QuantSimDB | None,
        limit: int = 10000,
        trace_id: str,
    ) -> dict[str, Any]:
        """Score matured run signals and expose feedback to run-local execution state."""
        outcome_batch = score_signal_batch(
            OutcomeBatchRequest(
                db=self.db,
                artifact_store=MarketTechnicalArtifactStore(self.replay_db_file),
                scope=OutcomeBatchScope(run_id=run_id, run_type=run_type, domain=domain),
                as_of_checkpoint=checkpoint_at,
                limit=limit,
                trace_id=trace_id,
            )
        )
        if temp_db is not None:
            self._sync_run_outcome_feedback_to_temp_db(
                run_id=run_id,
                run_type=run_type,
                checkpoint_at=checkpoint_at,
                temp_db=temp_db,
                stock_codes=outcome_batch.get("feedback_stocks") or [],
            )
        return outcome_batch

    def _sync_run_outcome_feedback_to_temp_db(
        self,
        *,
        run_id: int,
        run_type: str,
        checkpoint_at: str,
        temp_db: QuantSimDB,
        stock_codes: list[str],
    ) -> None:
        from app.quant_sim.db import OutcomeFeedbackFilters

        run_scope = {"run_id": int(run_id), "run_type": str(run_type)}
        for code in sorted({str(item).strip() for item in stock_codes if str(item).strip()}):
            row = self.db.get_latest_outcome_feedback(
                OutcomeFeedbackFilters(stock_code=code, as_of_checkpoint_lte=checkpoint_at, limit=1),
                run_scope=run_scope,
            )
            if not row:
                continue
            temp_db.upsert_outcome_feedback_score(
                {
                    "stock_code": row.get("stock_code"),
                    "profile_id": row.get("profile_id"),
                    "as_of_checkpoint": row.get("as_of_checkpoint"),
                    "feedback_score": row.get("feedback_score"),
                    "sample_count": row.get("sample_count"),
                    "buy_avg_score": row.get("buy_avg_score"),
                    "sell_avg_score": row.get("sell_avg_score"),
                    "latest_matured_at": row.get("latest_matured_at"),
                    "summary": row.get("summary") or {},
                    "created_at": row.get("created_at"),
                }
            )
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

        seed_statuses = [*self.LIVE_QUANT_DRILL_SCAN_STATUSES, "cooling"]
        quant_state_response = (
            self.shared_db.list_quant_universe_state(statuses=seed_statuses, limit=100000)
            if seed_current_quant_universe
            else {"items": []}
        )
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
        candidate_generation = self._estimate_candidate_generation(
            checkpoints=checkpoints,
            config=candidate_generation_config,
            enabled_sources=enabled_candidate_sources,
        )
        lifecycle_settings_snapshot = self.shared_db.get_quant_universe_settings()

        resolved_strategy_mode = str(strategy_profile_binding.get("profile_id") or selected_profile_id or "auto").strip() or "auto"

        return {
            "start_dt": start_dt,
            "end_dt": end_dt,
            "timeframe": timeframe,
            "market": market,
            "strategy_mode": resolved_strategy_mode,
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
                    "recovery_probe_until": row.get("recovery_probe_until"),
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
        resolved_commission_rate = self._resolve_fee_rate(
            commission_rate,
            scheduler_config.get("commission_rate"),
            DEFAULT_COMMISSION_RATE,
        )
        resolved_sell_tax_rate = self._resolve_fee_rate(
            sell_tax_rate,
            scheduler_config.get("sell_tax_rate"),
            DEFAULT_SELL_TAX_RATE,
        )

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

    @staticmethod
    def _resolve_fee_rate(value: Any, scheduler_value: Any, default: float) -> float:
        source = value if value is not None else scheduler_value
        try:
            parsed = float(default if source in (None, "") else source)
        except (TypeError, ValueError):
            parsed = float(default)
        if parsed < 0:
            parsed = 0.0
        if parsed > 1:
            parsed = parsed / 100.0
        if parsed > 0.2:
            parsed = 0.2
        return round(parsed, 8)
