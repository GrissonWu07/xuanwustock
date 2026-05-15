# Task Reviews: Fix Discover Lifecycle Scoring

## Task 1.1 Add Discovery Lifecycle Normalization Boundary

### Implementation Summary

- Added `app/discover/lifecycle_scoring.py` as the discovery lifecycle normalization boundary.
- Updated `app/discover/discover.py` to preserve AI scanner structured fields and normalize discovery rows with rank/strategy context.
- Added explicit test parameters at `openspec/changes/fix-discover-lifecycle-scoring/test-params/discovery-lifecycle-normalization.md`.
- Added `tests/test_discover_lifecycle_scoring.py`.

### Validation Evidence

- `python -m pytest -q tests/test_discover_lifecycle_scoring.py`
  - Result: `3 passed`.
- `python -m coverage run -m pytest --noconftest -q tests/test_discover_lifecycle_scoring.py`
  - Result: `3 passed`.
- `python -m coverage report -m app\discover\lifecycle_scoring.py`
  - Result: `app\discover\lifecycle_scoring.py` coverage `92%`.
- File length check:
  - `app/discover/discover.py`: 996 lines.
  - `app/discover/lifecycle_scoring.py`: 362 lines.
  - `tests/test_discover_lifecycle_scoring.py`: 100 lines.

### Alignment Review

Reviewed against `proposal.md`, `specs/discover-lifecycle-entry/spec.md`, `design.md`, task 1.1, and project rules.

Findings: none.

Closure evidence:

- AI scanner strategy preserves `scanner_score`, `source_score`, `confidence`, `trend`, `technical_confirmation_count`, and `technical_reasons`.
- Non-AI candidates with measurable evidence derive nonzero score/confidence.
- Source-only candidates remain zero-score with `insufficient_measurable_evidence`.
- Scoring logic is split out of `discover.py`, preserving the file-size guardrail.

### Security Review

Reviewed data handling, diagnostics, logging, dependencies, and external IO.

Findings: none.

Closure evidence:

- No new dependencies were added.
- The normalizer performs no network, file, or database IO.
- Diagnostics contain strategy keys, evidence bucket names, and reason codes only.
- No credentials, tokens, provider payloads, or secrets are logged or persisted by this task.

### Open Findings

None.

## Task 1.2 Persist Normalized Lifecycle Evidence Into Candidate Events

### Implementation Summary

- Updated `app/gateway/quant_universe_entry.py` so candidate event payloads persist normalized `source_score`, `confidence`, `trend`, technical confirmation count, technical reasons, and lifecycle score diagnostics.
- Updated read-only lifecycle enrichment to expose `candidate_confidence` alongside `candidate_score`, quant status, blocking reason, and already-in-quant status.
- Preserved zero-valued normalized evidence instead of dropping it through truthy fallback logic.
- Added explicit test parameters at `openspec/changes/fix-discover-lifecycle-scoring/test-params/lifecycle-event-handoff.md`.

### Validation Evidence

- `python -m pytest -q tests\test_discover_lifecycle_scoring.py`
  - Result: `9 passed`.
- `python -m pytest -q tests\test_discover_lifecycle_scoring.py tests\test_ui_backend_api_actions.py::test_discover_snapshot_exposes_read_only_lifecycle_entry_fields tests\test_ui_backend_api_actions.py::test_discover_run_strategy_auto_trial_promotes_discovered_stocks tests\test_ui_backend_api_actions.py::test_discover_run_strategy_executes_real_selector_runners_and_persists_results`
  - Result: `12 passed`.
- `python -m coverage run -m pytest --noconftest -q tests\test_discover_lifecycle_scoring.py tests\test_ui_backend_api_actions.py::test_discover_snapshot_exposes_read_only_lifecycle_entry_fields tests\test_ui_backend_api_actions.py::test_discover_run_strategy_auto_trial_promotes_discovered_stocks tests\test_ui_backend_api_actions.py::test_discover_run_strategy_executes_real_selector_runners_and_persists_results`
  - Result: `12 passed`.
