# Design: Fix Discover Lifecycle Scoring

## Current Behavior

Discovery strategies can return candidate rows, and discovery tasks call the
quant lifecycle ingestion path after strategy execution. The lifecycle path
works when rows contain explicit `score`, `confidence`, trend, and technical
evidence.

The current failure is at the discovery boundary:

- AI scanner results contain structured `scanner_score`, `theme_score`,
  `technical_score`, and `technical_reasons`, but the discover strategy runner
  rebuilds a display-only DataFrame and drops most structured fields.
- Non-AI selector results often contain code, name, source, price, and display
  text but no normalized `score` or `confidence`.
- The lifecycle ingestion layer reads `source_score`, `score`, `scanner_score`,
  and `confidence`, but falls back to `0.0` when those fields are absent.
- The source entry gate intentionally does not add score from source identity.
  With `source_score=0`, `confidence=0`, and neutral trend, aggressive
  lifecycle score becomes `0.075`, so candidates do not enter `trial`.

## Target Behavior

Discovery output will have a stable lifecycle input contract before it is
persisted, displayed, or ingested:

- `score` and `source_score`: normalized recommendation score in `0.0..1.0`.
- `confidence`: normalized confidence in `0.0..1.0`.
- `trend`: `up`, `neutral`, or `down`.
- `technical_confirmation_count`: non-negative integer evidence count.
- `lifecycle_score_diagnostics`: machine-readable diagnostics describing
  whether score/confidence were explicit or derived, what evidence was present,
  and why evidence was insufficient when score/confidence remain zero.

Explicit strategy scores always win after normalization. Derived scoring is
used only when measurable evidence is present. A row with only source identity
and no measurable evidence keeps `score=0.0`, `confidence=0.0`, and receives an
insufficient-evidence diagnostic.

Lifecycle thresholds, gates, capacity limits, and auto-entry modes remain
unchanged.

## Architecture Impact

Add a dedicated discovery lifecycle scoring module instead of expanding
`app/discover/discover.py` further. The discover gateway will call this module
when shaping strategy rows.

Recommended code paths:

- Create `app/discover/lifecycle_scoring.py`.
- Modify `app/discover/discover.py` only as the orchestration boundary:
  preserving AI scanner fields, passing strategy key/rank context to the
  normalizer, adding visible diagnostic table columns, and preserving async
  task behavior.
- Modify `app/gateway/quant_universe_entry.py` to pass normalized diagnostics,
  confidence, and technical confirmation fields into candidate event payloads
  and read-only row enrichment.
- Do not change lifecycle thresholds in
  `app/quant_sim/quant_universe_lifecycle.py`.
- Do not change source-family gate semantics in
  `app/quant_sim/candidate_entry_gate.py` except if a narrow fix is required
  to consume already-normalized evidence.

### Normalization Formula

All numeric scores are normalized with existing semantics: values in
`0.0..1.0` are kept, values in `1..100` are divided by `100`, and everything is
clamped to `0.0..1.0`.

Explicit score fields:

1. `source_score`
2. `score`
3. `scanner_score`
4. `candidate_score`

Explicit confidence fields:

1. `confidence`
2. `confidence_score`
3. `source_confidence`

### AI Scanner Scoring

AI scanner rows use `scanner_score` as lifecycle `source_score`.

AI confidence is derived when no explicit confidence is present:

```text
confidence =
  0.45 * technical_score
+ 0.25 * theme_score
+ 0.20 * sector_score
+ 0.10 * data_quality
```

Where missing `technical_score`, `theme_score`, or `sector_score` use neutral
`0.5`, but `data_quality` is reduced. `data_quality` is the ratio of populated
structured fields among:

- stock name
- industry or sector
- latest price
- market cap
- PE
- PB
- scanner score
- technical reasons

