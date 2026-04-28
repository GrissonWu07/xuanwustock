import inspect
from datetime import datetime

import pandas as pd

from app.quant_kernel.models import Decision
from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.db import QuantSimDB
from app.quant_sim.engine import QuantSimEngine
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.replay_service import MainProjectHistoricalSnapshotProvider, QuantSimReplayService
from app.quant_sim.signal_center_service import SignalCenterService
from app.notification_service import notification_service


def test_replay_queue_methods_accept_initial_cash():
    assert "initial_cash" in inspect.signature(QuantSimReplayService.enqueue_historical_range).parameters
    assert "initial_cash" in inspect.signature(QuantSimReplayService.enqueue_past_to_live).parameters


class FakeSnapshotProvider:
    def __init__(self):
        self.prepared = []

    def prepare(self, stock_codes, start_datetime, end_datetime, timeframe):
        self.prepared.append((tuple(stock_codes), start_datetime, end_datetime, timeframe))

    def get_snapshot(self, stock_code, checkpoint, timeframe, stock_name=None):
        del stock_name
        if checkpoint.date() == datetime(2026, 1, 5).date():
            price = 10.0
        else:
            price = 12.0
        return {
            "current_price": price,
            "latest_price": price,
            "ma5": price - 0.2,
            "ma20": price - 0.5,
            "ma60": price - 0.8,
            "macd": 0.6 if price <= 10 else -0.7,
            "rsi12": 55.0 if price <= 10 else 78.0,
            "volume_ratio": 1.5,
            "trend": "up" if price <= 10 else "down",
        }


class FakeAdapter:
    def __init__(self):
        self.candidate_calls = []
        self.position_calls = []

    def analyze_candidate(self, candidate, market_snapshot=None, analysis_timeframe="1d", strategy_mode="auto"):
        self.candidate_calls.append(
            {
                "stock_code": candidate["stock_code"],
                "analysis_timeframe": analysis_timeframe,
                "strategy_mode": strategy_mode,
            }
        )
        price = float((market_snapshot or {}).get("current_price") or 0)
        if price <= 10:
            return Decision(
                code=candidate["stock_code"],
                action="BUY",
                confidence=0.82,
                price=price,
                timestamp=datetime(2026, 1, 5, 14, 50),
                reason="历史回放买入信号",
                tech_score=0.72,
                context_score=0.28,
                position_ratio=0.6,
                decision_type="dual_track_resonance",
                strategy_profile={
                    "analysis_timeframe": {"key": analysis_timeframe},
                    "strategy_mode": {"key": strategy_mode, "label": strategy_mode},
                },
            )
        return Decision(
            code=candidate["stock_code"],
            action="HOLD",
            confidence=0.6,
            price=price,
            timestamp=datetime(2026, 1, 6, 14, 50),
            reason="历史回放继续观察",
            tech_score=0.1,
            context_score=0.28,
            position_ratio=0.0,
            decision_type="single_track",
            strategy_profile={
                "analysis_timeframe": {"key": analysis_timeframe},
                "strategy_mode": {"key": strategy_mode, "label": strategy_mode},
            },
        )

    def analyze_position(self, candidate, position, market_snapshot=None, analysis_timeframe="1d", strategy_mode="auto"):
        self.position_calls.append(
            {
                "stock_code": position["stock_code"],
                "analysis_timeframe": analysis_timeframe,
                "strategy_mode": strategy_mode,
            }
        )
        price = float((market_snapshot or {}).get("current_price") or 0)
        return Decision(
            code=position["stock_code"],
            action="SELL" if price >= 12 else "HOLD",
            confidence=0.84,
            price=price,
            timestamp=datetime(2026, 1, 6, 14, 50),
            reason="历史回放卖出信号",
            tech_score=-0.45,
            context_score=0.12,
            position_ratio=0.0,
            decision_type="dual_track_divergence",
            strategy_profile={
                "analysis_timeframe": {"key": analysis_timeframe},
                "strategy_mode": {"key": strategy_mode, "label": strategy_mode},
            },
        )


class FakeTdxFetcher:
    def get_kline_data_range(self, stock_code, *, kline_type, start_datetime, end_datetime, max_bars):
        del stock_code, kline_type, start_datetime, end_datetime, max_bars
        return pd.DataFrame(
            [
                {
                    "日期": pd.Timestamp("2026-01-05 10:00:00"),
                    "开盘": 10.0,
                    "收盘": 10.2,
                    "最高": 10.3,
                    "最低": 9.9,
                    "成交量": 1200,
                    "成交额": 12000,
                }
            ]
        )