- `python -m coverage report -m app\discover\lifecycle_scoring.py app\gateway\quant_universe_entry.py app\discover\discover.py`
  - Result: `app\discover\lifecycle_scoring.py` coverage `94%`; full-file coverage for `app\discover\discover.py` and `app\gateway\quant_universe_entry.py` remains lower due existing unrelated branches.
- Changed/affected code coverage from coverage JSON and git diff:
  - `app/discover/discover.py`: changed lines `16/17 = 94.1%`.
  - `app/discover/lifecycle_scoring.py`: new-file statement lines `192/204 = 94.1%`.
  - `app/gateway/quant_universe_entry.py`: changed lines `8/8 = 100.0%`.
- File length check:
  - `app/discover/discover.py`: 996 lines.
  - `app/discover/lifecycle_scoring.py`: 362 lines.
  - `app/gateway/quant_universe_entry.py`: 389 lines.
  - `tests/test_discover_lifecycle_scoring.py`: 227 lines.

### Alignment Review

Reviewed against `proposal.md`, `specs/discover-lifecycle-entry/spec.md`, `design.md`, task 1.2, and project rules.

Findings found and fixed:

- Candidate event payload nested diagnostics used truthy fallback for `source_score` and `confidence`, so normalized `0.0` evidence could be persisted as `None`.
  - Fix: compute top-level normalized `source_score`, `confidence`, and `trend` once and persist the same values into nested payload diagnostics.
  - Re-review result: no open alignment findings.

Closure evidence:

- Normalized AI evidence is preserved in candidate event payloads.
- Read-only discover row enrichment exposes `candidate_confidence`.
- Weak AI candidates without technical confirmation remain recommended-only with reason `ai_requires_technical_confirmation`; thresholds and gates were not lowered.
- Existing historical records are not rewritten; tests create only new candidate events in isolated temporary SQLite databases.

### Security Review

Reviewed data handling, diagnostics, persistence payload, dependencies, credentials, logging, and database behavior.

Findings: none.

Closure evidence:

- No new dependencies, network IO, credentials, or configuration files were added.
- Tests use isolated temporary SQLite database files and fake stock data only.
- Persisted diagnostics contain safe numeric evidence, strategy keys, stock codes, and machine-readable reason codes.
- Existing DB runtime and lifecycle manager are reused; no schema migration or pool change was introduced.

### Open Findings

None.

## Task 1.3 Expose Discover API/UI Lifecycle Diagnostics

### Implementation Summary

- Preserved discover-stage `candidate_score` and `candidate_confidence` when lifecycle enrichment has no persisted candidate event yet.
- Added discover API regression coverage for normalized score, confidence, technical confirmation, diagnostics, and non-UTC table time.
- Added discover task status regression coverage for `result.quantAutoEntry` attempted/events/promoted/eligible/skipped diagnostics.
- Updated discover UI badges to show score and confidence next to lifecycle status and blocking reason.
- Updated discover UI task completion feedback to show auto-entry counts.
- Updated frontend response types and locale entries for score and auto-entry diagnostics.
- Updated API and lifecycle documentation.
- Added explicit test parameters at `openspec/changes/fix-discover-lifecycle-scoring/test-params/discover-api-ui-diagnostics.md`.

### Validation Evidence

- `python -m pytest -q tests\test_discover_lifecycle_scoring.py`
  - Result: `11 passed`.
- `python -m pytest -q tests\test_ui_backend_api_actions.py::test_discover_snapshot_exposes_read_only_lifecycle_entry_fields tests\test_ui_backend_api_actions.py::test_discover_run_strategy_auto_trial_promotes_discovered_stocks tests\test_ui_backend_api_actions.py::test_discover_run_strategy_executes_real_selector_runners_and_persists_results`
  - Result: `3 passed`.
