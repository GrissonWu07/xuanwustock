from __future__ import annotations

from app.discover import discover as discover_gateway
from app.gateway.quant_universe_entry import enrich_lifecycle_entry_rows
from app.gateway_api import UIApiContext
from app.quant_sim.candidate_entry_gate import evaluate_candidate_entry_gate
from app.quant_sim.quant_universe_lifecycle import QuantUniverseLifecyclePolicy, calculate_candidate_score
from app.quant_sim.technical_entry_score import (
    _distance_quality,
    _num,
    _optional_num,
    _overextension_penalty,
    _overheated_penalty,
    _rsi_constructive_score,
    _rsi_risk_quality,
    _volume_constructive_score,
    _volume_risk_quality,
    min_candidate_confidence,
)


def _context(tmp_path):
    selector_dir = tmp_path / "selector_results"
    selector_dir.mkdir(parents=True, exist_ok=True)
    return UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=selector_dir,
        quant_sim_db_file=tmp_path / "quant_sim.db",
        quant_sim_replay_db_file=tmp_path / "quant_sim_replay.db",
    )


def _strong_technical_payload(**overrides):
    payload = {
        "price": 12.8,
        "ma5": 12.7,
        "ma10": 12.2,
        "ma20": 11.8,
        "ma20_slope": 0.035,
        "ma60": 10.6,
        "amount": 130_000_000,
        "volume_ratio": 1.45,
        "rsi": 61.0,
        "macd": 0.22,
        "trend": "up",
        "technical_snapshot_ready": True,
        "technical_snapshot_status": "ready",
        "technical_snapshot_missing_fields": [],
        "technical_snapshot_timeframe": "30m",
        "technical_snapshot_provider": "unit-test",
        "technical_snapshot_at": "2026-05-16 14:30:00",
        "technical_snapshot_prepared_at": "2026-05-16 14:35:00",
        "technical_snapshot_row_count": 180,
        "technical_snapshot_indicator_version": "technical-entry-v1",
        "artifact_ref": "mta:test",
        "source_status": "ready",
        "reason_code": "ok",
        "consecutive_checkpoint_score": 1.0,
        "ma20_breakout_retest_score": 1.0,
        "technical_confirmation_count": 5,
    }
    payload.update(overrides)
    return payload


def _event(*, source_score=0.0, confidence=0.0, source_key="ai_scanner", payload=None):
    evidence = payload if payload is not None else _strong_technical_payload()
    return {
        "stock_code": "600000",
        "source_type": "discover",
        "source_key": source_key,
        "source_score": source_score,
        "confidence": confidence,
        "trend": evidence.get("trend", "neutral"),
        "payload": evidence,
    }


def test_technical_candidate_score_ignores_source_score_and_confidence():
    policy = QuantUniverseLifecyclePolicy.stable_defaults()

    low_source = calculate_candidate_score([_event(source_score=0.01, confidence=0.01)], {}, policy)
    high_source = calculate_candidate_score([_event(source_score=0.99, confidence=0.99)], {}, policy)

    assert low_source["candidate_score"] == high_source["candidate_score"]
    assert low_source["candidate_confidence"] == high_source["candidate_confidence"]
    assert low_source["candidate_score"] >= policy.strong_candidate_threshold
    assert low_source["candidate_confidence"] >= 0.75
    forbidden = {"source_score_component", "confidence_component", "recommendation_score_component"}
    assert forbidden.isdisjoint(low_source["breakdown"].keys())


def test_single_snapshot_confirmation_is_capped_without_multi_checkpoint_evidence():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    payload = _strong_technical_payload()
    payload.pop("consecutive_checkpoint_score")
    payload.pop("ma20_breakout_retest_score")

    result = calculate_candidate_score([_event(payload=payload)], {}, policy)

    assert result["breakdown"]["confirmation_score"] == 0.5
    assert result["breakdown"]["confirmation_source"] == "single_snapshot_cap"


