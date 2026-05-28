from __future__ import annotations

from types import SimpleNamespace

from app.gateway.trades import build_trade_provenance
from app.quant_sim import candidate_re_evaluation
from app.quant_sim.decision_provenance import build_decision_provenance
from app.quant_sim.evidence_models import CandidateReevaluationRequest, DecisionProvenanceInput, PreparedEvidenceInput
from app.quant_sim.evidence_service import build_prepared_evidence, prepared_evidence_payload_fields
from app.quant_sim.replay_coverage import enrich_replay_tasks_with_coverage
from app.selector_result_store import save_latest_result


def test_prepared_evidence_falls_back_to_quant_blocking_reason_and_system_time():
    evidence = build_prepared_evidence(
        PreparedEvidenceInput(
            row={
                "id": "600010.SH",
                "name": "包钢股份",
                "strategyName": "low_price_bull",
                "blocking_reason": "missing_technical_snapshot",
                "technical_snapshot_status": "missing_technical_snapshot",
                "technical_snapshot_at": "2026-05-17T05:21:22Z",
                "source_score": "not-a-number",
                "confidence": "0.42",
            },
            run_id="discover-test",
            source_type="discover",
            evaluated_at="2026-05-17T05:22:00Z",
        )
    )

    assert evidence["stockCode"] == "600010"
    assert evidence["source"]["auditScore"] == 0.0
    assert evidence["entryGate"]["status"] == "blocked"
    assert evidence["entryGate"]["reasonCode"] == "missing_technical_snapshot"
    assert evidence["technicalSnapshot"]["asOf"]
    assert "T" not in evidence["technicalSnapshot"]["asOf"]
    assert not evidence["technicalSnapshot"]["asOf"].endswith("Z")
    assert "T" not in evidence["evidenceAt"]
    assert not evidence["evidenceAt"].endswith("Z")


def test_prepared_evidence_payload_builds_when_row_has_no_attached_evidence():
    payload = prepared_evidence_payload_fields(
        {
            "discoveryRunId": "discover-run",
            "code": "000001",
            "source_key": "ai_scanner",
            "price": 12.3,
            "ma5": 12.6,
            "ma10": 12.4,
            "ma20": 12.0,
            "ma20_slope": 0.03,
            "volume_ratio": 1.4,
            "amount": 120000000,
            "technical_snapshot_ready": True,
            "technical_snapshot_status": "ready",
            "refreshReEvaluation": {"run_reason": "refresh"},
        },
        source_type="discover",
    )

    assert payload["prepared_evidence"]["status"] == "ready"
    assert payload["score_semantics"]["candidate_score"] == "quant_technical_entry_score"
    assert payload["refresh_re_evaluation"]["run_reason"] == "refresh"


def test_candidate_re_evaluation_skips_when_artifact_empty(monkeypatch):
    monkeypatch.setattr(candidate_re_evaluation, "load_discovery_candidate_artifact", lambda base_dir: {})

    summary = candidate_re_evaluation._reevaluate(
        CandidateReevaluationRequest(
            context=SimpleNamespace(selector_result_dir="unused"),
            run_reason="refresh",
        )
    )

    assert summary["attempted"] == 0
    assert summary["updatedAt"]
    assert "T" not in summary["updatedAt"]


def test_candidate_re_evaluation_records_non_ready_skip(monkeypatch):
    class FakeDb:
        def list_candidate_events(self, stock_code, source_type, limit):
            return [
                {
                    "status": "blocked",
                    "payload_json": {
                        "entry_gate": {"reason_code": "missing_technical_snapshot"},
                        "technical_snapshot_status": "missing_technical_snapshot",
                    },
                }
            ]

    monkeypatch.setattr(
        candidate_re_evaluation,
        "load_discovery_candidate_artifact",
        lambda base_dir: {"runId": "discover-run", "rows": [{"code": "000001", "name": "平安银行"}]},
    )
    monkeypatch.setattr(candidate_re_evaluation, "_load_runtime_entries", lambda base_dir: {})

    summary = candidate_re_evaluation._reevaluate(
        CandidateReevaluationRequest(
            context=SimpleNamespace(selector_result_dir="unused", quant_db=lambda: FakeDb()),
            run_reason="refresh",
        )
    )

    assert summary["attempted"] == 1
    assert summary["reEvaluated"] == 0
    assert summary["skipped"] == [{"stockCode": "000001", "reason": "technical_snapshot_not_ready"}]