class NoLookupReplayFetcher:
    def build_snapshot_from_history(self, stock_code, snapshot_window, stock_name=None):
        assert stock_name == stock_code
        assert not snapshot_window.empty
        return {
            "code": stock_code,
            "name": stock_name,
            "current_price": float(snapshot_window.iloc[-1]["收盘"]),
        }


def test_snapshot_provider_accepts_intraday_dataframe_without_truthiness_error():
    provider = MainProjectHistoricalSnapshotProvider(tdx_fetcher=FakeTdxFetcher())

    history = provider._load_history(  # noqa: SLF001 - targeted regression coverage
        "300390",
        start_datetime=datetime(2026, 1, 5, 0, 0),
        end_datetime=datetime(2026, 1, 5, 23, 59),
        timeframe="30m",
    )

    assert isinstance(history, pd.DataFrame)
    assert list(history.columns) == ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"]
    assert len(history) == 1


def test_snapshot_provider_falls_back_to_stock_code_when_name_missing():
    provider = MainProjectHistoricalSnapshotProvider(tdx_fetcher=NoLookupReplayFetcher())
    provider.cache[("300390", "30m")] = pd.DataFrame(
        [
            {
                "日期": pd.Timestamp("2026-01-05 10:00:00"),
                "开盘": 10.0,
                "收盘": 10.2,
                "最高": 10.3,
                "最低": 9.9,
                "成交量": 1200,
                "成交额": 12000,
            }
        ]
    )

    snapshot = provider.get_snapshot("300390", datetime(2026, 1, 5, 10, 0), "30m", stock_name=None)

    assert snapshot["name"] == "300390"


def test_snapshot_provider_populates_extended_indicator_fields_from_history():
    provider = MainProjectHistoricalSnapshotProvider()
    dates = pd.date_range("2026-01-01 09:30:00", periods=80, freq="30min")
    history = pd.DataFrame(
        {
            "日期": dates,
            "开盘": [20 + i * 0.05 for i in range(80)],
            "收盘": [20 + i * 0.06 + (0.12 if i % 5 == 0 else 0.0) for i in range(80)],
            "最高": [20.3 + i * 0.06 for i in range(80)],
            "最低": [19.8 + i * 0.05 for i in range(80)],
            "成交量": [1000 + i * 25 for i in range(80)],
            "成交额": [20000 + i * 600 for i in range(80)],
        }
    )
    provider.cache[("300390", "30m")] = history

    snapshot = provider.get_snapshot("300390", dates[-1].to_pydatetime(), "30m", stock_name="天华新能")

    assert snapshot["name"] == "天华新能"
    assert "ma20_slope" in snapshot
    assert "dif" in snapshot
    assert "dea" in snapshot
    assert "hist" in snapshot
    assert "hist_prev" in snapshot
    assert "k" in snapshot
    assert "d" in snapshot
    assert "j" in snapshot
    assert "obv" in snapshot
    assert "obv_prev" in snapshot
    assert "atr" in snapshot
    assert snapshot["ma20_slope"] != 0
    assert snapshot["obv"] != snapshot["obv_prev"]
    assert snapshot["atr"] > 0


def test_historical_replay_persists_run_artifacts_without_touching_live_account(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        latest_price=10.0,
        notes="回放测试",
    )

    replay_service = QuantSimReplayService(
        db_file=db_file,
        snapshot_provider=FakeSnapshotProvider(),
        adapter=FakeAdapter(),
    )

    summary = replay_service.run_historical_range(
        start_datetime=datetime(2026, 1, 5, 0, 0),
        end_datetime=datetime(2026, 1, 6, 23, 59),
        timeframe="1d",
        market="CN",
    )

    db = QuantSimDB(db_file)
    runs = db.get_sim_runs(limit=5)
    run = runs[0]
    checkpoints = db.get_sim_run_checkpoints(run["id"])
    trades = db.get_sim_run_trades(run["id"])
    snapshots = db.get_sim_run_snapshots(run["id"])
    signals = db.get_sim_run_signals(run["id"])
    live_account = db.get_account_summary()

    assert summary["status"] == "completed"
    assert summary["trade_count"] == 2
    assert summary["checkpoint_count"] == 2
    assert run["mode"] == "historical_range"
    assert run["status"] == "completed"
    assert run["timeframe"] == "1d"
    assert run["trade_count"] == 2
    assert summary["final_equity"] == 101800.0
    assert summary["total_return_pct"] == 1.8
    assert float(run["final_equity"]) == 101800.0
    assert len(checkpoints) == 2
    assert [trade["action"] for trade in trades] == ["SELL", "BUY"]
    assert len(signals) >= 2
    assert all(int(trade["signal_id"]) > 0 for trade in trades)
    assert {int(trade["signal_id"]) for trade in trades}.issubset({int(signal["id"]) for signal in signals})
    assert len(snapshots) == 2
    assert live_account["trade_count"] == 0
    assert live_account["position_count"] == 0
    assert live_account["available_cash"] == 100000.0