Technical confirmation for AI rows is derived from structured
`technical_reasons`, not from display `reason` text. Positive confirmations are
recognized from tokens such as `trend=up`, `ma_short_up`,
`close_above_ma20`, `ma20_slope_up`, `macd_bullish`, `volume_expansion`, and
`momentum_20d_positive`. Negative trend is recognized from tokens such as
`trend=down`, `ma_short_down`, `close_below_ma20`, `ma20_slope_down`, and
`macd_bearish`.

AI trend is:

- `up` when explicit trend is up, or at least two positive technical
  confirmations exist.
- `down` when explicit trend is down, or negative technical evidence shows a
  falling MA20 / bearish MACD pattern.
- `neutral` otherwise.

AI rows with `technical_data_unavailable` or `technical_score_error` may still
publish scanner score and confidence, but technical confirmation remains low
and the lifecycle gate may classify them as `recommended_only`.

### Non-AI Fallback Scoring

Non-AI rows without explicit score or confidence use deterministic
evidence-based scoring. The normalizer requires at least two measurable
evidence buckets before deriving nonzero score/confidence. Source identity and
display-only reason text do not count as measurable evidence.

Evidence buckets:

- Rank evidence from strategy output order within the current result set.
- Market data evidence from latest price, market cap, PE, and PB.
- Liquidity evidence from amount, turnover, or volume ratio.
- Technical evidence from MA values, MA20 slope, MACD, RSI, or explicit
  technical confirmation count.
- Strategy measurable evidence from numeric selector fields such as fund-flow,
  growth, valuation, rank score, or price-change score when present.

Derived source score:

```text
source_score =
  0.35 * rank_component
+ 0.25 * strategy_component
+ 0.20 * data_quality
+ 0.10 * liquidity_component
+ 0.10 * technical_component
```

Derived confidence:

```text
confidence =
  0.35 * data_quality
+ 0.25 * liquidity_component
+ 0.20 * technical_data_quality
+ 0.20 * strategy_evidence_quality
```

Component definitions:

- `rank_component`: `1.0` for the top row, linearly decreasing to `0.45` for
  the last row. Single-row results use `1.0`.
- `data_quality`: populated ratio among latest price, market cap, PE, and PB.
- `liquidity_component`: `amount / 80,000,000` clamped to `0.0..1.0`; if
  amount is absent but volume ratio exists, use `volume_ratio / 2.0` clamped;
  otherwise `0.0`.
- `technical_component`: `technical_confirmation_count / 4.0` clamped.
- `technical_data_quality`: populated ratio among MA5, MA10, MA20, MA20 slope,
  RSI, and MACD.
- `strategy_component`: explicit numeric strategy-strength fields when present
  and normalized; otherwise rank component is used only when at least one
  non-source evidence bucket is present.
- `strategy_evidence_quality`: populated ratio for numeric strategy-strength
  fields known to the row; when no such fields exist, use `rank_component` only
  if market data evidence exists.

If the evidence bucket requirement is not met, the row gets:

- `score=0.0`
- `source_score=0.0`
- `confidence=0.0`
- `trend=neutral`
- diagnostic reason `insufficient_measurable_evidence`

## Generated Code Paths

Planned generated or modified code paths by feature area:

| Feature Area | Code Paths |
|---|---|
| Discovery normalization | `app/discover/lifecycle_scoring.py`, `app/discover/discover.py` |
| Lifecycle event payload and row enrichment | `app/gateway/quant_universe_entry.py` |
| Backend API regression tests | `tests/test_discover_lifecycle_scoring.py`, `tests/test_ui_backend_api_actions.py` |
| AI scanner regression tests | `tests/test_ai_stock_scanner.py` when direct scanner behavior changes |
| Frontend contract/types and display | `ui/src/lib/page-models.ts`, `ui/src/features/discover/discover-page.tsx`, `ui/src/features/quant/quant-entry-controls.tsx` |
| Frontend tests | `ui/src/tests/discover-page.test.tsx` |
| API/docs consistency | `docs/后端能力与服务接口清单.md`, `docs/量化股票生命周期与自动入池流程说明.md` when response/documentation text needs alignment |
| OpenSpec test parameters | `openspec/changes/fix-discover-lifecycle-scoring/test-params/*.md` |

