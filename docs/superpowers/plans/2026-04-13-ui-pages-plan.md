# REUI Full-Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a complete REUI single-page workbench with real Python-backed page snapshots/actions for every route, complete page implementations, independent frontend deployment, and end-to-end verified workflows.

**Architecture:** Add a real FastAPI-based UI backend in Python that exposes one snapshot endpoint and one action surface per REUI route. Keep existing Python business logic and SQLite persistence as the source of truth. The React/Vite frontend must consume only those live endpoints and fully implement every route: `/main`, `/discover`, `/research`, `/portfolio`, `/live-sim`, `/his-replay`, `/ai-monitor`, `/real-monitor`, `/history`, and `/settings`.

**Tech Stack:** Python 3.13, FastAPI, Uvicorn, React 19, TypeScript, Vite, React Router, Tailwind CSS, Vitest, Testing Library, nginx, Docker Compose.

---

### Task 1: Build the real REUI backend API contract

**Files:**
- Create: `app/gateway_api.py`
- Create: `app/reui_snapshots.py`
- Create: `app/reui_actions.py`
- Create: `tests/test_ui_backend_api_contract.py`
- Create: `tests/test_ui_backend_api_actions.py`
- Modify: `app/selector_result_store.py`
- Modify: `build/backend_api.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Write the failing backend snapshot tests**

```python
from fastapi.testclient import TestClient

from app.gateway_api import create_app


def test_reui_snapshot_endpoints_return_all_pages():
    app = create_reui_app()
    client = TestClient(app)

    routes = [
        "/api/v1/workbench",
        "/api/v1/discover",
        "/api/v1/research",
        "/api/v1/portfolio",
        "/api/v1/live-sim",
        "/api/v1/his-replay",
        "/api/v1/ai-monitor",
        "/api/v1/real-monitor",
        "/api/v1/history",
        "/api/v1/settings",
    ]

    for route in routes:
        response = client.get(route)
        assert response.status_code == 200, route
        payload = response.json()
        assert payload
```

```python
def test_reui_health_endpoint_survives_backend_api_upgrade():
    app = create_reui_app()
    client = TestClient(app)

    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_ui_backend_api_contract.py`

Expected: FAIL because the real API app and routes do not exist yet.

- [ ] **Step 3: Implement the FastAPI app and snapshot builders**

```python
# app/gateway_api.py
from fastapi import FastAPI

from app.reui_actions import register_reui_action_routes
from app.reui_snapshots import register_reui_snapshot_routes


def create_reui_app() -> FastAPI:
    app = FastAPI(title="玄武AI智能体股票团队分析系统 API")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "xuanwu-api"}

    register_reui_snapshot_routes(app)
    register_reui_action_routes(app)
    return app
```

```python
# build/backend_api.py
from app.gateway_api import create_app

app = create_reui_app()

if __name__ == "__main__":
    import os
    import uvicorn

    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8503")))
```

- [ ] **Step 4: Add action tests before implementing actions**

```python
def test_workbench_add_watchlist_action_returns_updated_snapshot():
    app = create_reui_app()
    client = TestClient(app)

    response = client.post("/api/v1/workbench/actions/add-watchlist", json={"stockCode": "600519"})
    assert response.status_code == 200
    payload = response.json()
    rows = payload["watchlist"]["rows"]
    assert any(row["id"] == "600519" for row in rows)
```

```python
def test_live_sim_start_action_returns_updated_status_snapshot():
    app = create_reui_app()
    client = TestClient(app)

    response = client.post("/api/v1/quant/live-sim/actions/start", json={})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"]["running"] is True
```

- [ ] **Step 5: Run the action tests and verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_ui_backend_api_actions.py`

Expected: FAIL because the action routes are not implemented yet.

- [ ] **Step 6: Implement action routes against current services**

