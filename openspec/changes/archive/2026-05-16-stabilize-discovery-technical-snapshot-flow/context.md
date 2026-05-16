# Context: Stabilize Discovery Technical Snapshot Flow

## Sources Read

- `AGENTS.md`
- `openspec/AGENTS.md`
- `openspec/project.md`
- `docs/ai-context/source-index.md`
- `docs/rules/project-implementation-standards.md`
- `docs/rules/python-code-standards.md`
- `docs/rules/configuration-standards.md`
- `docs/rules/testing-standards.md`
- `docs/standards/architecture.md`
- `docs/standards/backend.md`
- `docs/standards/api.md`
- `docs/standards/testing.md`
- `docs/wiki/discovery-lifecycle-scoring-and-auto-entry-diagnostics.md`
- `docs/wiki/stock-discovery-technical-snapshot-readiness.md`
- `openspec/changes/archive/2026-05-15-fix-discover-lifecycle-scoring/specs/discover-lifecycle-entry/spec.md`
- `openspec/changes/archive/2026-05-16-discover-market-data-snapshot-gate/specs/discover-lifecycle-entry/spec.md`
- `app/discover/discover.py`
- `app/discover/market_snapshot.py`
- `app/discover/lifecycle_scoring.py`
- `app/gateway/quant_universe_entry.py`
- `app/quant_sim/candidate_entry_gate.py`
- `app/quant_sim/quant_universe_lifecycle.py`
- `app/stock_refresh_scheduler.py`
- `tests/test_discover_market_snapshot.py`
- `tests/test_discover_lifecycle_scoring.py`

## Existing Specs

- Archived change `fix-discover-lifecycle-scoring` requires discovery candidates to publish normalized score, confidence, trend, and technical confirmation inputs. It explicitly says source identity alone must not add score, and lifecycle thresholds/gates must remain unchanged.
- Archived change `discover-market-data-snapshot-gate` requires discovery tasks to prepare 30m technical snapshots before automatic lifecycle eligibility. Complete snapshots require price/close, MA fields, MA20 slope, amount, volume ratio, RSI, MACD, trend, timestamp, provider, timeframe, and indicator version. Incomplete snapshots must block automatic trial entry with `missing_technical_snapshot`.
- Both archived changes say old records are not rewritten or migrated. New discovery runs must produce corrected evidence.

## Existing Code Patterns

- `app/discover/discover.py::_discover_row_from_mapping` normalizes lifecycle score evidence before market snapshot preparation. This creates rows where `technical_confirmation_count` and `trend` can be calculated from raw selector data only.
- `app/discover/discover.py::_run_discover_task` runs strategies, reads `_discover_rows(context)`, calls `prepare_discovery_market_snapshots(rows)`, and then passes those prepared rows to `ingest_lifecycle_entry_rows`.
- `app/discover/discover.py::_discover_rows` rebuilds rows from raw selector result snapshots and then calls `enrich_lifecycle_entry_rows`. It does not call `prepare_discovery_market_snapshots` and does not read a candidate artifact hydrated from a full unified technical snapshot.
- `app/discover/market_snapshot.py::prepare_discovery_market_snapshots` can prepare and merge 30m technical snapshot fields into rows. Manual local verification showed it can complete rows for current stale selector candidates.
- `app/gateway/quant_universe_entry.py::_candidate_event_payload` persists technical snapshot fields when they are present on rows. It does not synthesize missing MA/MACD/RSI values.
- `app/gateway/quant_universe_entry.py::enrich_lifecycle_entry_rows` hydrates lifecycle status and technical snapshot diagnostics from candidate event payloads, but does not hydrate raw technical indicator fields into discover rows.
- `app/quant_sim/candidate_entry_gate.py` rejects incomplete discovery snapshots before source-family gates.
- `app/quant_sim/quant_universe_lifecycle.py::ingest_candidate_event` adds candidate event, evaluates entry gate, then calculates lifecycle candidate score.
- `app/stock_refresh_scheduler.py::UnifiedStockRefreshScheduler` is the existing shared stock refresh path. It currently collects watchlist stocks, portfolio stocks, active quant candidates, and open positions. It does not clearly include latest discovery candidates that are not yet active, and its persisted runtime entries currently store latest price/basic info rather than full technical indicator fields.
- `app/discover/discover.py::_discover_rows` already overlays `load_stock_runtime_entries` for name/sector/latest price, which shows the codebase already has a partial pattern for hydrating discover rows from shared refresh data. That pattern is not yet complete enough for MA/MACD/RSI/amount/trend lifecycle evidence.