def test_historical_replay_does_not_send_live_signal_notifications(tmp_path, monkeypatch):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        latest_price=10.0,
        notes="回放通知隔离测试",
    )

    sent_notifications: list[dict] = []
    monkeypatch.setattr(notification_service, "send_notification", lambda payload: sent_notifications.append(payload) or True)

    replay_service = QuantSimReplayService(
        db_file=db_file,
        snapshot_provider=FakeSnapshotProvider(),
        adapter=FakeAdapter(),
    )

    summary = replay_service.run_historical_range(
        start_datetime=datetime(2026, 1, 5, 0, 0),
        end_datetime=datetime(2026, 1, 6, 23, 59),
        timeframe="1d",
        market="CN",
    )

    assert summary["status"] == "completed"
    assert sent_notifications == []


def test_historical_replay_allows_open_ended_end_datetime(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        latest_price=10.0,
        notes="回放测试",
    )

    snapshot_provider = FakeSnapshotProvider()
    replay_service = QuantSimReplayService(
        db_file=db_file,
        snapshot_provider=snapshot_provider,
        adapter=FakeAdapter(),
    )
    replay_service._current_time = lambda: datetime(2026, 1, 6, 23, 59)  # type: ignore[attr-defined]

    summary = replay_service.run_historical_range(
        start_datetime=datetime(2026, 1, 5, 0, 0),
        end_datetime=None,
        timeframe="1d",
        market="CN",
    )

    assert summary["status"] == "completed"
    assert snapshot_provider.prepared[0][2] == datetime(2026, 1, 6, 23, 59)


def test_historical_replay_passes_requested_timeframe_to_adapter(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        latest_price=10.0,
        notes="回放测试",
    )

    adapter = FakeAdapter()
    replay_service = QuantSimReplayService(
        db_file=db_file,
        snapshot_provider=FakeSnapshotProvider(),
        adapter=adapter,
    )

    summary = replay_service.run_historical_range(
        start_datetime=datetime(2026, 1, 5, 0, 0),
        end_datetime=datetime(2026, 1, 6, 23, 59),
        timeframe="30m",
        market="CN",
    )

    assert summary["status"] == "completed"
    assert adapter.candidate_calls[0]["analysis_timeframe"] == "30m"


def test_historical_replay_supports_resonance_timeframe(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        latest_price=10.0,
        notes="回放测试",
    )

    adapter = FakeAdapter()
    replay_service = QuantSimReplayService(
        db_file=db_file,
        snapshot_provider=FakeSnapshotProvider(),
        adapter=adapter,
    )

    summary = replay_service.run_historical_range(
        start_datetime=datetime(2026, 1, 5, 0, 0),
        end_datetime=datetime(2026, 1, 5, 23, 59),
        timeframe="1d+30m",
        market="CN",
    )

    assert summary["status"] == "completed"
    assert adapter.candidate_calls[0]["analysis_timeframe"] == "1d+30m"


def test_historical_replay_persists_run_strategy_signals(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        latest_price=10.0,
        notes="回放策略信号测试",
    )

    replay_service = QuantSimReplayService(
        db_file=db_file,
        snapshot_provider=FakeSnapshotProvider(),
        adapter=FakeAdapter(),
    )

    summary = replay_service.run_historical_range(
        start_datetime=datetime(2026, 1, 5, 0, 0),
        end_datetime=datetime(2026, 1, 6, 23, 59),
        timeframe="30m",
        market="CN",
    )

    db = QuantSimDB(db_file)
    run = db.get_sim_runs(limit=1)[0]
    replay_signals = db.get_sim_run_signals(run["id"])

    assert summary["status"] == "completed"
    assert replay_signals
    assert all(signal["run_id"] == run["id"] for signal in replay_signals)
    assert any(signal["action"] == "BUY" for signal in replay_signals)
    assert replay_signals[0]["strategy_profile"]["analysis_timeframe"]["key"] == "30m"


