"""Historical replay orchestration for quant simulation."""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from app.data_source_manager import data_source_manager
from app.quant_kernel import ReplayTimepointGenerator
from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.db import DEFAULT_DB_FILE, QuantSimDB
from app.quant_sim.dynamic_strategy import (
    DEFAULT_AI_DYNAMIC_LOOKBACK,
    DEFAULT_AI_DYNAMIC_STRENGTH,
    DEFAULT_AI_DYNAMIC_STRATEGY,
)
from app.quant_sim.engine import QuantSimEngine
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.replay_runner import get_quant_sim_replay_runner
from app.quant_sim.scheduler import get_quant_sim_scheduler
from app.quant_sim.signal_center_service import SignalCenterService
from app.quant_sim.stockpolicy_adapter import StockPolicyAdapter
from app.smart_monitor_tdx_data import SmartMonitorTDXDataFetcher


class MainProjectHistoricalSnapshotProvider:
    """Build replay snapshots using the main project's market-data stack."""

    DAILY_LOOKBACK_DAYS = 180
    INTRADAY_LOOKBACK_DAYS = 45

    def __init__(
        self,
        *,
        tdx_fetcher: Optional[SmartMonitorTDXDataFetcher] = None,
    ):
        self.tdx_fetcher = tdx_fetcher or SmartMonitorTDXDataFetcher()
        self.cache: dict[tuple[str, str], pd.DataFrame] = {}

    def prepare(
        self,
        stock_codes: list[str],
        start_datetime: datetime,
        end_datetime: datetime,
        timeframe: str,
    ) -> None:
        data_timeframe = self._normalize_data_timeframe(timeframe)
        for stock_code in stock_codes:
            self.cache[(stock_code, timeframe)] = self._load_history(
                stock_code,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                timeframe=data_timeframe,
            )

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
        resolved_name = stock_name if stock_name not in (None, "") else stock_code
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
    ) -> pd.DataFrame:
        normalized = self._normalize_data_timeframe(timeframe)
        if normalized in {"1d", "day", "daily"}:
            start_date = (start_datetime - timedelta(days=self.DAILY_LOOKBACK_DAYS)).strftime("%Y%m%d")
            end_date = end_datetime.strftime("%Y%m%d")
            df = data_source_manager.get_stock_hist_data(stock_code, start_date=start_date, end_date=end_date, adjust="qfq")
            return self._normalize_daily_history(df)

        if normalized in {"30m", "30min", "minute30"}:
            intraday_history = self.tdx_fetcher.get_kline_data_range(
                stock_code,
                kline_type="minute30",
                start_datetime=start_datetime - timedelta(days=self.INTRADAY_LOOKBACK_DAYS),
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

    def __init__(
        self,
        db_file: str | Path = DEFAULT_DB_FILE,
        *,
        snapshot_provider: Optional[MainProjectHistoricalSnapshotProvider] = None,
        adapter: Optional[StockPolicyAdapter] = None,
        timepoint_generator: Optional[ReplayTimepointGenerator] = None,
    ):
        self.db_file = str(db_file)
        self.db = QuantSimDB(db_file)
        self.snapshot_provider = snapshot_provider or MainProjectHistoricalSnapshotProvider()
        self.adapter = adapter or StockPolicyAdapter()
        self.timepoint_generator = timepoint_generator or ReplayTimepointGenerator()

    def run_historical_range(
        self,
        *,
        start_datetime: datetime | str,
        end_datetime: datetime | str | None,
        timeframe: str,
        market: str,
        strategy_mode: str = "auto",
        strategy_profile_id: str | None = None,
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
        ai_dynamic_strategy: str = DEFAULT_AI_DYNAMIC_STRATEGY,
        ai_dynamic_strength: float = DEFAULT_AI_DYNAMIC_STRENGTH,
        ai_dynamic_lookback: int = DEFAULT_AI_DYNAMIC_LOOKBACK,
        commission_rate: float | None = None,
        sell_tax_rate: float | None = None,
        overwrite_live: bool = False,
        auto_start_scheduler: bool = True,
    ) -> dict:
        self._validate_live_handoff(overwrite_live=overwrite_live)
        context = self._prepare_replay_context(
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            timeframe=timeframe,
            market=market,
            strategy_mode=strategy_mode,
            strategy_profile_id=strategy_profile_id,
            ai_dynamic_strategy=ai_dynamic_strategy,
            ai_dynamic_strength=ai_dynamic_strength,
            ai_dynamic_lookback=ai_dynamic_lookback,
            commission_rate=commission_rate,
            sell_tax_rate=sell_tax_rate,
        )
        run_id = self._create_replay_run(
            mode="continuous_to_live",
            handoff_to_live=True,
            timeframe=timeframe,
            market=market,
            context=context,
            status="running",
            status_message="正在同步执行接续回放",
        )
        summary = self._execute_prepared_replay(
            run_id=run_id,
            mode="continuous_to_live",
            handoff_to_live=True,
            context=context,
            auto_start_scheduler=auto_start_scheduler,
        )
        summary["handoff_to_live"] = True
        return summary

    def enqueue_historical_range(
        self,
        *,
        start_datetime: datetime | str,
        end_datetime: datetime | str | None,
        timeframe: str,
        market: str,
        strategy_mode: str = "auto",
        strategy_profile_id: str | None = None,
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
        runner = get_quant_sim_replay_runner(db_file=self.db_file)
        started = runner.start_run(
            run_id,
            execute_prepared_replay_worker,
            self.db_file,
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

    def enqueue_past_to_live(
        self,
        *,
        start_datetime: datetime | str,
        end_datetime: datetime | str | None,
        timeframe: str,
        market: str,
        strategy_mode: str = "auto",
        strategy_profile_id: str | None = None,
        ai_dynamic_strategy: str = DEFAULT_AI_DYNAMIC_STRATEGY,
        ai_dynamic_strength: float = DEFAULT_AI_DYNAMIC_STRENGTH,
        ai_dynamic_lookback: int = DEFAULT_AI_DYNAMIC_LOOKBACK,
        commission_rate: float | None = None,
        sell_tax_rate: float | None = None,
        overwrite_live: bool = False,
        auto_start_scheduler: bool = True,
    ) -> int:
        self._ensure_no_active_replay()
        self._validate_live_handoff(overwrite_live=overwrite_live)
        context = self._prepare_replay_context(
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            timeframe=timeframe,
            market=market,
            strategy_mode=strategy_mode,
            strategy_profile_id=strategy_profile_id,
            ai_dynamic_strategy=ai_dynamic_strategy,
            ai_dynamic_strength=ai_dynamic_strength,
            ai_dynamic_lookback=ai_dynamic_lookback,
            commission_rate=commission_rate,
            sell_tax_rate=sell_tax_rate,
        )
        run_id = self._create_replay_run(
            mode="continuous_to_live",
            handoff_to_live=True,
            timeframe=timeframe,
            market=market,
            context=context,
            status="queued",
            status_message="等待后台任务启动",
        )
        runner = get_quant_sim_replay_runner(db_file=self.db_file)
        started = runner.start_run(
            run_id,
            execute_prepared_replay_worker,
            self.db_file,
            run_id,
            "continuous_to_live",
            True,
            context,
            auto_start_scheduler,
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

    def _prepare_replay_context(
        self,
        *,
        start_datetime: datetime | str,
        end_datetime: datetime | str | None,
        timeframe: str,
        market: str,
        strategy_mode: str,
        strategy_profile_id: str | None,
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
        scheduler_config = self.db.get_scheduler_config()
        selected_profile_id = str(
            strategy_profile_id
            if strategy_profile_id not in (None, "")
            else scheduler_config.get("strategy_profile_id")
        ).strip() or None
        strategy_profile_binding = self.db.resolve_strategy_profile_binding(selected_profile_id)
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
            "candidates": candidates,
            "stock_codes": stock_codes,
            "checkpoints": checkpoints,
            "account_summary": self.db.get_account_summary(),
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
            metadata={
                "candidate_count": len(context["candidates"]),
                "strategy_mode": context["strategy_mode"],
                "strategy_profile_id": str(profile_binding.get("profile_id") or ""),
                "strategy_profile_name": str(profile_binding.get("profile_name") or ""),
                "strategy_profile_version_id": int(profile_binding["version_id"]) if profile_binding.get("version_id") is not None else None,
                "strategy_profile_version": int(profile_binding["version"]) if profile_binding.get("version") is not None else None,
                "ai_dynamic_strategy": context.get("ai_dynamic_strategy"),
                "ai_dynamic_strength": context.get("ai_dynamic_strength"),
                "ai_dynamic_lookback": context.get("ai_dynamic_lookback"),
                "commission_rate": float(context.get("commission_rate") or 0),
                "sell_tax_rate": float(context.get("sell_tax_rate") or 0),
            },
        )

    def _ensure_no_active_replay(self) -> None:
        active_run = self.db.get_active_sim_run()
        if active_run is not None:
            raise ValueError(f"已有回放任务运行中（#{active_run['id']}），请先等待完成或取消")

    def _validate_live_handoff(self, *, overwrite_live: bool) -> None:
        live_account = self.db.get_account_summary()
        if not overwrite_live and (live_account["trade_count"] > 0 or live_account["position_count"] > 0):
            raise ValueError("当前实时模拟账户已有交易或持仓，请勾选覆盖后再执行接续模拟")

    def _execute_prepared_replay(
        self,
        *,
        run_id: int,
        mode: str,
        handoff_to_live: bool,
        context: dict,
        auto_start_scheduler: bool,
    ) -> dict:
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
            temp_engine = QuantSimEngine(db_file=temp_db_file, adapter=self.adapter)
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
                checkpoint_summary = self._run_checkpoint(
                    run_id=run_id,
                    checkpoint=checkpoint,
                    timeframe=timeframe,
                    strategy_mode=strategy_mode,
                    strategy_profile_binding=strategy_profile_binding,
                    ai_dynamic_strategy=ai_dynamic_strategy,
                    ai_dynamic_strength=ai_dynamic_strength,
                    ai_dynamic_lookback=ai_dynamic_lookback,
                    engine=temp_engine,
                    portfolio=temp_portfolio,
                    signal_service=temp_signal_service,
                )
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
            lots = self._collect_open_lots(temp_db, positions, as_of=end_dt)
            self.db.replace_sim_run_results(run_id, trades=trades, snapshots=snapshots, positions=positions, signals=replay_signals)

            metrics = self._calculate_run_metrics(account_summary["initial_cash"], trades, snapshots)

            if cancelled:
                completed_checkpoints = len(self.db.get_sim_run_checkpoints(run_id))
                self.db.finalize_sim_run(
                    run_id,
                    status="cancelled",
                    final_equity=float(metrics["final_equity"]),
                    total_return_pct=float(metrics["total_return_pct"]),
                    max_drawdown_pct=float(metrics["max_drawdown_pct"]),
                    win_rate=float(metrics["win_rate"]),
                    trade_count=len(trades),
                    status_message="回放任务已取消",
                    metadata={"checkpoint_count": completed_checkpoints},
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

            self.db.finalize_sim_run(
                run_id,
                status="completed",
                final_equity=float(metrics["final_equity"]),
                total_return_pct=float(metrics["total_return_pct"]),
                max_drawdown_pct=float(metrics["max_drawdown_pct"]),
                win_rate=float(metrics["win_rate"]),
                trade_count=len(trades),
                status_message="回放任务已完成",
                metadata={"checkpoint_count": len(checkpoints)},
            )
            self.db.append_sim_run_event(run_id, f"回放任务已完成，共生成 {len(trades)} 笔交易。", level="success")

            if handoff_to_live:
                self.db.replace_runtime_state(
                    initial_cash=float(account_summary["initial_cash"]),
                    available_cash=float(temp_portfolio.get_account_summary()["available_cash"]),
                    positions=positions,
                    lots=lots,
                    trades=trades,
                    snapshots=snapshots,
                )
                scheduler = get_quant_sim_scheduler(db_file=self.db_file)
                status = scheduler.get_status()
                scheduler.update_config(
                    enabled=bool(auto_start_scheduler),
                    auto_execute=True,
                    interval_minutes=int(status["interval_minutes"]),
                    trading_hours_only=bool(status["trading_hours_only"]),
                    analysis_timeframe=timeframe,
                    market=market,
                    strategy_profile_id=str(strategy_profile_binding.get("profile_id") or "") or None,
                    ai_dynamic_strategy=ai_dynamic_strategy,
                    ai_dynamic_strength=ai_dynamic_strength,
                    ai_dynamic_lookback=ai_dynamic_lookback,
                    commission_rate=commission_rate,
                    sell_tax_rate=sell_tax_rate,
                )
                if auto_start_scheduler:
                    scheduler.start()
                self.db.append_sim_run_event(run_id, "回放结果已接续到实时模拟账户。", level="success")

            return {
                "run_id": run_id,
                "status": "completed",
                "checkpoint_count": len(checkpoints),
                "trade_count": len(trades),
                "final_equity": metrics["final_equity"],
                "total_return_pct": metrics["total_return_pct"],
                "max_drawdown_pct": metrics["max_drawdown_pct"],
                "win_rate": metrics["win_rate"],
                "handoff_to_live": handoff_to_live,
            }
        except Exception as exc:
            partial_trades: list[dict] = []
            partial_snapshots: list[dict] = []
            partial_positions: list[dict] = []
            partial_signals: list[dict] = list(locals().get("replay_signals", []))
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
                self.db.replace_sim_run_results(
                    run_id,
                    trades=partial_trades,
                    snapshots=partial_snapshots,
                    positions=partial_positions,
                    signals=partial_signals,
                )

            metrics = self._calculate_run_metrics(account_summary["initial_cash"], partial_trades, partial_snapshots)
            failure_context = ""
            if "last_checkpoint_index" in locals() and last_checkpoint_index > 0:
                failure_context = f"第 {last_checkpoint_index}/{len(checkpoints)} 个检查点"
                if last_checkpoint_text:
                    failure_context = f"{failure_context}（{last_checkpoint_text}）"
                failure_context = f"{failure_context} 失败："
            status_message = f"{failure_context}{exc}" if failure_context else f"回放任务失败：{exc}"
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
        strategy_mode: str = "auto",
        strategy_profile_binding: dict | None = None,
        ai_dynamic_strategy: str = DEFAULT_AI_DYNAMIC_STRATEGY,
        ai_dynamic_strength: float = DEFAULT_AI_DYNAMIC_STRENGTH,
        ai_dynamic_lookback: int = DEFAULT_AI_DYNAMIC_LOOKBACK,
        engine: QuantSimEngine,
        portfolio: PortfolioService,
        signal_service: SignalCenterService,
    ) -> dict:
        candidates = engine.candidate_pool.list_candidates(status="active")
        positions = portfolio.list_positions()
        signals_created = 0
        candidates_scanned = 0
        positions_checked = 0
        checkpoint_signals: list[dict] = []
        checkpoint_text = self._format_datetime(checkpoint)
        total_candidates = len(candidates)
        total_positions = len(positions)
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

        for candidate_index, candidate in enumerate(candidates, start=1):
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

            self._update_run_step_status(
                run_id=run_id,
                checkpoint_text=checkpoint_text,
                message=f"检查点 {checkpoint_text}：分析候选股 {candidate_index}/{total_candidates} {candidate['stock_code']}",
            )
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
                )
            decision = engine._evaluate_candidate_decision(
                candidate,
                market_snapshot=snapshot,
                analysis_timeframe=timeframe,
                strategy_mode=strategy_mode,
                strategy_profile_binding=candidate_binding,
            )
            decision_price = engine._extract_decision_price(decision)
            if decision_price > 0:
                engine.candidate_pool.db.update_candidate_latest_price(candidate["stock_code"], decision_price)
            signal = signal_service.create_signal(candidate, decision, notify=False, mirror_to_ai=False)
            signal["checkpoint_at"] = self._format_datetime(checkpoint)
            checkpoint_signals.append(signal)
            signals_created += 1

        for position_index, position in enumerate(positions, start=1):
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

            self._update_run_step_status(
                run_id=run_id,
                checkpoint_text=checkpoint_text,
                message=f"检查点 {checkpoint_text}：分析持仓 {position_index}/{total_positions} {position['stock_code']}",
            )
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
                )
            decision = engine._evaluate_position_decision(
                candidate,
                position,
                market_snapshot=snapshot,
                analysis_timeframe=timeframe,
                strategy_mode=strategy_mode,
                strategy_profile_binding=position_binding,
            )
            decision_price = engine._extract_decision_price(decision)
            if decision_price > 0:
                portfolio.db.update_position_market_price(position["stock_code"], decision_price)
                portfolio.db.update_candidate_latest_price(position["stock_code"], decision_price)
            signal = signal_service.create_signal(candidate, decision, notify=False, mirror_to_ai=False)
            signal["checkpoint_at"] = self._format_datetime(checkpoint)
            checkpoint_signals.append(signal)
            signals_created += 1

        auto_executed = 0
        pending_signals = signal_service.list_pending_signals()
        total_pending = len(pending_signals)
        for signal_index, signal in enumerate(pending_signals, start=1):
            if run_id is not None and self.db.is_sim_run_cancel_requested(run_id):
                break
            self._update_run_step_status(
                run_id=run_id,
                checkpoint_text=checkpoint_text,
                message=(
                    f"检查点 {checkpoint_text}：自动执行信号 {signal_index}/{total_pending} "
                    f"{str(signal.get('action') or '').upper()} {signal.get('stock_code')}"
                ),
            )
            try:
                if portfolio.auto_execute_signal(signal, note="历史回放自动执行", executed_at=checkpoint):
                    auto_executed += 1
            except Exception as exc:
                if run_id is not None:
                    stock_code = str(signal.get("stock_code") or "")
                    action = str(signal.get("action") or "").upper()
                    self.db.append_sim_run_event(
                        run_id,
                        f"检查点 {self._format_datetime(checkpoint)} 自动执行 {action} {stock_code} 失败：{exc}",
                        level="error",
                    )
                continue

        self._update_run_step_status(
            run_id=run_id,
            checkpoint_text=checkpoint_text,
            message=f"检查点 {checkpoint_text}：写入账户快照",
        )
        portfolio.db.add_account_snapshot(run_reason=f"historical_range@{self._format_datetime(checkpoint)}")
        account_summary = portfolio.get_account_summary()
        return {
            "cancelled": False,
            "candidates_scanned": candidates_scanned,
            "positions_checked": positions_checked,
            "signals_created": signals_created,
            "auto_executed": auto_executed,
            "available_cash": account_summary["available_cash"],
            "market_value": account_summary["market_value"],
            "total_equity": account_summary["total_equity"],
            "signals": checkpoint_signals,
        }

    def _update_run_step_status(
        self,
        *,
        run_id: int | None,
        checkpoint_text: str,
        message: str,
    ) -> None:
        if run_id is None:
            return
        self.db.update_sim_run_progress(
            run_id,
            status="running",
            latest_checkpoint_at=checkpoint_text,
            status_message=message,
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


def execute_prepared_replay_worker(
    db_file: str,
    run_id: int,
    mode: str,
    handoff_to_live: bool,
    context: dict,
    auto_start_scheduler: bool,
) -> None:
    service = QuantSimReplayService(db_file=db_file)
    service._execute_prepared_replay(
        run_id=run_id,
        mode=mode,
        handoff_to_live=handoff_to_live,
        context=context,
        auto_start_scheduler=auto_start_scheduler,
    )
