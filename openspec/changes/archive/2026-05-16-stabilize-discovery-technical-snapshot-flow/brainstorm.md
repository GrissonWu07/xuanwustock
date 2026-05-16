# Brainstorm: Stabilize Discovery Technical Snapshot Flow

## Problem

Stock discovery currently has multiple partially overlapping sources and refresh views:

- selector result JSON files under `data/selector_results`
- transient rows prepared inside the asynchronous discovery task
- candidate event payload JSON in the quant database
- discover API rows rebuilt from selector result snapshots
- lifecycle status fields hydrated from candidate events and quant universe state
- unified stock runtime snapshot entries maintained by the stock refresh scheduler

The previous changes required discovered stocks to prepare 30m market data and technical indicators before lifecycle eligibility. Local investigation confirms the market snapshot preparation function can fetch and compute MA, MACD, RSI, amount, volume ratio, trend, and metadata for current discovery rows. However, the discover API can still show rows with all technical fields empty because it rebuilds rows from stale selector results that never stored prepared technical snapshots. Old candidate events created before the snapshot-readiness change also lack snapshot payload fields.

The workflow is therefore confusing:

1. Discovery task prepares technical snapshots only in-memory.
2. Lifecycle ingestion receives those prepared rows.
3. The discover page later reloads from selector result JSON and loses the prepared technical fields.
4. Lifecycle scoring may have been normalized before technical snapshot preparation, so technical confirmation can remain stale.
5. The unified stock refresh scheduler already exists but currently does not clearly own discovered candidate codes or expose a full latest technical snapshot for discovery/lifecycle reads.
6. Users see candidates that look discovered but not technically prepared, even when the current preparation service can prepare them.

The product need is a clear discovery-to-quant contract: discovery should persist the candidate set and source evidence, the unified stock refresh path should own latest 30m quote and technical snapshots for those candidates, and both lifecycle ingestion and discover API reads should hydrate from the same latest refreshed snapshot view. A prepared discovery artifact is still useful, but it must not become a long-lived substitute for the unified stock refresh runtime data.

## User Scenarios

- A user runs stock discovery and expects discovered candidates to have 30m quote and technical indicators prepared before automatic quant lifecycle judgment.
- A user opens the discover page after a completed run and expects the table/detail diagnostics to use the latest stock refresh snapshot, not a stale raw selector row.
- A user expects lifecycle ingestion and discover API rendering to evaluate against the same latest market/technical evidence for a candidate.
- A user sees a candidate blocked from auto entry and expects a machine-readable reason such as `missing_technical_snapshot`, plus missing field names or provider failure reason.
- A user sees an already-in-quant candidate and expects readiness diagnostics to remain visible rather than disappearing because candidate events were consumed.
- A user reruns discovery after old selector data exists and expects new rows to supersede stale rows for snapshot readiness and lifecycle scoring, without migrating old records.

## Scope

- Define a discovery candidate artifact that preserves the latest discovered candidate set, source evidence, run metadata, and initial preparation summary.
- Ensure discovered candidate codes are included in the unified stock refresh universe so 30m quote and technical indicators are fetched/updated through the shared refresh path.
- Ensure discover API rows and automatic lifecycle candidate ingestion both hydrate from the same latest refreshed stock snapshot view before scoring or display.
- Ensure lifecycle score/confidence/trend/technical confirmation are calculated after latest snapshot hydration, not from raw selector text alone.
- Ensure stale selector rows or old candidate events without technical snapshots are labeled as stale/unprepared instead of appearing like current prepared output.
- Preserve the hard rule that incomplete technical snapshots cannot auto-enter quant trial state.
- Preserve historical records without database migration, while making new discovery runs correct.

## Out of Scope

- Changing buy/sell signal logic for realtime simulation or historical replay.
- Lowering lifecycle trial thresholds, source-family gates, or capacity limits.
- Deleting or migrating old DB records.
- Deleting market-data cache files.
- Introducing a new database schema unless design later proves JSON/cache persistence cannot satisfy the contract.
- UI redesign beyond surfacing accurate readiness/status from the backend contract.

## Candidate Requirements

