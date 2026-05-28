from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.gateway_api as gateway_api
from app.gateway_api import UIApiContext, create_app
from app.quant_sim.market_technical_artifact import MarketTechnicalArtifactRef
from app.selector_result_store import save_latest_result
from app.stock_refresh_artifact_writer import StockRefreshArtifactRequest, write_live_artifacts
from app.stock_refresh_scheduler import save_stock_runtime_entries


class _NoopScheduler:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _disable_background_schedulers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gateway_api, "get_unified_stock_refresh_scheduler", lambda context: _NoopScheduler())
    monkeypatch.setattr(gateway_api, "get_stock_analysis_daily_scheduler", lambda context: _NoopScheduler())


def _context(tmp_path: Path) -> UIApiContext:
    return UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=tmp_path / "selector_results",
        quant_sim_db_file=tmp_path / "quant_sim.db",
        quant_sim_replay_db_file=tmp_path / "quant_sim_replay.db",
        monitor_db_file=tmp_path / "stock_monitor.db",
        smart_monitor_db_file=tmp_path / "smart_monitor.db",
    )


def _entry(code: str, *, price: float, name: str = "浦发银行", sector: str = "银行") -> dict[str, Any]:
    return {
        "stock_code": code,
        "stock_name": name,
        "sector": sector,
        "latest_price": price,
        "open": price - 0.2,
        "high": price + 0.3,
        "low": price - 0.4,
        "close": price,
        "amount": 120_000_000.0,
        "volume": 10_000_000.0,
        "volume_ratio": 1.5,
        "ma5": price - 0.1,
        "ma10": price - 0.2,
        "ma20": price - 0.5,
        "ma60": price - 1.0,
        "ma20_slope": 0.02,
        "rsi": 58.0,
        "macd": 0.12,
        "trend": "up",
        "technical_snapshot_ready": True,
        "technical_snapshot_status": "ready",
        "technical_snapshot_timeframe": "30m",
        "technical_snapshot_provider": "fixture",
        "technical_snapshot_indicator_version": "mta-test",
        "technical_snapshot_at": "2026-01-05 10:00:00",
    }


def _seed_live_artifact(context: UIApiContext, code: str = "600000", *, price: float = 12.34) -> dict[str, Any]:
    projection = write_live_artifacts(
        StockRefreshArtifactRequest(
            db_file=context.quant_sim_db_file,
            entries={code: _entry(code, price=price)},
        )
    )[code]
    save_stock_runtime_entries(
        {code: {**projection, "latest_price": 999.0}},
        base_dir=context.selector_result_dir,
        updated_at="2026-01-05T02:00:10Z",
    )
    return projection


def _row(rows: list[dict[str, Any]], code: str) -> dict[str, Any]:
    return next(item for item in rows if item.get("code") == code or item.get("id") == code)


def test_workbench_watchlist_uses_artifact_projection_and_reports_missing(tmp_path):
    context = _context(tmp_path)
    projection = _seed_live_artifact(context, price=12.34)
    db = context.quant_db()
    db.add_watch(stock_code="600000", stock_name="旧名称", source="manual", latest_price=888.0)
    db.add_watch(stock_code="600001", stock_name="缺失样本", source="manual", latest_price=777.0)

    with TestClient(create_app(context=context)) as client:
        payload = client.get("/api/v1/workbench").json()

    backed = _row(payload["watchlist"]["rows"], "600000")
    missing = _row(payload["watchlist"]["rows"], "600001")
    assert backed["latestPrice"] == "12.34"
    assert backed["artifactDiagnostics"]["artifact_ref"] == projection["artifact_ref"]
    assert backed["marketTechnicalBacked"] is True
    assert missing.get("latestPrice") == "--"
    assert missing["cells"][2] == "--"
    assert missing["artifactDiagnostics"]["reason_code"] == "missing_artifact_reference"
    assert missing["marketTechnicalBacked"] is False


def test_discover_and_research_rows_use_artifact_projection(tmp_path):
    context = _context(tmp_path)
    projection = _seed_live_artifact(context, price=13.21)
    save_latest_result(
        "discovery_candidate_artifact",
        {"rows": [{"code": "600000", "name": "浦发银行", "source": "fixture", "latestPrice": "999.00"}]},
        base_dir=context.selector_result_dir,
    )
    save_latest_result(
        context.research_result_key,
        {
            "outputTable": {
                "rows": [{"code": "600000", "name": "浦发银行", "source": "研究", "latestPrice": "999.00"}]
            }
        },
        base_dir=context.selector_result_dir,
    )

    with TestClient(create_app(context=context)) as client:
        discover = client.get("/api/v1/discover").json()
        research = client.get("/api/v1/research").json()

    discover_row = _row(discover["candidateTable"]["rows"], "600000")
    research_row = _row(research["outputTable"]["rows"], "600000")
    assert discover_row["latestPrice"] == "13.21"
    assert discover_row["artifactDiagnostics"]["artifact_ref"] == projection["artifact_ref"]
    assert research_row["latestPrice"] == "13.21"
    assert research_row["artifactDiagnostics"]["reason_code"] == "ok"