```python
# app/reui_actions.py
# Register POST routes for:
# /api/v1/workbench/actions/*
# /api/v1/discover/actions/*
# /api/v1/research/actions/*
# /api/v1/portfolio/actions/*
# /api/v1/quant/live-sim/actions/*
# /api/v1/quant/his-replay/actions/*
# /api/v1/monitor/ai/actions/*
# /api/v1/monitor/real/actions/*
# /api/v1/history/actions/*
# /api/v1/settings/actions/save
#
# Every action must:
# 1. call existing business logic
# 2. return the full updated page snapshot
```

- [ ] **Step 7: Run backend tests and verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_ui_backend_api_contract.py tests/test_ui_backend_api_actions.py`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/gateway_api.py app/selector_result_store.py app/gateway.py requirements.txt tests/test_ui_backend_api_contract.py tests/test_ui_backend_api_actions.py
git commit -m "feat: add real reui backend api"
```

### Task 2: Complete `/main`, `/discover`, and `/research` with live API semantics

**Files:**
- Modify: `ui/src/lib/api-client.ts`
- Modify: `ui/src/lib/page-models.ts`
- Modify: `ui/src/features/workbench/workbench-page.tsx`
- Modify: `ui/src/features/workbench/watchlist-panel.tsx`
- Modify: `ui/src/features/workbench/stock-analysis-panel.tsx`
- Modify: `ui/src/features/workbench/next-steps-panel.tsx`
- Modify: `ui/src/features/discover/discover-page.tsx`
- Modify: `ui/src/features/research/research-page.tsx`
- Create: `ui/src/tests/reui-main-discover-research.test.tsx`

- [ ] **Step 1: Write the failing page tests**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createApiClient } from "../lib/api-client";
import { WorkbenchPage } from "../features/workbench/workbench-page";
import { DiscoverPage } from "../features/discover/discover-page";
import { ResearchPage } from "../features/research/research-page";

