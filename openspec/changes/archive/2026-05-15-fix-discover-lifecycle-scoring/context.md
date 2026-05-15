# Context: Fix Discover Lifecycle Scoring

## Sources Read

- `AGENTS.md`
- `openspec/AGENTS.md`
- `openspec/project.md`
- `docs/ai-context/source-index.md`
- `docs/rules/project-implementation-standards.md`
- `docs/rules/python-code-standards.md`
- `docs/rules/testing-standards.md`
- `docs/rules/configuration-standards.md`
- `docs/standards/backend.md`
- `docs/standards/api.md`
- `docs/standards/testing.md`
- `app/discover/discover.py`
- `app/discover/ai_stock_scanner.py`
- `app/gateway/quant_universe_entry.py`
- `app/quant_sim/candidate_entry_gate.py`
- `app/quant_sim/quant_universe_lifecycle.py`
- `tests/test_ai_stock_scanner.py`
- `tests/test_ui_backend_api_actions.py`
- `tests/test_research_watchlist_integration.py`
- family-mac runtime DB/API observations from the prior investigation.

## Existing Specs

No active OpenSpec capability specs exist under `openspec/specs/` beyond `.gitkeep`. No active change folders overlap this scope.

Existing test behavior acts as de facto context:

- `tests/test_ui_backend_api_actions.py` already has tests showing that discovery auto-promotes when fake selector rows include `score`, `confidence`, `trend`, and technical evidence.
- `tests/test_ai_stock_scanner.py` verifies `AIStockScanner` calculates `scanner_score`, `theme_score`, `technical_score`, and `technical_reasons`.
- `tests/test_research_watchlist_integration.py` shows lifecycle read-only fields expose candidate score and eligible status when candidate events contain structured score/confidence.

## Existing Code Patterns

- `app/discover/discover.py` maps selector outputs into discover rows through `_discover_row_from_mapping`.
- `_discover_row_from_mapping` already recognizes `score`, `scanner_score`, `confidence`, `trend`, `ma5`, `ma10`, `ma20`, `ma20_slope`, `amount`, `volume_ratio`, `rsi`, and `macd` when those fields are present.
- `_run_ai_scanner_strategy` currently calls `AIStockScanner.scan()` and then rebuilds a small DataFrame that drops `scanner_score`, `theme_score`, `technical_score`, and `technical_reasons`.
- `app/gateway/quant_universe_entry.py` converts discover rows into lifecycle events through `_candidate_event_payload`; `_source_score` reads `source_score`, `score`, or `scanner_score`; `_confidence` reads `confidence`, `confidence_score`, or `source_confidence`.
- `app/quant_sim/candidate_entry_gate.py` treats AI/research sources through `_research_gate`. AI candidates with missing score or confidence are marked `recommended_only` with `ai_requires_technical_confirmation`.
- `app/quant_sim/quant_universe_lifecycle.py` computes candidate score from `recommendation_score_component`, `confidence_component`, `trend_component`, and bonuses/penalties. With zero score/confidence and neutral trend, aggressive scoring becomes `0.075`.

## Wiki / Standard Rules Applied

- Backend/API/testing standards are placeholders and do not add concrete behavior beyond the project rules.
- `docs/ai-context/source-index.md` requires reading Python, configuration, and testing rules for this scope.

## Project Rules Applied

- `PIR-001`: Later design/tasks must identify exact modified code paths.
- `PIR-002`: Later implementation must keep changed files <= 1000 lines; `app/discover/discover.py` is a likely risk because it is already broad.
- `PIR-003`: This change reads/writes existing database tables through existing DB runtime; no new database is expected, but design must state database impact explicitly.
- `PIR-004`: No new backend API is currently implied; existing discover API behavior changes. If API response fields are added, OpenAPI/API impact must be documented in design.
- `PIR-005`: Discovery is time-consuming and already runs async through task manager; design should preserve async behavior.
- `PY-001..PY-011`: Python changes should follow existing package layout, typed helper functions where practical, explicit error handling, and no hidden IO failures.
- `TEST-001`: Changed/affected code requires at least 90% coverage evidence.
- `TEST-002`: OpenSpec-driven tests require explicit parameter files under `openspec/changes/fix-discover-lifecycle-scoring/test-params/` in later implementation.
- `TEST-003`: Tests must assert meaningful behavior such as persisted candidate event score/confidence and AI gate status.
- `CFG-005`: Existing DB behavior must remain compatible with SQLite/MySQL runtime decisions and connection pooling from prior DB work.

## Conflicts

- Current code comments in `candidate_entry_gate.py` and `quant_universe_lifecycle.py` state source identity must not add points by itself. Any proposal to auto-score purely from source labels would conflict with this and should be rejected.
- The user wants discovery results to enter lifecycle automatically when rules permit. Current runtime behavior shows discovery results are written but score/confidence are missing, so the current implementation conflicts with that expected behavior.
- Existing manual UI batch quant path can directly create `active` rows without lifecycle promotion events. This is related to audit consistency but outside the narrow discovery scoring fix unless the next phase expands scope.

## Context Gaps

- The exact business formula for non AI strategy `source_score/confidence` is not specified by an approved spec.
- The desired UI visibility for score/confidence/technical confirmation is not specified.
- The acceptable auto-entry rate per strategy after scoring normalization is not specified.
- It is not yet decided whether historical candidate events with zero score/confidence should be ignored or remediated.

## Design Implications

- The design should introduce a discover candidate scoring/normalization boundary instead of spreading ad hoc field mapping through selector runners.
- AI scanner should preserve structured fields from `AIStockScanner.scan()` and should not downgrade them to reason text.
- Non AI selectors need deterministic score/confidence fallback logic that is evidence-based and testable.
- Tests should cover both the row normalization level and the persisted lifecycle event level.
- Runtime verification should include a discovery run showing nonzero `source_score/confidence`, correct `entry_gate`, and explainable promoted/eligible/skipped counts.
