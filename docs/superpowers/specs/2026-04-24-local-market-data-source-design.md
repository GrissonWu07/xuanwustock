# Local Market Data Source Design

**Date:** 2026-04-24  
**Status:** ready for review  
**Scope:** local-first Parquet market-data layer for AKShare, TDX, and Tushare.

## 1. Objective

Add a persistent local market-data source so historical data, realtime snapshots, and all technical indicators stop repeatedly hitting AKShare, Tushare, and TDX when data already exists locally.

The required behavior is:

- Every supported provider has its own local source: `local_akshare`, `local_tdx`, `local_tushare`.
- Local data maps one-to-one to its remote provider. Local AKShare data only comes from remote AKShare. Local TDX data only comes from remote TDX. Local Tushare data only comes from remote Tushare.
- Reads are local-first. If the requested data is available and fresh enough locally, return it without remote access.
- Misses, stale realtime records, or incomplete historical ranges trigger remote fetch, then persist back to the matching local source.
- Technical indicators must calculate from local-first OHLCV data, not bypass the local source.
- Docker deployment must mount the data directory so Parquet files survive container rebuilds and restarts.

## 2. Non-Goals

- Do not build a new database server.
- Do not replace SQLite result storage.
- Do not cache model/LLM outputs in this layer.
- Do not deduplicate AKShare, TDX, and Tushare into one shared truth table. Cross-source reconciliation can be added later, but first implementation must preserve source identity.
- Do not cache derived technical indicators as the source of truth. Indicators are derived from cached OHLCV so formula changes remain deterministic.

## 3. Current State

Market data is fetched through multiple direct paths:

- `app/data_source_manager.py`
  - AKShare historical data, realtime quote, basic info, financial data.
  - Tushare fallback for historical data, realtime-like daily quote, basic info, financial data.
- `app/smart_monitor_tdx_data.py`
  - TDX realtime quote, K-line data, range K-line data, technical indicators.
- `app/stock_data.py`
  - Chinese stock history currently tries TDX first, then `DataSourceManager`, then TDX fallback.
  - Technical indicators are calculated from the returned history.
- `app/smart_monitor_data.py`
  - Direct AKShare quote/history usage and Tushare fallback for realtime and indicators.
- `app/value_stock_strategy.py`
  - Direct AKShare historical calls for RSI.
- `app/low_price_bull_service.py`
  - TDX K-line calls for MA checks.
- `app/quant_sim/stockpolicy_adapter.py`
  - Quant kernel market snapshots come from `SmartMonitorTDXDataFetcher`.

This means replay, realtime simulation, watchlist analysis, and strategy checks can repeatedly query remote providers for the same symbol and date range.

## 4. Recommended Architecture

Introduce a new local-first data layer with three responsibilities:

1. `LocalMarketDataStore`
   - Owns Parquet paths, schema normalization, merge/upsert, filtering, TTL checks, and atomic writes.
   - Does not import AKShare, Tushare, TDX, or strategy code.

2. Source-specific local clients
   - `AkshareLocalClient`
   - `TdxLocalClient`
   - `TushareLocalClient`
   - Each client wraps one remote provider and one local namespace.
   - Each client returns the same shape expected by the existing caller.

3. Integration adapters
   - Replace direct remote calls in existing services with local-first clients.
   - Keep fallback order explicit: for example AKShare local/remote first, then Tushare local/remote if AKShare fails.

Recommended files:

- `app/local_market_data_store.py`
- `app/local_market_data_clients.py`
- `tests/test_local_market_data_store.py`
- `tests/test_local_market_data_clients.py`

Optional later split if files grow too large:

- `app/market_data_normalizers.py`
- `app/market_data_schemas.py`

## 5. Storage Layout

Base directory:

```text
data/local_sources/
```

Runtime path:

```text
${LOCAL_MARKET_DATA_DIR:-/app/data/local_sources}
```

Local source layout:

