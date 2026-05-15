# Tasks: Fix Discover Lifecycle Scoring

## 1. Implementation

- [x] 1.1 Add discovery lifecycle normalization boundary
  - Related requirement: `Discovery Candidates Publish Lifecycle Inputs`, `AI Discovery Preserves Structured Evidence`, `Existing Historical Records Are Not Rewritten`
  - Applicable rules: `PIR-001`, `PIR-002`, `PIR-003`, `PY-001`, `PY-002`, `PY-003`, `PY-007`, `TEST-001`, `TEST-002`, `TEST-003`, `TEST-007`, `TEST-008`, `TEST-010`
  - Target code paths: `app/discover/lifecycle_scoring.py`, `app/discover/discover.py`, `tests/test_discover_lifecycle_scoring.py`, `tests/test_ai_stock_scanner.py`
  - File size guardrail: each generated/modified code file must stay <= 1000 lines; split plan: put formulas and diagnostics in `app/discover/lifecycle_scoring.py`, keep `app/discover/discover.py` as orchestration only
  - Database impact: existing quant DB runtime only; no schema migration; existing SQLite/MySQL/pool behavior remains in force
  - API contract/layers: existing `POST /api/v1/discover/actions/run-strategy` and `GET /api/v1/discover`; discovery orchestration remains separate from FastAPI route layer
  - API IO / async: strategy execution remains background async through `DiscoverTaskManager`; normalizer must not introduce new external IO
  - Change: implement normalized lifecycle fields for AI and non-AI discovery rows, preserve AI scanner structured fields, derive confidence/trend/technical confirmation from approved formulas, and set zero-score diagnostics for rows without measurable evidence
  - Validation: unit tests cover explicit score preservation, AI scanner field preservation, non-AI derived score/confidence, source-only zero scoring, trend derivation, and no historical record rewrite; verify old selector rows still load
  - Test parameters: `openspec/changes/fix-discover-lifecycle-scoring/test-params/discovery-lifecycle-normalization.md`
  - Coverage target: at least 90% code coverage for changed/affected code
  - Required reviews after implementation:
    - Alignment review against spec, design, task, rules, and changed code
    - Security review against security-sensitive behavior and project-defined security rules
  - Review gate: all findings must be fixed and re-reviewed before the next task starts

- [x] 1.2 Persist normalized lifecycle evidence into candidate events
  - Related requirement: `Lifecycle Entry Remains Rule Driven`, `Discovery Candidates Publish Lifecycle Inputs`, `AI Discovery Preserves Structured Evidence`
  - Applicable rules: `PIR-001`, `PIR-002`, `PIR-003`, `PY-001`, `PY-003`, `PY-007`, `TEST-001`, `TEST-002`, `TEST-003`, `TEST-007`, `TEST-010`
  - Target code paths: `app/gateway/quant_universe_entry.py`, `tests/test_discover_lifecycle_scoring.py`, `tests/test_ui_backend_api_actions.py`
  - File size guardrail: each generated/modified code file must stay <= 1000 lines; split plan: move payload helper code to a small helper module only if `quant_universe_entry.py` approaches the limit
  - Database impact: writes existing `stock_universe_candidate_events` payload fields only; no schema migration; existing SQLite/MySQL/pool behavior remains in force
  - API contract/layers: existing discover operations only; no new route
  - API IO / async: candidate event ingestion keeps existing DB IO; no new external IO
  - Change: ensure `_candidate_event_payload` uses normalized `source_score`, `confidence`, `trend`, technical confirmation count, and diagnostics; enrich discover rows with candidate confidence and gate reasons from persisted events without rewriting old rows
  - Validation: backend tests assert candidate events contain nonzero `source_score/confidence` when evidence exists, AI candidates with technical confirmation are not recommended-only due to missing confirmation, weak candidates remain blocked or recommended-only with reason, and lifecycle thresholds are unchanged
  - Test parameters: `openspec/changes/fix-discover-lifecycle-scoring/test-params/lifecycle-event-handoff.md`
  - Coverage target: at least 90% code coverage for changed/affected code
  - Required reviews after implementation:
    - Alignment review against spec, design, task, rules, and changed code
    - Security review against security-sensitive behavior and project-defined security rules
  - Review gate: all findings must be fixed and re-reviewed before the next task starts

