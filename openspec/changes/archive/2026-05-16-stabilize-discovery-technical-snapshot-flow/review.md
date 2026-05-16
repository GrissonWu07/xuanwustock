# Implementation Review: Stabilize Discovery Refresh Hydration

## Summary

The implementation now uses a current discovery candidate artifact as source
evidence and the unified stock refresh runtime snapshot as the latest technical
truth. Discovery lifecycle ingestion and discover API rows share the same
hydrated view. Raw selector fallback rows are explicitly stale/unprepared.

## Requirement Coverage

- `Discovery Publishes Current Candidate Evidence`: covered by candidate artifact
  persistence, run id exposure, and selected strategy scoping.
- `Discovery Candidates Use Latest Refreshed Technical Snapshot`: covered by
  unified refresh technical snapshot persistence and hydrated row diagnostics.
- `Discovery API And Lifecycle Ingestion Share Hydrated Evidence`: covered by
  shared artifact/runtime hydration before API readback and lifecycle ingestion.
- `Lifecycle Scoring Runs After Refresh Hydration`: covered by
  `renormalize_hydrated_discovery_rows`.
- `Discovery Fallback Rows Are Explicitly Stale`: covered by
  `mark_rows_stale_unprepared`.

## Scenario Coverage

- Selector result without technical fields is hydrated from runtime snapshot.
- Complete refreshed snapshots are exposed in API rows and candidate events.
- Missing/stale fallback rows are blocked with `missing_technical_snapshot`.
- Current task artifact is limited to strategies completed in that task.
- Real API discovery run verifies task diagnostics, discover rows, and candidate
  event technical payload.

## Task Completion

- Task 1.1: complete.
- Task 1.2: complete.

## Per-Task Review Completion

`task-reviews.md` records Alignment Review and Security Review for both tasks.
All findings are closed.

## Out-of-Spec Behavior

None found. The change did not alter thresholds, lifecycle gates, capacity,
trading logic, cache deletion, or UI layout.

## Architecture Compliance

- Candidate source evidence and latest technical evidence are separated.
- Unified stock refresh owns current 30m technical snapshot hydration.
- Discovery POST remains async; discover GET remains read-only.
- Existing gateway controller and discovery service boundaries are preserved.
- AI scanner orchestration was split into `app/discover/ai_strategy.py` to keep
  `app/discover/discover.py` at the 1000-line limit.

## Implementation Standards Compliance

- No new dependencies.
- No schema migration or database runtime change.
- Reused selector result storage, runtime snapshot storage, market snapshot
  preparation, lifecycle normalization, and lifecycle ingestion.
- New/changed implementation files are at or below 1000 lines:
  `discover.py` 1000, `candidate_artifact.py` 297, `ai_strategy.py` 107,
  `market_snapshot.py` 331, `stock_refresh_scheduler.py` 845,
  `quant_universe_entry.py` 458.
- Existing `tests/test_ui_backend_api_actions.py` remains a pre-existing
  oversized test module. New change-specific coverage was placed in
  `tests/test_discover_refresh_hydration.py`; only minimal compatibility edits
  were made to the existing oversized test to keep its existing API action
  scenarios valid.

## Rules Compliance

- `PIR-001`: implementation paths are mapped in design/tasks and review.
- `PIR-002`: production files stay within the file-size guardrail.
- `PIR-003` / `CFG-005`: no new database schema or pool behavior.
- `PIR-004`: existing API operations keep controller/service separation.
- `PIR-005`: expensive market IO is async task/scheduler work, not read API work.
- `PY-001`, `PY-003`, `PY-007`: package-local helpers, explicit imports, and
  safe diagnostics.
- `TEST-001`, `TEST-002`, `TEST-003`, `TEST-007`, `TEST-008`, `TEST-010`:
  independent parameter files, meaningful assertions, mocked external IO for
  unit tests, coverage evidence, real E2E evidence, and review evidence.

## Test Coverage

Coverage command:

```powershell
python -m pytest -q tests\test_discover_refresh_hydration.py tests\test_discover_market_snapshot.py tests\test_discover_lifecycle_scoring.py tests\test_ui_backend_api_actions.py::test_discover_run_strategy_auto_trial_promotes_discovered_stocks --cov=app.discover.candidate_artifact --cov=app.discover.ai_strategy --cov=app.discover.market_snapshot --cov-report=term-missing -p no:cacheprovider
```

Result: `37 passed`, total coverage `93%`.

Module coverage:

- `app\discover\ai_strategy.py`: `90%`
- `app\discover\candidate_artifact.py`: `96%`
- `app\discover\market_snapshot.py`: `91%`

The run emitted existing SQLite `ResourceWarning` messages from test DB runtime
cleanup. They did not fail the command and are not introduced by this discovery
hydration change.

## Test Quality

Tests use explicit stock codes, strategy names, scores, timestamps, and expected
technical fields saved under `test-params/`. Tests assert behavior through
artifact persistence, scheduler runtime entries, discover API rows, task
diagnostics, and lifecycle candidate events. No test only verifies class or
method initialization.

## Documentation Consistency

OpenSpec proposal, spec, design, tasks, test parameters, and task reviews are
aligned with the implemented source paths and verification evidence. Wiki
documentation will be generated during `/sp-complete`.

## Final Code Review Pass 1

Finding:

- Real E2E mixed old `ai_scanner` selector cache into a current
  `low_price_bull` run.

Fix:

- `_raw_discover_rows` now accepts the set of completed strategy keys.
- `_run_discover_task` stores only current completed strategy rows in the
  candidate artifact.
- Added regression test
  `test_discovery_task_artifact_only_uses_completed_strategies`.

Re-review result: no open findings.

## Final Code Review Pass 2

Checked the full diff after the strategy-scope fix for regressions, stale
fallback behavior, security-sensitive data handling, API IO boundaries, file
sizes, and coverage evidence.

Result: no open findings.

## Blocking Issues

None.

## Unresolved Findings

None.

## Recommended Fixes

None for this change.
