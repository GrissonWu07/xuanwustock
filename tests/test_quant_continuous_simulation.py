from datetime import datetime

from quant_kernel.models import Decision
from quant_sim.candidate_pool_service import CandidatePoolService
from quant_sim.db import QuantSimDB
from quant_sim.replay_service import QuantSimReplayService
from quant_sim.scheduler import get_quant_sim_scheduler
from watchlist_integration import add_watchlist_rows_to_quant_pool
from watchlist_service import WatchlistService


class HoldSnapshotProvider:
    def prepare(self, stock_codes, start_datetime, end_datetime, timeframe):
        return None

    def get_snapshot(self, stock_code, checkpoint, timeframe, stock_name=None):
        del stock_code, stock_name
        return {
            "current_price": 10.0,
            "latest_price": 10.0,
            "ma5": 9.8,
            "ma20": 9.5,
            "ma60": 9.2,
            "macd": 0.5,
            "rsi12": 58.0,
            "volume_ratio": 1.4,
            "trend": "up",
        }


class BuyAndHoldAdapter:
    def analyze_candidate(self, candidate, market_snapshot=None):
        return Decision(
            code=candidate["stock_code"],
            action="BUY",
            confidence=0.81,
            price=float((market_snapshot or {}).get("current_price") or 10.0),
            timestamp=datetime(2026, 1, 5, 14, 50),
            reason="连续模拟建仓",
            tech_score=0.7,
            context_score=0.26,
            position_ratio=0.6,
            decision_type="dual_track_resonance",
        )

    def analyze_position(self, candidate, position, market_snapshot=None):
        return Decision(
            code=position["stock_code"],
            action="HOLD",
            confidence=0.65,
            price=float((market_snapshot or {}).get("current_price") or 10.0),
            timestamp=datetime(2026, 1, 5, 14, 50),
            reason="连续模拟持有",
            tech_score=0.15,
            context_score=0.2,
            position_ratio=0.0,
            decision_type="single_track",
        )


def test_continuous_replay_handoff_replaces_live_state_and_enables_scheduler(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        latest_price=10.0,
    )
    scheduler = get_quant_sim_scheduler(db_file=db_file)
    scheduler.stop()

    replay_service = QuantSimReplayService(
        db_file=db_file,
        snapshot_provider=HoldSnapshotProvider(),
        adapter=BuyAndHoldAdapter(),
    )

    summary = replay_service.run_past_to_live(
        start_datetime=datetime(2026, 1, 5, 0, 0),
        end_datetime=datetime(2026, 1, 5, 23, 59),
        timeframe="1d",
        market="CN",
        overwrite_live=True,
        auto_start_scheduler=False,
    )

    db = QuantSimDB(db_file)
    live_account = db.get_account_summary()
    live_positions = db.get_positions()
    live_trades = db.get_trade_history()
    scheduler_config = db.get_scheduler_config()
    runs = db.get_sim_runs(limit=1)

    assert summary["handoff_to_live"] is True
    assert live_account["position_count"] == 1
    assert live_account["trade_count"] == 1
    assert len(live_positions) == 1
    assert live_positions[0]["stock_code"] == "300390"
    assert len(live_trades) == 1
    assert live_trades[0]["action"] == "buy"
    assert scheduler_config["auto_execute"] is True
    assert scheduler_config["analysis_timeframe"] == "1d"
    assert runs[0]["mode"] == "continuous_to_live"


def test_continuous_replay_accepts_candidates_promoted_from_watchlist(tmp_path):
    watch_db = tmp_path / "watchlist.db"
    quant_db = tmp_path / "quant_sim.db"

    watchlist = WatchlistService(db_file=watch_db)
    quant_pool = CandidatePoolService(db_file=quant_db)
    watchlist.add_stock("300390", "天华新能", "main_force", 10.0, None, {})
    add_watchlist_rows_to_quant_pool(["300390"], watchlist, quant_pool)

    replay_service = QuantSimReplayService(
        db_file=quant_db,
        snapshot_provider=HoldSnapshotProvider(),
        adapter=BuyAndHoldAdapter(),
    )

    summary = replay_service.run_past_to_live(
        start_datetime=datetime(2026, 1, 5, 0, 0),
        end_datetime=datetime(2026, 1, 5, 23, 59),
        timeframe="1d",
        market="CN",
        overwrite_live=True,
        auto_start_scheduler=False,
    )

    assert summary["trade_count"] == 1
    assert watchlist.get_watch("300390")["in_quant_pool"] is True


