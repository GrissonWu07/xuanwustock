from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.gateway.artifact_diagnostics import (
    artifact_diagnostics_from_payload,
    artifact_diagnostics_from_signal_payload,
    build_signal_artifact_diagnostics,
    latest_candidate_artifact_diagnostics,
)
from app.gateway.signal_market import _build_signal_ai_monitor_payload
from app.gateway_api import UIApiContext, create_app
from app.gateway.quant_universe_entry import _candidate_event_payload
from app.quant_sim.candidate_entry_gate import evaluate_candidate_entry_gate
from app.quant_sim.drill_artifact_adapter import write_drill_artifact_from_snapshot
from app.quant_sim.lifecycle_artifact_adapter import artifact_gate_from_evidence, artifact_market_snapshot
from app.quant_sim.market_technical_artifact import (
    ArtifactQuery,
    ArtifactWriteRequest,
    MarketTechnicalArtifactData,
    MarketTechnicalArtifactRef,
    parse_artifact_ref,
)
from app.quant_sim.market_technical_artifact_store import MarketTechnicalArtifactStore
from app.quant_sim.engine import QuantSimEngine
from app.quant_sim.replay_service import QuantSimReplayService
from app.quant_sim.replay_artifact_adapter import (
    RunArtifactContext,
    read_run_artifact,
    write_missing_run_artifact,
    write_run_artifact_from_snapshot,
)
from app.quant_sim.technical_entry_score import calculate_technical_entry_score
from app.selector_result_store import save_latest_result
from app.stock_refresh_artifact_writer import StockRefreshArtifactRequest, write_live_artifacts
from app.stock_refresh_seed_entries import collect_local_seed_entries, merge_runtime_seed


def _sample_data(**overrides) -> MarketTechnicalArtifactData:
    values = {
        "open": 10.0,
        "high": 10.8,
        "low": 9.8,
        "close": 10.5,
        "latest_price": 10.5,
        "prev_close": 9.9,
        "volume": 1200000.0,
        "amount": 12600000.0,
        "turnover_rate": 1.25,
        "volume_ratio": 1.8,
        "ma5": 10.1,
        "ma10": 9.9,
        "ma20": 9.7,
        "ma60": 9.2,
        "ma20_slope": 0.03,
        "rsi": 58.5,
        "macd": 0.15,
        "macd_signal": 0.1,
        "macd_histogram": 0.05,
        "trend": "up",
        "price_vs_ma20": 0.0825,
        "price_vs_ma60": 0.1413,
        "ma_stack": "ma5>ma10>ma20",
        "above_ma20_checkpoints": 4,
        "retest_confirmed": True,
        "is_suspended": False,
        "is_limit_up": False,
        "is_limit_down": False,
        "liquidity_ready": True,
        "provider": "fixture",
        "indicator_version": "indicator_v1",
        "source_status": "ready",
        "reason_code": "ok",
        "missing_fields": [],
        "computed_at": "2026-01-05T02:00:05Z",
        "provider_diagnostics": {"latency_ms": 12},
    }
    values.update(overrides)
    return MarketTechnicalArtifactData(**values)


def _test_context(tmp_path):
    return UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=tmp_path / "selector_results",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        quant_sim_replay_db_file=tmp_path / "quant_sim_replay.db",
        monitor_db_file=tmp_path / "stock_monitor.db",
        smart_monitor_db_file=tmp_path / "smart_monitor.db",
    )


def _minimal_explainability() -> dict:
    return {
        "technical_breakdown": {
            "track": {"score": 0.2, "confidence": 0.7},
            "dimensions": [{"id": "trend", "group": "trend", "score": 0.2, "reason": "fixture"}],
        },
        "context_breakdown": {
            "track": {"score": 0.1, "confidence": 0.6},
            "dimensions": [{"id": "risk", "group": "risk", "score": 0.1, "reason": "fixture"}],
        },
        "fusion_breakdown": {
            "tech_score": 0.2,
            "context_score": 0.1,
            "fusion_score": 0.15,
            "fusion_confidence": 0.65,
            "buy_threshold_base": 0.35,
            "sell_threshold_base": -0.2,
            "final_action": "HOLD",
            "mode": "hybrid",
        },
        "dual_track": {"final_action": "HOLD", "final_reason": "fixture"},
    }


def test_artifact_ref_round_trips_with_url_safe_values():
    ref = MarketTechnicalArtifactRef(
        domain="replay",
        run_id="run 001",
        run_type="historical_replay",
        stock_code="600000",
        market="CN",
        checkpoint_at="2026-01-05T02:00:00Z",
        timeframe="30m",
        data_version="mta_v1",
    )

    serialized = ref.to_ref()
    parsed = parse_artifact_ref(serialized)

    assert "%20" in serialized
    assert parsed == ref


def test_invalid_artifact_ref_returns_invalid_reason():
    parsed = parse_artifact_ref("bad-ref")

    assert parsed.reason_code == "invalid_artifact_ref"


