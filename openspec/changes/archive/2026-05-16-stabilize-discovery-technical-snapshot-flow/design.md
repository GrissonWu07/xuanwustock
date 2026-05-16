# Design: Stabilize Discovery Refresh Hydration

## Current Behavior

Discovery runs persist raw strategy outputs per strategy under selector-result
storage. The asynchronous discovery task then builds rows, prepares 30m
technical snapshots in memory, and sends those rows to lifecycle ingestion.
Later discover API reads rebuild rows from raw selector outputs and can lose the
prepared technical fields. Unified stock refresh exists, but it currently stores
mostly latest price/basic metadata and does not clearly include newly discovered
but not-yet-active candidates.

## Target Behavior

Discovery runs persist a latest aggregate candidate artifact containing candidate
identity, source strategy evidence, selected time, discovery run id, and initial
preparation summary. Newly discovered codes are part of the unified stock
refresh universe. Unified stock refresh writes latest 30m technical snapshot
fields into runtime snapshot entries. Discovery task lifecycle ingestion and
discover API reads hydrate candidate rows from the latest artifact plus runtime
snapshot entries, then calculate lifecycle score/confidence/trend/technical
confirmation from the hydrated data.

Raw selector results remain available only as stale/unprepared fallback rows.

## Architecture Impact

- Candidate source evidence and latest market/technical evidence are separated.
- The discovery task remains the async orchestration boundary for expensive
  refresh work.
- Discover read APIs do not perform remote market-data IO.
- Lifecycle event payloads and discover API rows are fed from one hydrated
  candidate view.

## Generated Code Paths

- Candidate artifact storage and hydration:
  - `app/discover/candidate_artifact.py`
- AI scanner split to keep file-size rule:
  - `app/discover/ai_strategy.py`
  - `app/discover/discover.py`
- Snapshot reuse:
  - `app/discover/market_snapshot.py`
- Unified stock refresh:
  - `app/stock_refresh_scheduler.py`
- Discovery orchestration/API shaping:
  - `app/discover/discover.py`
- Tests:
  - `tests/test_discover_refresh_hydration.py`
  - existing relevant discovery tests when needed

## Reuse / Common Logic Plan

- Reuse `selector_result_store.save_latest_result/load_latest_result` for the
  candidate artifact.
- Reuse `prepare_discovery_market_snapshots` normalization by exposing a
  one-code snapshot helper for unified refresh.
- Reuse `load_stock_runtime_entries/save_stock_runtime_entries` as the latest
  runtime snapshot persistence boundary.
- Reuse `normalize_discovery_lifecycle_row` after hydration instead of adding a
  second scoring path.
- Reuse existing task manager and `ingest_lifecycle_entry_rows`.

## Requirement Scope / Compatibility / Fallback

- New discovery runs use the latest candidate artifact and hydrated runtime
  snapshot evidence.
- Raw selector fallback is allowed only for display compatibility and must be
  marked stale/unprepared.
- No migration or rewrite of existing old candidate records.
- No threshold, gate, capacity, buy/sell, or UI redesign changes.

## Method / Function Parameter Plan

- New helper functions will accept either one data object or no more than five
  explicit parameters.
- Candidate artifact payloads have documented keys: `runId`, `selectedAt`,
  `rows`, `summary`, and `updatedAt`.
- Runtime technical snapshot entries use explicit technical keys already used by
  discovery/lifecycle payloads.

## File Size / Split Plan

- `app/discover/discover.py` is already over 1000 lines. Before marking
  implementation complete, move AI scanner orchestration into
  `app/discover/ai_strategy.py` and keep the modified `discover.py` at or below
  1000 lines.
- All new files must stay below 1000 lines.

## Data Impact

- Adds a selector-result JSON artifact for the latest discovery candidates.
- Extends `stock_runtime_snapshot` JSON entries with technical fields such as
  `ma5`, `ma10`, `ma20`, `ma20_slope`, `ma60`, `amount`, `volume_ratio`, `rsi`,
  `macd`, `trend`, readiness status, provider, timeframe, row count, and
  indicator version.
- Candidate event payload JSON continues to store refreshed technical fields.

## Database Decision

No relational database schema change is required. Existing quant DB payload JSON
is reused for lifecycle events. Existing selector-result JSON storage is used for
candidate artifacts and runtime snapshots. SQLite/MySQL pool behavior is
unchanged and no migration is required.

## API Impact

- Existing `POST /api/v1/discover/actions/run-strategy` behavior remains async
  and may report refresh diagnostics in the task result.
- Existing `GET /api/v1/discover` rows may include `discoveryRunId`,
  `discoveryArtifactStatus`, refreshed technical fields, readiness diagnostics,
  and stale/unprepared fallback diagnostics.
