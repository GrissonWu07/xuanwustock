# Brainstorm Review: Discover Market Data Snapshot Gate

## Summary

The brainstorm defines a focused change: discovery must prepare 30m market data and technical indicators before candidate event ingestion, and incomplete snapshots must not enter auto-trial.

No implementation code, proposal, spec, design, or task files were created in this phase.

## Requirement Alignment

The artifacts cover the user's core requirements:

- Duplicate discovery data is allowed.
- Market data must be fetched or generated.
- The preparation point is before writing `stock_universe_candidate_events`.
- MA, MACD, RSI, volume ratio, and amount completeness is required for auto-entry.
- Missing technical snapshots must be blocked or downgraded.
- The UI must expose field completeness.

The requirement that cache data must not be deleted during normal DB cleanup is captured as a cache-safety candidate requirement and context note.

## Context Alignment

The context file ties the requirement to current code paths:

- Discovery orchestration in `app/discover/discover.py`.
- Candidate event persistence in `app/gateway/quant_universe_entry.py`.
- Lifecycle scoring in `app/discover/lifecycle_scoring.py`.
- Market-data and indicator services in `app/data/services/market_data_service.py` and `app/data/indicators/engine.py`.

It also records the family-mac runtime evidence showing that discovery can currently create lifecycle rows while every candidate lacks the required technical fields.

## Rule Alignment

The brainstorm follows the OpenSpec workflow by stopping at exploratory artifacts only.

The recommended direction preserves existing module boundaries and avoids lowering lifecycle thresholds as a workaround. It also calls for explicit tests at the discovery, lifecycle gate, and UI/API layers.

## Scope Risks

The largest scope risk is turning discovery into a slow remote-fetch workflow when the cache is empty. The later design should limit this with batching, bounded concurrency, timeout diagnostics, and clear partial-failure behavior.

Another risk is overloading lifecycle ingestion with market-data IO. The brainstorm recommends discovery-time enrichment plus a defensive lifecycle gate, which keeps the primary data preparation responsibility in discovery while still protecting other callers.

## Missing Context

The following points should be resolved or given defaults in `/sp-spec`:

- Whether incomplete candidates should persist as `blocked` or `recommended_only`.
- Required number of 30m bars for MA60 readiness.
- Provider fallback order when TDX data is unavailable.
- Technical snapshot freshness rules during trading and non-trading hours.
- Whether manual actions can trigger a retry for missing snapshots.

## Required Follow-Up Before /sp-spec

No blocking gap prevents drafting the spec. If the user does not choose otherwise, the spec should default to:

- `blocked: missing_technical_snapshot` for auto-entry prevention.
- MA60-ready 30m data as the strict readiness baseline.
- Existing market-data service/provider configuration as the provider source of truth.
- UI display of readiness status plus missing-field list.
