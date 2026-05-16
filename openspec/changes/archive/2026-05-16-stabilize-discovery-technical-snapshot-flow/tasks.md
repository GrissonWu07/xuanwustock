# Tasks: Stabilize Discovery Refresh Hydration

## 1. Implementation

- [x] 1.1 Add discovery candidate artifact and unified refresh technical snapshot support
  - Related requirement: `Discovery Publishes Current Candidate Evidence`, `Discovery Candidates Use Latest Refreshed Technical Snapshot`
  - Applicable rules: `PIR-001`, `PIR-002`, `PIR-003`, `PIR-005`, `PY-001`, `PY-003`, `PY-007`, `TEST-001`, `TEST-002`, `TEST-003`, `TEST-007`, `TEST-008`, `TEST-010`
  - Target code paths: `app/discover/candidate_artifact.py`, `app/discover/market_snapshot.py`, `app/stock_refresh_scheduler.py`, `tests/test_discover_refresh_hydration.py`
  - Reuse/common logic impact: reuse selector-result storage, market snapshot normalization, and runtime snapshot persistence; no duplicate scoring path
  - Requirement scope / fallback: implement candidate artifact and refresh hydration only; no threshold/gate/cache-deletion behavior
  - Method/function parameter plan: helper functions use explicit parameters or documented artifact/runtime row dictionaries with fixed keys; no function with more than five inputs
  - File size guardrail: each generated/modified code file must stay <= 1000 lines; split plan: new helper module for artifact logic
  - Database impact: no schema change; existing SQLite/MySQL DB runtime unchanged
  - API contract/layers: no new API route; supports additive data for existing discover operations
  - API IO / async: refresh IO remains inside scheduler/discovery task path; read APIs must not fetch remote market data
  - Change: create candidate artifact save/load/hydrate helpers, expose one-code technical snapshot preparation for refresh, persist technical fields in runtime snapshot entries, and include latest discovery candidates in unified refresh collection
  - Standalone verification: `python -m pytest -q tests\test_discover_refresh_hydration.py -p no:cacheprovider` with fake market snapshots and isolated selector-result directory
  - Real E2E test: required at final task level; this task uses mocked IO unit coverage
  - Validation: focused tests plus coverage for new helper module and changed refresh behavior
  - Test parameters: `openspec/changes/stabilize-discovery-technical-snapshot-flow/test-params/candidate-artifact-refresh.md`
  - Coverage target: at least 90% code coverage for changed/affected code
  - Required reviews after implementation:
    - Alignment review against spec, design, task, rules, and changed code
    - Security review against security-sensitive behavior and project-defined security rules
  - Review gate: all findings must be fixed and re-reviewed before the next task starts

- [x] 1.2 Wire discovery task/API/lifecycle to the hydrated candidate view
  - Related requirement: `Discovery API And Lifecycle Ingestion Share Hydrated Evidence`, `Lifecycle Scoring Runs After Refresh Hydration`, `Discovery Fallback Rows Are Explicitly Stale`
  - Applicable rules: `PIR-001`, `PIR-002`, `PIR-004`, `PIR-005`, `PY-001`, `PY-003`, `PY-007`, `TEST-001`, `TEST-002`, `TEST-003`, `TEST-007`, `TEST-008`, `TEST-010`
  - Target code paths: `app/discover/ai_strategy.py`, `app/discover/discover.py`, `tests/test_discover_refresh_hydration.py`, relevant existing discovery tests if needed
  - Reuse/common logic impact: reuse candidate artifact hydration, runtime snapshot entries, lifecycle normalization, and lifecycle ingestion
  - Requirement scope / fallback: lifecycle ingestion and API readback use the hydrated artifact view; raw selector fallback is display-only and stale/unprepared
  - Method/function parameter plan: task orchestration helpers use existing context/payload/task parameters and helper modules; no method/function with more than five inputs
  - File size guardrail: each generated/modified code file must stay <= 1000 lines; split plan: move AI scanner orchestration into `app/discover/ai_strategy.py` so `discover.py` falls below 1000 lines
  - Database impact: no schema change; candidate event payload JSON continues to store diagnostics
  - API contract/layers: additive response fields on existing `POST /api/v1/discover/actions/run-strategy` task result and `GET /api/v1/discover`; controller remains `app/gateway_api.py`, service remains discovery gateway
  - API IO / async: POST task performs refresh asynchronously; GET reads persisted artifact/runtime state and table cache only
  - Change: persist artifact after strategies, trigger bounded unified refresh, hydrate rows from runtime snapshot, re-run lifecycle scoring after hydration, ingest lifecycle events from hydrated rows, make discover API prefer hydrated artifact rows, and mark raw fallback rows stale/unprepared
  - Standalone verification: `python -m pytest -q tests\test_discover_refresh_hydration.py tests\test_discover_market_snapshot.py tests\test_discover_lifecycle_scoring.py -p no:cacheprovider`
  - Real E2E test: required; run a real backend discovery task through the local API with a bounded strategy/topN and verify task diagnostics, discover API rows, and candidate event payload or safe provider failure diagnostics
  - Validation: focused tests, relevant existing discovery tests, coverage, file-length check, and a real API discovery verification when local services are available
  - Test parameters: `openspec/changes/stabilize-discovery-technical-snapshot-flow/test-params/discovery-hydrated-lifecycle.md`
  - Coverage target: at least 90% code coverage for changed/affected code
  - Required reviews after implementation:
    - Alignment review against spec, design, task, rules, and changed code
    - Security review against security-sensitive behavior and project-defined security rules
  - Review gate: all findings must be fixed and re-reviewed before the next task starts