def test_missing_technical_snapshot_cannot_be_scored_from_source_metadata():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()

    result = calculate_candidate_score(
        [_event(source_score=1.0, confidence=1.0, payload={"trend": "up"})],
        {},
        policy,
    )

    assert result["candidate_score"] == 0.0
    assert result["candidate_confidence"] < 0.70
    assert result["breakdown"]["blocking_reason"] == "missing_technical_snapshot"


def test_ai_entry_gate_uses_technical_snapshot_not_source_confidence():
    result = evaluate_candidate_entry_gate(_event(source_score=0.0, confidence=0.0), profile_id="stable")

    assert result["passed"] is True
    assert result["status"] == "active"


def test_default_discovery_selection_includes_ai_scanner():
    selected = discover_gateway._normalize_discover_strategy_selection({})

    assert "ai_scanner" in selected


def test_discover_enrichment_does_not_fallback_to_source_score_without_lifecycle_state(tmp_path):
    context = _context(tmp_path)

    rows = enrich_lifecycle_entry_rows(
        context,
        [{"code": "600000", "source_score": 0.99, "confidence": 0.98, "score": 0.97}],
    )

    assert rows[0]["candidate_score"] == 0.0
    assert rows[0]["candidate_confidence"] == 0.0


def test_empty_events_and_profile_confidence_thresholds():
    policy = QuantUniverseLifecyclePolicy.conservative_defaults()

    result = calculate_candidate_score([], {}, policy)

    assert result["candidate_score"] == 0.0
    assert result["breakdown"]["blocking_reason"] == "missing_candidate_event"
    assert min_candidate_confidence("aggressive") == 0.70
    assert min_candidate_confidence("stable") == 0.75
    assert min_candidate_confidence("conservative") == 0.80


def test_technical_score_blocks_stale_snapshot_instead_of_penalizing_it():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()
    payload = _strong_technical_payload(
        price=13.7,
        ma5=13.2,
        ma10=13.0,
        ma20=11.8,
        ma60=9.4,
        rsi=78.0,
        volume_ratio=3.2,
        technical_snapshot_status="stale",
    )

    result = calculate_candidate_score([_event(payload=payload)], {"is_liquid": False}, policy)

    assert result["candidate_score"] == 0.0
    assert result["candidate_confidence"] == 0.0
    assert result["breakdown"]["blocking_reason"] == "stale_required_snapshot"
    assert result["breakdown"]["trend_structure_score"] == 0.0


def test_technical_score_handles_mid_quality_boundaries_and_payload_json():
    policy = QuantUniverseLifecyclePolicy.stable_defaults()
    payload = _strong_technical_payload(
        price=10.4,
        ma5=10.5,
        ma10=10.4,
        ma20=10.0,
        ma20_slope=0.0,
        ma60=9.8,
        amount=65_000_000,
        volume_ratio=2.8,
        rsi=47.0,
        trend="neutral",
    )
    payload.pop("consecutive_checkpoint_score")
    payload.pop("ma20_breakout_retest_score")

    result = calculate_candidate_score(
        [{"source_type": "discover", "source_score": 0.0, "confidence": 0.0, "payload_json": payload}],
        {},
        policy,
    )

    assert result["breakdown"]["trend_structure_score"] > 0.5
    assert result["breakdown"]["volume_liquidity_score"] < 1.0
    assert result["breakdown"]["confirmation_source"] == "single_snapshot_cap"
    assert result["candidate_confidence"] >= policy.min_candidate_confidence


def test_technical_score_penalizes_contradictory_and_thin_evidence():
    policy = QuantUniverseLifecyclePolicy.stable_defaults()
    payload = _strong_technical_payload(
        price=9.4,
        ma5=9.1,
        ma10=9.3,
        ma20=10.0,
        ma20_slope=-0.02,
        ma60=10.2,
        amount=20_000_000,
        volume_ratio=0.6,
        rsi=39.0,
        macd=0.04,
        technical_snapshot_ready=True,
        technical_snapshot_at="",
        technical_snapshot_row_count=40,
    )
    payload.pop("technical_snapshot_at")

    result = calculate_candidate_score([_event(payload=payload)], {}, policy)

    assert result["candidate_score"] == 0.0
    assert result["candidate_confidence"] == 0.0
    assert result["breakdown"]["blocking_reason"] == "missing_required_snapshot"