## Wiki / Standard Rules Applied

- `docs/wiki/discovery-lifecycle-scoring-and-auto-entry-diagnostics.md` says discovery task output should preserve structured score, confidence, trend, and technical confirmation evidence.
- `docs/wiki/stock-discovery-technical-snapshot-readiness.md` says discovery task workflow should prepare snapshots, merge them into rows, persist candidate event payloads, and expose readiness in API/UI.
- `docs/standards/*.md` files are placeholders and do not add concrete behavior beyond source-index read requirements.

## Project Rules Applied

- `PIR-001`: Design and tasks must identify code paths by feature point.
- `PIR-002`: Generated/modified files must stay under 1000 lines.
- `PIR-003` / `CFG-005`: If DB-backed candidate artifacts or runtime technical snapshots are chosen later, design must state SQLite/MySQL behavior and connection pool <= 100.
- `PIR-004`: Any API-visible change must be designed from OpenAPI and separate controller/service responsibilities.
- `PIR-005`: Expensive market-data preparation must remain asynchronous rather than happening in discover page reads.
- `PY-001`, `PY-003`, `PY-007`: Python changes should follow package layout, explicit imports, and visible error handling.
- `TEST-001`, `TEST-002`, `TEST-003`, `TEST-007`, `TEST-008`, `TEST-010`: Future tests need explicit OpenSpec parameters, meaningful behavior assertions, isolated external IO, and coverage evidence.

## Conflicts

- Existing wiki says discovery task merges prepared snapshots into rows and API/UI expose readiness. Current `_snapshot_discover` can still show raw selector rows with all technical fields empty because latest technical snapshots are not the source for the API.
- Existing spec says candidates with complete snapshots may proceed to normal score/confidence/technical confirmation rules. Current score normalization can happen before snapshot preparation, so technical confirmation may not reflect prepared data.
- Previous behavior intentionally avoids rewriting old historical records. That does not conflict with fixing new discovery run output, but it means stale old rows need explicit stale/unprepared diagnostics instead of silent backfill.
- Existing stock refresh behavior points toward one shared latest-stock-data path, but current discovery snapshot preparation is separate and discovery candidates are not guaranteed to be part of the refresh universe. The future design should unify these rather than make discovery maintain its own long-lived technical truth.

## Context Gaps

- The codebase does not currently expose a clear discovery candidate artifact repository.
- It is not yet decided whether discovery candidate output should be stored in SQLite, JSON under selector results, or another existing cache.
- The unified stock refresh runtime snapshot does not currently persist all technical indicator fields required by discovery lifecycle readiness.
- The refresh freshness SLA for discovery auto-entry is not yet defined.
- There is no active OpenSpec capability spec under `openspec/specs`; relevant requirements are archived.
- Existing tests cover preparation and lifecycle ingestion, but they do not fully pin that discover API and lifecycle ingestion hydrate from the same latest refreshed stock snapshot.
- Existing tests do not appear to require post-refresh re-normalization of `technical_confirmation_count`.

## Design Implications

- The next `/sp-spec` should define the discovery candidate artifact contract plus the latest refreshed technical snapshot contract consumed by discovery/lifecycle/API.
- The next `/sp-tasks` should design storage location, refresh registration, freshness rules, and read/write ownership before code changes.
- Page reads should not trigger expensive market-data preparation; they should read the latest candidate artifact hydrated with existing refreshed snapshots or explicitly report stale/unprepared fallback rows.
- Lifecycle ingestion and discover API rendering should consume the same hydrated candidate view for a given discovery task/run.
- Snapshot refresh/hydration should precede lifecycle scoring normalization for new discovery task output.
- Old selector files and old candidate events should remain untouched, but UI/API must not imply they are current prepared outputs.