it("renders the workbench with watchlist, analysis module, and next-step navigation", async () => {
  const client = createApiClient({ mode: "live" });
  render(<WorkbenchPage client={client} />);
  expect(await screen.findByText("我的关注")).toBeInTheDocument();
  expect(screen.getByText("股票分析")).toBeInTheDocument();
  expect(screen.getByText("下一步")).toBeInTheDocument();
});
```

```tsx
it("renders discover and research pages from live snapshots", async () => {
  const client = createApiClient({ mode: "live" });
  render(<DiscoverPage client={client} />);
  expect(await screen.findByText("发现股票")).toBeInTheDocument();
  render(<ResearchPage client={client} />);
  expect(await screen.findByText("研究情报")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd ui && npm test -- --runInBand src/tests/reui-main-discover-research.test.tsx`

Expected: FAIL because the pages still depend on hybrid/mock assumptions or incomplete live semantics.

- [ ] **Step 3: Implement the complete workbench flow**

```tsx
// ui/src/features/workbench/workbench-page.tsx
// Keep the workbench single-page structure:
// summary cards -> 我的关注 -> 股票分析 -> 下一步
// Use only live snapshots/actions when mode is live.
```

```tsx
// ui/src/features/workbench/watchlist-panel.tsx
// Support:
// - add by stock code
// - refresh quotes
// - row selection
// - batch add to quant pool
// - delete from watchlist
// - bring selected stock into the stock-analysis module
```

```tsx
// ui/src/features/discover/discover-page.tsx
// Render all selector sections completely.
// Candidate tables must support row selection and add-to-watchlist actions.
```

```tsx
// ui/src/features/research/research-page.tsx
// Render all research/intelligence sections completely.
// Modules with stock outputs must support add-to-watchlist actions.
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd ui && npm test -- --runInBand src/tests/reui-main-discover-research.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/api-client.ts ui/src/lib/page-models.ts ui/src/features/workbench/workbench-page.tsx ui/src/features/workbench/watchlist-panel.tsx ui/src/features/workbench/stock-analysis-panel.tsx ui/src/features/workbench/next-steps-panel.tsx ui/src/features/discover/discover-page.tsx ui/src/features/research/research-page.tsx ui/src/tests/reui-main-discover-research.test.tsx
git commit -m "feat: complete reui workbench discover and research pages"
```

### Task 3: Complete `/portfolio`, `/live-sim`, and `/his-replay`

**Files:**
- Modify: `ui/src/features/portfolio/portfolio-page.tsx`
- Modify: `ui/src/features/quant/live-sim-page.tsx`
- Modify: `ui/src/features/quant/his-replay-page.tsx`
- Modify: `ui/src/components/ui/strategy-narrative.tsx`
- Create: `ui/src/tests/reui-portfolio-quant.test.tsx`

- [ ] **Step 1: Write the failing render and action tests**

```tsx
it("renders portfolio with metrics, holdings and actions", async () => {
  const client = createApiClient({ mode: "live" });
  render(<PortfolioPage client={client} />);
  expect(await screen.findByText("当前持仓")).toBeInTheDocument();
  expect(screen.getByText("收益归因")).toBeInTheDocument();
});
```

```tsx
it("renders live simulation with config, candidate pool, execution center and account results", async () => {
  const client = createApiClient({ mode: "live" });
  render(<LiveSimPage client={client} />);
  expect(await screen.findByText("定时任务配置")).toBeInTheDocument();
  expect(screen.getByText("候选池")).toBeInTheDocument();
  expect(screen.getByText("账户结果")).toBeInTheDocument();
});
```

```tsx
it("renders historical replay with candidate pool, tasks, results and signals", async () => {
  const client = createApiClient({ mode: "live" });
  render(<HisReplayPage client={client} />);
  expect(await screen.findByText("历史回放")).toBeInTheDocument();
  expect(screen.getByText("量化候选池")).toBeInTheDocument();
  expect(screen.getByText("回放结果")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd ui && npm test -- --runInBand src/tests/reui-portfolio-quant.test.tsx`

Expected: FAIL because the current pages are not fully aligned with the live API and complete action set.

- [ ] **Step 3: Implement complete pages**

```tsx
// ui/src/features/portfolio/portfolio-page.tsx
// Complete page with holdings list, latest analyses, attribution, equity curve,
// refresh, analyze, and scheduler controls.
```

```tsx
// ui/src/features/quant/live-sim-page.tsx
// Complete page with:
// - left-side task config and running status
// - right-side account summary, holdings, trades, curve
// - candidate pool with row actions
// - pending signal list with explanations and execution notes
```

```tsx
// ui/src/features/quant/his-replay-page.tsx
// Complete page with:
// - left-side replay config, run status, shared candidate pool
// - right-side task selection, metrics, trading analysis, holdings, trades, signals, curve
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd ui && npm test -- --runInBand src/tests/reui-portfolio-quant.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src/features/portfolio/portfolio-page.tsx ui/src/features/quant/live-sim-page.tsx ui/src/features/quant/his-replay-page.tsx ui/src/components/ui/strategy-narrative.tsx ui/src/tests/reui-portfolio-quant.test.tsx
git commit -m "feat: complete reui portfolio and quant pages"
```

### Task 4: Complete `/ai-monitor`, `/real-monitor`, `/history`, and `/settings`

**Files:**
- Modify: `ui/src/features/monitor/ai-monitor-page.tsx`
- Modify: `ui/src/features/monitor/real-monitor-page.tsx`
- Modify: `ui/src/features/history/history-page.tsx`
- Modify: `ui/src/features/settings/settings-page.tsx`
- Create: `ui/src/tests/reui-monitor-history-settings.test.tsx`

- [ ] **Step 1: Write the failing page tests**

```tsx
it("renders AI monitor with metrics, queue, signals, and timeline", async () => {
  const client = createApiClient({ mode: "live" });
  render(<AiMonitorPage client={client} />);
  expect(await screen.findByText("盯盘队列")).toBeInTheDocument();
  expect(screen.getByText("策略信号")).toBeInTheDocument();
});
```

```tsx
it("renders real monitor with rules, triggers, and notifications", async () => {
  const client = createApiClient({ mode: "live" });
  render(<RealMonitorPage client={client} />);
  expect(await screen.findByText("监控规则")).toBeInTheDocument();
  expect(screen.getByText("触发记录")).toBeInTheDocument();
});
```

```tsx
it("renders history and settings pages with live data", async () => {
  const client = createApiClient({ mode: "live" });
  render(<HistoryPage client={client} />);
  expect(await screen.findByText("分析记录")).toBeInTheDocument();
  render(<SettingsPage client={client} />);
  expect(await screen.findByText("模型配置")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd ui && npm test -- --runInBand src/tests/reui-monitor-history-settings.test.tsx`

Expected: FAIL before live page renderers are complete.

- [ ] **Step 3: Implement the complete pages**

```tsx
// ui/src/features/monitor/ai-monitor-page.tsx
// Complete with summary metrics, monitoring queue, signal cards, action buttons,
// and event timeline.
```

```tsx
// ui/src/features/monitor/real-monitor-page.tsx
// Complete with rules table, trigger history, notification summaries, and action controls.
```

```tsx
// ui/src/features/history/history-page.tsx
// Complete with analysis history, replay summaries, and workflow event timeline.
```

```tsx
// ui/src/features/settings/settings-page.tsx
// Complete with model, data source, runtime, and filesystem settings views.
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd ui && npm test -- --runInBand src/tests/reui-monitor-history-settings.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src/features/monitor/ai-monitor-page.tsx ui/src/features/monitor/real-monitor-page.tsx ui/src/features/history/history-page.tsx ui/src/features/settings/settings-page.tsx ui/src/tests/reui-monitor-history-settings.test.tsx
git commit -m "feat: complete reui monitor history and settings pages"
```

### Task 5: Wire live frontend integration and Docker/nginx deployment

**Files:**
- Modify: `ui/src/lib/api-client.ts`
- Modify: `ui/src/App.tsx`
- Modify: `ui/src/routes/index.tsx`
- Modify: `ui/README.md`
- Modify: `README.md`
- Modify: `build/docker-compose.yml`
- Modify: `build/nginx.conf`
- Modify: `build/Dockerfile.ui`
- Create: `tests/test_reui_layout_docs.py`
- Create: `ui/src/tests/reui-routing-smoke.test.tsx`

- [ ] **Step 1: Write the failing integration tests**

```tsx
it("renders every top-level route inside the single-page shell", async () => {
  // Use MemoryRouter entries for each route and assert page heading appears.
});
```

```python
def test_build_files_route_ui_through_nginx_and_backend_api():
    compose = Path("build/docker-compose.yml").read_text(encoding="utf-8")
    assert "nginx" in compose
    assert "build/Dockerfile.ui" in compose
    assert "/api/health" in compose
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_reui_layout_docs.py`

Run: `cd ui && npm test -- --runInBand src/tests/reui-routing-smoke.test.tsx`

Expected: FAIL until routing and docs are aligned to the final shell.

- [ ] **Step 3: Implement live-mode defaults and deployment wiring**

```ts
// ui/src/lib/api-client.ts
// Keep mock mode available for local isolated frontend work,
// but make production/dev integration default to live or configured mode.
```

```yaml
# build/docker-compose.yml
# Services:
# - backend: python API on 8503
# - frontend: nginx serving ui/dist and proxying /api to backend
```

- [ ] **Step 4: Run full validation**

Run: `python -m pytest -q -p no:cacheprovider tests/test_ui_backend_api_contract.py tests/test_ui_backend_api_actions.py tests/test_ui_layout_docs.py tests/test_watchlist_workflow_e2e.py tests/test_quant_sim_auto_execution.py tests/test_quant_continuous_simulation.py`

Run: `cd ui && npm test`

Run: `cd ui && npm run build`

Run: `python -m compileall app app.py run.py build`

Expected: All commands PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/api-client.ts ui/src/App.tsx ui/src/routes/index.tsx ui/README.md README.md build/docker-compose.yml build/nginx.conf build/Dockerfile.ui tests/test_reui_layout_docs.py ui/src/tests/reui-routing-smoke.test.tsx
git commit -m "feat: wire reui live integration and deployment"
```