def test_historical_replay_persists_signals_incrementally_per_checkpoint(tmp_path, monkeypatch):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        latest_price=10.0,
        notes="回放增量信号测试",
    )

    replay_service = QuantSimReplayService(
        db_file=db_file,
        snapshot_provider=FakeSnapshotProvider(),
        adapter=FakeAdapter(),
    )

    visible_signal_counts: list[int] = []
    visible_trade_counts: list[int] = []
    original_add_checkpoint = replay_service.db.add_sim_run_checkpoint

    def recording_add_checkpoint(run_id, *args, **kwargs):
        visible_signal_counts.append(len(replay_service.db.get_sim_run_signals(run_id)))
        visible_trade_counts.append(len(replay_service.db.get_sim_run_trades(run_id)))
        return original_add_checkpoint(run_id, *args, **kwargs)

    monkeypatch.setattr(replay_service.db, "add_sim_run_checkpoint", recording_add_checkpoint)

    summary = replay_service.run_historical_range(
        start_datetime=datetime(2026, 1, 5, 0, 0),
        end_datetime=datetime(2026, 1, 6, 23, 59),
        timeframe="30m",
        market="CN",
    )

    assert summary["status"] == "completed"
    assert visible_signal_counts
    assert visible_signal_counts[0] > 0
    assert any(count > 0 for count in visible_trade_counts)


def test_historical_replay_persists_selected_strategy_mode(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        latest_price=10.0,
        notes="回放策略模式测试",
    )

    adapter = FakeAdapter()
    replay_service = QuantSimReplayService(
        db_file=db_file,
        snapshot_provider=FakeSnapshotProvider(),
        adapter=adapter,
    )

    summary = replay_service.run_historical_range(
        start_datetime=datetime(2026, 1, 5, 0, 0),
        end_datetime=datetime(2026, 1, 6, 23, 59),
        timeframe="30m",
        market="CN",
        strategy_mode="neutral",
    )

    db = QuantSimDB(db_file)
    run = db.get_sim_runs(limit=1)[0]
    replay_signals = db.get_sim_run_signals(run["id"])

    assert summary["status"] == "completed"
    assert run["metadata"]["strategy_mode"] == "neutral"
    assert adapter.candidate_calls[0]["strategy_mode"] == "neutral"
    assert replay_signals[0]["strategy_profile"]["strategy_mode"]["key"] == "neutral"


def test_enqueue_historical_replay_creates_background_run_record(tmp_path, monkeypatch):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        latest_price=10.0,
        notes="回放测试",
    )

    replay_service = QuantSimReplayService(
        db_file=db_file,
        snapshot_provider=FakeSnapshotProvider(),
        adapter=FakeAdapter(),
    )

    runner_calls = []

    class FakeReplayRunner:
        def start_run(self, run_id, target, *args):
            runner_calls.append({"run_id": run_id, "target": target, "args": args})
            return True

    monkeypatch.setattr("app.quant_sim.replay_service.get_quant_sim_replay_runner", lambda db_file=None: FakeReplayRunner())

    run_id = replay_service.enqueue_historical_range(
        start_datetime=datetime(2026, 1, 5, 0, 0),
        end_datetime=datetime(2026, 1, 6, 23, 59),
        timeframe="30m",
        market="CN",
    )

    db = QuantSimDB(db_file)
    run = db.get_sim_runs(limit=1)[0]
    expected_checkpoints = len(
        replay_service.timepoint_generator.generate(
            datetime(2026, 1, 5, 0, 0),
            datetime(2026, 1, 6, 23, 59),
            "30m",
        )
    )

    assert run_id == run["id"]
    assert run["status"] == "queued"
    assert run["progress_total"] == expected_checkpoints
    assert run["status_message"] == "等待后台任务启动"
    assert runner_calls[0]["run_id"] == run_id