def test_candidate_re_evaluation_counts_ingest_skips(monkeypatch):
    class FakeDb:
        def list_candidate_events(self, stock_code, source_type, limit):
            return [{"status": "recommended_only", "payload_json": {"blocking_reason": "stale_unprepared"}}]

    monkeypatch.setattr(
        candidate_re_evaluation,
        "load_discovery_candidate_artifact",
        lambda base_dir: {"runId": "discover-run", "rows": [{"code": "000002", "name": "万科A"}]},
    )
    monkeypatch.setattr(
        candidate_re_evaluation,
        "_load_runtime_entries",
        lambda base_dir: {
            "000002": {
                "price": 8.2,
                "ma5": 8.4,
                "ma10": 8.3,
                "ma20": 8.0,
                "ma20_slope": 0.01,
                "amount": 90000000,
                "volume_ratio": 1.2,
                "technical_snapshot_ready": True,
                "technical_snapshot_status": "ready",
            }
        },
    )
    captured: dict[str, list[dict[str, object]]] = {}

    def fake_ingest(context, rows, source_type):
        captured["rows"] = rows
        return {
            "events": 1,
            "promoted": 0,
            "eligible": 1,
            "skipped": [{"stockCode": "000002", "reason": "below_threshold"}],
        }

    monkeypatch.setattr(candidate_re_evaluation, "ingest_lifecycle_entry_rows", fake_ingest)

    summary = candidate_re_evaluation._reevaluate(
        CandidateReevaluationRequest(
            context=SimpleNamespace(selector_result_dir="unused", quant_db=lambda: FakeDb()),
            run_reason="refresh",
            evaluated_at="2026-05-17T05:22:00Z",
        )
    )

    assert summary["reEvaluated"] == 1
    assert summary["events"] == 1
    assert summary["eligible"] == 1
    assert summary["skipped"] == [{"stockCode": "000002", "reason": "below_threshold"}]
    assert "T" not in summary["updatedAt"]
    row = captured["rows"][0]
    assert row["preparedEvidence"]["refresh"]["lastReevaluation"]["run_reason"] == "refresh"


def test_runtime_entries_loader_normalizes_codes_and_ignores_invalid_items(tmp_path):
    save_latest_result(
        candidate_re_evaluation.RUNTIME_SNAPSHOT_KEY,
        {"entries": {"000001.SZ": {"price": 11.1}, "bad": "skip"}},
        base_dir=tmp_path,
    )

    entries = candidate_re_evaluation._load_runtime_entries(tmp_path)

    assert entries == {"000001": {"price": 11.1}}


def test_decision_provenance_uses_indicator_price_and_default_replay_context():
    payload = build_decision_provenance(
        DecisionProvenanceInput(
            signal={"stock_code": "600000", "action": "BUY"},
            decision={"checkpointAt": "2026-05-17 10:00:00", "finalAction": "BUY"},
            strategy_profile={
                "analysis_timeframe": "30m",
                "explainability": {
                    "fusion_breakdown": {
                        "weighted_gate_fail_reasons": "not-a-list",
                        "core_rule_action": "BUY",
                    }
                },
            },
            technical_indicators=[{"name": "当前价", "value": 10.5}],
            source="replay",
        )
    )

    assert payload["marketSnapshot"]["status"] == "ready"
    assert payload["marketSnapshot"]["asOf"] == "current_price=10.5"
    assert payload["stockAnalysisContext"] == {
        "status": "omitted",
        "omittedReason": "historical_replay_asof_safety",
    }
    assert payload["gateResult"]["failReasons"] == []


def test_decision_provenance_keeps_used_research_context():
    payload = build_decision_provenance(
        DecisionProvenanceInput(
            signal={"stock_code": "000001"},
            decision={"action": "HOLD"},
            strategy_profile={"stock_analysis_context": {"used": True, "omitted_reason": "ignored"}},
            technical_indicators=[],
            source="live",
        )
    )

    assert payload["stockAnalysisContext"] == {"status": "used", "omittedReason": ""}
    assert payload["marketSnapshot"]["status"] == "unavailable"


def test_replay_coverage_handles_empty_payload_and_invalid_metadata():
    payload = {"tasks": [{"runId": "missing", "checkpointCount": "bad"}, "skip"]}

    result = enrich_replay_tasks_with_coverage(payload, runs=[{"id": "other", "metadata": {"checkpoint_coverage": {}}}])

    assert result["tasks"][0]["checkpointCoverage"]["status"] == "unavailable"
    assert result["tasks"][0]["checkpointCoverage"]["checkpointCount"] == 0
    assert result["tasks"][0]["contextParity"]["stockAnalysisContext"]["omittedReason"] == (
        "historical_replay_asof_safety"
    )
    assert result["tasks"][1] == "skip"
    assert enrich_replay_tasks_with_coverage({"tasks": []}, runs=[]) == {"tasks": []}


def test_trade_provenance_reports_missing_buy_and_sell_links():
    buy = build_trade_provenance(
        {
            "signal_id": "sig-buy",
            "stock_code": "000001",
            "action": "BUY",
            "quantity": 100,
            "price": 10,
            "trade_metadata": "{}",
        }
    )
    sell = build_trade_provenance(
        {
            "signal_id": "sig-sell",
            "stock_code": "000001",
            "action": "SELL",
            "quantity": 100,
            "price": 9,
            "realized_pnl": -100,
            "trade_metadata": {},
        }
    )

    assert buy["missingReasons"] == ["lot_missing", "slot_allocation_missing"]
    assert sell["missingReasons"] == ["consumed_lots_missing", "released_slot_allocations_missing"]
