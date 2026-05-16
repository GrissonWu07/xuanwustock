# Design: Discover Market Data Snapshot Gate

## Current Behavior

Discovery strategies write selector results, then the discovery task builds UI rows and immediately hands those rows to lifecycle ingestion. If strategy output does not already include 30m market data and technical indicators, candidate event payloads are created with missing `ma5`, `ma10`, `ma20`, `ma20_slope`, `ma60`, `amount`, `volume_ratio`, `rsi`, and `macd`.

The candidate entry gate currently allows some discovery source families to continue when market data is missing. This lets score and confidence evidence drive lifecycle evaluation even when the structured technical snapshot is incomplete.

The discovery UI renders candidate table cells plus lifecycle badges. It does not currently expose a dedicated technical snapshot readiness state or missing-field list.

The deployment reset script deletes database files and SQLite sidecars. It does not intentionally delete local market-data caches, but tests should lock that behavior because the runtime issue was caused by cache removal outside normal DB reset semantics.

## Target Behavior

Discovery task flow:

1. Run selected discovery strategies.
2. Build discovery rows once for the task.
3. Prepare 30m technical snapshots for each unique stock code in those rows before lifecycle ingestion.
4. Merge snapshot fields and readiness diagnostics into every matching row.
5. Ingest candidate events with the merged technical snapshot payload.
6. Block automatic lifecycle entry for any discovery candidate whose snapshot is incomplete.
7. Return task diagnostics with prepared, complete, incomplete, failed, and blocked counts.

Readiness uses a strict 30m technical snapshot baseline. A complete snapshot requires:

- `close` or current price
- `ma5`
- `ma10`
- `ma20`
- `ma20_slope`
- `ma60`
- `amount`
- `volume_ratio`
- `rsi` or a normalized RSI alias
- `macd`
- `trend`
- `snapshot_at`
- `provider`
- `timeframe`
- `indicator_version`

Freshness default: this change treats completeness as the blocking condition and records snapshot time/provider as diagnostics. Staleness should be visible but should not block automatic entry unless the snapshot is absent or incomplete. A stricter trading-session freshness gate is a future spec because it requires market-calendar semantics not defined here.

Incomplete discovery candidates use `missing_technical_snapshot` as the machine-readable gate reason and must not enter automatic quant trial state.

## Architecture Impact

Add a focused discovery snapshot preparation boundary. Recommended code path:

- New module: `app/discover/market_snapshot.py`
- Primary caller: `app/discover/discover.py`
- Defensive gate: `app/quant_sim/candidate_entry_gate.py`
- Payload and row enrichment: `app/gateway/quant_universe_entry.py`
- Market data service improvements when needed: `app/data/services/market_data_service.py`

The snapshot preparation boundary should be small and data-oriented:

- Input: discovery rows with stock code/name/source metadata.
- Output: enriched rows plus aggregate diagnostics.
- No lifecycle status writes inside the snapshot preparation module.
- No UI rendering decisions inside the snapshot preparation module.

The lifecycle gate remains responsible for final pass/block semantics. Snapshot preparation makes the data available; the gate enforces that incomplete discovery snapshots cannot pass.

## Data Impact

No relational schema migration is required.

Existing candidate event payload JSON should carry:

- Normalized technical fields at the existing payload level for entry-gate compatibility.
- `technical_snapshot_ready`: boolean.
- `technical_snapshot_status`: `ready`, `incomplete`, or `failed`.
- `technical_snapshot_missing_fields`: list of missing canonical field names.
- `technical_snapshot_timeframe`: `30m`.
- `technical_snapshot_provider`: provider name.
- `technical_snapshot_at`: snapshot bar time.
- `technical_snapshot_prepared_at`: task preparation time.
- `technical_snapshot_row_count`: number of indicator rows used when available.

Existing historical records are not rewritten. UI and enrichment logic must tolerate older candidate events that do not contain the new fields.

