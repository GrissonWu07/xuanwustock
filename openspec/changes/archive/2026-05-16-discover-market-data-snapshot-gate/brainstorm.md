# Brainstorm: Discover Market Data Snapshot Gate

## Problem

Discovery results are currently written into `stock_universe_candidate_events` and evaluated by the quant lifecycle before the system guarantees that 30m market data and technical indicators exist locally.

This is not an individual missing-stock issue. On family-mac, after the market-data cache was cleared, a discovery run still produced candidate events and quant state rows while every API row and every candidate payload missed the technical fields needed for lifecycle judgment:

- `ma5`
- `ma10`
- `ma20`
- `ma20_slope`
- `ma60`
- `amount`
- `volume_ratio`
- `rsi`
- `macd`

One candidate still entered auto-trial despite the missing technical snapshot. That conflicts with the desired lifecycle contract: discovery may produce duplicate rows, but market data must be fetched and indicators must be generated before a discovered stock can enter automatic quant processing.

## User Scenarios

1. After a user starts stock discovery with an empty local cache, the discovery task fetches or generates the required 30m OHLCV and indicator snapshot before creating lifecycle candidate events.
2. When a discovered stock has a complete 30m technical snapshot, the lifecycle scoring and auto-entry logic can use the same structured fields that the UI displays.
3. When a discovered stock lacks required MA, MACD, RSI, volume ratio, or amount fields, the stock is not allowed to enter `auto_trial`.
4. The UI clearly shows whether each discovery row has a complete technical snapshot, so "discovered successfully" is not confused with "ready for quant lifecycle".
5. Duplicate discovery rows from different strategies are acceptable, but each unique stock code should share one prepared market snapshot in the task.

## Scope

- Add a discovery-time market data preparation step before writing candidate events.
- Require 30m technical snapshot completeness before automatic lifecycle entry.
- Persist snapshot completeness and missing-field diagnostics in candidate event payloads.
- Surface snapshot readiness and missing technical fields in discovery API/UI data.
- Keep discovery asynchronous and task-based; the HTTP request should not perform long blocking market-data work directly.
- Add tests that prove missing technical snapshots cannot enter auto-trial.

## Out of Scope

- Changing stock selection strategy formulas.
- Lowering lifecycle thresholds to compensate for missing data.
- Removing duplicate discovery results across strategies.
- Rebuilding historical replay or realtime simulation decision logic.
- Migrating old database data.
- Deleting or invalidating local market-data caches during normal DB cleanup.

## Candidate Requirements

- **Before Event Write**: The discovery task MUST prepare market data for every unique discovered stock before calling lifecycle candidate event ingestion.
- **Required Timeframe**: The prepared snapshot MUST be based on 30m data.
- **Required Fields**: A complete technical snapshot SHOULD include latest close/current price, `ma5`, `ma10`, `ma20`, `ma20_slope`, `ma60`, `amount`, `volume_ratio`, `rsi` or equivalent RSI field, `macd`, trend classification, snapshot timestamp, provider, timeframe, and indicator version.
- **Fetch Behavior**: If local 30m OHLCV or indicators are missing, the discovery task MUST attempt to fetch or generate them before lifecycle ingestion.
- **Completeness Gate**: If any required technical field is unavailable after preparation, the candidate MUST NOT enter `auto_trial`.
- **Blocked State**: Missing-snapshot candidates SHOULD be marked as `blocked: missing_technical_snapshot` or downgraded to `recommended_only`, with the missing fields recorded.
- **Payload Contract**: Candidate event payloads MUST include the technical snapshot fields and a machine-readable completeness result.
- **Lifecycle Defense**: The lifecycle entry gate SHOULD independently reject incomplete technical snapshots, even if another ingestion path bypasses discovery.
- **Task Diagnostics**: Discovery task output SHOULD report how many candidates were complete, incomplete, fetched, generated, failed, or blocked.
- **UI Visibility**: The discovery table SHOULD show technical readiness and missing-field diagnostics.
- **Duplicate Handling**: Duplicate rows can be kept for display, but market-data preparation SHOULD be batched by unique stock code.
- **Cache Safety**: DB reset/cleanup workflows MUST NOT delete market-data caches unless explicitly requested.

## Alternative Solutions

### A. Pre-ingest Enrichment in Discovery Orchestrator

Run a batch enrichment step inside the discovery task after strategies finish and before `stock_universe_candidate_events` are written.

Pros:

- Matches the user's requested timing exactly.
- Keeps candidate event payloads truthful at creation time.
- Allows task-level diagnostics for fetch/generation failures.
- Avoids UI or lifecycle code needing to infer missing market state from text.

Cons:

- Discovery tasks can become slower when cache is empty.
- Needs bounded concurrency and clear timeout behavior.

### B. Central Gate Inside Lifecycle Ingestion

Make `ingest_lifecycle_entry_rows()` fetch missing technical data or block rows centrally.

Pros:

- Protects all lifecycle ingestion paths.
- Reduces duplication if other features ingest candidate rows.

Cons:

- Mixes data fetching with lifecycle persistence.
- Makes lifecycle ingestion slower and harder to reason about.
- Provides weaker discovery-task diagnostics unless carefully designed.

### C. Lazy Fetch After Candidate Event Creation

Allow candidate events to be written first, then fetch indicators later from UI or background reconciliation.

Pros:

- Minimal immediate changes.
- Keeps discovery task fast.

Cons:

- Allows invalid lifecycle states to exist.
- Can still enter auto-trial before data is ready.
- Does not satisfy the requirement that data is prepared before candidate event write.

## Recommended Direction

Use Alternative A as the primary design, with a defensive lifecycle gate from Alternative B.

Introduce a small discovery market snapshot preparation layer that:

- Accepts unique discovered stock codes.
- Uses the existing market-data service and indicator engine to load or fetch 30m OHLCV.
- Generates the latest technical snapshot.
- Merges the snapshot into discovery lifecycle rows before ingestion.
- Records completeness and missing-field diagnostics.

Then update lifecycle ingestion so incomplete technical snapshots cannot enter auto-trial even if a future caller forgets to run discovery enrichment.

## Impacted Modules

- `app/discover/discover.py`
- `app/discover/lifecycle_scoring.py`
- `app/gateway/quant_universe_entry.py`
- `app/quant_sim/candidate_entry_gate.py`
- `app/data/services/market_data_service.py`
- `app/data/indicators/engine.py`
- Discovery API response models and UI table rendering
- Tests under `tests/` for discovery lifecycle scoring, candidate ingestion, and UI/API discovery fields

## Risks

- Empty-cache discovery can take materially longer if many symbols require remote fetches.
- Some stocks may not have enough 30m history for MA60, especially newly listed stocks.
- Provider differences may produce missing fields for specific exchanges or symbols.
- Market holidays and after-hours runs need a clear freshness definition.
- If the UI only shows the display row but not the candidate event payload, discrepancies may remain hidden.

## Open Questions

1. Should incomplete candidates always be persisted as `blocked: missing_technical_snapshot`, or should they be persisted as `recommended_only` with a blocked auto-entry reason?
2. What minimum 30m history is required for readiness: enough bars for MA20, MA60, or the full indicator set?
3. Which provider order should be used when TDX local data is missing or unavailable?
4. What freshness threshold should apply during market hours versus after market close?
5. Should a manual UI action be allowed to force a retry for missing technical snapshots?

## Suggested Change ID

`discover-market-data-snapshot-gate`
