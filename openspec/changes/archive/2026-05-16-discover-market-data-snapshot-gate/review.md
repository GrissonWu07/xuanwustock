# Review: Discover Market Data Snapshot Gate

## Summary

Implementation is complete. Discovery task results now prepare 30m technical snapshots before lifecycle ingestion, persist readiness diagnostics, block incomplete discovery candidates from automatic lifecycle entry, expose readiness in API/UI, and preserve market-data cache during normal DB reset.

## Requirement Coverage

- Discovery prepares a 30m technical snapshot before lifecycle eligibility: covered by `app/discover/market_snapshot.py`, `app/discover/discover.py`, and backend tests.
- Complete snapshot defines automatic entry readiness: covered by readiness normalization and candidate gate tests.
- Lifecycle gate defends against incomplete discovery inputs: covered by score-only, text-only, false-ready, and complete-snapshot gate tests.
- Discovery results expose technical readiness: covered by API and Vitest UI tests.
- Discovery task reports snapshot preparation diagnostics: covered by task-flow backend and UI completion-summary tests.
- Normal DB cleanup preserves market-data cache: covered by reset script regression test.

## Scenario Coverage

- Complete snapshot is ready and flows to existing lifecycle rules.
- Missing fields are reported and block automatic entry with `missing_technical_snapshot`.
- Provider failures are task diagnostics and do not promote candidates.
- Duplicate discovery rows prepare one snapshot per unique code.
- Empty local TDX cache path calls the existing remote fetcher.
- False `technical_snapshot_ready` flag without structured fields is rejected.
- Zero-valued valid indicators such as `ma20_slope=0.0` and `macd=0.0` are preserved.
- Consumed candidate events for already-in-quant stocks still hydrate discovery-row snapshot diagnostics.
- UI displays ready/incomplete status, missing fields, and preparation counts.
- Reset with `--yes --recreate` preserves `local_sources` cache files.

## Task Completion

All tasks in `tasks.md` are marked complete, including final validation and reviews.

## Per-Task Review Completion

`task-reviews.md` records validation, alignment review, security review, test parameters, and coverage evidence for tasks 1.1 through 5.1. All review findings are closed.

## Out-of-Spec Behavior

None found. The implementation stayed within the approved discovery snapshot gate scope and did not add schema migrations or unrelated lifecycle behavior.

## Architecture Compliance

- Snapshot preparation is isolated in `app/discover/market_snapshot.py`.
- Discovery remains task-asynchronous; the HTTP request starts/polls a task and market-data work runs inside `_run_discover_task`.
- Existing DB runtime and candidate event payload storage are reused.
- TDX market-data fetching uses the existing `SmartMonitorTDXDataFetcher` path.
- Changed source files remain under the 1000-line file-length rule.

## Rules Compliance

- Explicit test parameter files are used by backend and UI tests.
- Tests assert meaningful blocked/ready behavior rather than initialization-only checks.
- External market-data IO is mocked in tests.
- Normal DB reset remains database-file scoped and does not delete cache directories.

## Test Coverage

- `openspec validate discover-market-data-snapshot-gate --strict`: passed before archival; after archival the CLI no longer resolves the original active change id.
- `python -m pytest -q tests\test_discover_market_snapshot.py tests\test_discover_lifecycle_scoring.py tests\test_reset_stock_universe_deployment.py -p no:cacheprovider`: `32 passed`.
- `python -m pytest -q tests\test_discover_market_snapshot.py --cov=app.discover.market_snapshot --cov-report=term-missing -p no:cacheprovider`: `16 passed`, `app\discover\market_snapshot.py` `93%`.
- `npm test -- src/tests/discover-page.test.tsx`: `6 passed`.

## Test Quality

Tests use OpenSpec parameter files, exercise real discovery/lifecycle code paths, and mock only external market data/provider boundaries. New regressions cover the final review findings for remote fetch, false readiness, zero-valued indicator preservation, and consumed-event snapshot hydration.

## Documentation Consistency

The proposal, spec, design, tasks, test parameters, task reviews, and this implementation review are aligned. No spec update was required during implementation.

## Blocking Issues

None.

## Unresolved Findings

None.

## Recommended Fixes

None for this change. A tooling-only note remains: broad coverage instrumentation against pandas-importing modules fails in this Windows Python 3.13 environment with `numpy: cannot load module more than once per process`; targeted functionality tests and focused snapshot coverage pass.
