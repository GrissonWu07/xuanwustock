---
source: openspec
change_id: stabilize-discovery-technical-snapshot-flow
title: Stock Discovery Refresh Hydration
last_synced: 2026-05-16
last_reviewed: 2026-05-16
status: archived
---

# Stock Discovery Refresh Hydration

## Story / Capability Summary

Stock discovery now publishes source candidate evidence separately from latest
market/technical evidence. A discovery task writes the current candidate set,
the unified stock refresh job prepares or refreshes 30m technical snapshots, and
both lifecycle ingestion and the discover API read the same hydrated candidate
view.

This closes the case where selector outputs could look successful while
structured MA/MACD/RSI/amount/trend fields were missing or stale by the time
automatic quant lifecycle rules evaluated the candidate.

## User-Facing Behavior

- A completed discovery task exposes the stock code, name, strategy source,
  selected time, discovery run id, score/confidence, and refreshed technical
  snapshot diagnostics.
- Discover API rows and lifecycle candidate events show the same refreshed
  technical readiness fields for the candidate.
- Old raw selector outputs can still be displayed only as stale/unprepared
  fallback rows; they cannot appear as current technically ready candidates.
- Existing lifecycle thresholds, gates, capacity limits, and buy/sell logic are
  unchanged.

## Workflow

1. The user triggers a discovery strategy task.
2. The task saves only the strategies completed in that task as the current
   discovery candidate artifact.
3. Unified stock refresh includes those candidate codes in its refresh universe.
4. Runtime snapshot entries store latest price/basic fields plus 30m technical
   fields and readiness metadata.
5. Discovery rows are hydrated from candidate artifact plus runtime snapshot.
6. Lifecycle score, confidence, trend, and technical confirmation are
   recalculated after hydration.
7. Lifecycle ingestion and `GET /api/v1/discover` consume that same hydrated
   view.

## Rules Applied

- `PIR-001`: planned and reviewed implementation paths are documented.
- `PIR-002`: production implementation files are at or below 1000 lines.
- `PIR-003` / `CFG-005`: no schema change or DB runtime migration.
- `PIR-004`: existing API operations remain additive and keep controller/service
  separation.
- `PIR-005`: expensive refresh IO stays in async discovery/scheduler paths.
- `PY-001`, `PY-003`, `PY-007`: package helpers, explicit imports, safe
  diagnostics, and no secret-bearing output.
- `TEST-001`, `TEST-002`, `TEST-003`, `TEST-007`, `TEST-008`, `TEST-010`:
  independent test parameters, meaningful assertions, external IO mocked in
  tests, coverage, real E2E evidence, and review closure.

## Design Summary

The design separates immutable discovery source evidence from current technical
truth:

- `app/discover/candidate_artifact.py` stores the latest candidate artifact and
  hydrates rows from runtime entries.
- `app/stock_refresh_scheduler.py` includes discovery candidate codes in the
  unified refresh universe and persists 30m technical snapshot fields.
- `app/discover/market_snapshot.py` exposes single-code snapshot preparation so
  refresh and discovery use the same technical normalization.
- `app/discover/discover.py` orchestrates strategy execution, artifact write,
  refresh, hydration, scoring, lifecycle ingestion, and API readback.
- `app/discover/ai_strategy.py` holds AI scanner orchestration so
  `discover.py` stays within the file-size guardrail.

## Implemented Code Paths

- `app/discover/candidate_artifact.py`
- `app/discover/ai_strategy.py`
- `app/discover/market_snapshot.py`
- `app/discover/discover.py`
- `app/stock_refresh_scheduler.py`
- `app/gateway/quant_universe_entry.py`
- `tests/test_discover_refresh_hydration.py`
- `tests/test_discover_market_snapshot.py`
- `tests/test_discover_lifecycle_scoring.py`
- `tests/test_ui_backend_api_actions.py`

## API / Data / UI Impact

Existing discover APIs may now include additive row/task fields:

- `discoveryRunId`
- `discoveryArtifactStatus`
- `technical_snapshot_ready`
- `technical_snapshot_status`
- `technical_snapshot_missing_fields`
- `technical_snapshot_timeframe`
- `technical_snapshot_provider`
- `technical_snapshot_at`
- `technical_snapshot_prepared_at`
- `technical_snapshot_row_count`
- `technical_snapshot_indicator_version`
- refreshed `trend`, `technical_confirmation_count`, score, and confidence

No frontend layout change is required by this change.

## Database / API IO / Async Notes

No relational schema migration was added. Candidate event payload JSON continues
to store lifecycle diagnostics and refreshed technical fields.

