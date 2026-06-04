from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from datetime import datetime

from app.quant_sim.market_technical_artifact import MarketTechnicalArtifactRef
from app.quant_sim.market_technical_artifact_store import MarketTechnicalArtifactStore
from app.quant_sim.replay_artifact_adapter import RunArtifactItem
from app.quant_sim.run_market_artifact_preloader import (
    RunMarketArtifactPreloadRequest,
    preload_run_market_artifacts,
)


def _snapshot(price: float) -> dict:
    return {
        "open": price - 0.2,
        "high": price + 0.3,
        "low": price - 0.4,
        "close": price,
        "latest_price": price,
        "prev_close": price - 0.1,
        "volume": 1_000_000,
        "amount": price * 1_000_000,
        "turnover_rate": 1.2,
        "volume_ratio": 1.5,
        "ma5": price - 0.1,
        "ma10": price - 0.2,
        "ma20": price - 0.3,
        "ma60": price - 0.6,
        "ma20_slope": 0.02,
        "rsi": 58.0,
        "macd": 0.12,
        "macd_signal": 0.08,
        "macd_histogram": 0.04,
        "trend": "up",
        "price_vs_ma20": 0.03,
        "price_vs_ma60": 0.06,
        "ma_stack": "ma5>ma10>ma20",
        "above_ma20_checkpoints": 3,
        "retest_confirmed": True,
        "is_suspended": False,
        "is_limit_up": False,
        "is_limit_down": False,
        "liquidity_ready": True,
        "provider": "fixture",
        "indicator_version": "test_v1",
        "technical_snapshot_ready": True,
        "technical_snapshot_status": "ready",
        "technical_snapshot_timeframe": "30m",
    }


def test_preload_run_market_artifacts_materializes_full_stock_checkpoint_range(tmp_path):
    shared_db = tmp_path / "quant_sim.db"
    replay_db = tmp_path / "quant_sim_replay.db"
    checkpoints = [datetime(2026, 1, 5, 10, 0), datetime(2026, 1, 5, 10, 30)]
    calls: list[tuple[str, datetime]] = []

    def load_snapshot(item: RunArtifactItem) -> dict:
        calls.append((item.stock_code, item.checkpoint))
        return _snapshot(10.0 + len(calls))

    report = preload_run_market_artifacts(
        RunMarketArtifactPreloadRequest(
            db_file=replay_db,
            shared_db_file=shared_db,
            run_id=11,
            run_type="live_quant_drill",
            market="CN",
            timeframe="30m",
            stock_items=[
                {"stock_code": "600000", "stock_name": "浦发银行"},
                {"stock_code": "000001", "stock_name": "平安银行"},
            ],
            checkpoints=checkpoints,
            snapshot_loader=load_snapshot,
            trace_id="test-preload",
        )
    )

    assert report["requested"] == 4
    assert report["ready"] == 4
    assert report["missing"] == 0
    assert len(calls) == 4
    with closing(sqlite3.connect(shared_db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM market_technical_artifacts").fetchone()[0] == 4
    with closing(sqlite3.connect(replay_db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sim_run_market_technical_artifacts").fetchone()[0] == 4

    preload_run_market_artifacts(
        RunMarketArtifactPreloadRequest(
            db_file=replay_db,
            shared_db_file=shared_db,
            run_id=11,
            run_type="live_quant_drill",
            market="CN",
            timeframe="30m",
            stock_items=[
                {"stock_code": "600000", "stock_name": "浦发银行"},
                {"stock_code": "000001", "stock_name": "平安银行"},
            ],
            checkpoints=checkpoints,
            snapshot_loader=load_snapshot,
            trace_id="test-preload",
        )
    )

    assert len(calls) == 4


def test_preload_writes_run_missing_without_polluting_shared_store(tmp_path):
    shared_db = tmp_path / "quant_sim.db"
    replay_db = tmp_path / "quant_sim_replay.db"

    report = preload_run_market_artifacts(
        RunMarketArtifactPreloadRequest(
            db_file=replay_db,
            shared_db_file=shared_db,
            run_id=12,
            run_type="historical_replay",
            market="CN",
            timeframe="30m",
            stock_items=[{"stock_code": "600000", "stock_name": "浦发银行"}],
            checkpoints=[datetime(2026, 1, 5, 10, 0)],
            snapshot_loader=lambda item: None,
            trace_id="test-missing",
        )
    )

    assert report["requested"] == 1
    assert report["missing"] == 1
    with closing(sqlite3.connect(replay_db)) as conn:
        row = conn.execute(
            "SELECT source_status, reason_code FROM sim_run_market_technical_artifacts"
        ).fetchone()
        assert row == ("missing", "missing_artifact")
    with closing(sqlite3.connect(shared_db)) as conn:
        exists = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='market_technical_artifacts'"
        ).fetchone()[0]
        if exists:
            assert conn.execute("SELECT COUNT(*) FROM market_technical_artifacts").fetchone()[0] == 0


def test_run_scope_probe_missing_can_suppress_warning(tmp_path, caplog):
    db_file = tmp_path / "quant_sim_replay.db"
    ref = MarketTechnicalArtifactRef(
        domain="drill",
        run_id="88",
        run_type="live_quant_drill",
        stock_code="600000",
        market="CN",
        checkpoint_at="2026-01-05 10:00:00",
        timeframe="30m",
    ).to_ref()

    caplog.set_level(logging.WARNING, logger="app.quant_sim.market_technical_artifact_store")
    result = MarketTechnicalArtifactStore(db_file).get_by_ref(ref, log_missing=False)

    assert result.artifact is None
    assert result.reason_code == "missing_artifact"
    assert "market_technical_artifact_missing" not in caplog.text
