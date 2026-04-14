# Remove Streamlit Mainline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Streamlit from the product runtime and code mainline so the system runs only as `gateway + SPA` on one port while preserving current business logic and data flow.

**Architecture:** Keep all selector, research, watchlist, quant, monitor, and persistence services in `app/` unchanged where possible, but delete Streamlit-only rendering modules and helpers. The Python runtime becomes a single FastAPI gateway that serves both `/api/*` and the built SPA on `8501`; the React frontend in `ui/` remains the only UI. Docker keeps `build/` for container assets only and can still split nginx/frontend from backend, but the backend container exposes the same `8501` gateway.

**Tech Stack:** Python 3.13, FastAPI, uvicorn, React, Vite, TypeScript, pytest, vitest, SQLite, Docker, nginx.

---

## File Structure / Ownership

### Runtime and backend
- Keep: `app/gateway.py` — single Python runtime entry
- Keep: `app/gateway_api.py` — FastAPI app factory, snapshot routes, action routes, SPA fallback
- Keep: service/data modules under `app/` that do not depend on Streamlit
- Remove or replace: Streamlit-only modules in `app/` (`*_ui.py`, `streamlit_flash.py`, `stm.py`, old `app/app.py` behavior)
- Keep thin root entrypoints: `app.py`, `run.py`

### Frontend
- Keep and extend: `ui/src/**`
- Ensure every page route is complete and owns the user interaction that used to live in Streamlit

### Docs and tests
- Update: `README.md`, `docs/QUICK_START.md`, `ui/README.md`, Docker docs
- Update/remove Streamlit-specific tests, replace with gateway/runtime assertions

---

### Task 1: Lock the single-service runtime contract

**Files:**
- Modify: `tests/test_ui_backend_api_contract.py`
- Modify: `tests/test_docker_build_layout.py`
- Modify: `tests/test_ui_layout_docs.py`

- [ ] **Step 1: Write/adjust failing tests for the runtime contract**
- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Implement minimal config/doc/runtime changes**
- [ ] **Step 4: Run tests to verify they pass**

### Task 2: Remove Streamlit from runtime entrypoints and dependencies

**Files:**
- Modify: `app.py`
- Modify: `run.py`
- Modify: `app/run.py`
- Modify: `requirements.txt`
- Test: `tests/test_runtime_db_paths.py`

- [ ] **Step 1: Write the failing test**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Write minimal implementation**
- [ ] **Step 4: Run test to verify it passes**

### Task 3: Delete Streamlit-only UI modules from `app/`

**Files:**
- Delete: `app/app.py`
- Delete: `app/discovery_hub_ui.py`
- Delete: `app/research_hub_ui.py`
- Delete: `app/watchlist_ui.py`
- Delete: `app/portfolio_ui.py`
- Delete: `app/monitor_ui.py`
- Delete: `app/smart_monitor_ui.py`
- Delete: `app/longhubang_ui.py`
- Delete: `app/news_flow_ui.py`
- Delete: `app/macro_analysis_ui.py`
- Delete: `app/macro_cycle_ui.py`
- Delete: `app/sector_strategy_ui.py`
- Delete: `app/main_force_ui.py`
- Delete: `app/main_force_history_ui.py`
- Delete: `app/low_price_bull_ui.py`
- Delete: `app/low_price_bull_monitor_ui.py`
- Delete: `app/profit_growth_ui.py`
- Delete: `app/small_cap_ui.py`
- Delete: `app/value_stock_ui.py`
- Delete: `app/quant_sim/ui.py`
- Delete: `app/streamlit_flash.py`
- Delete: `app/stm.py`
- Create: `tests/test_streamlit_removal.py`

- [ ] **Step 1: Write the failing test**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Write minimal implementation**
- [ ] **Step 4: Run test to verify it passes**

### Task 4: Replace Streamlit-based tests with gateway/service tests

**Files:**
- Delete: `tests/test_streamlit_flash.py`
- Modify/Delete Streamlit UI tests that depend on deleted modules
- Expand API/dataflow tests in:
  - `tests/test_ui_backend_api_actions.py`
  - `tests/test_ui_backend_api_contract.py`
  - `tests/test_ui_backend_api_dataflow.py`

- [ ] **Step 1: Write failing test updates**
- [ ] **Step 2: Run tests to verify failures**
- [ ] **Step 3: Write minimal implementation**
- [ ] **Step 4: Run tests to verify they pass**

### Task 5: Make every frontend route fully driven by gateway data/actions

**Files:**
- Modify: `ui/src/routes/manifest.tsx`
- Modify: `ui/src/lib/api-client.ts`
- Modify: `ui/src/lib/page-models.ts`
- Modify: all page feature files under `ui/src/features/**`
- Test: `ui/src/tests/**`

- [ ] **Step 1: Write/adjust failing frontend tests**
- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Write minimal implementation**
- [ ] **Step 4: Run tests to verify they pass**

### Task 6: Sweep current docs so the active product no longer describes Streamlit

**Files:**
- Modify: `README.md`
- Modify: `ui/README.md`
- Modify: `docs/README.md`
- Modify: `docs/QUICK_START.md`
- Modify: `docs/前端页面与交互清单.md`
- Modify: `docs/后端能力与服务接口清单.md`
- Modify: `docs/工作流与数据流说明.md`
- Modify: current Docker docs under `docs/DOCKER*.md`

- [ ] **Step 1: Write failing doc assertions**
- [ ] **Step 2: Run tests to verify they fail**
- [ ] **Step 3: Write minimal implementation**
- [ ] **Step 4: Run tests to verify they pass**

### Task 7: Full-system verification and cleanup

**Files:**
- Modify: `.gitignore` if needed

- [ ] **Step 1: Run backend verification**
- [ ] **Step 2: Run frontend verification**
- [ ] **Step 3: Run import/compile verification**
- [ ] **Step 4: Run live runtime verification**
- [ ] **Step 5: Commit**