- A completed discovery task MUST persist a candidate artifact containing discovered codes, names, source strategy, source score/confidence evidence, selected-at time, run id, and preparation summary.
- Discovered candidate codes MUST be registered for unified stock refresh before lifecycle eligibility is evaluated.
- Unified stock refresh MUST prepare or update the 30m quote and technical snapshot used by discovery, lifecycle ingestion, and discover API rendering.
- Discover API rows MUST be built from the latest discovery candidate artifact hydrated with the latest unified stock refresh snapshot.
- If no refreshed technical snapshot exists or the snapshot is stale/incomplete, discover API rows MUST explicitly mark rows as stale/unprepared and expose missing fields or refresh failure reason.
- Automatic lifecycle ingestion MUST consume the same hydrated candidate view that discover API exposes, not raw selector result JSON.
- Lifecycle score normalization MUST run after latest snapshot hydration so `trend` and `technical_confirmation_count` reflect MA/MACD/RSI evidence.
- Candidate event payloads MUST include the refreshed technical fields, readiness diagnostics, and snapshot timestamp/provider for new discovery runs.
- Candidate event ingestion MUST preserve event gate diagnostics in payload JSON after status changes such as `eligible` or `consumed`.
- Already-in-quant rows MUST still expose the latest refreshed technical snapshot diagnostics when available.
- Tests MUST include a case where selector source rows have no technical fields but unified refresh prepares a complete snapshot; the API and event payload must both expose the refreshed fields.
- Tests MUST include a stale old-selector case that does not silently present all-empty technical fields as current prepared output.

## Alternative Solutions

### Option A: Persist prepared discovery rows as the canonical selector result

After `_run_discover_task` prepares snapshots and recalculates lifecycle scoring, write the enriched rows back to the existing selector result storage for the active strategy/all-strategy aggregate. `_discover_rows` then naturally reads prepared rows.

Pros:
- Minimal new concepts.
- Discover API keeps current source path.
- Easy to reason about for UI.

Cons:
- Existing selector result files currently represent strategy raw output; overwriting them with prepared rows mixes raw selector output with runtime-prepared lifecycle evidence.
- Multi-strategy aggregation may be awkward because each strategy file is saved before the global snapshot preparation step.

### Option B: Add a dedicated prepared discovery artifact only

Create a separate prepared-discovery artifact owned by discovery, for example under selector result storage or DB runtime cache, keyed by latest discovery task/run. `_run_discover_task` writes prepared rows there after snapshot preparation and post-snapshot normalization. `_snapshot_discover` reads that artifact first; raw selector results are fallback/stale context only.

Pros:
- Clear separation between raw strategy output and lifecycle-ready discovery output.
- Avoids mutating selector semantics.
- Gives a single source for API/UI and lifecycle ingestion.
- Can carry run id, preparation summary, scorer version, snapshot timestamp, and stale markers.

Cons:
- Requires a new small repository/helper and tests.
- Need explicit fallback behavior when no prepared artifact exists.
- Risks duplicating the unified stock refresh responsibility and letting discover API drift away from the latest refreshed market/technical data over time.

### Option C: Re-prepare snapshots on every discover API read

Keep selector result files as-is and call `prepare_discovery_market_snapshots` inside `_snapshot_discover` before returning rows.

Pros:
- No new persistence artifact.
- Discover page always attempts to hydrate technical fields.

Cons:
- Violates API IO expectations for a read endpoint; it can trigger network/file IO and become slow.
- Can make UI reads mutate caches unpredictably.
- Duplicates the async task responsibility.
- Harder to ensure lifecycle ingestion and UI used the exact same evidence.

### Option D: Discovery candidate artifact plus unified stock refresh snapshot

Persist discovery output as candidate identity/source evidence, then register discovered codes into the unified stock refresh universe. Discovery task completion triggers or awaits a bounded refresh for those codes. Lifecycle ingestion and discover API rendering both hydrate the candidate artifact from the latest refreshed stock runtime snapshot and then run post-hydration lifecycle scoring.

Pros:
- Keeps raw selector output, candidate identity, and latest market/technical data in separate ownership boundaries.
- Matches the existing direction that all stock views should use the same refresh logic for latest quote and technical indicators.
- Prevents a prepared discovery artifact from becoming stale immediately after the market moves.
- Gives lifecycle and UI the same hydrated candidate view without doing expensive market IO in read APIs.

