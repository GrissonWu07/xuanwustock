# Spec Review: Stabilize Discovery Refresh Hydration

## Summary

Review completed for `proposal.md` and
`specs/discovery-refresh-hydration/spec.md`.

The spec converts the accepted brainstorm correction into observable behavior:
discovery publishes candidate/source evidence, latest stock refresh provides
technical snapshots, lifecycle ingestion and discover API share the hydrated
view, stale raw selector fallback is explicit, and lifecycle thresholds remain
unchanged.

## Brainstorm Alignment

- The proposal follows the recommended Option D from brainstorm.
- The spec avoids making a prepared discovery row artifact the long-lived
  technical source of truth.
- The spec preserves the hard technical snapshot gate and the user correction
  that latest行情/技术指标 should come from the unified refresh path.

Finding status: no blocking findings.

## Context Alignment

- Requirements cover the context gap where `_snapshot_discover` can show raw
  selector rows with empty technical fields.
- Requirements cover the gap where discovery candidates are not guaranteed to
  be part of the latest stock refresh scope.
- Requirements cover post-refresh scoring and candidate event/API consistency.

Finding status: no blocking findings.

## Rule Alignment

- API-visible behavior is specified through discovery task results and discover
  API rows.
- Expensive market-data work remains task-side and not read-side.
- No database migration, cache deletion, threshold lowering, or unrelated
  trading behavior is added to spec scope.

Finding status: no blocking findings.

## Requirement Quality

- Each requirement uses SHALL language and has at least one scenario.
- Requirements are observable through task completion, discover API output,
  lifecycle event payloads, and lifecycle outcomes.
- Implementation details such as module names and storage files are left to
  design.

Finding status: no blocking findings.

## Scenario Coverage

- Current candidate evidence, duplicate unique-code readiness, selector rows
  without technical fields, complete snapshots, stale/incomplete snapshots,
  event/API evidence consistency, post-refresh scoring, unchanged gates, stale
  fallback rows, and no historical rewrite are covered.

Finding status: no blocking findings.

## Standalone Verifiability

- Backend task/API behavior can be verified with unit tests and an API-level
  discovery task run.
- Event payload behavior can be verified against the local quant DB runtime or
  isolated test DB.
- Stale fallback behavior can be verified from API-shaped rows without external
  IO.

Finding status: no blocking findings.

## E2E-Verifiable Behavior

- Real E2E is applicable: run a discovery task through the backend API and
  verify task diagnostics, discover API rows, and candidate event payloads.
- The design phase must record the user-confirmed E2E requirement and define
  the exact command, runtime target, data, assertions, and evidence.

Finding status: no blocking findings.

## Out-of-Scope or Implementation Leakage

- No buy/sell logic, threshold lowering, historical migration, cache deletion,
  or UI redesign is specified.
- Storage and exact code paths are left to design/tasks.

Finding status: no blocking findings.

## Required Fixes Before /sp-tasks

Unresolved blocking gaps: none.