def test_live_artifact_upsert_and_query_by_ref(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    store = MarketTechnicalArtifactStore(db_file)
    store.ensure_schema()
    ref = MarketTechnicalArtifactRef.live(
        stock_code="600000",
        market="CN",
        checkpoint_at="2026-01-05T02:00:00Z",
        timeframe="30m",
        data_version="mta_v1",
    )

    written = store.upsert(ArtifactWriteRequest(ref=ref, data=_sample_data()))
    loaded = store.get_by_ref(written.artifact_ref)

    assert loaded.reason_code == "ok"
    assert loaded.artifact is not None
    assert loaded.artifact.ref == ref
    assert loaded.artifact.data.latest_price == 10.5
    assert loaded.artifact.data.ma20 == 9.7
    assert loaded.artifact.data.market_json["prev_close"] == 9.9
    assert loaded.artifact.data.indicator_json["ma60"] == 9.2
    assert loaded.artifact.data.structure_json["ma_stack"] == "ma5>ma10>ma20"
    assert loaded.artifact.data.quality_json["provider_diagnostics"]["latency_ms"] == 12


def test_live_query_rejects_run_scope(tmp_path):
    store = MarketTechnicalArtifactStore(tmp_path / "quant_sim.db")
    query = ArtifactQuery(
        domain="live",
        stock_code="600000",
        market="CN",
        checkpoint_at="2026-01-05T02:00:00Z",
        timeframe="30m",
        data_version="mta_v1",
        run_id="run-001",
        run_type="historical_replay",
    )

    loaded = store.get_by_query(query)

    assert loaded.reason_code == "run_scope_required"
    assert loaded.artifact is None


def test_run_query_requires_run_scope(tmp_path):
    store = MarketTechnicalArtifactStore(tmp_path / "replay.db")
    query = ArtifactQuery(
        domain="replay",
        stock_code="300736",
        market="CN",
        checkpoint_at="2026-05-08T02:00:00Z",
        timeframe="30m",
        data_version="mta_v1",
    )

    loaded = store.get_by_query(query)

    assert loaded.reason_code == "run_scope_required"
    assert loaded.artifact is None


def test_run_scoped_artifact_does_not_conflict_with_live_identity(tmp_path):
    db_file = tmp_path / "artifacts.db"
    store = MarketTechnicalArtifactStore(db_file)
    live_ref = MarketTechnicalArtifactRef.live(
        stock_code="300736",
        market="CN",
        checkpoint_at="2026-05-08T02:00:00Z",
        timeframe="30m",
        data_version="mta_v1",
    )
    replay_ref = MarketTechnicalArtifactRef(
        domain="replay",
        run_id="run-001",
        run_type="historical_replay",
        stock_code="300736",
        market="CN",
        checkpoint_at="2026-05-08T02:00:00Z",
        timeframe="30m",
        data_version="mta_v1",
    )

    store.upsert(ArtifactWriteRequest(ref=live_ref, data=_sample_data(latest_price=21.0, close=21.0)))
    store.upsert(ArtifactWriteRequest(ref=replay_ref, data=_sample_data(latest_price=18.0, close=18.0)))

    live = store.get_by_ref(live_ref.to_ref())
    replay = store.get_by_ref(replay_ref.to_ref())

    assert live.artifact is not None
    assert replay.artifact is not None
    assert live.artifact.data.latest_price == 21.0
    assert replay.artifact.data.latest_price == 18.0


def test_duplicate_upsert_updates_same_artifact(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    store = MarketTechnicalArtifactStore(db_file)
    ref = MarketTechnicalArtifactRef.live(
        stock_code="600000",
        market="CN",
        checkpoint_at="2026-01-05T02:00:00Z",
        timeframe="30m",
        data_version="mta_v1",
    )

    store.upsert(ArtifactWriteRequest(ref=ref, data=_sample_data(latest_price=10.5, close=10.5)))
    store.upsert(ArtifactWriteRequest(ref=ref, data=_sample_data(latest_price=11.2, close=11.2)))

    with closing(sqlite3.connect(db_file)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM market_technical_artifacts").fetchone()[0]
    loaded = store.get_by_ref(ref.to_ref())

    assert count == 1
    assert loaded.artifact is not None
    assert loaded.artifact.data.latest_price == 11.2


def test_artifact_upsert_defaults_computed_at_when_missing(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    store = MarketTechnicalArtifactStore(db_file)
    ref = MarketTechnicalArtifactRef.live(
        stock_code="600000",
        market="CN",
        checkpoint_at="2026-01-05T02:00:00Z",
        timeframe="30m",
        data_version="mta_v1",
    )

    store.upsert(ArtifactWriteRequest(ref=ref, data=_sample_data(computed_at=None)))

    loaded = store.get_by_ref(ref.to_ref())
    assert loaded.artifact is not None
    assert loaded.artifact.data.computed_at
    with closing(sqlite3.connect(db_file)) as conn:
        row = conn.execute(
            "SELECT computed_at, updated_at FROM market_technical_artifacts WHERE artifact_ref = ?",
            (ref.to_ref(),),
        ).fetchone()
    assert row[0]
    assert row[1]


def test_partial_artifact_sorts_missing_fields(tmp_path):
    store = MarketTechnicalArtifactStore(tmp_path / "quant_sim.db")
    ref = MarketTechnicalArtifactRef.live(
        stock_code="600000",
        market="CN",
        checkpoint_at="2026-01-05T02:00:00Z",
        timeframe="30m",
        data_version="mta_v1",
    )

    store.upsert(
        ArtifactWriteRequest(
            ref=ref,
            data=_sample_data(source_status="partial", reason_code="incomplete_artifact", missing_fields=["rsi", "ma20"]),
        )
    )

    loaded = store.get_by_ref(ref.to_ref())

    assert loaded.artifact is not None
    assert loaded.artifact.data.source_status == "partial"
    assert loaded.artifact.data.missing_fields == ["ma20", "rsi"]
    assert loaded.artifact.data.quality_json["missing_fields"] == ["ma20", "rsi"]


def test_source_score_fields_are_not_persisted(tmp_path):
    store = MarketTechnicalArtifactStore(tmp_path / "quant_sim.db")
    ref = MarketTechnicalArtifactRef.live(
        stock_code="600000",
        market="CN",
        checkpoint_at="2026-01-05T02:00:00Z",
        timeframe="30m",
        data_version="mta_v1",
    )
    data = _sample_data(
        market_json={"source_score": 0.9, "open": 10.0},
        indicator_json={"source_confidence": 0.8, "ma5": 10.1},
        quality_json={"multi_source_bonus": 1.0, "provider_diagnostics": {"ok": True}},
    )

    store.upsert(ArtifactWriteRequest(ref=ref, data=data))
    loaded = store.get_by_ref(ref.to_ref())

    assert loaded.artifact is not None
    payload = loaded.artifact.to_dict()
    assert "source_score" not in str(payload)
    assert "source_confidence" not in str(payload)
    assert "multi_source_bonus" not in str(payload)


def test_missing_artifact_returns_missing_reason(tmp_path):
    store = MarketTechnicalArtifactStore(tmp_path / "quant_sim.db")
    ref = MarketTechnicalArtifactRef.live(
        stock_code="600000",
        market="CN",
        checkpoint_at="2026-01-05T02:00:00Z",
        timeframe="30m",
        data_version="mta_v1",
    )

    loaded = store.get_by_ref(ref.to_ref())

    assert loaded.reason_code == "missing_artifact"
    assert loaded.artifact is None


def test_artifact_api_returns_live_artifact_by_ref_and_identity(tmp_path):
    context = _test_context(tmp_path)
    ref = MarketTechnicalArtifactRef.live(
        stock_code="600000",
        market="CN",
        checkpoint_at="2026-01-05T02:00:00Z",
        timeframe="30m",
    )
    written = MarketTechnicalArtifactStore(context.quant_sim_db_file).upsert(
        ArtifactWriteRequest(ref=ref, data=_sample_data(latest_price=11.1, ma20=10.2))
    )

    with TestClient(create_app(context=context)) as client:
        by_ref = client.get(
            f"/api/v1/quant/market-technical-artifacts/{quote(written.artifact_ref, safe='')}"
        )
        by_identity = client.get(
            "/api/v1/quant/market-technical-artifacts",
            params={
                "domain": "live",
                "stock_code": "600000",
                "market": "CN",
                "checkpoint_at": "2026-01-05T02:00:00Z",
                "timeframe": "30m",
            },
        )

    assert by_ref.status_code == 200
    assert by_ref.json()["artifact_ref"] == written.artifact_ref
    assert by_ref.json()["latest_price"] == 11.1
    assert by_identity.status_code == 200
    assert by_identity.json()["ma20"] == 10.2


def test_artifact_api_reports_scope_and_missing_errors(tmp_path):
    context = _test_context(tmp_path)
    replay_ref = MarketTechnicalArtifactRef(
        domain="replay",
        run_id="42",
        run_type="historical_replay",
        stock_code="300736",
        market="CN",
        checkpoint_at="2026-05-08T02:00:00Z",
        timeframe="30m",
    )
    MarketTechnicalArtifactStore(context.quant_sim_replay_db_file).upsert(
        ArtifactWriteRequest(ref=replay_ref, data=_sample_data(latest_price=22.0))
    )

    with TestClient(create_app(context=context)) as client:
        invalid_live_scope = client.get(
            "/api/v1/quant/market-technical-artifacts",
            params={
                "domain": "live",
                "stock_code": "600000",
                "market": "CN",
                "checkpoint_at": "2026-01-05T02:00:00Z",
                "timeframe": "30m",
                "run_id": "42",
                "run_type": "historical_replay",
            },
        )
        missing_run_scope = client.get(
            "/api/v1/quant/market-technical-artifacts",
            params={
                "domain": "replay",
                "stock_code": "300736",
                "market": "CN",
                "checkpoint_at": "2026-05-08T02:00:00Z",
                "timeframe": "30m",
            },
        )
        replay_hit = client.get(
            "/api/v1/quant/market-technical-artifacts",
            params={
                "domain": "replay",
                "run_id": "42",
                "run_type": "historical_replay",
                "stock_code": "300736",
                "market": "CN",
                "checkpoint_at": "2026-05-08T02:00:00Z",
                "timeframe": "30m",
            },
        )
        missing = client.get(
            "/api/v1/quant/market-technical-artifacts",
            params={
                "domain": "live",
                "stock_code": "600001",
                "market": "CN",
                "checkpoint_at": "2026-01-05T02:00:00Z",
                "timeframe": "30m",
            },
        )
        invalid_ref = client.get("/api/v1/quant/market-technical-artifacts/not-a-ref")

    assert invalid_live_scope.status_code == 400
    assert invalid_live_scope.json()["reason_code"] == "run_scope_required"
    assert missing_run_scope.status_code == 400
    assert missing_run_scope.json()["reason_code"] == "run_scope_required"
    assert replay_hit.status_code == 200
    assert replay_hit.json()["latest_price"] == 22.0
    assert missing.status_code == 404
    assert missing.json()["reason_code"] == "missing_artifact"
    assert invalid_ref.status_code == 400
    assert invalid_ref.json()["reason_code"] == "invalid_artifact_ref"


def test_signal_detail_surfaces_artifact_diagnostics(tmp_path):
    context = _test_context(tmp_path)
    written = MarketTechnicalArtifactStore(context.quant_sim_db_file).upsert(
        ArtifactWriteRequest(
            ref=MarketTechnicalArtifactRef.live(
                stock_code="600000",
                market="CN",
                checkpoint_at="2026-01-05T02:00:00Z",
                timeframe="30m",
            ),
            data=_sample_data(source_status="partial", reason_code="incomplete_artifact", missing_fields=["rsi"]),
        )
    )
    signal_id = context.quant_db().add_signal(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "action": "HOLD",
            "confidence": 65,
            "reasoning": "fixture",
            "status": "observed",
            "position_size_pct": 0.0,
            "decision_type": "dual_track_weighted_hold",
            "tech_score": 0.2,
            "context_score": 0.1,
            "strategy_profile": {
                "analysis_timeframe": "30m",
                "strategy_mode": "auto",
                "market_snapshot": {
                    "artifact_ref": written.artifact_ref,
                    "source_status": "partial",
                    "reason_code": "incomplete_artifact",
                    "technical_snapshot_missing_fields": ["rsi"],
                },
                "explainability": _minimal_explainability(),
            },
        }
    )

    with TestClient(create_app(context=context)) as client:
        response = client.get(f"/api/v1/quant/signals/{signal_id}", params={"source": "live"})

    assert response.status_code == 200
    detail = response.json()
    assert detail["artifactDiagnostics"]["artifact_ref"] == written.artifact_ref
    assert detail["artifactDiagnostics"]["source_status"] == "partial"
    assert detail["artifactDiagnostics"]["reason_code"] == "incomplete_artifact"
    assert detail["artifactDiagnostics"]["missing_fields"] == ["rsi"]
    assert detail["decision"]["artifactRef"] == written.artifact_ref


def test_signal_ai_monitor_refresh_uses_artifact_projection(tmp_path):
    context = _test_context(tmp_path)
    written = MarketTechnicalArtifactStore(context.quant_sim_db_file).upsert(
        ArtifactWriteRequest(
            ref=MarketTechnicalArtifactRef.live(
                stock_code="600000",
                market="CN",
                checkpoint_at="2026-01-05T02:00:00Z",
                timeframe="30m",
            ),
            data=_sample_data(latest_price=23.45, close=23.45, ma20=22.2, rsi=55.5),
        )
    )

    payload = _build_signal_ai_monitor_payload(
        context=context,
        signal={"stock_code": "600000"},
        strategy_profile={
            "market_snapshot": {
                "artifact_ref": written.artifact_ref,
                "source_status": "ready",
                "reason_code": "ok",
            }
        },
        checkpoint_at="2026-01-05 10:00:00",
        fetch_realtime_snapshot=True,
    )

    market_rows = {row["label"]: row["value"] for row in payload["marketData"]}
    assert payload["message"] == "无 AI 盯盘记录，已使用行情技术 artifact 补全技术指标。"
    assert market_rows["当前价"] == "23.45"
    assert market_rows["MA20"] == "22.20"
    assert market_rows["RSI12"] == "55.50"


def test_artifact_diagnostics_cover_invalid_missing_and_candidate_payloads(tmp_path):
    context = _test_context(tmp_path)
    missing = build_signal_artifact_diagnostics(
        context,
        signal={},
        source="live",
        strategy_profile={},
    )
    invalid = build_signal_artifact_diagnostics(
        context,
        signal={},
        source="live",
        strategy_profile={"market_snapshot": {"artifact_ref": "not-a-ref"}},
    )
    absent_store = build_signal_artifact_diagnostics(
        context,
        signal={},
        source="live",
        strategy_profile={
            "market_snapshot": {
                "artifact_ref": MarketTechnicalArtifactRef.live(
                    stock_code="600002",
                    market="CN",
                    checkpoint_at="2026-01-05T02:00:00Z",
                    timeframe="30m",
                ).to_ref()
            }
        },
    )
    direct_signal = artifact_diagnostics_from_signal_payload(
        {"artifact_ref": "abc", "source_status": "ready", "reason_code": "ok"}
    )
    payload = artifact_diagnostics_from_payload(
        {"artifact_ref": "abc", "technical_snapshot_missing_fields": "ma20,rsi"}
    )

    class NoCandidateEvents:
        pass

    class EmptyCandidateEvents:
        def list_candidate_events(self, stock_code, limit):
            return []

    class PayloadCandidateEvents:
        def list_candidate_events(self, stock_code, limit):
            return [{"payload_json": {"artifact_ref": "abc", "source_status": "stale"}}]

    assert missing["reason_code"] == "missing_artifact_reference"
    assert invalid["reason_code"] == "invalid_artifact_ref"
    assert absent_store["reason_code"] == "missing_artifact"
    assert direct_signal["available"] is True
    assert payload["missing_fields"] == ["ma20", "rsi"]
    assert latest_candidate_artifact_diagnostics(NoCandidateEvents(), "600000")["reason_code"] == "missing_artifact_reference"
    assert latest_candidate_artifact_diagnostics(EmptyCandidateEvents(), "600000")["reason_code"] == "missing_artifact_reference"
    assert latest_candidate_artifact_diagnostics(PayloadCandidateEvents(), "600000")["source_status"] == "stale"


def test_live_refresh_writer_persists_artifact_and_projection(tmp_path):
    entry = {
        "stock_code": "600000",
        "latest_price": 10.5,
        "price": 10.4,
        "price_as_of": "2026-01-05 10:00:00",
        "data_source": "runtime_cache",
        "technical_snapshot_ready": True,
        "technical_snapshot_status": "ready",
        "technical_snapshot_timeframe": "30m",
        "technical_snapshot_provider": "tdx",
        "technical_snapshot_at": "2026-01-05 10:00:00",
        "technical_snapshot_indicator_version": "indicator_v1",
        "ma5": 10.1,
        "ma10": 9.9,
        "ma20": 9.7,
        "ma60": 9.2,
        "ma20_slope": 0.03,
        "amount": 12600000,
        "volume_ratio": 1.8,
        "rsi": 58.5,
        "macd": 0.15,
        "trend": "up",
    }

    projections = write_live_artifacts(
        StockRefreshArtifactRequest(db_file=tmp_path / "quant_sim.db", entries={"600000": entry})
    )
    projection = projections["600000"]
    store = MarketTechnicalArtifactStore(tmp_path / "quant_sim.db")
    loaded = store.get_by_ref(projection["artifact_ref"])

    assert loaded.reason_code == "ok"
    assert loaded.artifact is not None
    assert loaded.artifact.ref.checkpoint_at == "2026-01-05 10:00:00"
    assert projection["latest_price"] == 10.5
    assert projection["price"] == 10.5
    assert projection["data_source"] == "tdx"
    assert projection["source_status"] == "ready"
    assert projection["reason_code"] == "ok"
    assert projection["technical_snapshot_status"] == "ready"
    assert projection["ma20"] == 9.7


def test_live_refresh_writer_records_partial_missing_fields(tmp_path):
    entry = {
        "stock_code": "600000",
        "latest_price": 10.5,
        "technical_snapshot_ready": False,
        "technical_snapshot_status": "incomplete",
        "technical_snapshot_missing_fields": ["rsi", "ma20"],
        "technical_snapshot_timeframe": "30m",
        "technical_snapshot_provider": "tdx",
        "technical_snapshot_at": "2026-01-05 10:00:00",
        "technical_snapshot_indicator_version": "indicator_v1",
    }

    projections = write_live_artifacts(
        StockRefreshArtifactRequest(db_file=tmp_path / "quant_sim.db", entries={"600000": entry})
    )
    loaded = MarketTechnicalArtifactStore(tmp_path / "quant_sim.db").get_by_ref(
        projections["600000"]["artifact_ref"]
    )

    assert loaded.artifact is not None
    assert loaded.artifact.data.source_status == "partial"
    assert loaded.artifact.data.reason_code == "incomplete_artifact"
    assert set(loaded.artifact.data.missing_fields) >= {"ma20", "rsi", "macd", "volume_ratio"}
    assert projections["600000"]["technical_snapshot_status"] == "incomplete"


def test_live_refresh_writer_records_source_failure(tmp_path):
    entry = {
        "stock_code": "600000",
        "latest_price": 10.5,
        "technical_snapshot_ready": False,
        "technical_snapshot_status": "failed",
        "technical_snapshot_missing_fields": ["ma20"],
        "technical_snapshot_error": "remote timeout",
        "technical_snapshot_timeframe": "30m",
        "technical_snapshot_provider": "tdx",
        "technical_snapshot_at": "2026-01-05 10:00:00",
    }

    projections = write_live_artifacts(
        StockRefreshArtifactRequest(db_file=tmp_path / "quant_sim.db", entries={"600000": entry})
    )
    loaded = MarketTechnicalArtifactStore(tmp_path / "quant_sim.db").get_by_ref(
        projections["600000"]["artifact_ref"]
    )

    assert loaded.artifact is not None
    assert loaded.artifact.data.source_status == "source_failed"
    assert loaded.artifact.data.reason_code == "source_failed"
    assert loaded.artifact.data.quality_json["provider_diagnostics"]["technical_snapshot_error"] == "provider_error"


def test_live_refresh_writer_handles_stale_and_ignores_invalid_entries(tmp_path):
    entries = {
        "": {"latest_price": 1.0},
        "000001": {
            "stock_code": "000001",
            "latest_price": "nan",
            "price": "12.30",
            "technical_snapshot_ready": False,
            "technical_snapshot_status": "stale_unprepared",
            "technical_snapshot_timeframe": "30m",
            "technical_snapshot_provider": "tdx",
            "technical_snapshot_at": "2026-01-05 10:00:00",
            "above_ma20_checkpoints": "3",
            "retest_confirmed": "yes",
            "is_suspended": "no",
            "is_limit_up": "0",
            "is_limit_down": "false",
            "liquidity_ready": "true",
        },
    }

    projections = write_live_artifacts(
        StockRefreshArtifactRequest(db_file=tmp_path / "quant_sim.db", entries=entries)
    )
    loaded = MarketTechnicalArtifactStore(tmp_path / "quant_sim.db").get_by_ref(
        projections["000001"]["artifact_ref"]
    )

    assert "" not in projections
    assert loaded.artifact is not None
    assert loaded.artifact.data.latest_price == 12.3
    assert loaded.artifact.data.source_status == "stale"
    assert loaded.artifact.data.reason_code == "stale_artifact"
    assert loaded.artifact.data.above_ma20_checkpoints == 3
    assert loaded.artifact.data.retest_confirmed is True
    assert loaded.artifact.data.is_suspended is False
    assert loaded.artifact.data.liquidity_ready is True
    assert projections["000001"]["technical_snapshot_status"] == "stale"


def test_seed_entries_collect_discovery_and_selector_payloads(tmp_path):
    save_latest_result(
        "main_force",
        {
            "result": {
                "final_recommendations": [
                    {
                        "stock_data": {"股票代码": "1", "股票名称": "平安银行"},
                        "industry": "银行",
                        "总市值(亿)": "1,234.5",
                        "市盈率TTM": "6.5",
                    }
                ]
            }
        },
        base_dir=tmp_path,
    )
    save_latest_result(
        "discovery_candidate_artifact",
        {
            "rows": [
                {
                    "code": "600001",
                    "name": "邯郸钢铁",
                    "sector": "钢铁",
                    "latestPrice": "7.25",
                    "pbRatio": "1.1",
                }
            ]
        },
        base_dir=tmp_path,
    )

    seeds = collect_local_seed_entries(SimpleNamespace(selector_result_dir=tmp_path))

    assert seeds["000001"]["stock_name"] == "平安银行"
    assert seeds["000001"]["sector"] == "银行"
    assert seeds["000001"]["market_cap"] == 1234.5
    assert seeds["000001"]["pe_ratio"] == 6.5
    assert seeds["600001"]["stock_name"] == "邯郸钢铁"
    assert seeds["600001"]["latest_price"] == 7.25


def test_merge_runtime_seed_preserves_existing_values_and_fills_missing():
    merged = merge_runtime_seed(
        {"stock_code": "600001", "stock_name": "已有名称", "latest_price": 8.0},
        {"stock_name": "新名称", "sector": "金融", "latest_price": 9.0, "pb_ratio": "bad", "pe_ratio": 12.0},
        "600001",
    )

    assert merged["stock_name"] == "已有名称"
    assert merged["latest_price"] == 8.0
    assert merged["sector"] == "金融"
    assert merged["pe_ratio"] == 12.0
    assert "pb_ratio" not in merged


def test_artifact_adapter_reports_missing_store_and_source_status():
    snapshot = artifact_market_snapshot({"artifact_ref": "mta:v1/domain=live"}, db_file="")
    failed_gate = artifact_gate_from_evidence(
        {"artifact_ref": "abc", "source_status": "source_failed", "technical_snapshot_missing_fields": ["ma20"]}
    )
    stale_gate = artifact_gate_from_evidence({"artifact_ref": "abc", "source_status": "stale"})

    assert snapshot["reason_code"] == "missing_artifact"
    assert failed_gate["reason_code"] == "source_failed"
    assert failed_gate["missing_fields"] == ["ma20"]
    assert stale_gate["reason_code"] == "stale_artifact"


def test_candidate_entry_common_gate_blocks_after_artifact_gate_passes():
    base = {
        "artifact_ref": "abc",
        "source_status": "ready",
        "reason_code": "ok",
        "price": 10.0,
        "ma5": 10.2,
        "ma10": 10.1,
        "ma20": 11.0,
        "ma20_slope": -0.1,
        "ma60": 9.8,
        "amount": 100_000_000,
        "volume_ratio": 1.0,
        "rsi": 55,
        "macd": 0.1,
        "trend": "down",
        "technical_snapshot_status": "ready",
        "technical_snapshot_at": "2026-01-05T02:00:00Z",
        "technical_snapshot_timeframe": "30m",
        "technical_snapshot_provider": "fixture",
        "technical_snapshot_indicator_version": "v1",
    }

    downtrend = evaluate_candidate_entry_gate({"source_type": "discover", "payload_json": base}, profile_id="aggressive")
    illiquid = evaluate_candidate_entry_gate(
        {"source_type": "discover", "payload_json": {**base, "price": 12.0, "amount": 1.0}},
        profile_id="aggressive",
    )
    incomplete = evaluate_candidate_entry_gate(
        {"source_type": "discover", "payload_json": {**base, "price": 12.0, "ma5": None}},
        profile_id="aggressive",
    )

    assert downtrend["reason_code"] == "persistent_downtrend"
    assert illiquid["reason_code"] == "liquidity_weak"
    assert incomplete["reason_code"] == "missing_technical_snapshot"


def test_replay_and_drill_artifacts_are_run_scoped_and_isolated_from_live(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    live_store = MarketTechnicalArtifactStore(db_file)
    live_store.upsert(
        ArtifactWriteRequest(
            ref=MarketTechnicalArtifactRef.live(
                stock_code="600000",
                market="CN",
                checkpoint_at="2026-01-05T02:00:00Z",
                timeframe="30m",
            ),
            data=_sample_data(latest_price=99.0, ma20=98.0),
        )
    )
    replay_context = RunArtifactContext(
        db_file=db_file,
        run_id=7,
        run_type="historical_replay",
        market="CN",
        timeframe="30m",
    )
    drill_context = RunArtifactContext(
        db_file=db_file,
        run_id=8,
        run_type="live_quant_drill",
        market="CN",
        timeframe="30m",
    )

    replay_written = write_run_artifact_from_snapshot(
        replay_context,
        stock_code="600000",
        checkpoint="2026-01-05 10:00:00",
        snapshot={"current_price": 12.0, "ma20": 11.5, "ma5": 12.1, "ma10": 11.8, "ma60": 10.5, "amount": 80_000_000, "volume_ratio": 1.2, "rsi": 58, "macd": 0.1, "trend": "up"},
    )
    drill_written = write_run_artifact_from_snapshot(
        drill_context,
        stock_code="600000",
        checkpoint="2026-01-05 10:00:00",
        snapshot={"current_price": 13.0, "ma20": 12.5, "ma5": 13.1, "ma10": 12.8, "ma60": 10.5, "amount": 80_000_000, "volume_ratio": 1.2, "rsi": 58, "macd": 0.1, "trend": "up"},
    )

    replay_read = read_run_artifact(replay_context, stock_code="600000", checkpoint="2026-01-05 10:00:00")
    drill_read = read_run_artifact(drill_context, stock_code="600000", checkpoint="2026-01-05 10:00:00")

    assert "domain=replay" in replay_written["artifact_ref"]
    assert "domain=drill" in drill_written["artifact_ref"]
    assert replay_read["latest_price"] == 12.0
    assert drill_read["latest_price"] == 13.0
    assert replay_read["latest_price"] != 99.0


def test_run_artifact_reuses_shared_checkpoint_artifact_when_available(tmp_path):
    shared_db = tmp_path / "quant_sim.db"
    replay_db = tmp_path / "replay.db"
    MarketTechnicalArtifactStore(shared_db).upsert(
        ArtifactWriteRequest(
            ref=MarketTechnicalArtifactRef.live(
                stock_code="600000",
                market="CN",
                checkpoint_at="2026-01-05 10:00:00",
                timeframe="30m",
            ),
            data=_sample_data(latest_price=99.0, close=99.0, ma20=98.0),
        )
    )
    context = RunArtifactContext(
        db_file=replay_db,
        shared_db_file=shared_db,
        run_id=17,
        run_type="live_quant_drill",
        market="CN",
        timeframe="30m",
    )

    written = write_run_artifact_from_snapshot(
        context,
        stock_code="600000",
        checkpoint="2026-01-05 10:00:00",
        snapshot={"current_price": 12.0, "close": 12.0, "ma20": 11.5, "amount": 80_000_000},
    )
    read = read_run_artifact(context, stock_code="600000", checkpoint="2026-01-05 10:00:00")

    assert written["source_status"] == "ready"
    assert read["latest_price"] == 99.0
    assert read["ma20"] == 98.0
    with closing(sqlite3.connect(shared_db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM market_technical_artifacts").fetchone()[0] == 1
    with closing(sqlite3.connect(replay_db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sim_run_market_technical_artifacts").fetchone()[0] == 1


def test_missing_run_artifact_copies_shared_checkpoint_artifact(tmp_path):
    shared_db = tmp_path / "quant_sim.db"
    replay_db = tmp_path / "replay.db"
    MarketTechnicalArtifactStore(shared_db).upsert(
        ArtifactWriteRequest(
            ref=MarketTechnicalArtifactRef.live(
                stock_code="600000",
                market="CN",
                checkpoint_at="2026-01-05 10:00:00",
                timeframe="30m",
            ),
            data=_sample_data(latest_price=88.0, close=88.0),
        )
    )
    context = RunArtifactContext(
        db_file=replay_db,
        shared_db_file=shared_db,
        run_id=18,
        run_type="historical_replay",
        market="CN",
        timeframe="30m",
    )

    written = write_missing_run_artifact(context, stock_code="600000", checkpoint="2026-01-05 10:00:00")
    read = read_run_artifact(context, stock_code="600000", checkpoint="2026-01-05 10:00:00")

    assert written["source_status"] == "ready"
    assert read["latest_price"] == 88.0
    assert read["reason_code"] == "ok"


def test_market_technical_artifact_store_upsert_many_writes_checkpoint_batch(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    store = MarketTechnicalArtifactStore(db_file)
    requests = [
        ArtifactWriteRequest(
            ref=MarketTechnicalArtifactRef.live(
                stock_code=f"60000{index}",
                market="CN",
                checkpoint_at="2026-01-05 10:00:00",
                timeframe="30m",
            ),
            data=_sample_data(latest_price=10.0 + index),
        )
        for index in range(3)
    ]

    written = store.upsert_many(requests)

    assert [item.data.latest_price for item in written] == [10.0, 11.0, 12.0]
    with closing(sqlite3.connect(db_file)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM market_technical_artifacts").fetchone()[0] == 3


def test_replay_service_reads_shared_artifact_before_snapshot_provider(tmp_path):
    class FailingSnapshotProvider:
        def get_snapshot(self, *args, **kwargs):
            del args, kwargs
            raise AssertionError("provider should not run when stable shared artifact exists")

    shared_db = tmp_path / "quant_sim.db"
    replay_db = tmp_path / "quant_sim_replay.db"
    MarketTechnicalArtifactStore(shared_db).upsert(
        ArtifactWriteRequest(
            ref=MarketTechnicalArtifactRef.live(
                stock_code="600000",
                market="CN",
                checkpoint_at="2026-01-05 10:00:00",
                timeframe="30m",
            ),
            data=_sample_data(latest_price=77.0, close=77.0, ma20=76.0),
        )
    )
    service = QuantSimReplayService(
        db_file=shared_db,
        replay_db_file=replay_db,
        snapshot_provider=FailingSnapshotProvider(),
    )

    artifacts = service._get_or_prepare_run_market_artifacts_batch(
        run_id=23,
        run_type="live_quant_drill",
        checkpoint=datetime(2026, 1, 5, 10, 0),
        timeframe="30m",
        market="CN",
        items=[{"stock_code": "600000", "stock_name": "浦发银行"}],
    )
    artifact = artifacts["600000"]

    assert artifact["latest_price"] == 77.0
    assert artifact["ma20"] == 76.0
    assert artifact["source_status"] == "ready"
    with closing(sqlite3.connect(replay_db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sim_run_market_technical_artifacts").fetchone()[0] == 1


def test_no_live_fallback_when_run_artifact_missing(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    MarketTechnicalArtifactStore(db_file).upsert(
        ArtifactWriteRequest(
            ref=MarketTechnicalArtifactRef.live(
                stock_code="600000",
                market="CN",
                checkpoint_at="2026-01-05T02:00:00Z",
                timeframe="30m",
            ),
            data=_sample_data(latest_price=99.0),
        )
    )
    replay_context = RunArtifactContext(
        db_file=db_file,
        run_id=9,
        run_type="historical_replay",
        market="CN",
        timeframe="30m",
    )

    missing = read_run_artifact(replay_context, stock_code="600000", checkpoint="2026-01-05 10:00:00")

    assert missing["source_status"] == "missing"
    assert missing["reason_code"] == "missing_artifact"
    assert "domain=replay" in missing["artifact_ref"]


def test_drill_adapter_uses_live_quant_drill_run_type(tmp_path):
    written = write_drill_artifact_from_snapshot(
        db_file=tmp_path / "quant_sim.db",
        run_id=10,
        stock_code="600000",
        checkpoint="2026-01-05 10:00:00",
        snapshot={"current_price": 13.0, "ma20": 12.5, "amount": 80_000_000},
    )

    assert "domain=drill" in written["artifact_ref"]
    assert "run_type=live_quant_drill" in written["artifact_ref"]


def test_run_artifact_marks_missing_required_indicator_incomplete(tmp_path):
    context = RunArtifactContext(
        db_file=tmp_path / "quant_sim.db",
        run_id=11,
        run_type="historical_replay",
        market="CN",
        timeframe="30m",
    )

    written = write_run_artifact_from_snapshot(
        context,
        stock_code="600000",
        checkpoint="2026-01-05 10:00:00",
        snapshot={"current_price": 13.0, "ma20": 12.5, "amount": 80_000_000},
    )
    read = read_run_artifact(context, stock_code="600000", checkpoint="2026-01-05 10:00:00")

    assert written["source_status"] == "partial"
    assert written["reason_code"] == "incomplete_artifact"
    assert read["source_status"] == "partial"
    assert read["reason_code"] == "incomplete_artifact"
    assert set(read["technical_snapshot_missing_fields"]) >= {"rsi", "macd", "volume_ratio"}


def test_run_artifact_derives_trend_confirmation_fields_from_recent_checkpoints(tmp_path):
    context = RunArtifactContext(
        db_file=tmp_path / "quant_sim.db",
        run_id=12,
        run_type="live_quant_drill",
        market="CN",
        timeframe="30m",
    )

    write_run_artifact_from_snapshot(
        context,
        stock_code="600000",
        checkpoint="2026-01-05 10:00:00",
        snapshot={
            "current_price": 12.0,
            "close": 12.0,
            "ma5": 12.2,
            "ma10": 11.8,
            "ma20": 11.3,
            "ma60": 10.9,
            "ma20_slope": 0.02,
            "rsi": 55.0,
            "macd": 0.08,
            "volume_ratio": 1.6,
            "amount": 80_000_000,
            "technical_snapshot_ready": True,
            "technical_snapshot_status": "ready",
            "recent_checkpoints": [
                {"close": 11.5, "low": 11.25, "ma20": 11.2, "ma20_slope": 0.01},
                {"close": 11.8, "low": 11.35, "ma20": 11.25, "ma20_slope": 0.01},
                {"close": 12.0, "low": 11.5, "ma20": 11.3, "ma20_slope": 0.02},
            ],
        },
    )

    read = read_run_artifact(context, stock_code="600000", checkpoint="2026-01-05 10:00:00")

    assert read["source_status"] == "ready"
    assert read["ma_stack"] == "ma5>ma10>ma20"
    assert read["above_ma20_checkpoints"] == 3
    assert read["retest_confirmed"] is True
    assert read["recent_checkpoints"][-1]["close"] == 12.0
    assert "above_ma20_checkpoints" not in read["technical_snapshot_missing_fields"]
    assert "retest_confirmed" not in read["technical_snapshot_missing_fields"]


def test_run_artifact_does_not_mark_retest_when_pullback_stays_far_above_ma20(tmp_path):
    context = RunArtifactContext(
        db_file=tmp_path / "quant_sim.db",
        run_id=12,
        run_type="live_quant_drill",
        market="CN",
        timeframe="30m",
    )

    write_run_artifact_from_snapshot(
        context,
        stock_code="600000",
        checkpoint="2026-01-05 10:00:00",
        snapshot={
            "current_price": 13.2,
            "close": 13.2,
            "ma5": 13.0,
            "ma10": 12.6,
            "ma20": 11.3,
            "ma60": 10.9,
            "ma20_slope": 0.02,
            "technical_snapshot_ready": True,
            "technical_snapshot_status": "ready",
            "recent_checkpoints": [
                {"close": 12.8, "low": 12.2, "ma20": 11.2, "ma20_slope": 0.01},
                {"close": 13.0, "low": 12.4, "ma20": 11.25, "ma20_slope": 0.01},
                {"close": 13.2, "low": 12.6, "ma20": 11.3, "ma20_slope": 0.02},
            ],
        },
    )

    read = read_run_artifact(context, stock_code="600000", checkpoint="2026-01-05 10:00:00")

    assert read["above_ma20_checkpoints"] == 3
    assert read["retest_confirmed"] is False


def test_engine_blocks_candidate_decision_when_artifact_is_missing(tmp_path):
    class FailingAdapter:
        def analyze_candidate(self, *args, **kwargs):
            raise AssertionError("adapter should not be called when artifact is missing")

    engine = QuantSimEngine(db_file=tmp_path / "quant_sim.db", adapter=FailingAdapter())

    decision = engine._evaluate_candidate_decision(
        {"stock_code": "600000", "stock_name": "浦发银行", "latest_price": 10.0},
        current_time=datetime(2026, 1, 5, 10, 0),
    )

    assert decision["action"] == "HOLD"
    assert decision["decision_type"] == "missing_artifact_hold"
    assert decision["strategy_profile"]["market_snapshot"]["reason_code"] == "missing_artifact_reference"
