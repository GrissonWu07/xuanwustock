# Implementation Review: Fix Discover Lifecycle Scoring

## Summary

Implementation completed for the approved OpenSpec change. Discovery results now publish normalized lifecycle inputs, AI scanner structured evidence is preserved, candidate events persist lifecycle diagnostics, discover API/UI exposes score and confidence diagnostics, and discovery task status reports `quantAutoEntry` counts.

## Requirement Coverage

- `Discovery Candidates Publish Lifecycle Inputs`: covered by `app/discover/lifecycle_scoring.py`, `app/discover/discover.py`, and backend tests using `discovery-lifecycle-normalization.md`.
- `AI Discovery Preserves Structured Evidence`: covered by AI scanner normalization tests and candidate event payload tests.
- `Lifecycle Entry Remains Rule Driven`: covered by weak AI recommended-only tests, auto-trial promotion tests, and unchanged lifecycle thresholds/gates.
- `Discovery Task Reports Auto Entry Diagnostics`: covered by task status API tests and discover UI task feedback tests.
- `Existing Historical Records Are Not Rewritten`: covered by read-only enrichment tests that verify existing candidate events are not rewritten during discover snapshot reads.

## Scenario Coverage

Covered scenarios include explicit score evidence, derived non-AI evidence, source-only insufficient evidence, AI structured technical confirmation, weak AI recommended-only behavior, candidate event handoff, discover API row diagnostics, task `quantAutoEntry` diagnostics, UI status/score/confidence rendering, no UTC timestamp in discover table row payloads, and existing batch actions.

## Task Completion

- Task 1.1: complete.
- Task 1.2: complete.
- Task 1.3: complete.
- Task 2.1: complete after this review is recorded and `tasks.md` is updated.

## Per-Task Review Completion

`task-reviews.md` records Alignment Review and Security Review for tasks 1.1, 1.2, 1.3, and 2.1. All review findings found during implementation were fixed and re-reviewed. Open findings: none.

## Out-of-Spec Behavior

None. The implementation did not change lifecycle thresholds, source-family gates, realtime buy/sell decision logic, database schema, DB runtime, old records, or manual batch quant behavior.

## Architecture Compliance

- Discovery normalization is split into `app/discover/lifecycle_scoring.py`.
- `app/discover/discover.py` remains orchestration and response shaping.
- Candidate event persistence and read-only enrichment remain in `app/gateway/quant_universe_entry.py`.
- FastAPI route layer remains transport-only.
- Existing async discovery task flow is preserved.

## Implementation Standards Compliance

- File length guardrail passed; all generated/modified code and test files are <= 1000 lines.
- Existing SQLite/MySQL DB runtime and pool behavior are reused; no new schema or migration.
- Existing API operations are extended backward-compatibly.
- No new runtime or dev dependency was added.

## Rules Compliance

Applied `PIR-001` through `PIR-005` as relevant, `PY-001`, `PY-003`, `PY-007`, `PY-008`, `CFG-005`, `CFG-007`, `CFG-008`, `CFG-009`, and `TEST-001`, `TEST-002`, `TEST-003`, `TEST-007`, `TEST-008`, `TEST-010`.

## Test Coverage

Backend validation:

- `python -m pytest -q tests\test_discover_lifecycle_scoring.py tests\test_ui_backend_api_actions.py::test_discover_snapshot_exposes_read_only_lifecycle_entry_fields tests\test_ui_backend_api_actions.py::test_discover_run_strategy_auto_trial_promotes_discovered_stocks tests\test_ui_backend_api_actions.py::test_discover_run_strategy_executes_real_selector_runners_and_persists_results`
  - `14 passed`.
- Coverage changed/affected backend code:
  - `app/discover/discover.py`: changed lines `17/17 = 100.0%`.
  - `app/discover/lifecycle_scoring.py`: new-file statement lines `194/204 = 95.1%`.
  - `app/gateway/quant_universe_entry.py`: changed lines `18/18 = 100.0%`.

Frontend validation:

- `npm --prefix ui run test -- discover-page.test.tsx`
  - `4 passed`.
- `npm --prefix ui run build`
  - completed; Vite reported the existing large-chunk warning.

## Test Quality

Tests use explicit OpenSpec parameter files under `test-params/`. Assertions verify behavior, payload fields, persistence handoff, lifecycle gate outcome, task status diagnostics, UI rendering, and non-UTC table row output. Tests are not initialization-only and use fake data with isolated temporary SQLite DB files.

## Documentation Consistency

Updated:

- `docs/后端能力与服务接口清单.md`
- `docs/量化股票生命周期与自动入池流程说明.md`

Docs now describe discover candidate diagnostics, `result.quantAutoEntry`, evidence-based scoring, AI structured evidence preservation, and UI lifecycle diagnostic fields.

## Blocking Issues

None.

## Unresolved Findings

None.

## Recommended Fixes

None.