Cons:
- Requires the refresh scheduler/runtime snapshot to cover discovered candidates, not only watchlist/portfolio/active quant stocks.
- Requires a clear freshness policy for when lifecycle evaluation must wait, block, or mark `missing_technical_snapshot`.
- May require extending runtime snapshot storage to carry technical indicators, not only latest price/basic info.

## Recommended Direction

Use Option D: persist a discovery candidate artifact and make unified stock refresh the owner of latest market/technical snapshots.

The target flow should be:

1. Run selected discovery strategies and store raw strategy outputs as today.
2. Build and persist a latest discovery candidate artifact from raw outputs, including source evidence and run metadata.
3. Register the discovered codes into the unified stock refresh universe.
4. Trigger or await a bounded unified refresh that fetches 30m quote and technical indicators for those codes.
5. Hydrate candidate rows from the latest refreshed stock snapshot.
6. Re-run lifecycle scoring normalization on the hydrated rows.
7. Ingest lifecycle candidate events from that same hydrated candidate view.
8. Serve discover API rows from the latest candidate artifact hydrated with the same refreshed stock snapshot.
9. Fall back to raw selector rows only with explicit stale/unprepared diagnostics.

This preserves previous OpenSpec intent while removing the confusing split between raw selector output, discovery lifecycle evidence, and latest market/technical data. The prepared discovery artifact is no longer the long-term source of technical truth; it is a run artifact and refresh coordination point.

## Impacted Modules

- `app/discover/discover.py`
  - Discovery task orchestration, row building, API snapshot source selection, task result summaries.
- `app/discover/market_snapshot.py`
  - Snapshot preparation may become the per-code technical snapshot implementation used by unified refresh, or be refactored behind a shared refresh service.
- `app/discover/lifecycle_scoring.py`
  - Must run after latest snapshot hydration for discovery task output.
- `app/gateway/quant_universe_entry.py`
  - Candidate event payload and row enrichment should preserve/hydrate refreshed diagnostics.
- `app/stock_refresh_scheduler.py`
  - Must include discovered candidates in the refresh universe and persist latest technical snapshot fields, not only latest price/basic info.
- `app/selector_result_store.py` or a new discovery artifact repository
  - Potential home for the discovery candidate artifact and refresh registration metadata.
- `app/ui_table_cache_db.py`
  - Possible existing cache mechanism, but should not become the technical source of truth unless design explicitly chooses it.
- `tests/test_discover_market_snapshot.py`
  - Add/adjust integration tests for candidate artifact persistence, refresh hydration, and API readback.
- `tests/test_discover_lifecycle_scoring.py`
  - Add post-snapshot normalization expectations.
- `ui/src/features/discover/discover-page.tsx`
  - UI should consume backend-ready diagnostics; no speculative client logic.

## Risks

- If candidate artifacts are stored in files, concurrent discovery tasks may race unless the artifact includes task id and atomic replacement.
- If candidate artifacts or runtime snapshots are stored in DB, the design must respect DB runtime and connection pool rules.
- Re-normalizing after latest snapshot hydration changes candidate scores for new runs; this is intended but must be visible in tests and task diagnostics.
- Old selector data will still exist; fallback wording must make stale/unprepared status explicit.
- Discovery runs may remain slower when many candidates require 30m preparation. That belongs to async task execution, not page reads.
- If the refresh scheduler only tracks watchlist/portfolio/active quant stocks, newly discovered but not-yet-entered candidates will remain unprepared. The refresh universe must include latest discovery candidates.

## Open Questions

- Should the discovery candidate artifact live in DB runtime, selector result storage, or a dedicated JSON file under `selector_results`?
- Should the discover API hide stale raw rows by default when no candidate artifact exists, or show them with an explicit stale/unprepared status?
- Should candidate artifacts be per-strategy and aggregate, or only aggregate latest-run output?
- How long should discovery candidate artifacts be retained?
- What freshness window should make a technical snapshot acceptable for auto lifecycle evaluation?
- Should refresh completion be required for discovery task completion, or can task complete with blocked/unprepared rows while a background refresh continues?
- Should task id be exposed on discover rows for traceability?

## Suggested Change ID

`stabilize-discovery-technical-snapshot-flow`
