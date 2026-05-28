from __future__ import annotations

from app.gateway.quant_universe_entry import _candidate_event_payload
from app.quant_sim.candidate_entry_gate import evaluate_candidate_entry_gate
from app.quant_sim.lifecycle_artifact_adapter import candidate_artifact_payload
from app.quant_sim.market_technical_artifact import (
    ArtifactWriteRequest,
    MarketTechnicalArtifactData,
    MarketTechnicalArtifactRef,
)
from app.quant_sim.market_technical_artifact_store import MarketTechnicalArtifactStore
from app.quant_sim.technical_entry_score import calculate_technical_entry_score


def _sample_data(**overrides) -> MarketTechnicalArtifactData:
    values = {
        "latest_price": 21.0,
        "close": 21.0,
        "ma5": 21.2,
        "ma10": 20.8,
        "ma20": 20.0,
        "ma60": 18.5,
        "ma20_slope": 0.04,
        "rsi": 58.0,
        "macd": 0.12,
        "volume_ratio": 1.5,
        "amount": 120_000_000.0,
        "trend": "up",
        "provider": "unit-test",
        "indicator_version": "technical-entry-v1",
        "source_status": "ready",
        "reason_code": "ok",
        "computed_at": "2026-01-05T02:00:05Z",
    }
    values.update(overrides)
    return MarketTechnicalArtifactData(**values)


def _seed_artifact(db_file, **overrides):
    return MarketTechnicalArtifactStore(db_file).upsert(
        ArtifactWriteRequest(
            ref=MarketTechnicalArtifactRef.live(
                stock_code="600000",
                market="CN",
                checkpoint_at="2026-01-05T02:00:00Z",
                timeframe="30m",
            ),
            data=_sample_data(**overrides),
        )
    )


def test_candidate_payload_keeps_event_light_and_reads_facts_from_artifact(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    written = _seed_artifact(db_file)
    row = {
        "code": "600000",
        "name": "浦发银行",
        "source": "low_price",
        "artifact_ref": written.artifact_ref,
        "price": 1.0,
        "ma20": 1.0,
        "source_score": 0.99,
        "source_confidence": 0.99,
    }

    payload = _candidate_event_payload(row, source_type="discover", db_file=str(db_file))
    evidence = payload["payload"]
    gate = evaluate_candidate_entry_gate(
        {"source_type": "discover", "payload_json": evidence},
        profile_id="aggressive",
        artifact_db_file=str(db_file),
    )
    materialized = candidate_artifact_payload(evidence, db_file=str(db_file))
    score = calculate_technical_entry_score([{"payload_json": materialized}], profile_id="aggressive")

    assert evidence["artifact_ref"] == written.artifact_ref
    assert "price" not in evidence
    assert "ma20" not in evidence
    assert materialized["price"] == 21.0
    assert materialized["ma20"] == 20.0
    assert "source_score" not in evidence
    assert "source_confidence" not in evidence
    assert gate["passed"] is True
    assert score["candidate_score"] > 0


def test_candidate_entry_blocks_missing_artifact_reference():
    payload = _candidate_event_payload({"code": "600000", "name": "浦发银行"}, source_type="discover", db_file="")
    gate = evaluate_candidate_entry_gate({"source_type": "discover", "payload_json": payload["payload"]})

    assert gate["passed"] is False
    assert gate["reason_code"] == "missing_artifact_reference"


def test_candidate_entry_blocks_partial_artifact(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    written = _seed_artifact(
        db_file,
        source_status="partial",
        reason_code="incomplete_artifact",
        missing_fields=["ma20"],
    )

    payload = _candidate_event_payload(
        {"code": "600000", "name": "浦发银行", "artifact_ref": written.artifact_ref},
        source_type="discover",
        db_file=str(db_file),
    )
    gate = evaluate_candidate_entry_gate(
        {"source_type": "discover", "payload_json": payload["payload"]},
        profile_id="aggressive",
        artifact_db_file=str(db_file),
    )

    assert gate["passed"] is False
    assert gate["reason_code"] == "incomplete_artifact"
    assert gate["missing_fields"] == ["ma20"]
