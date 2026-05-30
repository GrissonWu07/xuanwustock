# Change: Quant Technical Entry Score

## Why

Automatic quant entry currently mixes discovery recommendation strength and
source confidence into lifecycle `candidate_score`. The user clarified that
these fields have no quant meaning. Discovery should find candidate stocks, but
quant lifecycle entry must be decided by market行情 and technical indicators.

## What Changes

- Redefine lifecycle `candidate_score` as a pure technical entry score.
- Redefine `candidate_confidence` as a pure technical confidence score.
- Keep discovery/research/AI source fields as candidate trigger and audit data
  only.
- Require ready market/technical snapshots before automatic trial entry.
- Make score breakdowns explain technical components and penalties.
- Persist prepared discovery candidates and their market/technical snapshots in
  the database as the authoritative downstream source.
- Align discovery auto-entry, live quant, historical replay, and live drill on
  the same entry scoring semantics.

## Scope

- Quant lifecycle candidate scoring.
- Candidate entry gates.
- Discovery/research/AI candidate handoff semantics.
- API/UI field semantics for source score vs quant entry score.
- Discovery candidate persistence after market/technical preparation.
- Tests and verification for live, replay, and drill entry behavior.

## Out of Scope

- Changing selector algorithms.
- Changing buy/sell signal generation.
- Changing execution sizing or capital slot rules.
- Tuning rules for a specific stock.
- Migrating old database records.

## Impact

- Fewer candidates may enter `trial` when their source rank is high but their
  technical structure is weak.
- Entry explanations become auditable from MA, MACD, RSI, volume, liquidity,
  freshness, and confirmation evidence.
- Existing source score/confidence fields may remain in API payloads only as
  discovery/audit fields, but they no longer affect quant entry scoring.
- File or provider caches may still accelerate行情 retrieval, but discover API
  and lifecycle entry read prepared database records, not raw selector cache, as
  the business source of truth.

## Rules Applied

- `PIR-001`: design/tasks must identify affected code paths.
- `PIR-002`: changed files must remain at or below 1000 lines, splitting score
  logic if needed.
- `PIR-003` / `CFG-005`: DB behavior must be stated explicitly in design; no
  old-data migration is required by scope.
- `PIR-004`: API field semantic changes must be documented through API
  contracts.
- `PIR-005`: expensive market-data preparation remains async.
- `TEST-001` through `TEST-010`: test parameters, meaningful assertions,
  isolated IO, and coverage evidence are required before completion.

## Risks

- Technical thresholds may initially be too strict or too loose.
- Replay requires as-of checkpoint snapshots, not latest snapshots.
- UI may confuse users if source score and quant score are both displayed
  without clear labels.

## Open Questions

- Should discovery UI continue to show a source/discovery score, or only show
  quant entry score and technical readiness?
- Should manual-pinned stocks bypass automatic entry score, or only bypass
  discovery trigger while preserving technical buy gates?
