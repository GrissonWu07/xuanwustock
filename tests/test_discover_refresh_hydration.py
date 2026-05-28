from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pandas as pd
from fastapi.testclient import TestClient

import app.discover.discover as discover_gateway
from app.gateway_api import UIApiContext, create_app


def _ready_snapshot(code: str = "600001") -> dict[str, Any]:
    return {
        "stock_code": code,
        "price": 12.34,
        "ma5": 12.50,
        "ma10": 12.30,
        "ma20": 12.00,
        "ma20_slope": 0.02,
        "ma60": 11.20,
        "amount": 90_000_000,
        "volume_ratio": 1.5,
        "rsi": 58.2,
        "macd": 0.12,
        "trend": "up",
        "technical_snapshot_ready": True,
        "technical_snapshot_status": "ready",
        "technical_snapshot_missing_fields": [],
        "technical_snapshot_timeframe": "30m",
        "technical_snapshot_provider": "fixture",
        "technical_snapshot_at": "2026-05-16 10:00:00",
        "technical_snapshot_prepared_at": "2026-05-16 10:01:00",
        "technical_snapshot_row_count": 120,
        "technical_snapshot_indicator_version": "fixture-v1",
    }


def test_candidate_artifact_hydrates_rows_from_runtime_snapshot(tmp_path):
    from app.discover.candidate_artifact import (
        discovery_candidate_codes,
        hydrate_discovery_candidate_rows,
        load_discovery_candidate_artifact,
        save_discovery_candidate_artifact,
        technical_summary_from_rows,
    )

    row = {
        "id": "600001",
        "code": "600001",
        "name": "旧名称",
        "strategyKey": "low_price_bull",
        "strategyName": "低价擒牛",
        "source": "低价擒牛",
        "cells": ["600001", "旧名称", "", "低价擒牛", "--", "--", "--", "--"],
    }
    save_discovery_candidate_artifact(
        [row],
        run_id="discover-test-001",
        selected_at="2026-05-16 10:00:00",
        base_dir=tmp_path,
    )

    payload = load_discovery_candidate_artifact(base_dir=tmp_path)
    assert payload["runId"] == "discover-test-001"
    assert discovery_candidate_codes(base_dir=tmp_path) == {"600001"}

    runtime = {
        "600001": {
            "stock_name": "测试股份",
            "sector": "测试行业",
            "latest_price": 12.34,
            **_ready_snapshot("600001"),
        }
    }
    hydrated = hydrate_discovery_candidate_rows(payload["rows"], runtime, run_id=payload["runId"])

    assert hydrated[0]["name"] == "测试股份"
    assert hydrated[0]["cells"][1] == "测试股份"
    assert hydrated[0]["latestPrice"] == 12.34
    assert hydrated[0]["technical_snapshot_ready"] is True
    assert hydrated[0]["technical_snapshot_status"] == "ready"
    assert hydrated[0]["trend"] == "up"
    assert technical_summary_from_rows(hydrated)["complete"] == 1


def test_raw_selector_fallback_is_marked_stale_unprepared():
    from app.discover.candidate_artifact import mark_rows_stale_unprepared, technical_summary_from_rows

    rows = [{"id": "600002", "code": "600002", "name": "旧缓存"}]
    stale = mark_rows_stale_unprepared(rows)

    assert stale[0]["discoveryArtifactStatus"] == "stale_unprepared"
    assert stale[0]["technical_snapshot_ready"] is False
    assert stale[0]["technical_snapshot_status"] == "stale_unprepared"
    assert stale[0]["blocking_reason"] == "missing_technical_snapshot"
    assert technical_summary_from_rows(stale)["blocked"] == 1


def test_candidate_artifact_handles_empty_invalid_and_failed_rows(tmp_path):
    from app.discover.candidate_artifact import (
        discovery_candidate_codes,
        hydrate_discovery_candidate_rows,
        load_discovery_candidate_artifact,
        mark_rows_stale_unprepared,
        save_discovery_candidate_artifact,
        technical_summary_from_rows,
    )

    assert load_discovery_candidate_artifact(base_dir=tmp_path) == {}
    assert discovery_candidate_codes(base_dir=tmp_path) == set()
    save_discovery_candidate_artifact(
        [None, {"id": "3", "code": "3", "cells": ["3"]}],
        run_id="discover-test-003",
        selected_at="2026-05-16 10:00:00",
        base_dir=tmp_path,
    )
    assert discovery_candidate_codes(base_dir=tmp_path) == {"000003"}

    failed_runtime = {
        "000003": {
            "technical_snapshot_ready": False,
            "technical_snapshot_status": "failed",
            "technical_snapshot_missing_fields": ["ma20"],
            "technical_snapshot_error": "provider unavailable",
        }
    }
    hydrated = hydrate_discovery_candidate_rows(
        [None, {"id": "3", "code": "3", "cells": ["3"]}],
        failed_runtime,
        run_id="discover-test-003",
    )
    assert hydrated[0]["code"] == "3"
    assert hydrated[0]["technical_snapshot_status"] == "failed"
    assert hydrated[0]["technical_snapshot_error"] == "provider unavailable"
    summary = technical_summary_from_rows([None, *hydrated])
    assert summary["failed"] == 1
    assert mark_rows_stale_unprepared([None]) == []


