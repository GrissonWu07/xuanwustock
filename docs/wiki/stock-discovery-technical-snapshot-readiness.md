---
source: openspec
change_id: discover-market-data-snapshot-gate
title: Stock Discovery Technical Snapshot Readiness
last_synced: 2026-05-16
last_reviewed: 2026-05-16
status: archived
---

# Stock Discovery Technical Snapshot Readiness

## Story / Capability Summary

Stock discovery now has a hard technical-readiness contract before automatic quant lifecycle entry. A discovered stock must have a complete 30m market and indicator snapshot before it can continue toward automatic trial entry.

The feature closes the gap where discovery could publish candidates with score/confidence text but without structured MA, MACD, RSI, volume, amount, and snapshot metadata.

## User-Facing Behavior

- Discovery candidates show technical snapshot readiness in the UI.
- Incomplete candidates show the missing field list and `missing_technical_snapshot` lifecycle reason.
- Discovery task completion feedback reports checked, ready, incomplete, failed, and blocked snapshot counts.
- Duplicated discovery rows may still appear, but readiness is prepared once per unique stock code.
- Normal database reset preserves local market-data cache files.

## Workflow

1. A discovery task runs selected strategies.
2. The task builds discovery rows once.
3. The task prepares a 30m technical snapshot for every unique stock code.
4. Snapshot fields and diagnostics are merged into every matching row.
5. Lifecycle candidate events persist the normalized snapshot fields.
6. The candidate entry gate blocks incomplete discovery snapshots with `missing_technical_snapshot`.
7. API and UI consumers receive readiness and missing-field diagnostics.

## Rules Applied

- `PIR-001`: Code paths were planned and mapped in the design and tasks.
- `PIR-002`: Modified/generated code files remain under 1000 lines.
- `PIR-003`: Existing DB runtime is reused; no schema migration was added.
- `PIR-004`: API-visible fields are additive and documented in the design.
- `PIR-005`: Discovery market-data preparation remains task-asynchronous.
- `CFG-009`: OpenSpec test parameter files back behavioral tests.
- `TEST-001`: Focused changed-module coverage reached 93%.
- `TEST-003`: Tests assert real blocked/ready outcomes.

## Design Summary

Snapshot preparation is isolated in `app/discover/market_snapshot.py`. It is data-oriented and does not write lifecycle state. The lifecycle gate remains the authority for pass/block semantics.

A complete snapshot requires:

- price or close
- `ma5`, `ma10`, `ma20`, `ma20_slope`, `ma60`
- `amount`, `volume_ratio`
- `rsi`, `macd`, `trend`
- snapshot timestamp, provider, timeframe, and indicator version

TDX empty-cache behavior now uses the existing `SmartMonitorTDXDataFetcher` remote path through `MarketDataService`.

## Implemented Code Paths

- `app/discover/market_snapshot.py`: prepares and normalizes 30m readiness.
- `app/discover/discover.py`: wires preparation before lifecycle ingestion and task diagnostics.
- `app/data/services/market_data_service.py`: TDX service now calls the real remote fetcher when cache is empty.
- `app/gateway/quant_universe_entry.py`: persists and hydrates technical snapshot fields in candidate events.
- `app/quant_sim/candidate_entry_gate.py`: blocks incomplete discovery snapshots.
- `ui/src/lib/page-models.ts`: extends row model fields.
- `ui/src/features/quant/quant-entry-controls.tsx`: renders snapshot status and missing fields.
- `ui/src/features/discover/discover-page.tsx`: renders task snapshot preparation counts.
- `tests/test_discover_market_snapshot.py`: covers snapshot preparation, lifecycle gate, API hydration, TDX fetch handoff, and consumed-event snapshot hydration.
- `tests/test_discover_lifecycle_scoring.py`: keeps weak-complete AI candidates on the existing recommended-only path.
- `tests/test_reset_stock_universe_deployment.py`: verifies DB reset preserves market-data cache.
- `ui/src/tests/discover-page.test.tsx`: covers UI readiness and task summary rendering.

## API / Data / UI Impact

Discovery rows may include:

- `technical_snapshot_ready`
- `technical_snapshot_status`
- `technical_snapshot_missing_fields`
- `technical_snapshot_timeframe`
- `technical_snapshot_provider`
- `technical_snapshot_at`
- `technical_snapshot_prepared_at`
- `technical_snapshot_row_count`
- `technical_snapshot_indicator_version`

Discovery task results include `technicalSnapshotPreparation` counts and item diagnostics.

UI additions are additive and preserve existing lifecycle controls.

## Database / API IO / Async Notes

No relational schema migration was added. Candidate event payload JSON stores readiness diagnostics.

Discovery market-data work runs inside the asynchronous discovery task path rather than directly in the request handler. External market-data IO remains behind the existing TDX/local-cache service boundary.

## Security and Permissions

