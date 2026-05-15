# Testing Standards

These rules are derived from the Java reference project at `C:\Projects\cmps\smartcmp`, the Python reference project at `C:\Projects\cmps\smartcmp-python`, and the OpenSpec workflow requirements in this template.

## TEST-001: Coverage Gate

Changed or affected code MUST reach at least 90% code coverage.

- Java projects SHOULD use the target project's Maven/Jacoco setup when present.
- Python projects SHOULD use coverage.py, pytest-cov, or the target project's existing coverage tool.
- Coverage evidence MUST be recorded in implementation review artifacts.
- Coverage from disabled tests, empty tests, or initialization-only tests does not count.

## TEST-002: Explicit Test Parameters

Every behavioral test MUST use explicit test parameters.

- OpenSpec-driven tests MUST save parameters under `openspec/changes/<change-id>/test-params/<scenario-name>.md`.
- Complex Java inputs SHOULD also use files under `src/test/resources`.
- Complex Python inputs SHOULD also use fixtures under `tests/fixtures` or project-local test resource folders.
- Test code may construct simple values inline only when the values are listed clearly in the test or referenced parameter file.

## TEST-003: Test Quality

Tests MUST assert meaningful behavior.

- Do not write empty/no-op tests.
- Do not write tests whose only purpose is class or method initialization.
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

## TEST-010: Review Evidence

Task review evidence MUST include test proof.

- Commands run.
- Coverage output.
- Test parameter file paths.
- Fixture file paths.
- Mocked external dependencies.
- Integration test gates, if any.
- Open findings and fixes.