def test_unified_refresh_collects_discovery_candidates(tmp_path):
    from app.discover.candidate_artifact import save_discovery_candidate_artifact
    from app.stock_refresh_scheduler import UnifiedStockRefreshScheduler

    save_discovery_candidate_artifact(
        [{"id": "600003", "code": "600003", "name": "刷新股份"}],
        run_id="discover-test-002",
        selected_at="2026-05-16 10:00:00",
        base_dir=tmp_path,
    )
    context = SimpleNamespace(
        selector_result_dir=tmp_path,
        watchlist=lambda: SimpleNamespace(list_watches=lambda: []),
        portfolio_manager=lambda: SimpleNamespace(get_all_stocks=lambda: []),
        quant_db=lambda: SimpleNamespace(get_candidates=lambda status=None: [], get_positions=lambda: []),
    )

    assert "600003" in UnifiedStockRefreshScheduler._collect_codes(context)


def test_unified_refresh_runtime_entry_persists_technical_snapshot(tmp_path, monkeypatch):
    import app.stock_refresh_scheduler as refresh_module
    from app.stock_refresh_scheduler import UnifiedStockRefreshScheduler, load_stock_runtime_entries, save_stock_runtime_entries

    monkeypatch.setattr(
        UnifiedStockRefreshScheduler,
        "_fetch_realtime_quote",
        staticmethod(lambda stock_code, preferred_name=None: {"name": "刷新股份", "price": 15.8, "data_source": "fixture"}),
    )
    monkeypatch.setattr(
        UnifiedStockRefreshScheduler,
        "_fetch_basic_info",
        staticmethod(lambda stock_code: {"industry": "测试行业", "market_cap": 10_000_000, "pe": 12, "pb": 1.2}),
    )
    monkeypatch.setattr(refresh_module, "prepare_discovery_market_snapshot", lambda stock_code: _ready_snapshot(stock_code))

    entry = UnifiedStockRefreshScheduler._fetch_runtime_entry(stock_code="600003", existing=None)
    save_stock_runtime_entries({"600003": entry}, base_dir=tmp_path, updated_at="2026-05-16T02:01:00Z")
    loaded = load_stock_runtime_entries(base_dir=tmp_path)["600003"]

    assert loaded["stock_name"] == "刷新股份"
    assert loaded["technical_snapshot_ready"] is True
    assert loaded["technical_snapshot_status"] == "ready"
    assert loaded["ma20"] == 12.0
    assert loaded["technical_snapshot_provider"] == "fixture"


def test_ai_strategy_maps_rows_and_reports_empty_results():
    from app.discover.ai_strategy import run_ai_scanner_strategy

    class FakeConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeScanner:
        def __init__(self, config):
            self.config = config

        def scan(self):
            return pd.DataFrame(
                [
                    {"code": "", "name": "无代码"},
                    {"code": "1", "name": "一号股份", "price": 8.8},
                ]
            )

    frame = run_ai_scanner_strategy(
        {"topKSectors": 1, "maxStocks": 2, "lookbackDays": 90},
        top_n=2,
        scanner_cls=FakeScanner,
        config_cls=FakeConfig,
    )

    assert frame.iloc[0]["股票代码"] == "000001"
    assert frame.iloc[0]["reason"]

    class EmptyScanner:
        def __init__(self, config):
            self.config = config

        def scan(self):
            return pd.DataFrame()

    try:
        run_ai_scanner_strategy({}, top_n=1, scanner_cls=EmptyScanner, config_cls=FakeConfig)
    except RuntimeError as exc:
        assert "候选股票" in str(exc) or "selected stocks" in str(exc)
    else:
        raise AssertionError("empty scanner result must raise")


