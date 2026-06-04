# Testing Standards

These rules are derived from the Java reference project at `C:\Projects\cmps\smartcmp`, the Python reference project at `C:\Projects\cmps\smartcmp-python`, and the OpenSpec workflow requirements in this template.

## TEST-001: Coverage Gate

Changed or affected code MUST reach at least 85% code coverage.

- Java projects SHOULD use the target project's Maven/Jacoco setup when present.
- Python projects SHOULD use coverage.py, pytest-cov, or the target project's existing coverage tool.
- Coverage evidence MUST be recorded in implementation review artifacts.
- Coverage from disabled tests, empty tests, or initialization-only tests does not count.
- Coverage percentage MUST NOT substitute requirement coverage, scenario coverage, or requirement-to-test mapping.

## TEST-002: Explicit Test Parameters

Every behavioral test MUST use explicit test parameters.

- OpenSpec-driven tests MUST save parameters under `.agent/workdir/sp-openspec/<change-id>/test-params/<scenario-name>.md`.
- Complex Java inputs SHOULD also use files under `src/test/resources`.
- Complex Python inputs SHOULD also use fixtures under `tests/fixtures` or project-local test resource folders.
- If automated tests need parameter files after completion, store stable fixtures in the project's normal test resource directory and reference them from the workdir parameter record; do not make committed tests depend on ignored `.agent/workdir/` files.
- Test code may construct simple values inline only when the values are listed clearly in the test or referenced parameter file.

## TEST-003: Test Quality

Tests MUST assert meaningful behavior.

- Do not write empty/no-op tests.
- Do not write tests whose only purpose is class or method initialization.
- Do not write tests whose primary purpose is to validate dependency packages, SDKs, frameworks, or standard-library behavior.
- Do not write tests whose primary purpose is to validate third-party API/provider correctness, availability, quota behavior, schema stability, or SDK internals.
- When dependencies or third-party APIs are involved, assertions MUST focus on project-owned code: request construction, adapter behavior, response mapping, error handling, retries, side effects, and fallback decisions approved by specs/design.
- Do not assert only that a method returns non-null unless non-null is the specified behavior.
- Assert state changes, returned values, thrown exceptions, repository calls, generated metrics, API response mapping, or emitted events.
- Negative and edge scenarios MUST be included for validation logic.

## TEST-004: Java Test Layout and Naming

Java tests MUST follow project layout and naming conventions.

- Put tests under `src/test/java`.
- Test resources go under `src/test/resources`.
- Test class names end with `Test`.
- Unit tests SHOULD mirror the package of the class under test.
- Use JUnit, JUnit 5, TestNG, Mockito, or PowerMockito only according to the target module's existing pattern.
- Do not count tests marked disabled, ignored, or excluded from the active suite as coverage evidence.

## TEST-005: Java Mocking and Fixtures

Java tests MUST isolate external IO unless the test is explicitly an integration test.

- Mock external cloud SDKs, HTTP clients, static helpers, repositories, and services when testing business logic.
- Use argument captors to verify saved or emitted domain objects.
- Use JSON/YAML fixtures for non-trivial request or provider payloads.
- Use `Assert.assertThrows` or the local equivalent for expected domain exceptions.
- Avoid real network, real database, or real message queue access in unit tests.

## TEST-006: Java Integration Tests

Java integration tests MUST be separated from unit tests.

- Use Maven profiles, naming patterns, or suite files to separate integration tests.
- Integration tests MUST document required services and environment variables.
- Integration tests MUST not run by default unless the project already requires that behavior.
- Database integration tests MUST use isolated schemas, local containers, or approved local test databases.
- Tests that depend on production-like data MUST not mutate shared environments.

## TEST-007: Python Test Layout and Naming

Python tests MUST follow project layout and naming conventions.

- Test files use `test_*.py`.
- Test classes use `Test<Subject>`.
- Test methods use `test_<behavior>`.
- Use `unittest`, `pytest`, or the target package's existing test framework consistently.
- Async tests MUST run async code explicitly through the chosen framework or `asyncio.run`.
- Do not leave ad hoc scripts in `tests/` unless they are clearly excluded from automated test discovery.

## TEST-008: Python Mocking and Async Tests

Python tests MUST isolate external IO unless explicitly marked as integration tests.

- Mock HTTP clients, SDK calls, Consul access, filesystem side effects, and secret decryption.
- Use fake access keys and fake secrets only.
- Async HTTP behavior SHOULD be tested with async mocks or explicit async context manager fakes.
- Assert error handling paths for HTTP errors, API errors, empty provider data, and missing labels.
- Close async clients or assert that code uses context managers.

## TEST-009: Integration Test Safety

Integration tests that require real environments MUST be opt-in.

- Gate them behind environment variables or explicit skip flags.
- Use `.example` or `.template` config files with fake values.
- Do not commit real credentials in test config.
- Print or log only safe identifiers.
- Timeouts and retry counts MUST be bounded.
- Integration tests MUST verify project-owned integration behavior, not dependency package behavior or third-party API/provider behavior.
- Third-party API calls SHOULD be replaced with mocks, contract fixtures, local fakes, stubs, or approved sandbox/test endpoints; live third-party calls require explicit design approval and MUST still assert only project-owned behavior.

## TEST-010: Review Evidence

Task review evidence MUST include test proof.

- Commands run.
- Coverage output.
- Requirement-to-test mapping.
- Requirement Counterexample Matrix for broad requirements.
- Masked-Test Analysis for gate or decision-chain behavior.
- Broad-Qualifier Audit comparing spec qualifiers to code qualifiers.
- Decision Chain Trace for applicable gate, filter, sort, score, rank, selection, state transition, workflow transition, or decision-chain behavior.
- Evidence Capture Timing Audit for semantic evidence fields.
- Deterministic Sort Audit for sort/rank/order behavior.
- Test parameter file paths.
- Fixture file paths.
- Mocked external dependencies.
- Evidence that tests target project code rather than dependency packages or third-party APIs.
- Integration test gates, if any.
- Open findings and fixes.

