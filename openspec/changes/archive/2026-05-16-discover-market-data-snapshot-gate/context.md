# Context: Discover Market Data Snapshot Gate

## Sources Read

- `C:\Users\gangw\.agents\skills\sp-brainstorm\SKILL.md`
- `C:\Projects\githubs\aiagents-stock\AGENTS.md`
- `C:\Projects\githubs\aiagents-stock\openspec\AGENTS.md`
- `C:\Projects\githubs\aiagents-stock\openspec\project.md`
- `C:\Projects\githubs\aiagents-stock\docs\ai-context\source-index.md`
- `C:\Projects\githubs\aiagents-stock\docs\rules\project-implementation-standards.md`
- `C:\Projects\githubs\aiagents-stock\docs\rules\python-code-standards.md`
- `C:\Projects\githubs\aiagents-stock\docs\rules\configuration-standards.md`
- `C:\Projects\githubs\aiagents-stock\docs\rules\testing-standards.md`
- `C:\Projects\githubs\aiagents-stock\docs\standards\architecture.md`
- `C:\Projects\githubs\aiagents-stock\docs\standards\backend.md`
- `C:\Projects\githubs\aiagents-stock\docs\standards\api.md`
- `C:\Projects\githubs\aiagents-stock\docs\standards\testing.md`
- `C:\Projects\githubs\aiagents-stock\openspec\changes\archive\2026-05-15-fix-discover-lifecycle-scoring\brainstorm.md`
- `C:\Projects\githubs\aiagents-stock\openspec\changes\archive\2026-05-15-fix-discover-lifecycle-scoring\context.md`
- `C:\Projects\githubs\aiagents-stock\openspec\changes\archive\2026-05-15-fix-discover-lifecycle-scoring\specs\discover-lifecycle-entry\spec.md`
- `C:\Projects\githubs\aiagents-stock\docs\wiki\discovery-lifecycle-scoring-and-auto-entry-diagnostics.md`
- `C:\Projects\githubs\aiagents-stock\app\discover\discover.py`
- `C:\Projects\githubs\aiagents-stock\app\gateway\quant_universe_entry.py`
- `C:\Projects\githubs\aiagents-stock\app\discover\lifecycle_scoring.py`
- `C:\Projects\githubs\aiagents-stock\app\data\services\market_data_service.py`
- `C:\Projects\githubs\aiagents-stock\app\data\indicators\engine.py`

## Existing Specs

The archived `fix-discover-lifecycle-scoring` change repaired the discovery-to-lifecycle score contract. It made discovery rows preserve structured score, confidence, trend, and technical confirmation fields so lifecycle scoring did not collapse to zero.

That archived change did not require discovery to fetch or generate 30m market data before lifecycle candidate event ingestion. It assumed the rows already carried market evidence when available.

The wiki page `discovery-lifecycle-scoring-and-auto-entry-diagnostics.md` explains scoring diagnostics and entry gating, but it does not currently define a hard pre-ingest market-data preparation requirement.

This new change should extend the existing discovery lifecycle contract rather than replace it.

## Existing Code Patterns

`app/discover/discover.py` currently runs discovery strategies, builds discovery lifecycle rows, and then calls `ingest_lifecycle_entry_rows(context, _discover_rows(context), source_type="discover")`.

`_discover_row_from_mapping()` maps technical fields such as `ma5`, `ma10`, `ma20`, `ma20_slope`, `ma60`, `amount`, `volume_ratio`, `rsi`, and `macd` into lifecycle rows when the source strategy already supplied them.

`_discover_rows(context)` calls `enrich_lifecycle_entry_rows(context, rows)`, but the current observed behavior shows this does not guarantee 30m OHLCV fetch or indicator generation before candidate event persistence.

`app/gateway/quant_universe_entry.py` creates `stock_universe_candidate_events` payloads from the row fields it receives. If technical fields are missing, the event payload remains missing those fields.

`app/discover/lifecycle_scoring.py` normalizes discovery lifecycle rows and derives scores from supplied evidence. It is not responsible for remote market-data fetches.

`app/data/services/market_data_service.py` provides market data access through `get_ohlcv()`, `get_indicators()`, and `get_latest_snapshot()`. This is the likely service boundary for loading or generating required 30m data.

`app/data/indicators/engine.py` calculates MA, MACD, RSI, volume, and trend indicators from OHLCV data.

## Runtime Evidence

The current family-mac environment shows the failure mode clearly:

- The latest discovery run produced 50 API rows across five non-AI strategies.
- API rows had zero complete technical snapshots.
- Candidate database rows had zero complete technical snapshots.
- `stock_universe_candidate_events` contained 48 rows.
- `stock_universe_quant_state` contained 48 rows.
- `stock_universe_quant_events` contained one event, meaning an incomplete candidate still entered lifecycle processing.
- The local TDX 30m kline and indicator cache directories were missing after prior cache deletion.

The user clarified that future cleanup should delete only DB data and must not delete market-data caches.

## Wiki / Standard Rules Applied

- Discovery and lifecycle contracts should be explicit and testable.
- Runtime work should remain asynchronous for long-running tasks.
- The implementation should reuse existing gateway and data-service boundaries before adding new infrastructure.
- DB cleanup and market-data cache cleanup are separate operational concerns.

## Project Rules Applied

- PIR-001: The change should minimize unnecessary new abstractions; a focused snapshot preparation service is acceptable only if it keeps discovery orchestration clear.
- PIR-002: No duplicated logic should be created for technical indicator completeness.
- PIR-003: Tests must cover user-visible lifecycle behavior, especially no auto-trial without required technical evidence.
- PIR-004: Configuration such as provider order, timeframe, and readiness thresholds should be explicit.
- PIR-005: The implementation must remain consistent with the existing runtime and DB patterns.
- PY-001 through PY-006: Python changes should use typed, small helper functions and pytest coverage.
- CFG-001: Any provider/freshness knobs should go through config, not hard-coded environment assumptions.
- TEST-001 through TEST-004: Use focused unit tests plus API-level coverage where behavior crosses module boundaries.

## Conflicts

The current implementation allows candidate lifecycle ingestion to proceed when discovery rows lack the required technical snapshot. That conflicts with the user requirement that missing MA/MACD/RSI/volume/amount fields must block automatic quant entry.

The prior scoring fix made score and confidence structured, but it did not guarantee the market-data inputs behind technical confirmation. This means a candidate can have a lifecycle score while still missing the technical snapshot required for quant decisions.

The current UI can show discovery success without clearly showing whether the result is technically ready for quant lifecycle evaluation.

## Context Gaps

- Exact readiness threshold for 30m bars is not yet specified.
- Provider fallback order needs confirmation or a clear default.
- Freshness rules need to account for market hours, after-hours, holidays, and suspended stocks.
- The desired UI presentation for blocked versus recommended-only candidates needs final wording.
- It is not yet confirmed whether manual pool entry should bypass or retry the same snapshot gate.

## Design Implications

The next spec should define a hard data contract:

- Discovery output is not lifecycle-ready until 30m market and indicator snapshot readiness is known.
- Candidate event payloads must carry both the snapshot fields and the completeness result.
- Lifecycle auto-entry must reject incomplete snapshots even if discovery enrichment is bypassed.
- UI must expose readiness and missing fields directly.

The implementation should likely batch unique symbols, prepare snapshots through existing market-data and indicator services, merge results into lifecycle rows, and persist blocked diagnostics for incomplete rows.