## File Size / Split Plan

`app/discover/discover.py` is already close to the 1000-line guardrail. New
normalization logic must live in `app/discover/lifecycle_scoring.py`.

Implementation must verify every generated or modified Python/TypeScript code
file remains at or below 1000 lines. If a touched file would exceed the limit,
split lifecycle scoring, UI helpers, or tests before marking the task complete.

## Data Impact

No new database tables are required.

Existing selector result JSON files will include additional structured fields
for new discovery runs. Existing candidate event rows will keep their old
payloads. New candidate events will include lifecycle diagnostics and technical
confirmation evidence in `payload_json`.

Existing historical records with zero score/confidence are not rewritten.

## Database Decision

This change uses the existing quant database runtime. It requires database
reads and writes through existing application services, but it does not require
a new database, a schema migration, or new connection pool configuration.

The existing runtime remains responsible for SQLite local behavior, MySQL
deployment behavior, and connection pool limits. No pool may exceed size 100.

## API Impact

No new API route is added.

Existing FastAPI operations affected:

- `GET /api/v1/discover`
- `POST /api/v1/discover/actions/run-strategy`
- `GET /api/v1/tasks/{task_id}` for discovery task result inspection

Response schema additions are backward compatible:

- Candidate rows include `score`, `source_score`, `confidence`,
  `candidate_confidence`, `technical_confirmation_count`, and
  `lifecycle_score_diagnostics` when available.
- Candidate tables expose visible score/confidence diagnostics through added
  columns or row detail fields.
- Discovery task result `quantAutoEntry` continues to include attempted,
  events, eligible, promoted, and skipped counts and must include
  machine-readable skip reasons.

## OpenAPI / Backend Layering

The project currently uses FastAPI route functions as the OpenAPI source. The
design identifies the existing OpenAPI operations above. Implementation should
preserve controller/service separation already present in this area:

- FastAPI route layer in `app/gateway_api.py` remains transport-only.
- Discovery orchestration stays in `app/discover/discover.py`.
- Lifecycle scoring is delegated to `app/discover/lifecycle_scoring.py`.
- Quant lifecycle event payload mapping stays in
  `app/gateway/quant_universe_entry.py`.

No route should embed scoring formulas directly.

## API IO / Async

`GET /api/v1/discover`:

- IO: reads selector result files and quant database state.
- Execution: synchronous snapshot read, no long-running strategy work.

`POST /api/v1/discover/actions/run-strategy`:

- IO: may call selector data providers, write selector result files, read/write
  quant database candidate lifecycle events.
- Execution: remains async via the existing discovery task manager. The request
  may briefly wait for task completion according to existing `waitMs`, but
  long-running strategy execution remains background work.

`GET /api/v1/tasks/{task_id}`:

- IO: reads in-memory task manager state.
- Execution: synchronous status read.

## UI Impact

The discover UI should expose lifecycle diagnostics without adding a separate
new page:

- Candidate table should show score and confidence when returned by the backend
  or otherwise make them visible through the row's quant status area.
- The existing quant status badge remains the main status indicator.
- Blocking reasons remain visible next to the status badge.
- No UTC timestamps may be introduced in table display as part of this change.

## Integration Impact

Discovery-to-lifecycle integration becomes stricter:

- AI scanner structured fields must not be downgraded to display text.
- Non-AI selectors get a single normalized handoff shape before lifecycle
  ingestion.
- Candidate entry gates continue to consume normalized event payloads.
- Realtime quant and historical replay buy/sell decision logic are not changed.

## Security Impact

No new authentication surface is introduced.

The implementation must avoid logging secrets or provider credentials when
strategy calls fail. Diagnostics must use safe stock codes, strategy keys, and
reason codes only. Tests must not use real credentials.

## Error Handling

Strategy failures keep the existing partial-completion behavior:

- If all selected strategies fail, the discovery task status is `failed`.
- If some strategies succeed, the task is `completed` with failed strategy
  details.