```text
data/local_sources/
  akshare/
    hist_daily/
      adjust=qfq/
        000001.parquet
    hist_minute/
      period=1/
        adjust=none/
          000001.parquet
    spot_quote/
      000001.parquet
    basic_info/
      000001.parquet
    financial/
      report_type=income/
        000001.parquet
    fund_flow/
      000001.parquet

  tdx/
    kline/
      kline_type=day/
        000001.parquet
      kline_type=minute30/
        000001.parquet
    realtime_quote/
      000001.parquet
    security_name/
      market=0/
        000001.parquet

  tushare/
    daily/
      adjust=qfq/
        000001.parquet
    stock_basic/
      000001.parquet
    daily_basic/
      000001.parquet
    moneyflow/
      000001.parquet
    financial/
      report_type=income/
        000001.parquet
```

Directory names use stable parameter keys so different data shapes never share a file.

## 6. Canonical Schemas

### 6.1 OHLCV K-Line Schema

All K-line data should be persisted with canonical columns:

- `symbol`: six-digit stock code.
- `datetime`: timezone-naive Asia/Shanghai datetime.
- `date`: `YYYY-MM-DD` string derived from `datetime`.
- `open`
- `high`
- `low`
- `close`
- `volume`
- `amount`
- `turnover`
- `pct_change`
- `change`
- `source`: `akshare`, `tdx`, or `tushare`.
- `dataset`: provider dataset name, such as `hist_daily`, `kline`.
- `adjust`: `qfq`, `hfq`, or `none`.
- `timeframe`: `1d`, `1m`, `5m`, `15m`, `30m`, `1h`, `1w`, or `1mo`.
- `fetched_at`: local fetch timestamp.

Provider-specific original columns may be preserved with `raw_` prefix only when useful. Strategy and indicator code must read canonical columns.

### 6.2 Realtime Quote Schema

- `symbol`
- `name`
- `current_price`
- `change_pct`
- `change_amount`
- `volume`
- `amount`
- `high`
- `low`
- `open`
- `pre_close`
- `turnover_rate`
- `volume_ratio`
- `quote_time`
- `source`
- `fetched_at`

Realtime quote files are append/upsert by `quote_time` and `fetched_at`, but readers normally return the newest fresh row.

### 6.3 Basic Info Schema

- `symbol`
- `name`
- `industry`
- `market`
- `list_date`
- `market_cap`
- `circulating_market_cap`
- `source`
- `fetched_at`

Basic info TTL should be long because it rarely changes.

## 7. Local-First Rules

### 7.1 Historical Date Range

For requests with `start_date` and `end_date`:

1. Read the provider-specific Parquet file.
2. Filter by canonical `datetime` or `date`.
3. If local coverage includes the requested range and has non-empty rows, return local rows.
4. If missing, fetch remote for the missing range or a safe full request range.
5. Normalize remote rows.
6. Merge with existing local rows.
7. Drop duplicates by `symbol`, `datetime`, `timeframe`, `adjust`, and `source`, keeping latest `fetched_at`.
8. Atomically write the merged Parquet file.
9. Return the requested slice.

### 7.2 Limit-Based K-Line Reads

For TDX methods such as `get_kline_data(symbol, kline_type, limit)`:

1. Read local `tdx/kline/kline_type=<type>/<symbol>.parquet`.
2. If row count is at least `limit` and the newest row is fresh enough for the current session, return tail `limit`.
3. Otherwise fetch remote `limit` or a configured safety size, merge, write, return tail `limit`.

Freshness is:

- During trading hours: latest row date/time must be today for intraday and at least the latest known trading day for daily.
- After market close: latest daily row for today is acceptable if present; otherwise previous trading day is acceptable only when today is not a trading day.
- First implementation may use a conservative stale policy: if newest row date is older than today and the request end is today or unset, fetch remote.

### 7.3 Realtime Quote TTL

Default TTL:

```text
MARKET_DATA_REALTIME_TTL_SECONDS=45
```

Rule:

- If newest local quote age is within TTL, return local quote.
- If stale, fetch remote, append/upsert, return remote.
- Outside trading hours, quote TTL can be relaxed to 24 hours only when `MARKET_DATA_RELAX_REALTIME_AFTER_CLOSE=true`.

### 7.4 Fallback Source Isolation

Fallback must not pollute the source namespace.

Example:

- Caller asks `DataSourceManager.get_stock_hist_data`.
- AKShare local miss, AKShare remote fails.
- Tushare local hit succeeds.
- Returned data source is `tushare`.
- Written file is under `data/local_sources/tushare/...`.
- No file is written under `data/local_sources/akshare/...`.

## 8. Provider Mapping

### 8.1 AKShare

Remote calls to wrap:

- `ak.stock_zh_a_hist`
- `ak.stock_zh_a_hist_min_em`
- `ak.stock_zh_a_spot_em`
- `ak.stock_individual_info_em`
- `ak.stock_financial_report_sina`
- `ak.stock_individual_fund_flow`
- `ak.stock_individual_fund_flow_rank`

Initial mandatory datasets:

- daily historical OHLCV
- minute historical OHLCV when used by realtime fallback
- basic info
- spot quote

Secondary datasets:

- financial reports
- fund flow

### 8.2 TDX

Remote calls to wrap:

- `TdxHq_API.get_security_quotes`
- `TdxHq_API.get_security_bars`
- `TdxHq_API.get_security_list`

Initial mandatory datasets:

- realtime quote
- K-line by `kline_type`
- security name lookup

Technical indicator functions in `SmartMonitorTDXDataFetcher` must use local-first K-line data.

### 8.3 Tushare

Remote calls to wrap:

- `pro.daily`
- `pro.stock_basic`
- `pro.daily_basic`
- `pro.moneyflow`
- `pro.income`
- `pro.balancesheet`
- `pro.cashflow`

Initial mandatory datasets:

- daily historical OHLCV
- basic info

Secondary datasets:

- daily basic
- moneyflow
- financial reports

## 9. Integration Points

### 9.1 `app/data_source_manager.py`

Replace direct AKShare/Tushare calls with local-first clients:

- `get_stock_hist_data`
- `get_stock_basic_info`
- `get_realtime_quotes`
- `get_financial_data`

Preserve public return shapes to avoid broad caller changes.

### 9.2 `app/smart_monitor_tdx_data.py`

Modify:

- `get_realtime_quote`
- `get_kline_data`
- `get_kline_data_range`
- `_get_stock_name`
- `get_technical_indicators`

Remote low-level methods `_fetch_quote_data` and `_fetch_kline_data` should remain testable, but public methods should be local-first.

### 9.3 `app/stock_data.py`

Keep existing high-level behavior, but rely on local-first TDX and DataSourceManager:

- `_get_chinese_stock_data`
- `_get_chinese_stock_data_from_tdx`
- `calculate_technical_indicators`
- `get_latest_indicators`

Indicators must operate on cached history when available.

### 9.4 `app/smart_monitor_data.py`

Remove direct cache-bypassing calls for:

- realtime quote fallback
- technical indicator fallback
- Tushare indicator fallback

Route those through local-first clients.

### 9.5 Strategy Helpers

Update:

- `app/value_stock_strategy.py`
- `app/low_price_bull_service.py`

RSI, MA5, and MA20 must read local-first historical OHLCV.

### 9.6 Quant Simulation and Replay

Quant simulation already flows through `MainProjectMarketDataProvider` and `SmartMonitorTDXDataFetcher`.

Required result:

- realtime simulation reads local TDX K-line and quote first.
- historical replay can warm/fill local K-line data while running.
- replay checkpoints must not repeatedly fetch the same symbol/date range remotely after the first successful fetch.

## 10. Configuration

New environment variables:

```env
MARKET_DATA_CACHE_ENABLED=true
LOCAL_MARKET_DATA_DIR=/app/data/local_sources
MARKET_DATA_REALTIME_TTL_SECONDS=45
MARKET_DATA_BASIC_INFO_TTL_DAYS=30
MARKET_DATA_FINANCIAL_TTL_DAYS=7
MARKET_DATA_RELAX_REALTIME_AFTER_CLOSE=false
MARKET_DATA_PARQUET_ENGINE=pyarrow
MARKET_DATA_FORCE_REMOTE=false
```

Rules:

- `MARKET_DATA_CACHE_ENABLED=false` bypasses local source completely.
- `MARKET_DATA_FORCE_REMOTE=true` fetches remote and refreshes local files, useful for manual repair.
- Defaults must work in local development without requiring extra configuration.

## 11. Docker and Deployment Requirements

Implementation must update Docker deployment files.

### 11.1 Python Dependencies

`requirements.txt` must add:

```text
pyarrow>=16.0.0
```

Pandas Parquet support requires `pyarrow` or `fastparquet`. Use `pyarrow` for first implementation.

### 11.2 Dockerfile

`build/Dockerfile` must:

- install `pyarrow` through `requirements.txt`.
- create the local data directory:

```dockerfile
RUN mkdir -p /app/data/local_sources && chmod -R 777 /app/data
```

- define default path:

```dockerfile
ENV LOCAL_MARKET_DATA_DIR=/app/data/local_sources
```

### 11.3 Compose Files

`build/docker-compose.yml` backend service must include:

```yaml
volumes:
  - ../data:/app/data
environment:
  - TZ=Asia/Shanghai
  - MARKET_DATA_CACHE_ENABLED=true
  - LOCAL_MARKET_DATA_DIR=/app/data/local_sources
```

`build/docker-compose.deploy.yml` backend service must include:

```yaml
volumes:
  - ${XUANWUSTOCK_DATA_DIR:-./data}:/app/data
environment:
  - TZ=Asia/Shanghai
  - MARKET_DATA_CACHE_ENABLED=true
  - LOCAL_MARKET_DATA_DIR=/app/data/local_sources
```

The existing `/app/data` mount is sufficient as long as `local_sources` is under `/app/data`. The explicit environment variable is still required so the path is auditable.

### 11.4 Ignore Rules

Add to `.gitignore` and `.dockerignore`:

```text
data/local_sources/
```

Reason:

- local Parquet files can grow large.
- they must not enter git.
- they must not be copied into Docker build context.
- runtime persistence comes from the bind mount, not image layers.

### 11.5 Deployment Docs

Update Docker docs:

- `docs/DOCKER_DEPLOYMENT.md`
- `docs/DOCKER_README.md`

Required content:

- `./data/local_sources` stores local AKShare/TDX/Tushare Parquet data.
- backup/restore should include this directory if replay speed and offline historical reads matter.
- deleting it is safe but causes remote refetch.

## 12. Error Handling

Local read failures:

- Log warning with source, dataset, symbol, path.
- Ignore corrupt local file for the current request.
- Fetch remote if allowed.
- Do not delete corrupt file automatically.

Remote failures:

- If local stale data exists, return stale data only for non-realtime historical reads and include `cache_status="stale"`.
- For realtime quotes, stale fallback is allowed only outside trading hours or when explicitly configured.
- If no usable local data and remote fails, preserve current behavior: return `None`, `{}`, or existing error dict depending on caller contract.

Write failures:

- Return fetched remote data to caller.
- Log error.
- Do not fail the market-data request solely because local persistence failed.

## 13. Concurrency and Atomicity

Parquet writes must be atomic:

1. Write merged frame to a temporary file in the same directory.
2. Replace target path with `Path.replace`.

In-process locks:

- Use a per-file `threading.RLock` registry in `LocalMarketDataStore`.

Cross-process safety:

- First implementation can rely on one backend process.
- If multi-worker deployment is introduced, add file locks using a small dependency or SQLite lock table.

## 14. Observability

Every local-first read should emit structured log fields:

- `source`
- `dataset`
- `symbol`
- `cache_status`: `hit`, `miss`, `partial`, `stale`, `remote_refresh`, `remote_failed`
- `rows`
- `path`

Later UI exposure can show cache hit ratio, but first implementation only needs logs and tests.

## 15. Testing Requirements

### 15.1 Unit Tests

Add tests for:

- Parquet write/read round trip.
- Historical range local hit avoids remote call.
- Historical partial miss fetches remote and merges without duplicate dates.
- TDX limit read returns local tail when enough rows exist.
- Realtime quote TTL hit avoids remote call.
- Realtime quote stale path calls remote and persists.
- Source isolation: AKShare fallback to Tushare writes only Tushare namespace.
- Corrupt local file does not crash caller and falls back to remote.

### 15.2 Integration Tests

Update existing tests:

- `tests/test_data_source_manager.py`
- `tests/test_data_source_manager_proxy.py`
- `tests/test_stock_data_tdx_fallback.py`
- `tests/test_smart_monitor_tdx_data.py`
- `tests/test_low_price_bull_service.py`
- `tests/test_app_stock_fetch.py`
- `tests/test_quant_sim_stockpolicy_adapter.py`

Assertions must verify:

- technical indicators use local-first K-line data when available.
- repeated calls do not call remote fetch twice.
- Docker path defaults do not break local development.

### 15.3 Manual Verification

Commands:

```bash
python -m pytest tests/test_local_market_data_store.py tests/test_local_market_data_clients.py -q
python -m pytest tests/test_data_source_manager.py tests/test_smart_monitor_tdx_data.py tests/test_stock_data_tdx_fallback.py -q
python -m pytest tests/test_quant_sim_stockpolicy_adapter.py tests/test_quant_replay_engine.py -q
docker compose -f build/docker-compose.yml config
```

Build check:

```bash
docker build -f build/Dockerfile -t xuanwustock-local-data-spec-check .
```

## 16. Rollout Plan

### Phase 1: Core Store and TDX K-Line

- Add `LocalMarketDataStore`.
- Add TDX K-line local-first support.
- Make TDX technical indicators use cached K-line.
- Add tests for K-line and indicator flow.

This immediately benefits quant simulation and replay.

### Phase 2: AKShare and Tushare Historical Data

- Wrap `DataSourceManager.get_stock_hist_data`.
- Add source-isolated fallback behavior.
- Update `StockDataFetcher` tests.

This benefits workbench analysis and RSI/MA strategy helpers.

### Phase 3: Realtime Quotes and Basic Info

- Add TDX quote cache.
- Add AKShare spot quote cache.
- Add AKShare/Tushare basic info cache.
- Update watchlist and monitor paths.

This reduces repeated quote/name lookup pressure.

### Phase 4: Secondary Datasets

- Fund flow.
- Financial reports.
- Daily basic.
- Security list/name cache improvements.

These are useful but should not block the main performance fix.

## 17. Acceptance Criteria

Implementation is complete when:

- `data/local_sources/akshare`, `data/local_sources/tdx`, and `data/local_sources/tushare` are supported.
- A repeated historical K-line request for the same source/symbol/range uses local Parquet on the second call.
- A repeated technical-indicator calculation uses local-first OHLCV.
- AKShare fallback to Tushare writes only Tushare local data.
- TDX indicator calculation uses local TDX K-line before remote TDX.
- Historical replay no longer repeatedly fetches the same symbol/date window after it has been cached.
- Docker Compose mounts `/app/data`, sets `LOCAL_MARKET_DATA_DIR`, and keeps Parquet files on the host.
- `.gitignore` and `.dockerignore` exclude `data/local_sources/`.
- Tests cover local hit, miss, partial refill, source isolation, and TTL behavior.