def test_run_checkpoint_honors_cancel_request_inside_candidate_loop(tmp_path, monkeypatch):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_candidate(stock_code="300390", stock_name="天华新能", source="main_force", latest_price=10.0, notes="回放测试")
    candidate_service.add_candidate(stock_code="600531", stock_name="豫光金铅", source="main_force", latest_price=8.0, notes="回放测试")

    replay_service = QuantSimReplayService(
        db_file=db_file,
        snapshot_provider=FakeSnapshotProvider(),
        adapter=FakeAdapter(),
    )
    engine = QuantSimEngine(db_file=db_file, adapter=replay_service.adapter)
    portfolio = PortfolioService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)

    state = {"count": 0}

    def fake_cancel_requested(run_id):
        state["count"] += 1
        return state["count"] >= 2

    monkeypatch.setattr(replay_service.db, "is_sim_run_cancel_requested", fake_cancel_requested)

    summary = replay_service._run_checkpoint(  # noqa: SLF001 - targeted cancellation regression
        run_id=99,
        checkpoint=datetime(2026, 1, 5, 10, 0),
        timeframe="30m",
        engine=engine,
        portfolio=portfolio,
        signal_service=signal_service,
    )

    assert summary["cancelled"] is True
    assert summary["candidates_scanned"] == 1


def test_run_checkpoint_logs_signal_execution_error_and_continues(tmp_path, monkeypatch):
    db_file = tmp_path / "app.quant_sim.db"
    replay_service = QuantSimReplayService(
        db_file=db_file,
        snapshot_provider=FakeSnapshotProvider(),
        adapter=FakeAdapter(),
    )
    engine = QuantSimEngine(db_file=db_file, adapter=replay_service.adapter)
    portfolio = PortfolioService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)
    run_id = replay_service.db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-01-05 09:30:00",
        end_datetime="2026-01-05 15:00:00",
        initial_cash=100000.0,
        status="running",
        progress_total=1,
    )

    monkeypatch.setattr(signal_service, "list_pending_signals", lambda: [{"id": 99, "stock_code": "301291", "action": "SELL"}])

    def fake_auto_execute_signal(signal, note=None, executed_at=None):
        raise ValueError("sell quantity exceeds sellable quantity")

    monkeypatch.setattr(portfolio, "auto_execute_signal", fake_auto_execute_signal)

    summary = replay_service._run_checkpoint(  # noqa: SLF001 - targeted replay resilience coverage
        run_id=run_id,
        checkpoint=datetime(2026, 1, 5, 10, 0),
        timeframe="30m",
        engine=engine,
        portfolio=portfolio,
        signal_service=signal_service,
    )

    events = replay_service.db.get_sim_run_events(run_id, limit=10)

    assert summary["cancelled"] is False
    assert summary["auto_executed"] == 0
    assert any("sell quantity exceeds sellable quantity" in event["message"] for event in events)


def test_run_checkpoint_updates_run_status_message_for_substeps(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        latest_price=10.0,
        notes="回放状态测试",
    )
    replay_service = QuantSimReplayService(
        db_file=db_file,
        snapshot_provider=FakeSnapshotProvider(),
        adapter=FakeAdapter(),
    )
    engine = QuantSimEngine(db_file=db_file, adapter=replay_service.adapter)
    portfolio = PortfolioService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)
    run_id = replay_service.db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-01-05 09:30:00",
        end_datetime="2026-01-05 15:00:00",
        initial_cash=100000.0,
        status="running",
        progress_total=1,
        status_message="执行中",
    )

    summary = replay_service._run_checkpoint(  # noqa: SLF001 - targeted progress visibility coverage
        run_id=run_id,
        checkpoint=datetime(2026, 1, 5, 10, 0),
        timeframe="30m",
        engine=engine,
        portfolio=portfolio,
        signal_service=signal_service,
    )
    run = replay_service.db.get_sim_run(run_id)

    assert summary["cancelled"] is False
    assert "写入账户快照" in str(run["status_message"])