## TEST-010A: Requirement Counterexample Matrix

Implementation review MUST actively try to disprove broad requirements.

- For every `SHALL`, `MUST`, and scenario, extract behavior dimensions such as source, type, status, profile, state, time, data-readiness, error, fallback, permission, tenant/user, and API/UI output when relevant.
- For broad qualifier words such as `all`, `any`, `same`, `unified`, `source-agnostic`, `every`, `不得按来源`, and `统一`, include at least two non-default variants and one adversarial variant.
- Positive-path and negative-path tests MUST both exist when the requirement affects admission, scoring, persistence, API output, UI output, authorization, validation, or external side effects.
- A test blocked by an earlier gate, filter, sort, or transform does not prove later semantics. Review evidence MUST state why each proving test is not masked by another condition.
- If code implements a narrower qualifier than the spec, record a finding unless specs/design/tasks explicitly approve the exception.

## TEST-010B: Decision Chain and Evidence Timing Audits

Tests and reviews MUST map semantic claims to actual code data flow when the behavior depends on gates, filters, sorts, scores, ranks, selections, state transitions, or evidence fields.

- Decision Chain Trace is required for gate, filter, admission, eligibility, validation, sort, score, rank, selection, state transition, workflow transition, or decision-chain behavior.
- The trace MUST list ordered code steps, inputs, outputs, conditions/transforms, evidence generated, downstream consumers, masking risks, and unmasked tests.
- Evidence Capture Timing Audit is required for fields whose semantics represent order/rank/position, snapshot, readiness/eligibility, confidence, score, timestamp, provenance/source/lineage, status/state/stage, audit trail, or decision reason.
- Evidence fields MUST be captured at the semantic moment required by specs/design/tasks, not only after normalization, filtering, sorting, enrichment, deduplication, pagination, caching, retry, persistence, or status update transforms unless approved artifacts explicitly require post-transform semantics.
- Deterministic Sort Audit is required for sorting, ranking, ordering, priority, first/last selection, top-N selection, pagination order, or display order requirements.
- Sort audit evidence MUST list keys, directions, null handling, stability strategy, tie-break rules, and tests where all earlier sort keys are equal.
- Reviewers MUST explicitly answer whether an earlier gate, filter, sort, or transform can let a test pass without proving the target semantic behavior.
- Checklist section presence is not enough; evidence MUST cite code paths, test inputs, expected outputs, and finding closure.

## TEST-011: Standalone Full Verification

Every changed behavior MUST be verified through a complete standalone path when the project provides one.

- Backend service changes require a real API request/response verification against a running service or project-supported test server.
- UI changes require a UI test case that verifies the changed interface behavior.
- Bug fixes require a regression verification through the original bug entry point.
- Database, Redis, Elasticsearch, queue, cache, or external integration changes require verification against the project-provided connection, local environment, test container, or documented test configuration when available.
- If an external service verification path is unavailable, record the skip reason and verify all locally testable behavior.
- Mock-only tests do not replace standalone verification when a real project-supported verification path exists.

## TEST-012: Real E2E Decision, Design, and Execution

Every changed capability MUST have an explicit real E2E required/not-required decision in design artifacts, confirmed with the user before tasks or implementation.

- Specs MUST identify enough externally observable behavior for design to decide E2E applicability: external entry point, actor/client, trigger, expected externally observable result, and side effects.
- `design.md` MUST assess whether real E2E is required for each changed capability and record user confirmation of the required/not-required decision.
- When E2E is confirmed as required, `design.md` MUST include command/tool, runtime target, test data, request/UI flow/job trigger, assertions, and evidence to collect.
- `tasks.md` MUST include a real E2E test line for each relevant task, or a documented not-applicable reason tied to the spec.
- Backend E2E MUST call a running service or project-supported test server and verify request, response status, response body/schema, and relevant side effects.
- UI E2E MUST use a browser-level or project-approved UI test runner and verify the changed interface behavior, not just component initialization.
- Job, CLI, or workflow E2E MUST trigger the real supported entry point and verify resulting output, state change, or externally observable side effect.
- Unit tests, mock-only tests, class initialization tests, isolated method tests, and static screenshots do not satisfy required E2E evidence.
- If real E2E cannot run because the project lacks a runnable target or documented environment, record the blocker, user-confirmed skip reason, and locally testable fallback evidence in `design.md`, `tasks.md`, `task-reviews.md`, and `review.md`.

## TEST-013: Project-Code Test Boundary

Tests MUST focus on project-owned code and behavior.

- Tests MAY use dependencies, frameworks, SDKs, and third-party API clients as collaborators, but those collaborators MUST NOT be the subject under test.
- Do not create tests dedicated to proving a dependency package works as documented.
- Do not create tests dedicated to proving a third-party API works, is available, or returns a particular live response.
- For third-party integrations, test the project-owned boundary with mocks, stubs, contract fixtures, recorded safe samples, local fakes, or explicitly approved sandbox/test endpoints.
- Assertions MUST prove project behavior: generated request shape, validation, auth/tenant handling, response translation, error mapping, retry/timeout handling, persistence, emitted events, logs, and user/API/UI-visible results.
- If a real external provider call is unavoidable for an approved integration check, record the reason, isolate credentials, bound timeout/retry behavior, avoid sensitive logging, and do not treat provider correctness as project test coverage.