def test_discovery_task_hydrates_before_lifecycle_ingest_and_api_readback(tmp_path, monkeypatch):
    from app.stock_refresh_scheduler import save_stock_runtime_entries

    context = UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=tmp_path / "selector_results",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        quant_sim_replay_db_file=tmp_path / "quant_sim_replay.db",
    )
    context.quant_db().update_quant_universe_settings({"auto_entry_mode": "auto_trial"})

    class FakeLowPriceBullSelector:
        def get_low_price_stocks(self, top_n=5):
            return True, pd.DataFrame(
                [
                    {
                        "股票代码": "600010",
                        "股票简称": "水位测试",
                        "所属行业": "测试行业",
                        "最新价": 10.0,
                        "成交额": 88_000_000,
                    }
                ]
            ), "ok"

    def fake_refresh(ctx):
        save_stock_runtime_entries(
            {
                "600010": {
                    "stock_code": "600010",
                    "stock_name": "水位测试",
                    "sector": "测试行业",
                    "latest_price": 12.34,
                    **_ready_snapshot("600010"),
                }
            },
            base_dir=ctx.selector_result_dir,
            updated_at="2026-05-16T02:01:00Z",
        )
        return {"reason": "discover", "updated": 1, "failed": 0, "totalCodes": 1}

    monkeypatch.setattr(discover_gateway, "_selector_cls", lambda name: FakeLowPriceBullSelector)
    monkeypatch.setattr(discover_gateway, "_run_discovery_refresh", fake_refresh)
    client = TestClient(create_app(context=context))

    response = client.post(
        "/api/v1/discover/actions/run-strategy",
        json={"strategies": ["low_price_bull"], "waitMs": 5000},
    )

    assert response.status_code == 200
    task_id = response.json()["taskId"]
    task_payload = client.get(f"/api/v1/tasks/{task_id}").json()
    assert task_payload["result"]["technicalSnapshotPreparation"]["complete"] == 1
    assert task_payload["result"]["stockRefresh"]["updated"] == 1

    discover_payload = client.get("/api/v1/discover", params={"pageSize": 20}).json()
    row = {item["code"]: item for item in discover_payload["candidateTable"]["rows"]}["600010"]
    assert row["discoveryRunId"] == task_id
    assert row["discoveryArtifactStatus"] == "current"
    assert row["technical_snapshot_ready"] is True
    assert row["technical_snapshot_status"] == "ready"
    assert row["ma20"] == 12.0
    assert row["trend"] == "up"
    assert row["technical_confirmation_count"] >= 3
    evidence = row["preparedEvidence"]
    assert evidence["id"].startswith(f"{task_id}:600010:")
    assert evidence["runId"] == task_id
    assert evidence["stockCode"] == "600010"
    assert evidence["status"] == "ready"
    assert evidence["technicalSnapshot"]["status"] == "ready"
    assert evidence["quantTechnical"]["candidateScore"] > 0
    assert evidence["quantTechnical"]["candidateConfidence"] > 0
    assert evidence["scoreSemantics"]["sourceScore"] == "discovery_source_audit_only"
    assert evidence["scoreSemantics"]["candidateScore"] == "quant_technical_entry_score"

    events = context.quant_db().list_candidate_events(stock_code="600010", source_type="discover", limit=5)
    assert events
    payload = events[0]["payload_json"]
    assert payload["technical_snapshot_status"] == "ready"
    assert payload["ma20"] == 12.0
    assert payload["trend"] == "up"
    assert payload["prepared_evidence"]["id"] == evidence["id"]
    assert payload["score_semantics"]["candidate_score"] == "quant_technical_entry_score"