- No new route is added.

## OpenAPI / Backend Layering

- OpenAPI operation impact: additive response fields on existing discover task
  and discover snapshot operations.
- Controller boundary: `app/gateway_api.py` continues to parse requests and map
  responses.
- Service/orchestration boundary: `app/discover/discover.py` and new helper
  modules perform candidate artifact, refresh hydration, scoring, and lifecycle
  handoff.

## UI Impact

No required UI layout change. Existing discover UI can consume backend readiness
fields. UI tests may be updated only if frontend assertions depend on the new
field names.

## Integration Impact

Unified stock refresh may call existing market-data providers for discovered
candidate codes. Tests must mock this IO unless running explicit real E2E
verification.

## Security Impact

No new credentials, authentication, authorization, or secret-bearing config.
Diagnostics must contain only safe stock identifiers, strategy names, numeric
technical fields, provider names, and machine-readable reason codes.

## Error Handling

- Per-stock refresh failures produce `technical_snapshot_status=failed`, safe
  error text, missing fields, and `missing_technical_snapshot` blocking reason.
- Missing or stale runtime snapshot entries produce stale/unprepared diagnostics.
- Discovery task completes with diagnostics even when some candidates fail
  refresh.

## Compatibility / Migration

Old selector files and old candidate events are not migrated. When no current
candidate artifact exists, discover API may show raw selector rows only with
explicit stale/unprepared markers.

## Test Strategy

- Unit tests for candidate artifact save/load, stale fallback, and runtime
  hydration.
- Unit tests for unified refresh writing technical snapshot fields and including
  latest discovery candidates in its code universe.
- API/task tests for discovery task hydrate -> re-score -> lifecycle ingestion
  -> discover API readback consistency.
- Coverage target: at least 90% for changed/affected code.

## Standalone Verification Plan

- Run focused pytest files covering artifact, scheduler, discover task, and
  lifecycle event behavior.
- Run coverage for new/changed discovery helper modules and scheduler changes.
- Run a real backend discovery task through the supported API boundary and
  inspect task diagnostics plus discover API rows. If external provider access
  fails, record the provider failure and locally verify all deterministic logic.

## Real E2E Test Design

Decision: real E2E is required. User-confirmed evidence comes from the prior
requirement for this feature area: "对这个功能而言，跑一次股票发现，检查数据才是完整验证".

Runtime target: local backend API when available.

Flow:

1. Start or use the local backend.
2. Trigger `POST /api/v1/discover/actions/run-strategy` with one bounded
   strategy and small `topN`.
3. Poll task completion.
4. Read `GET /api/v1/discover`.
5. Assert task diagnostics contain refresh/readiness counts, at least one row is
   ready or explicitly failed/stale with safe diagnostics, and non-stale rows do
   not show all technical fields empty.
6. Inspect the local quant DB candidate event payload for the same stock when an
   event is created.

## Rules Compliance

- `PIR-001`: Code paths are listed in this design and will be repeated in tasks.
- `PIR-002`: `discover.py` split plan is required before completion.
- `PIR-003` / `CFG-005`: No DB schema change; existing DB runtime unchanged.
- `PIR-004`: Existing API operations get additive response behavior through the
  existing controller/service split.
- `PIR-005`: Refresh remains async in discovery task and scheduler paths; read
  APIs do not perform market-data IO.
- `PY-001`, `PY-003`, `PY-007`, `PY-008`: Use package-local helpers, explicit
  imports, safe errors, and no secrets.
- `TEST-001`, `TEST-002`, `TEST-003`, `TEST-007`, `TEST-008`, `TEST-010`:
  Parameter files, meaningful tests, mocked external IO, coverage, and review
  evidence are required.

## Source Mapping

| Design Decision | Source | Reason |
|---|---|---|
| Candidate artifact stores source evidence only | Brainstorm Option D | Avoid stale prepared rows becoming technical truth |
| Unified runtime snapshot owns latest technical evidence | User correction and `app/stock_refresh_scheduler.py` | All pages should share the latest refresh logic |
| Post-hydration scoring | Archived lifecycle scoring spec | Technical confirmation must reflect structured indicators |
| Stale raw selector fallback | Current `_discover_rows` behavior and spec fallback requirement | Old raw outputs must not appear current/prepared |
| No DB migration | User history and archived specs | Old data does not need migration |
| Real E2E required | User prior explicit validation requirement | Feature correctness depends on running discovery path |

## Spec Gaps

None blocking. The spec leaves storage and freshness window to design; this
design sets storage to selector-result JSON and technical freshness to runtime
refresh readiness written by the scheduler.
