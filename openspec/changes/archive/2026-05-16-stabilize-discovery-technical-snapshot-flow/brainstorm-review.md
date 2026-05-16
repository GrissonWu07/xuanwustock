# Brainstorm Review: Stabilize Discovery Technical Snapshot Flow

## Summary

Review completed again after user correction that the prepared discovery artifact must not become the long-lived market/technical source of truth. The brainstorm now frames the problem as candidate-source persistence plus unified latest-stock-refresh hydration, rather than as a standalone prepared-row artifact. It stays in discovery/context scope and does not create proposal, spec, design, tasks, or code.

## Requirement Alignment

- The user asked to analyze why the discovery/technical-data flow is disorganized and what to do.
- The brainstorm identifies the concrete local failure mode: discover API can show all-empty technical fields while the codebase has preparation/refresh capabilities that can fetch the same stocks.
- The recommended direction is aligned with the user correction: discovery stores candidate/source evidence, while unified stock refresh owns latest quote and technical indicators.
- Lifecycle ingestion and discover API are required to consume the same hydrated latest snapshot view rather than raw selector rows or a stale prepared artifact.
- No implementation work is proposed as approved scope; the next step is a formal `/sp-spec` if the direction is accepted.

Finding status: no blocking findings.

## Context Alignment

- Context includes project agent rules, OpenSpec workflow rules, source-index, relevant project rules, relevant archived specs/wiki, and current code paths.
- Context explicitly records the conflict between archived intended behavior and current discover API fallback behavior.
- Context records the gap that discovery candidate output has no single canonical repository today.
- Context now includes the existing `UnifiedStockRefreshScheduler` pattern and the current gap that discovery candidates are not clearly included in its refresh universe.
- Context records that current runtime snapshot hydration covers name/sector/latest price but not the full technical indicator contract needed for lifecycle readiness.

Finding status: no blocking findings.

## Rule Alignment

- Brainstorm phase did not modify runtime code.
- Artifacts created only under `openspec/changes/stabilize-discovery-technical-snapshot-flow/`.
- Database/API/async/testing implications are recorded for future design rather than implemented prematurely.
- The recommendation avoids synchronous market-data IO in read APIs, aligning with `PIR-005`.

Finding status: no blocking findings.

## Scope Risks

- Candidate artifact and runtime snapshot storage choices can expand into DB schema/API design. This must be decided in `/sp-tasks`, not guessed during implementation.
- Re-normalizing scores after latest snapshot hydration can change candidate scores for new runs. This is in scope but must be visible in specs and tests.
- Old selector files and old candidate events may continue to exist. Specs must distinguish "old/stale/unprepared" from "new prepared run".
- The refresh freshness window must be specified; otherwise a row may technically have indicators but still be too stale for auto-entry.

Finding status: non-blocking; carry into `/sp-spec`.

## Missing Context

- No active OpenSpec spec exists for discovery lifecycle entry; only archived specs/wiki exist.
- Discovery candidate artifact storage location is not decided.
- Retention behavior for candidate artifacts is not decided.
- Runtime snapshot technical field storage and freshness SLA are not decided.

Finding status: non-blocking for brainstorm; must be resolved by `/sp-tasks`.

## Required Follow-Up Before /sp-spec

- Decide whether the `/sp-spec` should modify the existing archived capability conceptually or add a new active capability delta for "discovery candidate refresh hydration".
- Specify observable behavior for stale raw selector rows when no discovery candidate artifact or refreshed technical snapshot exists.
- Specify whether discover API should expose a `discoveryRunId`/task id for traceability.
- Specify that new discovery task output must register discovered codes for unified refresh, hydrate latest technical snapshots, and re-normalize lifecycle score fields after hydration.
- Specify freshness requirements for snapshots used in lifecycle auto-entry.

Unresolved blocking gaps: none.
