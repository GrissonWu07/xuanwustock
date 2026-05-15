# Spec Review: Fix Discover Lifecycle Scoring

## Summary

Review completed for `proposal.md` and `specs/discover-lifecycle-entry/spec.md`. The spec stage defines observable discovery-to-lifecycle behavior and does not include implementation design, code paths, tasks, or code changes.

## Brainstorm Alignment

- The proposal and spec follow the recommended direction from brainstorm: fix discovery evidence normalization rather than lower lifecycle thresholds.
- AI structured evidence preservation is covered.
- Non-AI fallback scoring is covered as deterministic and evidence-based.
- Manual batch quant behavior remains out of scope.

Findings: none blocking.

## Context Alignment

- The spec reflects context that lifecycle already works when discovery candidates include score, confidence, trend, and technical evidence.
- The spec reflects context that current production failures come from missing normalized score/confidence and AI technical confirmation evidence.
- The spec avoids requiring migration of old records, matching the brainstorm risk and context gap.

Findings: none blocking.

## Rule Alignment

- Specs use observable behavior and SHALL language.
- Specs do not name internal files, classes, tables, or implementation functions.
- Source identity alone is explicitly prohibited from adding score credit, preserving the existing lifecycle rule.
- Long-running discovery remains task-based in behavior; detailed async implementation belongs in design.

Findings: none blocking.

## Requirement Quality

- Each requirement has at least one scenario.
- Requirements describe what users and API consumers can observe: lifecycle inputs, outcomes, reasons, diagnostics, and historical-record behavior.
- The exact scoring formula is intentionally not embedded in the spec; design must choose a deterministic formula that satisfies these observable constraints.

Findings: none blocking.

## Scenario Coverage

- Covered explicit score evidence.
- Covered missing explicit score evidence.
- Covered no measurable evidence.
- Covered AI technical confirmation preservation and failure.
- Covered promoted, eligible, recommended-only, blocked, and skipped outcomes.
- Covered historical records not being rewritten.

Findings: none blocking.

## Out-of-Scope or Implementation Leakage

- No implementation code paths are included in the spec.
- No database schema or migration behavior is specified beyond observable non-migration of historical records.
- No realtime buy/sell logic is changed.
- No manual batch quant behavior is changed.

Findings: none blocking.

## Required Fixes Before /sp-tasks

- No blocking fixes required before `/sp-tasks`.
- During `/sp-tasks`, design must finalize:
  - AI confidence formula.
  - Non-AI fallback scoring formula.
  - Where score/confidence diagnostics appear in API/UI.
  - Validation and coverage plan with explicit test parameter files.