def test_refresh_reevaluates_data_blocked_discovery_candidate(tmp_path):
    from app.discover.candidate_artifact import save_discovery_candidate_artifact
    from app.quant_sim.candidate_re_evaluation import reevaluate_refreshed_discovery_candidates
    from app.stock_refresh_scheduler import save_stock_runtime_entries

    context = UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=tmp_path / "selector_results",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        quant_sim_replay_db_file=tmp_path / "quant_sim_replay.db",
    )
    context.quant_db().update_quant_universe_settings({"auto_entry_mode": "auto_trial"})
    save_discovery_candidate_artifact(
        [
            {
                "id": "600020",
                "code": "600020",
                "name": "重评股份",
                "strategyKey": "low_price_bull",
                "strategyName": "低价擒牛",
                "source": "低价擒牛",
            }
        ],
        run_id="discover-refresh-reeval",
        selected_at="2026-05-16 10:00:00",
        base_dir=context.selector_result_dir,
    )
    context.quant_db().add_candidate_event(
        {
            "stock_code": "600020",
            "stock_name": "重评股份",
            "source_type": "discover",
            "source_key": "low_price_bull",
            "source_score": 0,
            "confidence": 0,
            "trend": "neutral",
            "reason_text": "缺少技术快照",
            "status": "blocked",
            "payload": {
                "technical_snapshot_status": "stale_unprepared",
                "entry_gate": {
                    "passed": False,
                    "status": "blocked",
                    "reason_code": "missing_technical_snapshot",
                },
            },
        }
    )
    save_stock_runtime_entries(
        {
            "600020": {
                "stock_code": "600020",
                "stock_name": "重评股份",
                "sector": "测试行业",
                "latest_price": 9.8,
                **_ready_snapshot("600020"),
            }
        },
        base_dir=context.selector_result_dir,
        updated_at="2026-05-16T02:01:00Z",
    )

    summary = reevaluate_refreshed_discovery_candidates(context, run_reason="unit")

    assert summary["attempted"] == 1
    assert summary["reEvaluated"] == 1
    events = context.quant_db().list_candidate_events(stock_code="600020", source_type="discover", limit=5)
    latest_payload = events[0]["payload_json"]
    assert latest_payload["technical_snapshot_status"] == "ready"
    assert latest_payload["prepared_evidence"]["status"] == "ready"
    assert latest_payload["candidate_score"] > 0
    assert latest_payload["candidate_confidence"] > 0
    assert latest_payload["refresh_re_evaluation"]["run_reason"] == "unit"
    assert latest_payload["prepared_evidence"]["refresh"]["lastReevaluation"]["run_reason"] == "unit"


def test_discovery_task_artifact_only_uses_completed_strategies(tmp_path, monkeypatch):
    from app.discover.candidate_artifact import load_discovery_candidate_artifact
    from app.selector_ui_state import save_simple_selector_state
    from app.stock_refresh_scheduler import save_stock_runtime_entries

    context = UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=tmp_path / "selector_results",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        quant_sim_replay_db_file=tmp_path / "quant_sim_replay.db",
    )
    save_simple_selector_state(
        "ai_scanner",
        pd.DataFrame([{"股票代码": "000066", "股票简称": "历史AI缓存"}]),
        "2026-05-15 10:00:00",
        base_dir=context.selector_result_dir,
    )

    class FakeLowPriceBullSelector:
        def get_low_price_stocks(self, top_n=5):
            return True, pd.DataFrame([{"股票代码": "600011", "股票简称": "本次低价股"}]), "ok"

    def fake_refresh(ctx):
        save_stock_runtime_entries(
            {"600011": {"stock_code": "600011", "stock_name": "本次低价股", **_ready_snapshot("600011")}},
            base_dir=ctx.selector_result_dir,
            updated_at="2026-05-16T02:01:00Z",
        )
        return {"reason": "discover", "updated": 1, "failed": 0, "totalCodes": 1}

    monkeypatch.setattr(discover_gateway, "_selector_cls", lambda name: FakeLowPriceBullSelector)
    monkeypatch.setattr(discover_gateway, "_run_discovery_refresh", fake_refresh)
    client = TestClient(create_app(context=context))

    response = client.post(
        "/api/v1/discover/actions/run-strategy",
        json={"strategies": ["low_price_bull"], "waitMs": 5000},
    )

    assert response.status_code == 200
    artifact = load_discovery_candidate_artifact(base_dir=context.selector_result_dir)
    assert [row["code"] for row in artifact["rows"]] == ["600011"]

    payload = client.get("/api/v1/discover", params={"pageSize": 20}).json()
    codes = [row["code"] for row in payload["candidateTable"]["rows"]]
    assert codes == ["600011"]


def test_discover_api_marks_raw_selector_fallback_stale(tmp_path):
    from app.selector_ui_state import save_simple_selector_state

    context = UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=tmp_path / "selector_results",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        quant_sim_replay_db_file=tmp_path / "quant_sim_replay.db",
    )
    save_simple_selector_state(
        "low_price_bull",
        pd.DataFrame([{"股票代码": "600012", "股票简称": "旧缓存"}]),
        "2026-05-16 10:00:00",
        base_dir=context.selector_result_dir,
    )
    client = TestClient(create_app(context=context))

    payload = client.get("/api/v1/discover", params={"pageSize": 20}).json()
    row = {item["code"]: item for item in payload["candidateTable"]["rows"]}["600012"]

    assert row["discoveryArtifactStatus"] == "stale_unprepared"
    assert row["technical_snapshot_ready"] is False
    assert row["technical_snapshot_status"] == "stale_unprepared"
    assert row["blocking_reason"] == "missing_technical_snapshot"