class OrderedSnapshotProvider:
    def __init__(self):
        self.prepared = []

    def prepare(self, stock_codes, start_datetime, end_datetime, timeframe):
        self.prepared.append((tuple(stock_codes), start_datetime, end_datetime, timeframe))

    def get_snapshot(self, stock_code, checkpoint, timeframe, stock_name=None):
        del stock_code, timeframe, stock_name
        price_map = {
            datetime(2026, 1, 5, 14, 50): 10.0,
            datetime(2026, 1, 6, 14, 50): 12.0,
        }
        price = price_map[checkpoint]
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


class BuyThenSellAdapter:
    def analyze_candidate(self, candidate, market_snapshot=None):
        price = float((market_snapshot or {}).get("current_price") or 0)
        if price <= 10:
            return Decision(
                code=candidate["stock_code"],
                action="BUY",
                confidence=0.82,
                price=price,
                timestamp=datetime(2026, 1, 5, 14, 50),
                reason="连续模拟建仓",
                tech_score=0.72,
                context_score=0.28,
                position_ratio=0.6,
                decision_type="dual_track_resonance",
            )
        return Decision(
            code=candidate["stock_code"],
            action="HOLD",
            confidence=0.6,
            price=price,
            timestamp=datetime(2026, 1, 6, 14, 50),
            reason="连续模拟继续观察",
            tech_score=0.1,
            context_score=0.28,
            position_ratio=0.0,
            decision_type="single_track",
        )

    def analyze_position(self, candidate, position, market_snapshot=None):
        price = float((market_snapshot or {}).get("current_price") or 0)
        return Decision(
            code=position["stock_code"],
            action="SELL" if price >= 12 else "HOLD",
            confidence=0.84,
            price=price,
            timestamp=datetime(2026, 1, 6, 14, 50),
            reason="连续模拟卖出",
            tech_score=-0.45,
            context_score=0.12,
            position_ratio=0.0,
            decision_type="dual_track_divergence",
        )


def test_continuous_replay_preserves_snapshot_order_and_allows_open_ended_end_datetime(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        latest_price=10.0,
    )

    snapshot_provider = OrderedSnapshotProvider()
    replay_service = QuantSimReplayService(
        db_file=db_file,
        snapshot_provider=snapshot_provider,
        adapter=BuyThenSellAdapter(),
    )
    replay_service._current_time = lambda: datetime(2026, 1, 6, 23, 59)  # type: ignore[attr-defined]

    summary = replay_service.run_past_to_live(
        start_datetime=datetime(2026, 1, 5, 0, 0),
        end_datetime=None,
        timeframe="1d",
        market="CN",
        overwrite_live=True,
        auto_start_scheduler=False,
    )

    db = QuantSimDB(db_file)
    live_snapshots = db.get_account_snapshots(limit=10)

    assert summary["final_equity"] == 112000.0
    assert snapshot_provider.prepared[0][2] == datetime(2026, 1, 6, 23, 59)
    assert live_snapshots[0]["run_reason"].endswith("2026-01-06 14:50:00")
    assert live_snapshots[1]["run_reason"].endswith("2026-01-05 14:50:00")


def test_continuous_replay_handoff_preserves_requested_timeframe(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    candidate_service = CandidatePoolService(db_file=db_file)
    candidate_service.add_candidate(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        latest_price=10.0,
    )

    replay_service = QuantSimReplayService(
        db_file=db_file,
        snapshot_provider=HoldSnapshotProvider(),
        adapter=BuyAndHoldAdapter(),
    )

    replay_service.run_past_to_live(
        start_datetime=datetime(2026, 1, 5, 0, 0),
        end_datetime=datetime(2026, 1, 5, 23, 59),
        timeframe="1d+30m",
        market="CN",
        overwrite_live=True,
        auto_start_scheduler=False,
    )

    scheduler_config = QuantSimDB(db_file).get_scheduler_config()

    assert scheduler_config["analysis_timeframe"] == "1d+30m"