- [x] 1.3 Expose discover API/UI lifecycle diagnostics
  - Related requirement: `Discovery Task Reports Auto Entry Diagnostics`, `Lifecycle Entry Remains Rule Driven`
  - Applicable rules: `PIR-001`, `PIR-002`, `PIR-004`, `PIR-005`, `PY-001`, `PY-003`, `PY-007`, `CFG-007`, `CFG-008`, `TEST-001`, `TEST-002`, `TEST-003`, `TEST-007`, `TEST-010`
  - Target code paths: `app/discover/discover.py`, `app/gateway_api.py` only if response mapping requires route-level schema notes, `ui/src/lib/page-models.ts`, `ui/src/features/discover/discover-page.tsx`, `ui/src/features/quant/quant-entry-controls.tsx`, `tests/test_ui_backend_api_actions.py`, `ui/src/tests/discover-page.test.tsx`, `docs/后端能力与服务接口清单.md`, `docs/量化股票生命周期与自动入池流程说明.md`
  - File size guardrail: each generated/modified code file must stay <= 1000 lines; split plan: keep reusable UI diagnostic rendering in `ui/src/features/quant/quant-entry-controls.tsx` if needed, not inline duplicated markup
  - Database impact: reads existing DB lifecycle state and candidate events; no schema migration; existing SQLite/MySQL/pool behavior remains in force
  - API contract/layers: existing `GET /api/v1/discover`, `POST /api/v1/discover/actions/run-strategy`, and `GET /api/v1/tasks/{task_id}` response additions; FastAPI route remains transport-only
  - API IO / async: `GET /api/v1/discover` remains synchronous DB/file snapshot read; `POST /api/v1/discover/actions/run-strategy` remains async background task with existing optional wait behavior
  - Change: expose visible score/confidence diagnostics in discover candidate rows, keep quant status and blocking reasons visible, and ensure task result `quantAutoEntry` reports attempts/promoted/eligible/skipped with machine-readable reasons
  - Validation: backend API tests assert response fields and task diagnostics; frontend tests assert score/confidence/status/reason render and existing batch actions still work; no UTC timestamp format appears in discover table rows
  - Test parameters: `openspec/changes/fix-discover-lifecycle-scoring/test-params/discover-api-ui-diagnostics.md`
  - Coverage target: at least 90% code coverage for changed/affected code
  - Required reviews after implementation:
    - Alignment review against spec, design, task, rules, and changed code
    - Security review against security-sensitive behavior and project-defined security rules
  - Review gate: all findings must be fixed and re-reviewed before the next task starts

## 2. Final Validation

- [x] 2.1 Run integrated OpenSpec verification and produce implementation reviews
  - Related requirement: `Discovery Candidates Publish Lifecycle Inputs`, `AI Discovery Preserves Structured Evidence`, `Lifecycle Entry Remains Rule Driven`, `Discovery Task Reports Auto Entry Diagnostics`, `Existing Historical Records Are Not Rewritten`
  - Applicable rules: `PIR-001`, `PIR-002`, `PIR-003`, `PIR-004`, `PIR-005`, `PY-001`, `PY-003`, `PY-007`, `PY-008`, `CFG-005`, `CFG-007`, `CFG-008`, `CFG-009`, `TEST-001`, `TEST-002`, `TEST-003`, `TEST-007`, `TEST-008`, `TEST-010`
  - Target code paths: `openspec/changes/fix-discover-lifecycle-scoring/test-params/*.md`, `openspec/changes/fix-discover-lifecycle-scoring/task-reviews.md`, `openspec/changes/fix-discover-lifecycle-scoring/review.md`, changed backend/frontend/test files from tasks 1.1 through 1.3
  - File size guardrail: each generated/modified code file must stay <= 1000 lines; split plan: split tests or helpers before completing this task if any file exceeds the guardrail
  - Database impact: verify existing SQLite test DB behavior; no schema migration; no historical row rewrite
  - API contract/layers: verify affected existing OpenAPI operations and docs/types are aligned with response additions
  - API IO / async: verify discovery task remains async and status polling exposes diagnostics
  - Change: create final task review evidence, run targeted backend/frontend tests and coverage, run file length checks, confirm no out-of-spec behavior, and update `tasks.md` statuses only after all review findings are closed
  - Validation: record commands, coverage, test parameter files, file length evidence, Alignment Review results, Security Review results, and final zero-finding `review.md`
  - Test parameters: `openspec/changes/fix-discover-lifecycle-scoring/test-params/final-integrated-discovery-lifecycle.md`
  - Coverage target: at least 90% code coverage for changed/affected code
  - Required reviews after implementation:
    - Alignment review against spec, design, task, rules, and changed code
    - Security review against security-sensitive behavior and project-defined security rules
  - Review gate: all findings must be fixed and re-reviewed before the change can proceed to `/sp-complete`
