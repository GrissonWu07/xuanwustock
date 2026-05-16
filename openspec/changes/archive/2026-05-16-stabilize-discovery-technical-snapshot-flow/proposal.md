# Change: Stabilize Discovery Refresh Hydration

## Why

Stock discovery can still display candidates with empty technical fields even
after the discovery task prepared market snapshots for lifecycle evaluation.
The visible result is confusing: selector output, task-prepared rows, candidate
events, and later discover API reads can disagree about whether a candidate has
30m market and technical evidence.

The system needs one observable discovery-to-lifecycle contract: discovery
stores candidate identity and source evidence, latest stock refresh owns the
30m market/technical snapshot, and lifecycle ingestion plus discover API reads
use the same hydrated candidate view.

## What Changes

- Discovery runs publish a current candidate artifact with source evidence,
  run traceability, and preparation diagnostics.
- Discovered stock codes are included in the latest-stock refresh scope before
  lifecycle eligibility is published.
- Discovery rows are hydrated from the latest refreshed 30m technical snapshot
  before lifecycle scoring and API rendering.
- Lifecycle candidate event payloads and discover API rows expose matching
  refreshed technical fields, readiness status, and blocking diagnostics.
- Raw selector output is only a stale/unprepared fallback and must be labeled as
  such when no current hydrated candidate view exists.

## Scope

- Discovery task output, discover API rows, and lifecycle candidate event handoff.
- Latest refreshed 30m quote and technical snapshot evidence for discovered
  candidates.
- Post-refresh lifecycle score normalization and technical confirmation evidence.
- Stale/unprepared fallback diagnostics for old selector results.

## Out of Scope

- Changing buy/sell signal logic for realtime simulation or historical replay.
- Lowering lifecycle thresholds, source-family gates, or capacity limits.
- Migrating or rewriting historical candidate records.
- Deleting or rebuilding market-data cache files.
- UI redesign beyond using backend-provided readiness/status fields.

## Impact

- Backend discovery task behavior becomes stricter and more traceable.
- Discover API consumers receive refreshed technical evidence or explicit
  stale/unprepared diagnostics.
- Lifecycle candidate events for new runs persist the same refreshed evidence
  that API consumers see.
- Tests must cover selector rows with no technical fields, refresh hydration,
  lifecycle ingestion, API readback, stale fallback behavior, and a real
  discovery task verification path.

## Rules Applied

- `PIR-001`: Design and tasks must identify target code paths.
- `PIR-002`: Modified/generated files must remain at or below 1000 lines.
- `PIR-003` / `CFG-005`: Any DB-backed storage decision must document SQLite,
  MySQL, and connection-pool behavior.
- `PIR-004`: API-visible behavior must be documented and layered through the
  existing backend API boundary.
- `PIR-005`: Market-data preparation must remain asynchronous and must not be
  performed by discover read requests.
- `PY-001`, `PY-003`, `PY-007`, `PY-008`: Python code must follow project
  layout, import, error-handling, and secret-safety rules.
- `TEST-001`, `TEST-002`, `TEST-003`, `TEST-007`, `TEST-008`, `TEST-010`:
  Tests need explicit parameters, meaningful assertions, isolated external IO
  where appropriate, coverage evidence, and review evidence.

## Risks

- Discovery tasks may take longer when many newly discovered candidates require
  30m refresh work.
- Existing old selector caches may still exist; fallback labeling must prevent
  users from interpreting them as current prepared results.
- If the latest refresh snapshot is stale, the lifecycle decision must block or
  clearly report stale evidence instead of silently using old indicators.
- A storage choice that duplicates latest technical data would risk drifting
  from the unified refresh path.

## Open Questions

- None blocking for spec. Design must decide the storage location for the
  discovery candidate artifact and the freshness window for refreshed
  snapshots.
