# Task Reviews: Stabilize Discovery Refresh Hydration

## Summary

All implementation tasks are complete. Alignment Review and Security Review were
run for each task, findings were fixed, and re-review found no open issues.

## Task 1.1: Candidate Artifact And Unified Refresh Snapshot Support

### Alignment Review Round 1

- Scope checked: `app/discover/candidate_artifact.py`,
  `app/discover/market_snapshot.py`, `app/stock_refresh_scheduler.py`, and
  `tests/test_discover_refresh_hydration.py`.
- Findings:
  - Finding 1: Initial coverage for `candidate_artifact.py` and
    `ai_strategy.py` was below 90%.
    - Evidence: coverage run reported total 86%.
    - Fix: added explicit tests for invalid/empty artifact rows and AI scanner
      empty-result/error mapping.
  - Finding 2: Error assertion assumed English text while runtime i18n returned
    Chinese.
    - Evidence: `RuntimeError: AI扫描器未返回候选股票`.
    - Fix: assertion now accepts the observable "no selected candidate" meaning
      in either supported language.

### Alignment Review Round 2

- Result: no open findings.
- Evidence:
  - `python -m pytest -q tests\test_discover_refresh_hydration.py -p no:cacheprovider`
    -> `9 passed`.
  - Coverage for changed discovery helper modules in the combined run reached
    93%.
  - File lengths: `candidate_artifact.py` 297 lines,
    `market_snapshot.py` 331 lines, `stock_refresh_scheduler.py` 845 lines.

### Security Review

- Checked data handling, persisted artifact shape, safe diagnostics, provider
  failures, secrets, and remote IO boundaries.
- Result: no open findings.
- Evidence:
  - Artifact rows persist stock identifiers, source evidence, numeric technical
    values, status, provider, timeframe, and safe reason text only.
  - Unified refresh failures are converted into per-stock failed technical
    snapshot diagnostics and do not expose credentials.
  - No new dependencies, schema changes, authentication changes, or secret
    config were introduced.

## Task 1.2: Discovery Task/API/Lifecycle Hydrated View

### Alignment Review Round 1

- Scope checked: `app/discover/discover.py`, `app/discover/ai_strategy.py`,
  `app/gateway/quant_universe_entry.py`, discovery API tests, lifecycle tests,
  and UI backend discovery action tests.
- Findings:
  - Finding 1: Real E2E showed a `low_price_bull` task mixed prior
    `ai_scanner` selector cache into the current candidate artifact.
    - Evidence: first real API run `discover-a2775716b6` returned candidate
      count 51 and included `ai_scanner` rows even though only
      `low_price_bull` was requested.
    - Root cause: `_run_discover_task` built artifact rows from all latest
      selector snapshots instead of only strategies completed by the current
      task.
    - Fix: `_raw_discover_rows` now accepts a completed strategy filter, and
      `_run_discover_task` saves only current completed strategy rows into the
      artifact. Added regression test
      `test_discovery_task_artifact_only_uses_completed_strategies`.

### Alignment Review Round 2

- Result: no open findings.
- Evidence:
  - `python -m pytest -q tests\test_discover_refresh_hydration.py tests\test_discover_market_snapshot.py tests\test_discover_lifecycle_scoring.py tests\test_ui_backend_api_actions.py::test_discover_snapshot_aggregates_selector_results tests\test_ui_backend_api_actions.py::test_discover_snapshot_exposes_read_only_lifecycle_entry_fields tests\test_ui_backend_api_actions.py::test_discover_run_strategy_auto_trial_promotes_discovered_stocks tests\test_ui_backend_api_actions.py::test_discover_run_strategy_executes_real_selector_runners_and_persists_results -p no:cacheprovider`
    -> `40 passed`.
  - Coverage command:
    `python -m pytest -q tests\test_discover_refresh_hydration.py tests\test_discover_market_snapshot.py tests\test_discover_lifecycle_scoring.py tests\test_ui_backend_api_actions.py::test_discover_run_strategy_auto_trial_promotes_discovered_stocks --cov=app.discover.candidate_artifact --cov=app.discover.ai_strategy --cov=app.discover.market_snapshot --cov-report=term-missing -p no:cacheprovider`
    -> `37 passed`, total coverage `93%`.
  - Real E2E re-run against temporary backend `http://127.0.0.1:8519`:
    `POST /api/v1/discover/actions/run-strategy` with
    `{"strategies":["low_price_bull"],"topN":1,"waitMs":1000}` completed task
    `discover-a52dd81a84`.
  - E2E assertions: task status `completed`, candidate count `1`, discover API
    strategy keys `["low_price_bull"]`, bad strategy keys `[]`, ready rows `1`,
    technical snapshot complete `1`, and latest candidate event payload for
    `003016` had `technical_snapshot_ready=true`, status `ready`, `ma20=8.1935`,
    `trend=up`, and `technical_confirmation_count=2`.
  - File lengths: `discover.py` 1000 lines, `ai_strategy.py` 107 lines,
    `quant_universe_entry.py` 458 lines. Existing
    `tests/test_ui_backend_api_actions.py` is a pre-existing oversized test
    module; only minimal compatibility assertions were changed there, while new
    coverage for this change lives in `tests/test_discover_refresh_hydration.py`
    at 377 lines.

### Security Review

- Checked authorization surface, async task IO, read API behavior, diagnostics,
  stale fallback handling, and data mutation.
- Result: no open findings.
- Evidence:
  - No new API route, credential, authorization bypass, schema migration, or
    dependency was added.
  - `GET /api/v1/discover` reads persisted artifact/runtime state only and does
    not perform remote market-data IO.
  - Expensive refresh remains inside the async discovery task and unified
    scheduler.
  - Raw selector fallback rows are marked `stale_unprepared` and blocked with
    `missing_technical_snapshot`; they cannot appear as current prepared
    candidates.

## Implementation Standards Evidence

- Requirement scope: no threshold, gate, buy/sell, cache deletion, or UI layout
  behavior was changed.
- Reuse/common logic: selector result storage, runtime snapshot persistence,
  market snapshot preparation, lifecycle normalization, and lifecycle ingestion
  were reused.
- Parameter plan: new functions use no more than five explicit inputs and use
  documented artifact/runtime row dictionaries.
- Database/API/IO: no schema change; existing SQLite/MySQL runtime unchanged;
  existing discover POST remains async; existing discover GET remains read-only.
- Test parameters: independent files exist under
  `openspec/changes/stabilize-discovery-technical-snapshot-flow/test-params/`.

## Open Findings

None.
