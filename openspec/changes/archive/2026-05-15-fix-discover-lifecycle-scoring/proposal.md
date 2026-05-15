# Change: Fix Discover Lifecycle Scoring

## Why

Stock discovery currently produces candidates but does not reliably provide the normalized score, confidence, trend, and technical confirmation signals required by the quant lifecycle. In production this caused discovery candidates to enter lifecycle evaluation with `source_score=0`, `confidence=0`, and neutral trend, so automatic entry did not happen even when discovery itself succeeded.

AI discovery is affected because its structured scanner and technical fields are downgraded into display text before lifecycle ingestion. Non-AI discovery strategies are affected because they often do not emit a common scoring contract.

## What Changes

- Discovery candidates will expose normalized lifecycle input fields for score, confidence, trend, technical confirmation, and evidence quality.
- AI discovery results will preserve structured scanner score, confidence, technical confirmation, and supporting evidence through discovery output and lifecycle ingestion.
- Non-AI discovery strategies will produce deterministic evidence-based score and confidence when explicit values are absent.
- Lifecycle entry outcomes will remain rule-driven: candidates may be promoted, marked eligible, recommended only, blocked, or skipped with a clear reason.
- Discovery task results and candidate rows will expose enough lifecycle diagnostics to explain why candidates did or did not enter the quant universe.

## Scope

- Discovery result normalization.
- Discovery-to-lifecycle handoff behavior.
- AI discovery scoring and technical confirmation behavior.
- Non-AI discovery fallback scoring behavior.
- Discover API/UI-visible lifecycle diagnostics.
- Tests and verification for discovery candidates entering lifecycle with nonzero evidence when evidence is available.

## Out of Scope

- Lowering lifecycle thresholds.
- Adding source-label-only score bonuses.
- Guaranteeing every discovered candidate auto-enters quant.
- Changing realtime quant buy/sell decision logic.
- Changing existing manual batch quant behavior.
- Migrating or rewriting old zero-score candidate records.

## Impact

- Discovery runs should produce more useful lifecycle inputs and more accurate auto-entry results.
- AI discovery candidates that have score and technical confirmation should no longer be recommended-only because structured evidence was lost.
- Users should be able to distinguish score failure, confidence failure, technical confirmation failure, capacity limits, and data gaps from the discover/lifecycle status.
- Existing historical candidate records may remain unchanged until a new discovery run is executed.

## Rules Applied

- Specs describe observable behavior only.
- Lifecycle score must be evidence-based; source identity alone must not add points.
- Long-running discovery remains asynchronous.
- Later design/tasks must cover Python code standards, testing standards, database/runtime impact, API impact, and coverage requirements from project rules.

## Risks

- Poor fallback scoring could admit weak candidates into lifecycle review.
- Different discovery strategies may have score distributions that are hard to compare.
- More evidence collection may increase discovery runtime.
- Manual quant entry remains a separate lifecycle audit concern unless addressed by a later change.

## Open Questions

- Exact scoring weights for non-AI fallback scoring should be finalized during design.
- Exact AI confidence formula should be finalized during design.
- Whether to expose score/confidence as visible table columns or only as candidate detail diagnostics should be finalized during design.
