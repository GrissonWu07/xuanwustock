from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
from fastapi.testclient import TestClient

import app.gateway_api as gateway_api
import app.discover.discover as discover_gateway
from app.discover.lifecycle_scoring import normalize_discovery_lifecycle_row
from app.gateway.quant_universe_entry import (
    _candidate_event_payload,
    enrich_lifecycle_entry_rows,
    ingest_lifecycle_entry_rows,
)
from app.gateway_api import UIApiContext, create_app
from app.selector_result_store import save_latest_result


CHANGE_ID = "fix-discover-lifecycle-scoring"
ARCHIVED_CHANGE_ID = "2026-05-15-fix-discover-lifecycle-scoring"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _params_dir() -> Path:
    candidates = [
        REPO_ROOT / "openspec" / "changes" / CHANGE_ID / "test-params",
        REPO_ROOT / "openspec" / "changes" / "archive" / ARCHIVED_CHANGE_ID / "test-params",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise AssertionError(f"missing OpenSpec test parameters for {CHANGE_ID}")


PARAMS_DIR = _params_dir()
PARAMS_PATH = PARAMS_DIR / "discovery-lifecycle-normalization.md"
UTC_TABLE_TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")
COMPLETE_WEAK_TECHNICAL_SNAPSHOT = {
    "price": 10.0,
    "latestPrice": 10.0,
    "ma5": 10.5,
    "ma10": 10.6,
    "ma20": 10.8,
    "ma20_slope": 0.0,
    "ma60": 11.0,
    "amount": 120_000_000,
    "volume_ratio": 1.2,
    "rsi": 45.0,
    "macd": 0.0,
    "trend": "sideways",
    "technical_snapshot_ready": True,
    "technical_snapshot_status": "ready",
    "technical_snapshot_missing_fields": [],
    "technical_snapshot_timeframe": "30m",
    "technical_snapshot_provider": "fixture",
    "technical_snapshot_at": "2026-05-15 14:30:00",
    "technical_snapshot_prepared_at": "2026-05-16 10:00:00",
    "technical_snapshot_indicator_version": "fixture-v1",
}
COMPLETE_STRONG_TECHNICAL_SNAPSHOT = {
    "price": 12.34,
    "latestPrice": 12.34,
    "ma5": 12.1,
    "ma10": 11.9,
    "ma20": 11.5,
    "ma20_slope": 0.05,
    "ma60": 10.8,
    "amount": 120_000_000,
    "volume_ratio": 1.35,
    "rsi": 58.2,
    "macd": 0.18,
    "trend": "up",
    "technical_snapshot_ready": True,
    "technical_snapshot_status": "ready",
    "technical_snapshot_missing_fields": [],
    "technical_snapshot_timeframe": "30m",
    "technical_snapshot_provider": "fixture",
    "technical_snapshot_at": "2026-05-15 14:30:00",
    "technical_snapshot_prepared_at": "2026-05-16 10:00:00",
    "technical_snapshot_indicator_version": "fixture-v1",
}


def _load_params() -> dict[str, Any]:
    text = PARAMS_PATH.read_text(encoding="utf-8")
    match = re.search(r"```json\s*(.*?)\s*```", text, flags=re.S)
    assert match, f"missing JSON block in {PARAMS_PATH}"
    return json.loads(match.group(1))


def _load_named_params(filename: str) -> dict[str, Any]:
    path = PARAMS_DIR / filename
    text = path.read_text(encoding="utf-8")
    match = re.search(r"```json\s*(.*?)\s*```", text, flags=re.S)
    assert match, f"missing JSON block in {path}"
    return json.loads(match.group(1))


def test_ai_scanner_strategy_preserves_structured_lifecycle_evidence(tmp_path, monkeypatch):
    params = _load_params()["ai_structured_candidate"]
    captured_config: dict[str, Any] = {}

    class FakeAIStockScanner:
        def __init__(self, config):
            captured_config["max_stocks"] = config.max_stocks

        def scan(self):
            return pd.DataFrame([params["scanner_row"]])

    monkeypatch.setattr(discover_gateway, "AIStockScanner", FakeAIStockScanner, raising=False)

    scanner_df = discover_gateway._run_ai_scanner_strategy(
        object(),
        {"maxStocks": 3},
        top_n=3,
    )

    row = scanner_df.iloc[0].to_dict()
    expected = params["expected"]
    assert captured_config["max_stocks"] == 3
    assert row["股票代码"] == expected["code"]
    assert row["scanner_score"] == expected["source_score"]
    assert row["source_score"] == expected["source_score"]
    assert row["confidence"] >= expected["min_confidence"]
    assert row["trend"] == expected["trend"]
    assert row["technical_confirmation_count"] >= expected["min_technical_confirmation_count"]
    assert "technical_reasons" in row
    assert row["lifecycle_score_diagnostics"]["score_source"] == "explicit"


def test_non_ai_candidate_derives_score_confidence_from_measurable_evidence():
    params = _load_params()["non_ai_ranked_candidate"]

    row = normalize_discovery_lifecycle_row(
        params["row"],
        strategy_key="low_price_bull",
        strategy_name="Low price momentum",
        rank=1,
        total=5,
    )

    expected = params["expected"]
    assert row["source_score"] >= expected["min_source_score"]
    assert row["score"] == row["source_score"]
    assert row["confidence"] >= expected["min_confidence"]
    assert row["trend"] == expected["trend"]
    assert row["technical_confirmation_count"] >= expected["min_technical_confirmation_count"]
    assert row["lifecycle_score_diagnostics"]["score_source"] == "derived"
    assert "source_identity" not in row["lifecycle_score_diagnostics"]["evidence_buckets"]


def test_discover_row_mapping_uses_lifecycle_normalization_boundary():
    params = _load_params()["non_ai_ranked_candidate"]

    row = discover_gateway._discover_row_from_mapping(
        params["row"],
        source="Low price momentum",
        selected_at="2026-04-24 10:00:00",
        strategy_key="low_price_bull",
        rank=1,
        total=5,
    )

    assert row is not None
    assert row["code"] == "000001"
    assert row["source_score"] == row["score"]
    assert row["confidence"] > 0
    assert row["trend"] == "up"
    assert row["technical_confirmation_count"] >= 4
    assert row["lifecycle_score_diagnostics"]["score_source"] == "derived"


def test_source_only_candidate_stays_zero_score_with_diagnostic_reason():
    params = _load_params()["source_only_candidate"]

    row = normalize_discovery_lifecycle_row(
        params["row"],
        strategy_key="main_force",
        strategy_name="Main force selection",
        rank=1,
        total=1,
    )

    expected = params["expected"]
    assert row["source_score"] == expected["source_score"]
    assert row["score"] == expected["source_score"]
    assert row["confidence"] == expected["confidence"]
    assert row["trend"] == expected["trend"]
    assert row["lifecycle_score_diagnostics"]["reason_code"] == expected["reason_code"]


def test_candidate_event_payload_preserves_normalized_diagnostics():
    params = _load_named_params("lifecycle-event-handoff.md")["normalized_ai_event_row"]

    payload = _candidate_event_payload(params["row"], source_type="discover")

    expected = params["expected"]
    assert payload["source_score"] == expected["source_score"]
    assert payload["confidence"] == expected["confidence"]
    assert payload["trend"] == expected["trend"]
    assert payload["payload"]["technical_confirmation_count"] == expected["technical_confirmation_count"]
    assert payload["payload"]["lifecycle_score_diagnostics"]["score_source"] == expected["score_source"]
    assert payload["payload"]["technical_reasons"] == params["row"]["technical_reasons"]


def test_candidate_event_payload_preserves_zero_normalized_evidence():
    params = _load_named_params("lifecycle-event-handoff.md")["zero_evidence_event_row"]

    payload = _candidate_event_payload(params["row"], source_type="discover")

    expected = params["expected"]
    assert payload["source_score"] == expected["source_score"]
    assert payload["confidence"] == expected["confidence"]
    assert payload["trend"] == expected["trend"]
    assert payload["payload"]["source_score"] == expected["source_score"]
    assert payload["payload"]["confidence"] == expected["confidence"]
    assert payload["payload"]["trend"] == expected["trend"]
    assert payload["payload"]["lifecycle_score_diagnostics"]["reason_code"] == expected["reason_code"]


def test_lifecycle_entry_enrichment_exposes_candidate_confidence(tmp_path):
    params = _load_named_params("lifecycle-event-handoff.md")["eligible_event_enrichment"]
    context = UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=tmp_path / "selector_results",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        quant_sim_replay_db_file=tmp_path / "quant_sim_replay.db",
    )
    context.quant_db().add_candidate_event(params["event"])

    rows = enrich_lifecycle_entry_rows(context, [{"code": params["event"]["stock_code"]}])

    expected = params["expected"]
    assert rows[0]["eligible_status"] == expected["eligible_status"]
    assert rows[0]["candidate_score"] == expected["candidate_score"]
    assert rows[0]["candidate_confidence"] == expected["candidate_confidence"]


