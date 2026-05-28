from __future__ import annotations

from datetime import datetime

from app.quant_kernel.models import Decision
from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.engine import QuantSimEngine
from app.quant_sim.portfolio_service import PortfolioService
from app.quant_sim.replay_artifact_adapter import RunArtifactContext, read_run_artifact
from app.quant_sim.replay_service import QuantSimReplayService
from app.quant_sim.signal_center_service import SignalCenterService
from app.stock_refresh_artifact_writer import build_market_technical_data_from_entry


class _MissingSnapshotProvider:
    def get_snapshot(self, *args, **kwargs):
        return None


class _FailingAdapter:
    def analyze_candidate(self, *args, **kwargs):
        raise AssertionError("adapter should not run when checkpoint snapshot is missing")

    def analyze_position(self, *args, **kwargs):
        raise AssertionError("adapter should not run when position artifact is not ready")


def test_run_checkpoint_records_missing_artifact_when_snapshot_is_absent(tmp_path):
    live_db = tmp_path / "quant_sim.db"
    replay_db = tmp_path / "quant_sim_replay.db"
    temp_db = tmp_path / "temp_quant.db"
    CandidatePoolService(temp_db).add_candidate(
        stock_code="600000",
        stock_name="浦发银行",
        source="fixture",
        latest_price=10.0,
        status="active",
    )
    service = QuantSimReplayService(
        db_file=live_db,
        replay_db_file=replay_db,
        snapshot_provider=_MissingSnapshotProvider(),
        adapter=_FailingAdapter(),
    )

    summary = service._run_checkpoint(  # noqa: SLF001 - validates missing artifact audit behavior
        run_id=1,
        checkpoint=datetime(2026, 1, 5, 10, 0),
        timeframe="30m",
        market="CN",
        engine=QuantSimEngine(db_file=temp_db, adapter=_FailingAdapter()),
        portfolio=PortfolioService(db_file=temp_db),
        signal_service=SignalCenterService(db_file=temp_db),
    )
    artifact = read_run_artifact(
        RunArtifactContext(
            db_file=replay_db,
            run_id=1,
            run_type="historical_replay",
            market="CN",
            timeframe="30m",
        ),
        stock_code="600000",
        checkpoint="2026-01-05 10:00:00",
    )

    assert summary["candidates_scanned"] == 1
    assert summary["signals_created"] == 0
    assert artifact["source_status"] == "missing"
    assert artifact["reason_code"] == "missing_artifact"
    assert "latest_price" in artifact["technical_snapshot_missing_fields"]
    assert "ma20" in artifact["technical_snapshot_missing_fields"]
    assert "rsi" in artifact["technical_snapshot_missing_fields"]
    assert "macd" in artifact["technical_snapshot_missing_fields"]
    assert "volume_ratio" in artifact["technical_snapshot_missing_fields"]


def test_artifact_writer_accepts_historical_rsi12_field():
    data = build_market_technical_data_from_entry(
        {
            "latest_price": 10.0,
            "ma20": 9.8,
            "rsi12": 56.0,
            "macd": 0.12,
            "volume_ratio": 1.4,
            "technical_snapshot_ready": True,
            "technical_snapshot_status": "ready",
        },
        computed_at="2026-01-05T02:00:05Z",
    )

    assert data.rsi == 56.0
    assert data.source_status == "ready"
    assert data.reason_code == "ok"
    assert "rsi" not in data.missing_fields


def test_artifact_writer_lists_optional_missing_fields_without_blocking_ready():
    data = build_market_technical_data_from_entry(
        {
            "latest_price": 10.0,
            "ma20": 9.8,
            "rsi": 56.0,
            "macd": 0.12,
            "volume_ratio": 1.4,
            "technical_snapshot_provider": "fixture",
            "technical_snapshot_indicator_version": "v1",
            "technical_snapshot_ready": True,
            "technical_snapshot_status": "ready",
        },
        computed_at="2026-01-05T02:00:05Z",
    )

    assert data.source_status == "ready"
    assert data.reason_code == "ok"
    assert "open" in data.missing_fields
    assert "macd_signal" in data.missing_fields
    assert "liquidity_ready" in data.missing_fields
    assert "latest_price" not in data.missing_fields
    assert "rsi" not in data.missing_fields


