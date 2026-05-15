# Tasks Review: Fix Discover Lifecycle Scoring

## Summary

Review completed for `design.md` and `tasks.md`. The task plan is
implementation-ready and stays within the approved discovery-to-lifecycle
scoring scope.

Findings: none blocking.

## Spec Alignment

- `Discovery Candidates Publish Lifecycle Inputs` is covered by task 1.1 and
  verified again in task 2.1.
- `AI Discovery Preserves Structured Evidence` is covered by tasks 1.1 and 1.2.
- `Lifecycle Entry Remains Rule Driven` is covered by tasks 1.2 and 1.3 without
  lowering thresholds or changing gate semantics.
- `Discovery Task Reports Auto Entry Diagnostics` is covered by task 1.3.
- `Existing Historical Records Are Not Rewritten` is covered by task 1.1 and
  final validation in task 2.1.

Findings: none blocking.

## Design Alignment

- The design finalizes the AI confidence formula, non-AI fallback formula, and
  API/UI diagnostic placement requested by `spec-review.md`.
- The design does not add manual batch quant unification, realtime buy/sell
  decision changes, threshold lowering, or historical data migration.
- The design keeps lifecycle scoring evidence-based and prohibits score credit
  from source identity alone.

Findings: none blocking.

## Rule Alignment

- `PIR-001`: Tasks list target code paths.
- `PIR-002`: Tasks include file size guardrails and split plans; the design
  moves new scoring logic out of `discover.py`.
- `PIR-003` / `CFG-005`: Database decision is explicit; no schema migration is
  required; existing runtime pool rules remain in force.
- `PIR-004` / `CFG-007`: Existing FastAPI/OpenAPI operations and response
  schema additions are identified.
- `PIR-005` / `CFG-008`: Discovery remains async for long-running strategy
  execution.
- Python and testing rule files are referenced by all implementation tasks.

Findings: none blocking.

## Task Quality

- Every implementation task references one or more requirements.
- Every task includes target code paths, implementation change, validation,
  test parameter paths, coverage target, and review gates.
- Tests are required to assert meaningful behavior, not initialization-only or
  no-op behavior.
- The final validation task requires `task-reviews.md` and `review.md` evidence
  before completion.

Findings: none blocking.

## Validation Coverage

The planned validation covers:

- AI structured field preservation.
- AI derived confidence and technical confirmation.
- Non-AI derived score/confidence.
- Source-only candidates remaining zero-score.
- Candidate event payload evidence.
- Lifecycle gate outcomes and unchanged thresholds.
- Discover task diagnostics.
- Discover UI diagnostics and existing batch actions.
- Historical records not being rewritten.
- File length and coverage evidence.

Findings: none blocking.

## Per-Task Review Gates

Each task requires:

- Alignment Review against spec, design, task text, rules, and changed code.
- Security Review against sensitive data handling, validation, logging,
  dependencies, configuration, and project-defined security rules.
- All findings fixed and re-reviewed before starting the next task.

Findings: none blocking.

## Implementation Readiness

The change can proceed to `/sp-impl` after this tasks phase. Implementation
must create the referenced `test-params/*.md` files before marking any task
complete.

Findings: none blocking.

## Required Fixes Before /sp-impl

None.
