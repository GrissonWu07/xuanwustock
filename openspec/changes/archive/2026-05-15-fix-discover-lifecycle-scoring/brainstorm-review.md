# Brainstorm Review: Fix Discover Lifecycle Scoring

## Summary

Review completed for `brainstorm.md` and `context.md`. The artifacts stay within `/sp-brainstorm` scope and do not create formal proposal/spec/design/tasks or implementation changes.

## Requirement Alignment

- Aligned with the user request to repair discovery-to-lifecycle behavior rather than lower thresholds.
- Captures both root causes from the investigation:
  - AI scanner structured fields are dropped by `_run_ai_scanner_strategy`.
  - Other discover strategies lack a unified score/confidence contract.
- Preserves the rule that not every discovery candidate must auto-enter; candidates should enter only when lifecycle rules pass.

Findings: none blocking.

## Context Alignment

- Context includes project OpenSpec workflow files, source index, relevant rule files, existing implementation, and test patterns.
- Context records that existing tests already prove auto-entry works when score/confidence fields are present.
- Context records the production observation that score/confidence are zero and AI candidates become `recommended_only`.

Findings: none blocking.

## Rule Alignment

- The brainstorm phase does not write code or formal spec artifacts.
- Required `brainstorm.md` sections are present.
- Required `context.md` sections are present.
- The review records scope risks and context gaps before `/sp-spec`.

Findings: none blocking.

## Scope Risks

- The manual UI batch quant path uses a different path that can write `active` without lifecycle events. This is related but can be scoped out unless the user explicitly expands this change.
- Non AI score formulas need a spec decision before implementation; otherwise the implementation may encode arbitrary scoring assumptions.
- UI exposure of score/confidence is useful but not yet approved as required behavior.

## Missing Context

- Approved scoring formula for non AI selector outputs.
- Approved confidence formula for AI scanner.
- Whether old zero-score candidate events need cleanup or whether rerunning discovery is sufficient.

## Required Follow-Up Before /sp-spec

- Decide whether the next spec should include only discovery scoring normalization or also manual batch quant event unification.
- Specify or approve a deterministic scoring/confidence approach for non AI strategies.
- Decide whether UI should expose lifecycle input scores and gate reasons beyond the existing eligibility fields.

No unresolved blocking gap prevents moving to `/sp-spec`, as long as the above decisions are captured there.
