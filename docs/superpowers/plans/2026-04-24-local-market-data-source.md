# Local Market Data Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first Parquet market-data layer for AKShare, TDX, and Tushare, then route supported technical-indicator and strategy data paths through it.

**Architecture:** Add a source-agnostic `LocalMarketDataStore` for Parquet reads/writes and source-specific clients for AKShare, TDX, and Tushare. Existing public APIs keep their return shapes, while local/remote provenance is exposed through `cache_source` and `cache_status`.

**Tech Stack:** Python, pandas, pyarrow Parquet, pytest, Docker Compose.

---

### Task 1: Core Parquet Store

**Files:**
- Create: `app/local_market_data_store.py`
- Test: `tests/test_local_market_data_store.py`

- [x] Write failing tests for Parquet round trip, local range hit, partial merge, realtime TTL, corrupt-file fallback, and source-isolated path building.
- [x] Implement `LocalMarketDataStore` with canonical paths, atomic writes, per-file locks, date filtering, merge/de-duplication, TTL checking, and cache status metadata.
- [x] Run targeted tests.
- [x] Review 1: inspect store API and path generation against spec sections 5-7.
- [x] Review 2: verify tests cover hit/miss/partial/stale/corrupt behavior.
- [x] Review 3: grep for unsafe writes or non-atomic cache persistence.

### Task 2: Local Clients

**Files:**
- Create: `app/local_market_data_clients.py`
- Test: `tests/test_local_market_data_clients.py`

- [x] Write failing tests for AKShare historical local hit, AKShare remote refresh writeback, Tushare source isolation, TDX K-line local hit, TDX quote TTL, and local indicator input conversion.
- [x] Implement source-specific clients for AKShare, Tushare, and TDX.
- [x] Keep remote provider calls inside client methods or existing low-level remote methods only.
- [x] Run targeted tests.
- [x] Review 1: inspect source namespace isolation.
- [x] Review 2: verify local hit avoids remote call.
- [x] Review 3: verify returned `data_source`, `cache_source`, and `cache_status` compatibility.

### Task 3: Production Integration

**Files:**
- Modify: `app/data_source_manager.py`
- Modify: `app/smart_monitor_tdx_data.py`
- Modify: `app/stock_data.py`
- Modify: `app/smart_monitor_data.py`
- Modify: `app/value_stock_strategy.py`
- Modify: `app/low_price_bull_service.py`
- Test: existing provider and quant tests.

- [x] Add local-first clients to `DataSourceManager`.
- [x] Route TDX public quote/K-line/name methods through local-first storage while keeping low-level pytdx methods testable.
- [x] Route smart monitor AKShare/Tushare indicator fallback through local-first clients.
- [x] Route RSI and MA helper strategies through local-first OHLCV.
- [x] Run provider and strategy tests.
- [x] Review 1: grep direct production provider calls for covered datasets.
- [x] Review 2: verify technical-indicator paths use local-first OHLCV.
- [x] Review 3: verify public return shapes remain compatible.

### Task 4: Docker, Dependencies, and Docs

**Files:**
- Modify: `requirements.txt`
- Modify: `build/Dockerfile`
- Modify: `build/Dockerfile国内源版`
- Modify: `build/docker-compose.yml`
- Modify: `build/docker-compose.deploy.yml`
- Modify: `.gitignore`
- Modify: `.dockerignore`
- Modify: `build/.dockerignore`
- Modify: `docs/DOCKER_DEPLOYMENT.md`
- Modify: `docs/DOCKER_README.md`

- [x] Add `pyarrow`.
- [x] Ensure Dockerfiles create `/app/data/local_sources` and set `LOCAL_MARKET_DATA_DIR`.
- [x] Ensure compose files mount `/app/data` and set cache environment variables.
- [x] Exclude `data/local_sources/` from git and Docker build context.
- [x] Update deployment docs with backup/restore notes.
- [x] Run compose config validation if Docker CLI is available.
- [x] Review 1: inspect Docker path consistency.
- [x] Review 2: verify ignore rules prevent cache files entering git/image build context.
- [x] Review 3: compare deployment docs to spec section 11.

### Task 5: Final Verification

**Files:**
- All touched files.

- [x] Run Python compile checks.
- [x] Run targeted pytest suite.
- [x] Run provider-call audit.
- [x] Run frontend build only if frontend files changed.
- [x] Review 1: requirements traceability against spec section 1.1.
- [x] Review 2: acceptance criteria checklist against spec section 17.
- [x] Review 3: final diff inspection for unrelated changes and dirty-worktree safety.

### Verification Evidence

- Python compile: `python -m py_compile app\local_market_data_store.py app\local_market_data_clients.py app\data_source_manager.py app\smart_monitor_tdx_data.py app\smart_monitor_data.py app\smart_monitor_kline.py app\stock_data.py app\value_stock_strategy.py app\low_price_bull_service.py`.
- Pytest: `python -m pytest tests/test_local_market_data_store.py tests/test_local_market_data_clients.py tests/test_data_source_manager.py tests/test_data_source_manager_proxy.py tests/test_smart_monitor_tdx_data.py tests/test_stock_data_tdx_fallback.py tests/test_low_price_bull_service.py tests/test_app_stock_fetch.py tests/test_quant_sim_stockpolicy_adapter.py tests/test_quant_replay_engine.py -q` -> 43 passed.
- Provider audit: no direct `stock_zh_a_hist`, `ts_pro.daily`, `self.ts_pro.daily`, or `ak.stock_individual_info_em` calls remain in covered technical-indicator paths.
- Docker config: Docker CLI is unavailable in this environment; both compose files were parsed with Python/YAML and backend contains `/app/data` volume plus `LOCAL_MARKET_DATA_DIR=/app/data/local_sources`.
- Frontend build: `npm run build` in `ui/` passed, with the existing Vite chunk-size warning.