- `python -m coverage erase`
  - Result: completed.
- `python -m coverage run -m pytest --noconftest -q tests\test_discover_lifecycle_scoring.py`
  - Result: `11 passed`.
- `python -m coverage run --append -m pytest --noconftest -q tests\test_ui_backend_api_actions.py::test_discover_snapshot_exposes_read_only_lifecycle_entry_fields tests\test_ui_backend_api_actions.py::test_discover_run_strategy_auto_trial_promotes_discovered_stocks tests\test_ui_backend_api_actions.py::test_discover_run_strategy_executes_real_selector_runners_and_persists_results`
  - Result: `3 passed`.
- `python -m coverage report -m app\discover\lifecycle_scoring.py app\gateway\quant_universe_entry.py app\discover\discover.py`
  - Result: `app\discover\lifecycle_scoring.py` coverage `95%`; full-file coverage for existing broad modules remains lower due unrelated legacy branches.
- Changed/affected backend code coverage from coverage JSON and git diff:
  - `app/discover/discover.py`: changed lines `17/17 = 100.0%`.
  - `app/discover/lifecycle_scoring.py`: new-file statement lines `194/204 = 95.1%`.
  - `app/gateway/quant_universe_entry.py`: changed lines `18/18 = 100.0%`.
- `npm --prefix ui run test -- discover-page.test.tsx`
  - Result: `4 passed`.
- `npm --prefix ui run build`
  - Result: TypeScript build and Vite build completed; Vite reported an existing bundle-size warning.
- File length check:
  - `app/discover/discover.py`: 996 lines.
  - `app/discover/lifecycle_scoring.py`: 362 lines.
  - `app/gateway/quant_universe_entry.py`: 398 lines.
  - `tests/test_discover_lifecycle_scoring.py`: 297 lines.
  - `ui/src/features/discover/discover-page.tsx`: 815 lines.
  - `ui/src/features/quant/quant-entry-controls.tsx`: 152 lines.
  - `ui/src/lib/page-models.ts`: 665 lines.
  - `ui/src/tests/discover-page.test.tsx`: 284 lines.
  - `ui/src/locales/en-US.json`: 703 lines.
  - `ui/src/locales/zh-CN.json`: 704 lines.

### Alignment Review

Reviewed against `proposal.md`, `specs/discover-lifecycle-entry/spec.md`, `design.md`, task 1.3, project rules, API docs, lifecycle docs, and changed code.

Findings found and fixed:

- Discover row enrichment overwrote discover-stage `candidate_confidence` with `0.0` when no candidate event existed.
  - Fix: preserve positive discover-stage score/confidence as read-only row diagnostics when lifecycle event enrichment has no stronger persisted value.
  - Re-review result: no open alignment findings.
- Task diagnostic test data expected auto-promotion but did not include the low-price gate MA/liquidity evidence required by existing lifecycle rules.
  - Fix: add MA, slope, amount, volume ratio, RSI, and MACD fields to the explicit test parameters.
  - Re-review result: no open alignment findings.
- Frontend build failed because the new Vitest parameter-file reader used Node imports without matching project TypeScript node declarations.
  - Fix: follow the existing static-test pattern and add `// @ts-nocheck` to the test file only.
  - Re-review result: no open alignment findings.

Closure evidence:

- Discover API candidate rows expose score, confidence, technical confirmation count, lifecycle diagnostics, status, and blocking reason.
- Discover UI shows lifecycle status, score, confidence, and blocking reason in the quant status cell.
- Discovery task status exposes `result.quantAutoEntry` machine-readable counts.
- No UTC timestamp format appears in the tested discover row payload.
- Existing lifecycle thresholds and gates remain unchanged.
- Documentation matches the implemented API/UI diagnostics.

### Security Review

Reviewed authorization surface, persistence payload, diagnostics content, logging, dependencies, configuration, and test data.

