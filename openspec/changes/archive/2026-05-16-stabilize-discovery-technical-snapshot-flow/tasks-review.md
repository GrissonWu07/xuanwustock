# Tasks Review: Stabilize Discovery Refresh Hydration

## Summary

Review completed for `design.md` and `tasks.md`.

The design and tasks stay inside the approved spec: candidate source evidence is
persisted separately, latest technical evidence is owned by unified refresh, and
discovery task/API/lifecycle consume the same hydrated candidate view.

## Spec Alignment

- Task 1 maps to candidate publication and latest refreshed snapshot behavior.
- Task 2 maps to API/event evidence consistency, post-refresh scoring, and stale
  fallback behavior.
- No task adds threshold lowering, historical migration, cache deletion, or
  trading signal changes.

Finding status: no blocking findings.

## Design Alignment

- Tasks follow the selected JSON artifact and runtime snapshot design.
- Tasks include the required `discover.py` split plan to satisfy the file-size
  rule.
- Tasks preserve read API no-remote-IO behavior.

Finding status: no blocking findings.

## Mandatory Implementation Standards

- Code paths are identified per task.
- Reuse/common logic, fallback boundaries, parameter plans, file-size plans,
  database impact, API/layer impact, IO/async behavior, validation, test
  parameters, and coverage targets are specified.
- Real E2E is recorded as required based on prior user confirmation.

Finding status: no blocking findings.

## Rule Alignment

- `PIR-001` through `PIR-005` are addressed.
- `PY-001`, `PY-003`, `PY-007`, and `PY-008` are addressed for Python changes.
- `TEST-001`, `TEST-002`, `TEST-003`, `TEST-007`, `TEST-008`, and `TEST-010`
  are addressed for tests and review evidence.

Finding status: no blocking findings.

## Task Quality

- Tasks are implementable independently in sequence.
- Each task lists target paths, concrete behavior, standalone verification, real
  E2E status, and review gates.

Finding status: no blocking findings.

## Validation Coverage

- Planned tests cover candidate artifact behavior, refresh runtime snapshot
  behavior, lifecycle ingestion/API consistency, stale fallback, existing
  discovery snapshot behavior, and real API discovery verification.

Finding status: no blocking findings.

## Per-Task Review Gates

- Both tasks require Alignment Review and Security Review.
- Findings must be closed and re-reviewed before moving to the next task.

Finding status: no blocking findings.

## Implementation Readiness

The change is ready for `/sp-impl`.

## Required Fixes Before /sp-impl

Unresolved blocking gaps: none.