No credentials or secret configuration were added. Diagnostics include stock code, readiness status, provider, timeframe, and missing field names only.

Normal DB reset remains database-file scoped. Market-data cache deletion is out of scope unless a future explicit cache-deletion command is added.

## Operational Notes

- Empty or stale cache can make discovery tasks slower because missing 30m data is prepared before lifecycle ingestion.
- Provider failures block only the affected candidates and are reported in task diagnostics.
- Older candidate events without readiness fields continue to render safely.

## Validation Evidence

- `openspec validate discover-market-data-snapshot-gate --strict`: passed before archival; after archival the CLI no longer resolves the original active change id.
- `python -m pytest -q tests\test_discover_market_snapshot.py tests\test_discover_lifecycle_scoring.py tests\test_reset_stock_universe_deployment.py -p no:cacheprovider`: `32 passed`.
- `npm test -- src/tests/discover-page.test.tsx`: `6 passed`.
- `git diff --check`: no whitespace errors.

## Test Parameter and Coverage Evidence

Test parameters:

- `openspec/changes/archive/2026-05-16-discover-market-data-snapshot-gate/test-params/discovery-snapshot-readiness.md`
- `openspec/changes/archive/2026-05-16-discover-market-data-snapshot-gate/test-params/lifecycle-gate-missing-snapshot.md`
- `openspec/changes/archive/2026-05-16-discover-market-data-snapshot-gate/test-params/discover-ui-snapshot-readiness.md`
- `openspec/changes/archive/2026-05-16-discover-market-data-snapshot-gate/test-params/reset-preserves-market-cache.md`

Coverage:

- `python -m pytest -q tests\test_discover_market_snapshot.py --cov=app.discover.market_snapshot --cov-report=term-missing -p no:cacheprovider`: `16 passed`, `app\discover\market_snapshot.py` at `93%`.

## Standalone Verification Evidence

The backend and frontend tests run without external market-data access. TDX remote IO is mocked at the service boundary in unit tests. Reset behavior is validated against isolated temporary directories.

An additional real discovery validation was run through the backend API with no mocked selector or market-data services:

- `POST /api/v1/discover/actions/run-strategy`
- Payload: `{"strategies": ["low_price_bull"], "topN": 1, "waitMs": 180000}`
- pywencai returned `139` matching stocks and selected `003016 欣贺股份`.
- Discovery task completed with one ready snapshot: `uniqueStocks=1`, `complete=1`, `missing_fields=[]`.
- TDX wrote `data/local_sources/tdx/kline/kline_type=minute30/003016.parquet`.
- The cache file contained `3241` 30m rows.
- Latest 30m bar was `2026-05-15 15:00:00`, close `8.14`, amount `4418145.0`, provider `tdx`.
- `MarketDataService(provider="tdx").get_latest_snapshot("003016", period="minute30")` returned complete MA/MACD/RSI/volume/metadata fields with no missing required field.
- The candidate event payload persisted the technical fields and passed the entry gate; lifecycle skipped promotion only because the candidate score was below trial threshold.
- A follow-up rerun verified `technical_snapshot_row_count=601` in both the discovery row and candidate event payload, matching the prepared 120-day indicator window.

A full default discovery validation was then run through the same backend API path:

- Payload: `{"waitMs": 600000}` with default strategies `main_force`, `low_price_bull`, `small_cap`, `profit_growth`, and `value_stock`.
- Task `discover-1431e3c61b` completed in `102.02` seconds with failed strategies `[]` and `50` candidate rows.
- Snapshot preparation checked `48` unique stocks: `45` complete, `1` incomplete, `2` failed, and `3` blocked with `missing_technical_snapshot`.
- Blocked stocks were `001393` missing MA/RSI history, and `920832` / `920017` with unavailable market data.
- All `45` non-missing candidate event payloads contained the required technical snapshot fields.
- Discovery API rendering over all `50` rows returned snapshot statuses `ready=47`, `incomplete=1`, `failed=2`; no non-blocked row lacked a ready snapshot.
- A validation finding where already-in-quant rows lost snapshot display after candidate events became `consumed` was fixed; `301081 严牌股份` now renders `technical_snapshot_ready=true`, status `ready`, and row count `600`.

## Source Mapping

- OpenSpec proposal: `openspec/changes/archive/2026-05-16-discover-market-data-snapshot-gate/proposal.md`
- Requirement spec: `openspec/changes/archive/2026-05-16-discover-market-data-snapshot-gate/specs/discover-lifecycle-entry/spec.md`
- Design: `openspec/changes/archive/2026-05-16-discover-market-data-snapshot-gate/design.md`
- Task reviews: `openspec/changes/archive/2026-05-16-discover-market-data-snapshot-gate/task-reviews.md`
- Final review: `openspec/changes/archive/2026-05-16-discover-market-data-snapshot-gate/review.md`