Primary runtime DB access remains through the existing DB runtime and `context.quant_db()`. Local development remains SQLite by default; deployment remains compatible with MySQL through the existing runtime layer. No new connection pool is introduced by this change.

## API Impact

OpenAPI-visible operations affected:

- `GET /api/v1/discover`
- `POST /api/v1/discover/actions/run-strategy`
- Existing generic page snapshot/action routes that delegate to discovery snapshots and actions.

Discovery candidate rows should add these API fields:

- `technical_snapshot_ready`
- `technical_snapshot_status`
- `technical_snapshot_missing_fields`
- `technical_snapshot_timeframe`
- `technical_snapshot_provider`
- `technical_snapshot_at`
- `technical_snapshot_prepared_at`

Discovery task result should add:

- `technicalSnapshotPreparation.uniqueStocks`
- `technicalSnapshotPreparation.prepared`
- `technicalSnapshotPreparation.complete`
- `technicalSnapshotPreparation.incomplete`
- `technicalSnapshotPreparation.failed`
- `technicalSnapshotPreparation.blocked`
- `technicalSnapshotPreparation.items`

Each failed or incomplete item should include stock code and safe reason or missing-field list.

The API should keep existing fields for backward compatibility. New fields are additive.

## UI Impact

Update discovery UI types and rendering:

- Extend `TableRow` in `ui/src/lib/page-models.ts` with technical snapshot readiness fields.
- Show a compact readiness badge in the discovery candidate table or the existing quant-status cell.
- For incomplete rows, display `missing_technical_snapshot` and the missing-field list in a readable compact form.
- Extend the run feedback summary to include technical snapshot preparation counts when present.

UI timestamps for discovery readiness must use the system-local display style already used by discovery rows. UTC ISO strings must not be shown directly in table text.

## Integration Impact

Market-data preparation may use local cache, provider fetch, and indicator generation. The preferred integration path is the existing market-data and indicator stack:

- `MarketDataService` for provider-facing market data.
- `TechnicalIndicatorEngine` for canonical indicators.
- Existing TDX/local cache clients for provider-local 30m data when configured.

The design should not introduce a separate remote market-data dependency if the existing TDX/local cache path can provide 30m bars. If the current `MarketDataService` cannot fetch missing TDX 30m bars because it uses an empty remote fetcher, update that service boundary rather than bypassing it in lifecycle code.

Market-data preparation should be bounded by unique stock count, timeout handling, and safe per-symbol failure reporting. A failed symbol blocks that candidate but does not fail the whole discovery task when strategies completed successfully.

## Security Impact

No new credentials should be added.

Provider errors and diagnostics must include safe identifiers such as stock code, provider, and missing field names only. They must not log secrets, private endpoints, tokens, or raw signed requests.

Cache deletion must remain explicit. DB cleanup commands must not broaden their filesystem scope to market-data cache directories.

## Error Handling

- Missing local data triggers a preparation attempt.
- Provider returns empty data: candidate snapshot status becomes `failed` or `incomplete`; auto-entry is blocked with `missing_technical_snapshot`.
- Indicator generation returns rows but required fields are null: candidate snapshot status becomes `incomplete`; missing fields are listed.
- One candidate fails preparation: discovery task completes with diagnostics if strategy execution completed.
- All strategies fail: existing discovery task failure behavior remains.
- Candidate event ingestion fails: existing per-stock skipped summary remains, with the new diagnostics preserved where available.

## Compatibility / Migration

No old database records are migrated or rewritten.

Older candidate events without technical snapshot diagnostics should render as not evaluated or unknown readiness instead of causing UI errors.

Existing discovery strategy formulas, thresholds, candidate duplication behavior, historical replay, and realtime simulation decision logic are unchanged.

DB reset behavior remains database-file scoped. Local market-data caches under `data/local_sources` or configured cache directories are preserved unless a future explicit cache deletion command is added.

## Test Strategy

Backend tests:

- Unit-test snapshot readiness classification with complete rows, missing fields, insufficient MA60 readiness, and provider failure.
- Unit-test discovery task enrichment with duplicate rows sharing one unique snapshot result.
- Unit-test lifecycle gate blocking discovery candidates that have score/confidence but incomplete snapshot.
- API-level test `GET /api/v1/discover` exposes readiness fields and does not render UTC ISO table timestamps.
- Reset script test proves DB reset does not delete `local_sources` cache content.

UI tests:

- Discovery page renders readiness badges and missing-field diagnostics.
- Discovery task feedback renders technical snapshot preparation counts.
- Existing lifecycle badges and promote/ignore controls continue to work.

External IO must be mocked in unit tests. Real provider integration tests, if added, must be opt-in and disabled by default.

Coverage target is at least 90% for changed or affected code.

## Rules Compliance

- PIR-001: Code paths are identified in Source Mapping and tasks.
- PIR-002: New snapshot logic should stay in a focused module and keep modified files under 1000 lines.
- PIR-003: No schema change is required; existing DB runtime is used.
- PIR-004: API-visible discovery row/task fields are identified.
- PIR-005: Discovery remains asynchronous; market-data work runs inside the task, not the request thread.
- CFG-001: Provider/timeframe/freshness behavior is explicitly owned by discovery snapshot preparation.
- CFG-005: No database configuration or migration is added.
- CFG-009: OpenSpec test parameter files are required for behavioral tests.
- TEST-001: Coverage target is at least 90%.
- TEST-002: Tasks require explicit test parameter files.
- TEST-003: Tests assert blocked and complete outcomes.
- TEST-007 and TEST-008: Python tests use pytest conventions and mock external IO.

## Source Mapping

| Design Decision | Source | Reason |
|---|---|---|
| Prepare snapshots before lifecycle ingestion in the discovery task | `openspec/changes/discover-market-data-snapshot-gate/specs/discover-lifecycle-entry/spec.md`; `app/discover/discover.py` | The spec requires readiness before automatic lifecycle eligibility; current task calls lifecycle ingestion immediately after strategy execution. |
| Evaluate readiness once per unique stock code | Spec scenario "Duplicate discovery rows reference the same stock"; `ingest_lifecycle_entry_rows()` already deduplicates by code | Keeps duplicate display rows while avoiding repeated market-data work. |
| Use 30m MA/MACD/RSI/volume fields as the blocking technical contract | Spec "Complete Snapshot Defines Automatic Entry Readiness"; family-mac runtime evidence in `context.md` | These are the missing fields that caused invalid lifecycle entry. |
| Store readiness in candidate event payload JSON rather than a new table | `app/gateway/quant_universe_entry.py`; `app/quant_sim/quant_universe_lifecycle.py` | Candidate events already persist payload and entry-gate diagnostics; no schema change is needed. |
| Enforce `missing_technical_snapshot` in the candidate entry gate | Spec "Lifecycle Gate Defends Against Incomplete Discovery Inputs"; `app/quant_sim/candidate_entry_gate.py` | Prevents bypass when score/confidence exists without structured indicators. |
| Hydrate UI rows from latest lifecycle event diagnostics | `enrich_lifecycle_entry_rows()` in `app/gateway/quant_universe_entry.py`; `ui/src/features/discover/discover-page.tsx` | Discovery table already consumes enriched lifecycle fields and can add readiness fields additively. |
| Preserve market-data caches during DB reset | Spec "Normal DB Cleanup Preserves Market Data Cache"; `scripts/reset_stock_universe_deployment.py` | The reset script should remain database-file scoped and have regression coverage. |

## Spec Gaps

No blocking gaps prevent implementation.

The current spec does not require manual "promote to trial" actions to retry or bypass snapshot preparation. This design leaves manual action semantics unchanged and only adds visible diagnostics for blocked discovery candidates. A future spec should define manual retry behavior if needed.

The current spec also does not require a trading-calendar freshness gate. This design records snapshot timestamps and provider diagnostics but blocks only on missing or incomplete fields.