def test_technical_score_applies_liquidity_adjustment_without_source_fallback():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()

    liquid = calculate_candidate_score([_event(source_score=1.0, confidence=1.0)], {"is_liquid": True}, policy)
    illiquid = calculate_candidate_score([_event(source_score=1.0, confidence=1.0)], {"is_liquid": False}, policy)

    assert liquid["candidate_score"] > illiquid["candidate_score"]
    assert round(liquid["candidate_score"] - illiquid["candidate_score"], 4) == 0.1
    assert "source_score_component" not in illiquid["breakdown"]


def test_snapshot_blocking_distinguishes_unready_stale_and_missing_metadata():
    policy = QuantUniverseLifecyclePolicy.aggressive_defaults()

    unready = calculate_candidate_score(
        [_event(payload=_strong_technical_payload(technical_snapshot_ready=False))],
        {},
        policy,
    )
    stale_unprepared = calculate_candidate_score(
        [_event(payload=_strong_technical_payload(technical_snapshot_status="stale_unprepared"))],
        {},
        policy,
    )
    missing_metadata_payload = _strong_technical_payload()
    missing_metadata_payload.pop("technical_snapshot_provider")
    missing_metadata = calculate_candidate_score([_event(payload=missing_metadata_payload)], {}, policy)

    assert unready["breakdown"]["blocking_reason"] == "missing_required_snapshot"
    assert stale_unprepared["breakdown"]["blocking_reason"] == "stale_required_snapshot"
    assert missing_metadata["breakdown"]["blocking_reason"] == "missing_required_snapshot"
    assert "technical_snapshot_provider" in missing_metadata["breakdown"]["missing_snapshot_fields"]


def test_score_boundaries_for_mid_and_bad_market_conditions():
    policy = QuantUniverseLifecyclePolicy.stable_defaults()
    payload = _strong_technical_payload(
        price=10.3,
        ma5=10.4,
        ma10=10.2,
        ma20=10.0,
        ma20_slope=-0.01,
        ma60=9.7,
        amount=45_000_000,
        volume_ratio=4.2,
        rsi=80.0,
        macd=-0.01,
        trend="sideways",
        technical_snapshot_row_count=65,
    )
    payload.pop("consecutive_checkpoint_score")
    payload.pop("ma20_breakout_retest_score")

    result = calculate_candidate_score([_event(payload=payload)], {}, policy)

    assert result["breakdown"]["confirmation_source"] == "single_snapshot_cap"
    assert result["breakdown"]["history_depth"] == 0.7
    assert result["breakdown"]["volume_liquidity_score"] < 0.5
    assert result["breakdown"]["overheated_penalty"] > 0


def test_technical_score_helper_boundaries_are_deterministic():
    assert _rsi_constructive_score(43) == 0.4
    assert _rsi_constructive_score(90) == 0.0
    assert _rsi_risk_quality(40) == 0.5
    assert _volume_constructive_score(0.7) == 0.3
    assert _volume_constructive_score(6.0) == 0.0
    assert _volume_risk_quality(0.6) == 0.5
    assert _volume_risk_quality(6.0) == 0.0
    assert _distance_quality(0, 10, ideal_high=0.08, warn_high=0.15, allow_negative=False) == 0.0
    assert _distance_quality(9.8, 10, ideal_high=0.08, warn_high=0.15, allow_negative=True) == 0.5
    assert _distance_quality(13, 10, ideal_high=0.08, warn_high=0.15, allow_negative=False) == 0.0
    assert _overextension_penalty(12, 10, 10) == 0.10
    assert _overextension_penalty(11, 10, 10) == 0.05
    assert _overheated_penalty(83, 1.0) == 0.10
    assert _overheated_penalty(76, 1.0) == 0.05
    assert _num("bad", 7.0) == 7.0
    assert _optional_num("bad") is None