def test_run_checkpoint_excludes_held_codes_from_candidate_scan(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        latest_price=10.0,
        notes="回放持仓排除测试",
    )
    replay_service = QuantSimReplayService(
        db_file=db_file,
        snapshot_provider=FakeSnapshotProvider(),
        adapter=FakeAdapter(),
    )
    engine = QuantSimEngine(db_file=db_file, adapter=replay_service.adapter)
    portfolio = PortfolioService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)

    entry_signal = signal_service.create_signal(
        {"stock_code": "300390", "stock_name": "天华新能", "source": "main_force", "latest_price": 10.0},
        Decision(
            code="300390",
            action="BUY",
            confidence=0.9,
            price=10.0,
            timestamp=datetime(2026, 1, 5, 9, 30),
            reason="pre-existing position",
            tech_score=0.8,
            context_score=0.3,
            position_ratio=0.2,
            decision_type="seed",
            strategy_profile={},
        ),
        notify=False,
        mirror_to_ai=False,
    )
    portfolio.confirm_buy(
        int(entry_signal["id"]),
        price=10.0,
        quantity=100,
        note="seed position",
        executed_at=datetime(2026, 1, 5, 9, 30),
    )
    conn = replay_service.db._connect()  # noqa: SLF001 - force inconsistent active+holding state
    try:
        conn.execute("UPDATE candidate_pool SET status = 'active' WHERE stock_code = '300390'")
        conn.commit()
    finally:
        conn.close()

    summary = replay_service._run_checkpoint(  # noqa: SLF001 - targeted replay parity regression
        checkpoint=datetime(2026, 1, 5, 10, 0),
        timeframe="30m",
        engine=engine,
        portfolio=portfolio,
        signal_service=signal_service,
    )

    assert summary["cancelled"] is False
    assert summary["candidates_scanned"] == 0
    assert summary["positions_checked"] == 1
    assert replay_service.adapter.candidate_calls == []
    assert replay_service.adapter.position_calls == [{"stock_code": "300390", "analysis_timeframe": "30m", "strategy_mode": "auto"}]


def test_run_checkpoint_resolves_dynamic_binding_per_symbol(tmp_path, monkeypatch):
    db_file = tmp_path / "app.quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        latest_price=10.0,
        notes="回放动态策略测试",
    )
    replay_service = QuantSimReplayService(
        db_file=db_file,
        snapshot_provider=FakeSnapshotProvider(),
        adapter=FakeAdapter(),
    )
    engine = QuantSimEngine(db_file=db_file, adapter=replay_service.adapter)
    portfolio = PortfolioService(db_file=db_file)
    signal_service = SignalCenterService(db_file=db_file)
    captured = []

    def fake_resolve(
        *,
        strategy_profile_id,
        ai_dynamic_strategy=None,
        ai_dynamic_strength=None,
        ai_dynamic_lookback=None,
        stock_code=None,
        stock_name=None,
        as_of=None,
    ):
        captured.append((stock_code, stock_name, ai_dynamic_strategy, ai_dynamic_strength, ai_dynamic_lookback, as_of))
        return {
            "profile_id": "aggressive",
            "profile_name": "积极",
            "version_id": 1,
            "version": 1,
            "config": {},
        }

    monkeypatch.setattr(engine, "_resolve_strategy_binding", fake_resolve)

    summary = replay_service._run_checkpoint(  # noqa: SLF001 - targeted dynamic binding coverage
        checkpoint=datetime(2026, 1, 5, 10, 0),
        timeframe="30m",
        ai_dynamic_strategy="hybrid",
        ai_dynamic_strength=0.5,
        ai_dynamic_lookback=48,
        engine=engine,
        portfolio=portfolio,
        signal_service=signal_service,
    )

    assert summary["cancelled"] is False
    assert captured == [
        ("300390", "天华新能", "hybrid", 0.5, 48, datetime(2026, 1, 5, 10, 0)),
    ]


def test_historical_snapshot_provider_daily_strict_mode_uses_unadjusted_prices(monkeypatch):
    from app.quant_sim import replay_service as replay_module

    captured = {}

    def fake_get_stock_hist_data(stock_code, *, start_date=None, end_date=None, adjust="qfq"):
        captured["stock_code"] = stock_code
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        captured["adjust"] = adjust
        return []

    monkeypatch.setattr(replay_module.data_source_manager, "get_stock_hist_data", fake_get_stock_hist_data)
    provider = replay_module.MainProjectHistoricalSnapshotProvider()

    provider._load_history(  # noqa: SLF001 - targeted data source contract coverage
        "002518",
        start_datetime=datetime(2025, 8, 1, 9, 30),
        end_datetime=datetime(2025, 8, 29, 15, 0),
        timeframe="1d",
    )

    assert captured["adjust"] == ""