Findings: none.

Closure evidence:

- No new routes, authentication changes, runtime dependencies, or database schema changes were introduced.
- Diagnostics contain stock codes, numeric evidence, status values, and reason codes only.
- Tests use fake stock data and isolated temporary SQLite database files.
- No credentials, tokens, provider secrets, or private endpoints were added to code, docs, tests, or test parameters.

### Open Findings

None.

## Task 2.1 Run Integrated OpenSpec Verification And Produce Implementation Reviews

### Implementation Summary

- Added final validation parameters at `openspec/changes/fix-discover-lifecycle-scoring/test-params/final-integrated-discovery-lifecycle.md`.
- Re-ran the integrated backend test set, backend coverage, frontend discover-page test, production UI build, file length checks, and whitespace checks.
- Created final implementation review at `openspec/changes/fix-discover-lifecycle-scoring/review.md`.

### Validation Evidence

- `python -m pytest -q tests\test_discover_lifecycle_scoring.py tests\test_ui_backend_api_actions.py::test_discover_snapshot_exposes_read_only_lifecycle_entry_fields tests\test_ui_backend_api_actions.py::test_discover_run_strategy_auto_trial_promotes_discovered_stocks tests\test_ui_backend_api_actions.py::test_discover_run_strategy_executes_real_selector_runners_and_persists_results`
  - Result: `14 passed`.
- `python -m coverage erase`
  - Result: completed.
- `python -m coverage run -m pytest --noconftest -q tests\test_discover_lifecycle_scoring.py`
  - Result: `11 passed`.
- `python -m coverage run --append -m pytest --noconftest -q tests\test_ui_backend_api_actions.py::test_discover_snapshot_exposes_read_only_lifecycle_entry_fields tests\test_ui_backend_api_actions.py::test_discover_run_strategy_auto_trial_promotes_discovered_stocks tests\test_ui_backend_api_actions.py::test_discover_run_strategy_executes_real_selector_runners_and_persists_results`
  - Result: `3 passed`.
- `python -m coverage report -m app\discover\lifecycle_scoring.py app\gateway\quant_universe_entry.py app\discover\discover.py`
  - Result: `app\discover\lifecycle_scoring.py` coverage `95%`.
- Changed/affected backend code coverage from coverage JSON and git diff:
  - `app/discover/discover.py`: changed lines `17/17 = 100.0%`.
  - `app/discover/lifecycle_scoring.py`: new-file statement lines `194/204 = 95.1%`.
  - `app/gateway/quant_universe_entry.py`: changed lines `18/18 = 100.0%`.
- `npm --prefix ui run test -- discover-page.test.tsx`
  - Result: `4 passed`.
- `npm --prefix ui run build`
  - Result: TypeScript build and Vite build completed; Vite reported the existing large-chunk warning.
- `git diff --check -- <changed files>`
  - Result: exit code `0`; Git reported line-ending normalization warnings only.
- File length check:
  - All generated/modified code and test files are at or below 1000 lines.

### Alignment Review

Reviewed all completed tasks against proposal, spec, design, task text, rules, test parameter files, tests, docs, and changed code.

Findings: none.

Closure evidence:

- All tasks are checked except this final task at the time of review.
- Required test parameter files exist.
- API, UI, persistence payload, and docs match the approved discovery lifecycle scoring scope.
- No lifecycle thresholds, source gates, database schema, DB runtime, or migration behavior were changed.

### Security Review

Reviewed final diff for secrets, dependency changes, new endpoints, logging, persistence payloads, database behavior, and test isolation.

Findings: none.

Closure evidence:

- No secrets, credentials, tokens, or private endpoints were introduced.
- No runtime or dev dependencies were added.
- Tests use fake data and isolated temporary SQLite DB files.
- Diagnostics remain limited to safe stock identifiers, numeric evidence, status values, and reason codes.

### Open Findings

None.