def test_position_decision_blocks_when_artifact_is_not_ready(tmp_path):
    engine = QuantSimEngine(db_file=tmp_path / "quant_sim.db", adapter=_FailingAdapter())

    decision = engine._evaluate_position_decision(  # noqa: SLF001 - verifies position artifact decision gate
        {"stock_code": "600000", "latest_price": 10.0},
        {"stock_code": "600000", "latest_price": 10.0},
        market_snapshot={
            "artifact_ref": "mta:v1|domain=live|market=CN|stock_code=600000|checkpoint_at=2026-01-05T02%3A00%3A00Z|timeframe=30m|data_version=mta_v1",
            "source_status": "partial",
            "reason_code": "incomplete_artifact",
            "technical_snapshot_missing_fields": ["ma20"],
        },
        current_time=datetime(2026, 1, 5, 10, 0),
    )

    assert decision["action"] == "HOLD"
    assert decision["decision_type"] == "missing_artifact_hold"
    assert decision["strategy_profile"]["market_snapshot"]["reason_code"] == "incomplete_artifact"


def test_position_decision_without_artifact_reference_blocks_adapter(tmp_path):
    engine = QuantSimEngine(db_file=tmp_path / "quant_sim.db", adapter=_FailingAdapter())

    decision = engine._evaluate_position_decision(  # noqa: SLF001 - verifies live position artifact requirement
        {"stock_code": "600000", "latest_price": 10.0},
        {"stock_code": "600000", "latest_price": 10.0},
        current_time=datetime(2026, 1, 5, 10, 0),
    )

    assert decision["action"] == "HOLD"
    assert decision["decision_type"] == "missing_artifact_hold"
    assert decision["strategy_profile"]["market_snapshot"]["reason_code"] == "missing_artifact_reference"


def test_run_checkpoint_missing_position_snapshot_creates_hold_diagnostic(tmp_path):
    live_db = tmp_path / "quant_sim.db"
    replay_db = tmp_path / "quant_sim_replay.db"
    CandidatePoolService(live_db).add_candidate(
        stock_code="600000",
        stock_name="浦发银行",
        source="fixture",
        latest_price=10.0,
        status="active",
    )
    signal_service = SignalCenterService(db_file=live_db)
    portfolio = PortfolioService(db_file=live_db)
    seed_signal = signal_service.create_signal(
        {"stock_code": "600000", "stock_name": "浦发银行"},
        Decision(
            code="600000",
            action="BUY",
            confidence=0.9,
            price=10.0,
            timestamp=datetime(2026, 1, 5, 9, 30),
            reason="seed position",
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
        int(seed_signal["id"]),
        price=10.0,
        quantity=100,
        note="seed position",
        executed_at=datetime(2026, 1, 5, 9, 30),
    )
    service = QuantSimReplayService(
        db_file=live_db,
        replay_db_file=replay_db,
        snapshot_provider=_MissingSnapshotProvider(),
        adapter=_FailingAdapter(),
    )

    summary = service._run_checkpoint(  # noqa: SLF001 - validates missing position artifact HOLD diagnostic
        run_id=2,
        checkpoint=datetime(2026, 1, 5, 10, 0),
        timeframe="30m",
        market="CN",
        engine=QuantSimEngine(db_file=live_db, adapter=_FailingAdapter()),
        portfolio=portfolio,
        signal_service=signal_service,
    )
    artifact = read_run_artifact(
        RunArtifactContext(db_file=replay_db, run_id=2, run_type="historical_replay", market="CN", timeframe="30m"),
        stock_code="600000",
        checkpoint="2026-01-05 10:00:00",
    )

    assert summary["positions_checked"] == 1
    assert summary["signals_created"] == 1
    assert summary["signals"][0]["action"] == "HOLD"
    assert summary["signals"][0]["decision_type"] == "missing_artifact_hold"
    assert artifact["source_status"] == "missing"
    assert artifact["reason_code"] == "missing_artifact"