def test_lifecycle_ingest_keeps_weak_ai_candidate_recommended_only(tmp_path):
    params = _load_named_params("lifecycle-event-handoff.md")["weak_ai_event_handoff"]
    context = UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=tmp_path / "selector_results",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        quant_sim_replay_db_file=tmp_path / "quant_sim_replay.db",
    )
    context.quant_db().update_quant_universe_settings({"auto_entry_mode": "auto_trial"})

    row = {**params["row"], **COMPLETE_WEAK_TECHNICAL_SNAPSHOT}
    summary = ingest_lifecycle_entry_rows(context, [row], source_type="discover")

    expected = params["expected"]
    events = context.quant_db().list_candidate_events(
        stock_code=row["code"],
        status=expected["event_status"],
        limit=10,
    )
    state = context.quant_db().get_quant_universe_state(row["code"]) or {}
    assert summary["attempted"] == expected["attempted"]
    assert summary["events"] == expected["events"]
    assert summary["promoted"] == expected["promoted"]
    assert summary["eligible"] == expected["eligible"]
    assert summary["skipped"][0]["reason"] == expected["skip_reason"]
    assert len(events) == 1
    assert events[0]["payload_json"]["entry_gate"]["reason_code"] == expected["skip_reason"]
    assert state.get("quant_status", "inactive") == expected["quant_status"]


