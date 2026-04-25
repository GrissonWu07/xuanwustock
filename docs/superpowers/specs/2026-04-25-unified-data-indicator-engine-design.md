# Unified Data And Indicator Engine Design

**Date:** 2026-04-25  
**Status:** implemented in this branch
**Scope:** unify local-first market-data access and technical indicator calculation across stock analysis, realtime simulation, and historical replay.

## 1. Goal

All market-data channels keep both local and remote access, but every business module must read through the same local-first path and calculate indicators through the same indicator engine.

The goal is not to force every module to use the same indicators. The goal is to make the same OHLCV input produce the same MA, RSI, MACD, BOLL, KDJ, OBV, ATR, and volume metrics everywhere.

## 2. Non-Negotiable Rules

- Each provider channel keeps an isolated local namespace and remote provider:
  - AKShare local maps only to remote AKShare.
  - TDX local maps only to remote TDX.
  - Tushare local maps only to remote Tushare.
- Every supported market-data fetch must read local Parquet first.
- If local data is missing, stale, corrupt, or does not cover the requested range, the matching remote provider may be called.
- Any successful remote fetch must be normalized, merged, deduplicated, and written back to that provider's local Parquet namespace before being returned.
- Technical indicators are derived only from canonical OHLCV frames. Remote provider indicator fields are not accepted as authoritative.
- Indicator formulas must live under `app/data/indicators/`. No business module may implement its own MA/MACD/RSI/BOLL/KDJ/OBV/ATR formulas.
- Historical replay may only pass bars visible at the checkpoint into the indicator engine.

## 3. Relationship To Existing Local Data Spec

This spec builds on `docs/superpowers/specs/2026-04-24-local-market-data-source-design.md`.

Existing foundations that should be reused:

- `app/local_market_data_store.py`
- `app/local_market_data_clients.py`
- `tests/test_local_market_data_store.py`
- `tests/test_local_market_data_clients.py`

The new work reorganizes the long-term production API under `app/data/` while preserving backward-compatible wrappers for existing imports.

Migration rule: there must be only one active implementation of local storage and provider wrappers at any time. During the migration, `app/data/*` may wrap or re-export the existing `LocalMarketDataStore` and local clients. After migration, the old modules must become compatibility wrappers around `app/data/*`. Do not create a second independent Parquet store, lock registry, or provider-cache path.

## 4. Target Package Layout

```text
app/data/
  __init__.py

  sources/
    __init__.py
    base.py
    akshare_source.py
    tdx_source.py
    tushare_source.py
    registry.py

  store/
    __init__.py
    parquet_store.py
    normalizer.py

  indicators/
    __init__.py
    schema.py
    profiles.py
    moving_average.py
    momentum.py
    volatility.py
    volume.py
    engine.py

  services/
    __init__.py
    market_data_service.py
```

## 5. Responsibilities

### `app/data/sources`

Source classes own local-first provider access.

- `AkshareMarketDataSource`
- `TdxMarketDataSource`
- `TushareMarketDataSource`

Each source must:

- Resolve local Parquet path through the store.
- Check local coverage for the requested symbol/range/timeframe.
- Fetch remote only for miss/partial/stale cases.
- Persist successful remote data to its own local namespace.
- Return canonical OHLCV where possible.

### `app/data/store`

Store classes own persistence and normalization.

- `ParquetMarketDataStore` owns file paths, atomic writes, merge/upsert, range checks, and corruption fallback.
- `normalizer.py` owns provider column mapping to canonical OHLCV.

The store must not import AKShare, TDX, Tushare, quant simulation, or stock analysis.

The store may backfill provider-neutral metadata such as `provider`, `source`, and `fetched_at`. Provider-specific request metadata such as `dataset`, `timeframe`, `adjust`, and `cache_source` must be supplied by the source layer or the normalizer before the frame reaches the indicator engine.

### `app/data/indicators`

Indicator modules own formulas only.

- `moving_average.py`: MA5/10/20/60, MA slope.
- `momentum.py`: MACD, RSI, KDJ.
- `volatility.py`: BOLL, ATR, Bollinger position.
- `volume.py`: volume ratio, OBV.
- `engine.py`: `TechnicalIndicatorEngine` orchestration.

