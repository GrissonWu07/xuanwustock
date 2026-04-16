from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_API_PATH = PROJECT_ROOT / "app" / "gateway.py"


def _load_backend_api_module():
    spec = importlib.util.spec_from_file_location("build_backend_api", BACKEND_API_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backend_api_exposes_fastapi_app_and_health_routes():
    module = _load_backend_api_module()
    assert hasattr(module, "create_app")

    app = module.create_app()
    client = TestClient(app)

    health = client.get("/api/health")
    assert health.status_code == 200
    payload = health.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "xuanwu-api"

    root = client.get("/health")
    assert root.status_code == 200
    assert root.json()["status"] == "ok"


def test_backend_api_serves_spa_entry_for_root_and_client_routes():
    module = _load_backend_api_module()
    app = module.create_app()
    client = TestClient(app)

    for route in ("/", "/main", "/discover", "/live-sim"):
        response = client.get(route)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "玄武AI智能体股票团队分析系统" in response.text


@pytest.mark.parametrize(
    "page_path, expected_keys",
    [
        ("/api/v1/workbench", {"updatedAt", "metrics", "watchlist", "watchlistMeta", "analysis", "nextSteps", "activity"}),
        ("/api/v1/discover", {"updatedAt", "metrics", "strategies", "summary", "candidateTable", "recommendation"}),
        ("/api/v1/research", {"updatedAt", "modules", "marketView", "outputTable", "summary"}),
        ("/api/v1/portfolio", {"updatedAt", "metrics", "holdings", "attribution", "curve", "actions"}),
        ("/api/v1/quant/live-sim", {"updatedAt", "config", "status", "metrics", "candidatePool", "pendingSignals", "executionCenter", "holdings", "trades", "curve"}),
        ("/api/v1/quant/his-replay", {"updatedAt", "config", "metrics", "candidatePool", "tasks", "tradingAnalysis", "holdings", "trades", "signals", "curve"}),
        ("/api/v1/monitor/ai", {"updatedAt", "metrics", "queue", "signals", "timeline"}),
        ("/api/v1/monitor/real", {"updatedAt", "metrics", "rules", "triggers", "notificationStatus"}),
        ("/api/v1/history", {"updatedAt", "metrics", "records", "recentReplay", "timeline"}),
        ("/api/v1/settings", {"dataSources", "runtimeParams"}),
    ],
)
def test_backend_api_exposes_page_snapshots(page_path: str, expected_keys: set[str]):
    module = _load_backend_api_module()
    app = module.create_app()
    client = TestClient(app)

    response = client.get(page_path)
    assert response.status_code == 200
    payload = response.json()
    assert expected_keys.issubset(payload.keys())
    if "updatedAt" in expected_keys:
        assert isinstance(payload["updatedAt"], str) and payload["updatedAt"].strip()


def test_workbench_analysis_contract_includes_decision_and_analyst_sections():
    module = _load_backend_api_module()
    app = module.create_app()
    client = TestClient(app)

    response = client.get("/api/v1/workbench")
    assert response.status_code == 200
    analysis = response.json()["analysis"]
    assert "finalDecisionText" in analysis
    assert "analystViews" in analysis