def test_lifecycle_entry_enrichment_empty_fields_include_confidence(tmp_path):
    context = UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=tmp_path / "selector_results",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        quant_sim_replay_db_file=tmp_path / "quant_sim_replay.db",
    )

    rows = enrich_lifecycle_entry_rows(context, [{"code": "300001"}])

    assert rows[0]["eligible_status"] == "skipped"
    assert rows[0]["candidate_score"] == 0.0
    assert rows[0]["candidate_confidence"] == 0.0
    assert rows[0]["blocking_reason"] == "not_evaluated"


def test_discover_api_exposes_lifecycle_diagnostics_without_utc_table_time(tmp_path):
    params = _load_named_params("discover-api-ui-diagnostics.md")["api_candidate_diagnostics"]
    context = UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=tmp_path / "selector_results",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        quant_sim_replay_db_file=tmp_path / "quant_sim_replay.db",
    )
    save_latest_result(
        "ai_scanner",
        {
            "stocks_df": pd.DataFrame([params["selector_row"]]),
            "selected_at": params["expected"]["selected_at"],
        },
        base_dir=context.selector_result_dir,
    )
    client = TestClient(create_app(context=context))

    response = client.get("/api/v1/discover")

    assert response.status_code == 200
    row = {item["code"]: item for item in response.json()["candidateTable"]["rows"]}[params["expected"]["code"]]
    assert row["source_score"] == params["expected"]["source_score"]
    assert row["confidence"] == params["expected"]["confidence"]
    assert row["candidate_confidence"] == params["expected"]["candidate_confidence"]
    assert row["technical_confirmation_count"] >= params["expected"]["min_technical_confirmation_count"]
    assert row["lifecycle_score_diagnostics"]["score_source"] == params["expected"]["score_source"]
    assert not UTC_TABLE_TIME_RE.search(json.dumps(row, ensure_ascii=False))


def test_discover_task_status_reports_quant_auto_entry_diagnostics(tmp_path, monkeypatch):
    params = _load_named_params("discover-api-ui-diagnostics.md")
    selector_row = params["api_candidate_diagnostics"]["selector_row"]
    expected = params["task_quant_auto_entry"]["expected"]
    context = UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=tmp_path / "selector_results",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        quant_sim_replay_db_file=tmp_path / "quant_sim_replay.db",
    )
    context.quant_db().update_quant_universe_settings({"auto_entry_mode": "auto_trial"})

    class FakeLowPriceBullSelector:
        def get_low_price_stocks(self, top_n=5):
            return True, pd.DataFrame([selector_row]), "ok"

    def fake_prepare(rows):
        prepared = [{**row, **COMPLETE_STRONG_TECHNICAL_SNAPSHOT} for row in rows]
        return SimpleNamespace(
            rows=prepared,
            summary={
                "uniqueStocks": len(prepared),
                "prepared": len(prepared),
                "complete": len(prepared),
                "incomplete": 0,
                "failed": 0,
                "blocked": 0,
                "items": [],
            },
        )

    monkeypatch.setattr(gateway_api, "LowPriceBullSelector", FakeLowPriceBullSelector)
    monkeypatch.setattr(discover_gateway, "prepare_discovery_market_snapshots", fake_prepare)
    client = TestClient(create_app(context=context))

    response = client.post(
        "/api/v1/discover/actions/run-strategy",
        json={"strategy": "low_price_bull", "waitMs": 5000},
    )

    assert response.status_code == 200
    task_id = response.json()["taskId"]
    task_response = client.get(f"/api/v1/tasks/{task_id}")
    assert task_response.status_code == 200
    quant_auto_entry = task_response.json()["result"]["quantAutoEntry"]
    assert quant_auto_entry["attempted"] == expected["attempted"]
    assert quant_auto_entry["events"] == expected["events"]
    assert quant_auto_entry["promoted"] == expected["promoted"]
    assert quant_auto_entry["eligible"] == expected["eligible"]
    assert len(quant_auto_entry["skipped"]) == expected["skipped"]