No indicator module should fetch market data.

### `app/data/services`

`MarketDataService` is the business-facing API:

```text
MarketDataService.get_ohlcv(...)
MarketDataService.get_indicators(...)
MarketDataService.get_latest_snapshot(...)
```

Business modules should depend on this service or on `TechnicalIndicatorEngine`, not on provider APIs.

## 6. Canonical OHLCV Schema

Every K-line frame entering the indicator engine must have:

- `symbol`
- `datetime`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `amount`
- `source`
- `dataset`
- `timeframe`
- `adjust`
- `provider`
- `cache_source`
- `fetched_at`

Provider-specific original columns may remain with `raw_` prefixes, but indicator code must ignore them.

Metadata ownership:

- `provider/source`: set by the provider source or store fallback.
- `dataset`: set by the source method, for example `hist_daily`, `kline`, or `spot_quote`.
- `timeframe`: normalized to values such as `1d`, `30m`, `1w`, `1mo`.
- `adjust`: normalized to `none`, `qfq`, or `hfq`; replay should prefer `none` unless an as-of adjustment profile exists.
- `cache_source`: set to `local_*`, `remote_*`, `partial_*`, or `stale_*` at the source boundary.
- `fetched_at`: set when data is written or read from cache.

Frames missing required canonical OHLCV fields must fail fast before indicator calculation. Frames missing optional metadata may be normalized only at source boundaries, not inside formula modules.

## 7. Canonical Indicator Schema

The engine must output a DataFrame with original OHLCV plus:

- `ma5`
- `ma10`
- `ma20`
- `ma60`
- `ma20_slope`
- `rsi6`
- `rsi12`
- `rsi14`
- `rsi24`
- `dif`
- `dea`
- `hist`
- `macd`
- `kdj_k`
- `kdj_d`
- `kdj_j`
- `obv`
- `obv_prev`
- `atr`
- `boll_upper`
- `boll_mid`
- `boll_lower`
- `boll_position_value`
- `volume_ma5`
- `volume_ma10`
- `volume_ratio`
- `trend`
- `indicator_version`
- `formula_profile`

Field aliases may be produced at wrapper boundaries for backward compatibility, but the canonical schema is the only source of truth.

## 8. Formula Profile

Initial formula profile: `cn_tdx_v1`.

Rules:

- MA: rolling arithmetic mean over `close`.
- MACD:
  - `dif = EMA(close, 12) - EMA(close, 26)`
  - `dea = EMA(dif, 9)`
  - `hist = dif - dea`
  - `macd = 2 * hist`
- RSI: output `rsi6`, `rsi12`, `rsi14`, `rsi24`.
- KDJ: RSV period 9, K/D smoothing 3/3, `J = 3K - 2D`.
- BOLL: 20-period middle band, 2 standard deviations.
- ATR: 14-period true range average.
- OBV: cumulative signed volume by close delta.
- Volume ratio: `volume / volume_ma5`.
- Trend:
  - `up` if `close > ma5 > ma20 > ma60`.
  - `down` if `close < ma5 < ma20 < ma60`.
  - otherwise `sideways`.

Future profiles can be added, but production must store `formula_profile` so signals remain auditable.

Compatibility note: in `cn_tdx_v1`, `macd` means `2 * (dif - dea)`. Legacy stock-analysis UI fields that previously used `MACD` from the `ta` library must be mapped deliberately:

- canonical `dif` may be exposed as `dif` or `macd_dif`.
- canonical `dea` may be exposed as `dea`, `macd_signal`, or `macd_dea`.
- canonical `hist` may be exposed as `hist` or `macd_histogram`.
- canonical `macd` must be labelled as the TDX-style MACD bar value, not as DIF.

Any UI, LLM prompt, or signal audit text that references MACD must use the canonical label so old and new values are not compared as if they were the same field.

## 9. Migration Requirements

### Stock Analysis

`StockDataFetcher.calculate_technical_indicators()` becomes a wrapper around `TechnicalIndicatorEngine`.

`StockDataFetcher.get_latest_indicators()` maps canonical output to legacy keys used by the analysis UI:

- `price` from `close`
- `rsi` from `rsi14`
- `macd`, `macd_signal`, `macd_histogram` from `macd`, `dea`, `hist`
- `bb_upper`, `bb_middle`, `bb_lower` from BOLL canonical fields
- `k_value`, `d_value` from KDJ canonical fields

### Realtime Simulation

`SmartMonitorTDXDataFetcher.get_technical_indicators()` becomes a wrapper around `TechnicalIndicatorEngine`.

It may still return old field names expected by `KernelStrategyRuntime`, but it may not calculate formulas itself.

### Historical Replay

`SmartMonitorTDXDataFetcher.build_snapshot_from_history()` must pass only the checkpoint-bounded OHLCV window into `TechnicalIndicatorEngine`.

It must not fetch remote data or use latest bars.

### Other Consumers

Any existing direct indicator calculations in `stock_data.py`, `smart_monitor_tdx_data.py`, `smart_monitor_data.py`, `low_price_bull_service.py`, `value_stock_strategy.py`, or strategy helpers must be replaced or explicitly wrapped through the unified engine.

This applies to direct `ta.*`, `rolling(...)`, `ewm(...)`, and hand-written MA/MACD/RSI/BOLL/KDJ/OBV/ATR/volume-ratio formulas in business modules. Business modules may still define which indicators they use and how they score them.

## 10. Backward Compatibility

Existing imports can remain temporarily:

- `app.local_market_data_store.LocalMarketDataStore`
- `app.local_market_data_clients.AkshareLocalClient`
- `app.local_market_data_clients.TdxLocalClient`
- `app.local_market_data_clients.TushareLocalClient`

But new code should import from `app/data/`.

Wrappers must preserve existing return shapes while internally using canonical data and the unified engine.

Implementation order:

1. Add `app/data/*` modules as thin wrappers around the existing local store and local clients.
2. Move canonical normalization and indicator formulas into `app/data/*`.
3. Point existing wrappers to the new canonical modules.
4. Only then consider physically moving the old implementation files.

The same tests must pass before and after each step. A migration that changes file paths but leaves two working implementations is not acceptable.

## 11. Testing Requirements

Unit tests:

- Same OHLCV input produces identical indicator output through stock analysis and TDX wrappers.
- MACD profile matches `cn_tdx_v1`.
- RSI outputs all required periods.
- Missing optional fields do not break indicator calculation.
- Historical replay snapshot calculation only uses provided bars.

Data-source tests:

- AKShare local hit avoids remote call.
- AKShare remote miss writes to AKShare local namespace.
- TDX local hit avoids remote call.
- TDX remote miss writes to TDX local namespace.
- Tushare local/remote behavior remains isolated from AKShare and TDX.

Audit tests:

- `StockDataFetcher.calculate_technical_indicators()` does not contain formula logic.
- `SmartMonitorTDXDataFetcher.get_technical_indicators()` does not contain formula logic.
- Grep audit for direct `ta.` usage outside indicator engine and tests.
- Grep audit for direct business-module `rolling(...)` or `ewm(...)` indicator formulas outside indicator engine and tests.
- Explicit coverage for `low_price_bull_service.py` and `value_stock_strategy.py` so legacy strategy helpers do not keep private indicator math.

## 12. Acceptance Criteria

- Stock analysis and realtime simulation use the same indicator engine.
- Same canonical OHLCV produces the same canonical indicator values in all modules.
- Provider-local and provider-remote paths remain isolated by source.
- Remote success always persists to local Parquet.
- Historical replay remains point-in-time safe.
- Signal detail can expose `indicator_version` and `formula_profile`.
- No business module contains authoritative indicator formula logic outside `app/data/indicators/`.

## 13. Out Of Scope

- Stock-analysis conclusion fusion into trading decisions.
- Cross-provider reconciliation between AKShare, TDX, and Tushare.
- Persisting derived indicators as authoritative source-of-truth.
- Rewriting all provider clients in one step if wrappers can safely preserve behavior.

## 14. Self-Review

- No unresolved requirements remain.
- The data-source concern and indicator-formula concern are separated.
- Historical replay as-of safety is explicitly preserved.
- The spec does not require all modules to use the same indicator set, only the same formula engine.