def test_live_quant_candidate_rows_use_candidate_artifact_reference(tmp_path):
    context = _context(tmp_path)
    projection = _seed_live_artifact(context, price=14.56)
    context.candidate_pool().add_candidate(
        stock_code="600000",
        stock_name="浦发银行",
        source="fixture",
        latest_price=999.0,
        status="active",
    )
    context.quant_db().add_candidate_event(
        {
            "stock_code": "600000",
            "source_type": "discover",
            "source_key": "fixture",
            "payload_json": {"artifact_ref": projection["artifact_ref"]},
            "source_score": 0.0,
            "confidence": 0.0,
            "trend": "up",
        }
    )

    with TestClient(create_app(context=context)) as client:
        payload = client.get("/api/v1/quant/live-sim").json()

    row = _row(payload["candidatePool"]["rows"], "600000")
    assert row["latestPrice"] == "14.56"
    assert row["artifactDiagnostics"]["artifact_ref"] == projection["artifact_ref"]
    assert row["lifecycle"]["artifactDiagnostics"]["reason_code"] == "ok"


def test_live_quant_candidate_rows_can_use_runtime_artifact_projection(tmp_path):
    context = _context(tmp_path)
    projection = _seed_live_artifact(context, price=15.67)
    context.candidate_pool().add_candidate(
        stock_code="600000",
        stock_name="浦发银行",
        source="fixture",
        latest_price=999.0,
        status="active",
    )

    with TestClient(create_app(context=context)) as client:
        payload = client.get("/api/v1/quant/live-sim").json()

    row = _row(payload["candidatePool"]["rows"], "600000")
    assert row["latestPrice"] == "15.67"
    assert row["artifactDiagnostics"]["artifact_ref"] == projection["artifact_ref"]
    assert row["marketTechnicalBacked"] is True


def test_quant_universe_state_reads_artifact_store_diagnostics(tmp_path):
    context = _context(tmp_path)
    projection = _seed_live_artifact(context, price=16.78)
    db = context.quant_db()
    db.upsert_quant_universe_state("600000", {"quant_status": "trial", "health_score": 80})
    db.add_candidate_event(
        {
            "stock_code": "600000",
            "source_type": "discover",
            "source_key": "fixture",
            "payload_json": {
                "artifact_ref": projection["artifact_ref"],
                "source_status": "stale",
                "reason_code": "stale_artifact",
            },
            "source_score": 0.0,
            "confidence": 0.0,
            "trend": "up",
        }
    )

    with TestClient(create_app(context=context)) as client:
        payload = client.get("/api/v1/quant/universe/state?status=trial").json()

    row = payload["items"][0]
    assert row["artifactDiagnostics"]["artifact_ref"] == projection["artifact_ref"]
    assert row["artifactDiagnostics"]["source_status"] == "ready"
    assert row["artifactDiagnostics"]["reason_code"] == "ok"


def test_page_projection_rejects_non_live_refs(tmp_path):
    context = _context(tmp_path)
    replay_ref = MarketTechnicalArtifactRef(
        domain="replay",
        run_id="1",
        run_type="historical_replay",
        stock_code="600000",
        market="CN",
        checkpoint_at="2026-01-05T02:00:00Z",
        timeframe="30m",
    ).to_ref()
    save_stock_runtime_entries(
        {"600000": {"stock_code": "600000", "stock_name": "浦发银行", "artifact_ref": replay_ref}},
        base_dir=context.selector_result_dir,
        updated_at="2026-01-05T02:00:10Z",
    )
    context.quant_db().add_watch(stock_code="600000", stock_name="浦发银行", source="manual")

    with TestClient(create_app(context=context)) as client:
        payload = client.get("/api/v1/workbench").json()

    row = _row(payload["watchlist"]["rows"], "600000")
    assert row["artifactDiagnostics"]["reason_code"] == "invalid_artifact_ref"
    assert row["marketTechnicalBacked"] is False