`POST /api/v1/discover/actions/run-strategy` remains the async work boundary for
strategy execution and refresh. `GET /api/v1/discover` reads persisted
artifact/runtime/cache state only and does not perform remote market-data IO.

## Security and Permissions

No credentials, auth rules, secrets, or permission checks changed. Diagnostics
contain stock identifiers, strategy names, numeric indicators, provider/timeframe
metadata, and safe reason codes only.

## Operational Notes

- The unified refresh universe can include active quant/workbench stocks in
  addition to the just-discovered candidate codes, so `stockRefresh.totalCodes`
  can be greater than the task candidate count.
- Provider failures are per-stock diagnostics. Failed or incomplete snapshots
  block automatic trial entry with `missing_technical_snapshot`.
- Raw selector fallback rows are explicitly `stale_unprepared`.

## Validation Evidence

Focused tests:

```powershell
python -m pytest -q tests\test_discover_refresh_hydration.py tests\test_discover_market_snapshot.py tests\test_discover_lifecycle_scoring.py tests\test_ui_backend_api_actions.py::test_discover_snapshot_aggregates_selector_results tests\test_ui_backend_api_actions.py::test_discover_snapshot_exposes_read_only_lifecycle_entry_fields tests\test_ui_backend_api_actions.py::test_discover_run_strategy_auto_trial_promotes_discovered_stocks tests\test_ui_backend_api_actions.py::test_discover_run_strategy_executes_real_selector_runners_and_persists_results -p no:cacheprovider
```

Result: `40 passed`.

Whitespace check:

```powershell
git diff --check -- app/discover/discover.py app/discover/market_snapshot.py app/gateway/quant_universe_entry.py app/stock_refresh_scheduler.py tests/test_discover_lifecycle_scoring.py tests/test_discover_market_snapshot.py tests/test_ui_backend_api_actions.py
```

Result: no whitespace errors.

## Test Parameter and Coverage Evidence

Test parameter files:

- `openspec/changes/archive/2026-05-16-stabilize-discovery-technical-snapshot-flow/test-params/candidate-artifact-refresh.md`
- `openspec/changes/archive/2026-05-16-stabilize-discovery-technical-snapshot-flow/test-params/discovery-hydrated-lifecycle.md`

Coverage:

```powershell
python -m pytest -q tests\test_discover_refresh_hydration.py tests\test_discover_market_snapshot.py tests\test_discover_lifecycle_scoring.py tests\test_ui_backend_api_actions.py::test_discover_run_strategy_auto_trial_promotes_discovered_stocks --cov=app.discover.candidate_artifact --cov=app.discover.ai_strategy --cov=app.discover.market_snapshot --cov-report=term-missing -p no:cacheprovider
```

Result: `37 passed`, total coverage `93%`.

## Standalone Verification Evidence

A temporary backend was started from the current workspace on
`http://127.0.0.1:8519`, then a real discovery API run was executed:

- Request: `POST /api/v1/discover/actions/run-strategy`
- Payload: `{"strategies":["low_price_bull"],"topN":1,"waitMs":1000}`
- Completed task: `discover-a52dd81a84`
- Status: `completed`
- Candidate count: `1`
- Discover API strategy keys: `["low_price_bull"]`
- Unexpected strategy keys: `[]`
- Ready rows: `1`
- Technical snapshot summary: `uniqueStocks=1`, `complete=1`, `failed=0`
- Latest candidate event for `003016` had
  `technical_snapshot_ready=true`, `technical_snapshot_status=ready`,
  `ma20=8.1935`, `trend=up`, and `technical_confirmation_count=2`.

## Real E2E Evidence

The same temporary backend run is the required real E2E verification. It used
the supported backend API boundary, real selector/market-data path, discover API
readback, and local quant DB candidate event inspection.

## Source Mapping

- Proposal:
  `openspec/changes/archive/2026-05-16-stabilize-discovery-technical-snapshot-flow/proposal.md`
- Spec:
  `openspec/changes/archive/2026-05-16-stabilize-discovery-technical-snapshot-flow/specs/discovery-refresh-hydration/spec.md`
- Design:
  `openspec/changes/archive/2026-05-16-stabilize-discovery-technical-snapshot-flow/design.md`
- Task reviews:
  `openspec/changes/archive/2026-05-16-stabilize-discovery-technical-snapshot-flow/task-reviews.md`
- Final review:
  `openspec/changes/archive/2026-05-16-stabilize-discovery-technical-snapshot-flow/review.md`
