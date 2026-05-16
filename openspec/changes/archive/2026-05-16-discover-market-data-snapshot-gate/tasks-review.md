# Tasks Review: Discover Market Data Snapshot Gate

## Summary

The design and tasks translate the approved spec into implementation-ready work. The plan keeps behavior inside the spec: discovery prepares 30m technical snapshots before lifecycle eligibility, incomplete discovery snapshots block automatic quant trial entry, UI/API diagnostics expose readiness, and normal DB reset preserves market-data cache.

No code was changed in this phase.

## Spec Alignment

The tasks map to all six spec requirements:

- Discovery pre-ingest snapshot preparation is covered by tasks 2.1 and 2.2.
- Complete snapshot readiness and missing-field blocking are covered by tasks 2.1, 2.3, and 2.4.
- Lifecycle defense against score/confidence-only or text-only evidence is covered by task 2.4.
- Discovery UI/API readiness visibility is covered by tasks 2.3 and 3.1.
- Task diagnostics are covered by tasks 2.2 and 3.1.
- DB reset cache preservation is covered by task 4.1.

## Design Alignment

The tasks follow the design decisions:

- Snapshot preparation is a focused discovery boundary.
- Candidate event payload JSON is extended without a schema migration.
- Lifecycle gate enforces `missing_technical_snapshot`.
- UI fields are additive and backward-compatible.
- Manual promote behavior remains unchanged because it is a documented spec gap.

## Rule Alignment

The tasks include required rules for code path planning, async API behavior, DB runtime boundaries, configuration ownership, Python style, explicit test parameters, meaningful assertions, mocked external IO, and coverage.

Each implementation task includes a coverage target of at least 90% for changed or affected code.

## Task Quality

Every task has:

- A specific requirement mapping.
- Specific implementation paths or owned areas.
- Concrete validation.
- Explicit OpenSpec test parameter file references.
- Required post-implementation review gates.

Task 1.1 exists to satisfy the OpenSpec test-parameter requirement before behavior tests are implemented.

## Validation Coverage

Planned validation covers:

- Complete snapshot readiness.
- Missing technical fields.
- Insufficient moving-average readiness.
- Provider failure.
- Duplicate discovery rows.
- Candidate payload persistence.
- Lifecycle entry gate blocking.
- Discovery API row diagnostics.
- Discovery UI diagnostics.
- DB reset preserving cache.

External provider IO is required to be mocked in unit tests.

## Per-Task Review Gates

Every implementation task requires:

- Alignment review against spec, design, task, rules, and changed code.
- Security review against security-sensitive behavior and project-defined security rules.
- Findings fixed and re-reviewed before the next task starts.

This satisfies the `/sp-tasks` review-gate rule.

## Implementation Readiness

The plan is ready for `/sp-impl`.

The design identifies all expected source areas and resolves the non-blocking spec-review defaults:

- Incomplete auto-entry defaults to blocked with `missing_technical_snapshot`.
- MA60-ready complete snapshot is the strict readiness baseline.
- Provider/timeframe behavior is owned by discovery snapshot preparation and existing market-data service configuration.
- UI readiness fields and labels are additive.
- Trading-session freshness is diagnostic only in this change.

## Required Fixes Before /sp-impl

No blocking fixes are required before `/sp-impl`.
