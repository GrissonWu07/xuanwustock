# Spec Review: Discover Market Data Snapshot Gate

## Summary

The proposal and `discover-lifecycle-entry` spec convert the brainstorm into observable OpenSpec requirements. The spec focuses on discovery-time 30m technical readiness, blocked automatic entry for incomplete snapshots, UI/API diagnostics, task diagnostics, and cache-preserving DB cleanup.

No `design.md`, `tasks.md`, or code changes were created.

## Brainstorm Alignment

The spec matches the brainstorm scope:

- Discovery prepares or checks 30m data before lifecycle eligibility.
- Missing MA/MACD/RSI/volume/amount evidence blocks automatic quant trial state.
- Duplicate discovery rows are allowed while readiness is evaluated per unique stock.
- Discovery results expose technical readiness and missing fields.
- DB cleanup does not delete market-data caches unless explicitly requested.

The spec uses `blocked` behavior for automatic lifecycle entry, matching the brainstorm-review default when the user did not choose between blocked and recommended-only.

## Context Alignment

The spec reflects the recorded family-mac failure mode without encoding implementation paths or table names in requirement language. It extends the prior discovery lifecycle scoring behavior by requiring structured technical snapshot readiness in addition to score and confidence evidence.

The spec avoids reworking discovery selection, historical replay, or realtime simulation.

## Rule Alignment

The proposal records the relevant project rules:

- API-visible readiness and diagnostics must be captured during design.
- Long-running market-data preparation must stay asynchronous.
- Configuration ownership and provider/freshness settings must be explicit later.
- Tests must assert meaningful complete and blocked outcomes with explicit OpenSpec test parameters.

## Requirement Quality

Requirements use `SHALL` for required observable behavior and avoid prescribing code files, classes, database schema, or implementation mechanics.

The required snapshot fields are observable through readiness and diagnostics. The exact implementation of data fetching, indicator generation, and persistence is intentionally deferred to design.

## Scenario Coverage

Covered scenarios include:

- Empty local 30m data.
- Duplicate rows for one stock.
- Complete snapshot.
- Missing required field.
- Insufficient moving-average readiness.
- Score/confidence without technical snapshot.
- Text-only technical explanations.
- Discovery table and detail diagnostics.
- Mixed task outcomes.
- Provider preparation failure.
- DB cleanup preserving cache.
- Explicit cache deletion.

## Out-of-Scope or Implementation Leakage

No blocking implementation leakage remains. The spec uses domain-level terms such as discovery task, lifecycle eligibility, automatic quant trial state, and technical snapshot.

The proposal mentions DB cleanup as product scope because the user explicitly clarified cache deletion behavior, but it does not prescribe schema or migration details.

## Required Fixes Before /sp-tasks

No blocking fixes are required before `/sp-tasks`.

The design phase should resolve these non-blocking defaults explicitly:

- Technical snapshot freshness window.
- Provider fallback behavior.
- Manual retry behavior for blocked candidates.
- Exact API field names and UI labels for readiness diagnostics.
