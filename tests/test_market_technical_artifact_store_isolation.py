from __future__ import annotations

import sqlite3
from pathlib import Path

from app.quant_sim.market_technical_artifact import (
    ArtifactWriteRequest,
    MarketTechnicalArtifactData,
    MarketTechnicalArtifactRef,
)
from app.quant_sim.market_technical_artifact_store import (
    LIVE_TABLE,
    RUN_TABLE,
    MarketTechnicalArtifactStore,
)


def _data() -> MarketTechnicalArtifactData:
    return MarketTechnicalArtifactData(
        latest_price=10.5,
        close=10.5,
        ma20=10.0,
        rsi=55.0,
        macd=0.1,
        volume_ratio=1.2,
        source_status="ready",
        reason_code="ok",
        computed_at="2026-01-05T02:00:05Z",
    )


def _table_exists(db_file: Path, table: str) -> bool:
    with sqlite3.connect(db_file) as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
    return row is not None


def test_live_upsert_creates_only_live_artifact_table(tmp_path: Path) -> None:
    db_file = tmp_path / "quant_sim.db"
    ref = MarketTechnicalArtifactRef.live(
        stock_code="600000",
        market="CN",
        checkpoint_at="2026-01-05T02:00:00Z",
        timeframe="30m",
    )

    MarketTechnicalArtifactStore(db_file).upsert(ArtifactWriteRequest(ref=ref, data=_data()))

    assert _table_exists(db_file, LIVE_TABLE) is True
    assert _table_exists(db_file, RUN_TABLE) is False


def test_replay_upsert_creates_only_run_artifact_table(tmp_path: Path) -> None:
    db_file = tmp_path / "quant_sim_replay.db"
    ref = MarketTechnicalArtifactRef(
        domain="replay",
        run_id="7",
        run_type="historical_replay",
        stock_code="600000",
        market="CN",
        checkpoint_at="2026-01-05T02:00:00Z",
        timeframe="30m",
    )

    MarketTechnicalArtifactStore(db_file).upsert(ArtifactWriteRequest(ref=ref, data=_data()))

    assert _table_exists(db_file, RUN_TABLE) is True
    assert _table_exists(db_file, LIVE_TABLE) is False


def test_missing_read_does_not_create_artifact_tables(tmp_path: Path) -> None:
    db_file = tmp_path / "quant_sim.db"
    ref = MarketTechnicalArtifactRef.live(
        stock_code="600000",
        market="CN",
        checkpoint_at="2026-01-05T02:00:00Z",
        timeframe="30m",
    ).to_ref()

    result = MarketTechnicalArtifactStore(db_file).get_by_ref(ref)

    assert result.reason_code == "missing_artifact"
    assert _table_exists(db_file, LIVE_TABLE) is False
    assert _table_exists(db_file, RUN_TABLE) is False
