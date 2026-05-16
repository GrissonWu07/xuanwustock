# Proposal: Discover Market Data Snapshot Gate

## Why

Stock discovery can currently complete and publish lifecycle candidates without proving that 30m market data and technical indicators are available. In the observed family-mac environment, discovery produced candidate rows while every row missed required technical fields such as moving averages, MACD, RSI, volume ratio, and amount. At least one incomplete candidate still entered lifecycle processing.

This creates a broken product signal: the UI can show discovery success while the quant lifecycle is judging candidates without the required market snapshot. The system needs a hard readiness contract before a discovered stock can be considered for automatic quant entry.

## What Changes

- Discovery results will be checked for 30m technical snapshot readiness before lifecycle eligibility is published.
- The system will attempt to prepare missing 30m market data and indicators for discovered stocks before automatic lifecycle evaluation.
- Candidates missing required technical fields will be prevented from entering automatic quant trial state.
- Discovery results and task diagnostics will expose technical readiness and missing-field reasons.
- Normal DB cleanup behavior will preserve local market-data caches unless cache deletion is explicitly requested.

## Scope

- 30m technical snapshot readiness for discovered stocks.
- Automatic lifecycle entry prevention when required market or indicator fields are missing.
- User-visible diagnostics for readiness, missing fields, and blocked lifecycle outcome.
- Task-level counts for prepared, complete, incomplete, and blocked candidates.
- Testable behavior for empty-cache discovery and missing technical fields.

## Out of Scope

- Changing discovery strategy selection formulas.
- Lowering score, confidence, or lifecycle thresholds.
- Removing duplicate discovery rows across strategies.
- Reworking historical replay or realtime simulation decisions.
- Migrating existing historical candidate records.
- Deleting market-data caches as part of normal DB reset.

## Impact

- Discovery task completion may take longer when local market data is missing.
- More candidates may be blocked from automatic quant entry until market data and indicators are ready.
- Discovery UI and API consumers will receive additional readiness and diagnostic fields.
- Operational cleanup must distinguish DB reset from market-data cache deletion.

## Rules Applied

- PIR-003: The change affects lifecycle persistence and must keep database/runtime behavior within the existing DB runtime standards.
- PIR-004: Any API-visible discovery readiness fields must be reflected in the API contract during design.
- PIR-005: Discovery work that may fetch or prepare market data must remain asynchronous and bounded.
- CFG-001: Snapshot provider, timeframe, and freshness settings must have clear runtime ownership.
- CFG-009: Test configuration and fixtures must be isolated from production data.
- TEST-001: Affected code must meet the project coverage gate.
- TEST-002: OpenSpec-driven tests must save explicit test parameters.
- TEST-003: Tests must assert blocked and complete lifecycle outcomes, not just non-null results.
- TEST-007 and TEST-008: Python tests must follow project naming conventions and isolate external IO unless explicitly marked as integration tests.

## Risks

- Market-data preparation can slow discovery when many unique symbols are returned and the cache is empty.
- Newly listed, suspended, or provider-incomplete stocks may not have enough 30m history for a complete snapshot.
- A stale or unavailable provider can block otherwise interesting candidates.
- If UI readiness wording is vague, users may still confuse "discovered" with "ready for quant entry".

## Open Questions

- What exact freshness window should apply during active trading hours versus after market close?
- Should manual user-initiated quant entry retry missing snapshot preparation or only show the block reason?
- Should incomplete candidates be displayed as blocked only, or displayed as recommended-only with a blocked auto-entry reason?