- Lifecycle ingestion failures are recorded in `quantAutoEntry.skipped` with
  machine-readable reasons and must not hide successful strategy output.
- Invalid numeric score/confidence fields are ignored and recorded in
  diagnostics rather than crashing the task.

## Compatibility / Migration

This is a forward-only compatibility change.

- Old selector result files and old candidate event rows remain readable.
- Old zero-score candidate events are not rewritten.
- New discovery runs generate corrected lifecycle input fields.
- Existing clients that ignore the new fields continue to work.

## Test Strategy

Implementation must create explicit OpenSpec test parameter files under
`openspec/changes/fix-discover-lifecycle-scoring/test-params/`.

Required behavioral coverage:

- AI scanner strategy preserves `scanner_score`, structured technical evidence,
  derived confidence, trend, and technical confirmation through discover output
  and candidate events.
- Non-AI strategy rows without explicit score/confidence derive deterministic
  evidence-based score/confidence when measurable evidence exists.
- Rows with source identity only remain zero-score and expose
  `insufficient_measurable_evidence`.
- Lifecycle auto-entry remains rule-driven and does not lower thresholds.
- Discovery task results include promoted/eligible/skipped diagnostics with
  machine-readable reasons.
- Discover UI displays score/confidence or row-level diagnostics without
  breaking existing batch actions.
- Existing historical candidate records are not rewritten.

Validation commands should include targeted backend tests, targeted frontend
tests when UI files change, file length checks, and coverage evidence showing
at least 90% coverage for changed/affected code.

## Rules Compliance

- `PIR-001`: Design and tasks identify exact code paths.
- `PIR-002`: New scoring logic is split out of `discover.py`; implementation
  must verify code files stay <= 1000 lines.
- `PIR-003` / `CFG-005`: Existing database runtime is reused; no new schema;
  existing SQLite/MySQL/pool decisions remain in force.
- `PIR-004`: Affected FastAPI operations and schema additions are documented.
- `PIR-005` / `CFG-008`: Long-running discovery remains async.
- `PY-001..PY-011`: New Python helper should follow package layout, type hints,
  explicit numeric validation, and safe logging.
- `TEST-001..TEST-010`: Tests require explicit parameter files, meaningful
  assertions, isolated external IO, and at least 90% coverage for
  changed/affected code.

## Source Mapping

| Design Decision | Source | Reason |
|---|---|---|
| Preserve AI structured fields instead of parsing reason text | `openspec/changes/fix-discover-lifecycle-scoring/specs/discover-lifecycle-entry/spec.md`, `app/discover/ai_stock_scanner.py`, `app/discover/discover.py` | Spec requires structured AI evidence to reach lifecycle evaluation; current runner drops fields. |
| Keep lifecycle thresholds and gates unchanged | `proposal.md`, `app/quant_sim/quant_universe_lifecycle.py`, `app/quant_sim/candidate_entry_gate.py` | The issue is missing discovery evidence, not threshold configuration. |
| Do not add score from source identity | `docs/量化股票生命周期与自动入池流程说明.md`, `app/quant_sim/quant_universe_lifecycle.py`, `candidate_entry_gate.py` | Existing lifecycle design says source identity is metadata and must not add points. |
| Add normalization helper module | `PIR-002`, current `app/discover/discover.py` line count | Existing discover gateway is near the file size guardrail. |
| Reuse existing DB runtime without migration | `proposal.md`, `PIR-003`, `CFG-005` | Spec says historical records are not rewritten and no schema change is required. |
| Preserve async discovery task execution | `PIR-005`, existing `DiscoverTaskManager` behavior | Strategy execution can be long-running and already uses background tasks. |
| Expose diagnostics through existing discover API/UI | `Discovery Task Reports Auto Entry Diagnostics` requirement, `ui/src/features/discover/discover-page.tsx` | User needs troubleshooting visibility without a new workflow. |

## Spec Gaps

No blocking spec gaps remain for this design.

The exact scoring formulas and API/UI diagnostic placement were intentionally
left to design and are finalized here within the approved observable behavior.
