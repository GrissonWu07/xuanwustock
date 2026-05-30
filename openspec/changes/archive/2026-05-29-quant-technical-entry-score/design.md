# Quant Technical Entry Score Design

## Current Behavior

Discovery and research rows are normalized into `source_score`, `confidence`,
`trend`, and technical fields. Lifecycle `calculate_candidate_score()` then
uses event `candidate_score/source_score/score`, event `confidence`, trend, and
strong recommendation bonus. This means source ranking and source confidence
can promote a stock even when the technical entry structure is weak.

Discovery currently writes raw selector artifacts under selector-result files,
refreshes runtime market/technical snapshots, hydrates rows, then creates DB
candidate events. Discover API reads hydrated artifact rows and enriches them
from DB lifecycle state.

Default discovery strategy selection excludes `ai_scanner`; AI scanner only
runs when explicitly selected.

## Target Behavior

`candidate_score` becomes a pure technical entry score. `candidate_confidence`
becomes pure technical confidence. Source score, source confidence, source name,
source count, scanner score, and display text are audit-only and ignored by
quant scoring.

Discovery default execution includes `ai_scanner`. After discovery raw rows are
found, the task refreshes行情 and technical indicators, persists prepared rows
as DB candidate events, and downstream lifecycle/API reads DB-prepared evidence
as the business source of truth. Provider/file caches may still accelerate
market-data retrieval, but they are not authoritative after task completion.

User-confirmed E2E decision: real E2E is required. The required E2E path is:
clear local DB only, preserve cache, restart backend if needed, run full stock
discovery including AI scanner, verify technical scores and quant pool entry,
then run live quant drill from `2026-01-01` to current date if discovery and
entry checks pass.

## Architecture Impact

- Add a focused technical entry scoring module under `app/quant_sim/`.
- Keep lifecycle manager as the orchestration boundary and delegate scoring to
  the new module.
- Use candidate event payload JSON as the prepared discovery DB record for this
  change. No dedicated table is required in this iteration because candidate
  events already persist stock identity, source audit metadata, technical fields,
  readiness, entry gate, and score diagnostics.
- Discover API may continue to assemble row presentation from hydrated rows, but
  lifecycle `candidate_score` fallback from source score must be removed.

## Generated Code Paths

- Technical scoring engine:
  - `app/quant_sim/technical_entry_score.py`
  - `app/quant_sim/quant_universe_lifecycle.py`
  - `app/quant_sim/candidate_entry_gate.py`
- Discovery and AI/default handoff:
  - `app/discover/discover.py`
  - `app/gateway/quant_universe_entry.py`
  - `app/discover/candidate_artifact.py`
- Tests:
  - `tests/test_quant_technical_entry_score.py`
  - `tests/test_discover_lifecycle_scoring.py`
  - focused existing tests in `tests/test_ui_backend_api_actions.py` when needed
- OpenSpec parameters and reviews:
  - `.agent/workdir/sp-openspec/quant-technical-entry-score/test-params/*.md`
  - `.agent/workdir/sp-openspec/quant-technical-entry-score/task-reviews.md`
  - `.agent/workdir/sp-openspec/quant-technical-entry-score/review.md`

## Reuse / Common Logic Plan

Reuse existing candidate event payloads, technical snapshot fields, and
candidate entry gates. Extract scoring to `technical_entry_score.py` instead of
duplicating scoring in discover and replay. Lifecycle, discovery, live drill,
and replay must call the same scorer through lifecycle manager entry points.

## Requirement Scope / Compatibility / Fallback

No old DB data migration is required. Legacy rows with source-weighted
breakdowns are treated as zero technical score until re-evaluated with prepared
technical evidence. There is no fallback that substitutes source score as
candidate score.

File/provider caches remain only as market-data retrieval acceleration. Raw
selector cache is not a business source after discovery task completion.

## Method / Function Parameter Plan

Use a named `TechnicalEntrySnapshot` dataclass for technical inputs and a
`TechnicalEntryScoreResult` dataclass for outputs. Public scorer functions must
take no more than five direct parameters.

## File Size / Split Plan

New files must stay below 1000 lines. Existing oversized files
`quant_universe_lifecycle.py` and `db.py` are pre-existing; this change keeps
edits to thin integration shims and places new logic in a new module. No new
logic will be added to `db.py`.

## Data Impact

No schema migration is required. Candidate event `payload_json` stores prepared
technical fields, readiness diagnostics, score breakdown, and entry gate
evidence. Quant state `snapshot_json.candidate_score_breakdown` stores the
technical score breakdown.

## Database Decision

Database is required because prepared discovery evidence and lifecycle state are
persisted. The project DB runtime already supports SQLite locally and MySQL by
configuration with pooled runtime rules from prior work. This change does not
introduce a new database connection or pool; it reuses the existing quant DB
runtime and keeps pool size constraints unchanged and <= 100.

## API Impact

Existing API operations remain:

- `POST /api/v1/discover/actions/run-strategy`
- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/discover`
- quant universe/live-sim/drill APIs that expose candidate state

Additive/semantic response changes:

- lifecycle `candidate_score` is technical entry score only
- lifecycle `candidate_confidence` is technical confidence only
- score breakdown fields are technical components and penalties
- source/discovery score may be exposed only as source/discovery evidence

## OpenAPI / Backend Layering

The gateway/controller boundary remains in existing gateway/discover modules.
Business scoring belongs in `app/quant_sim/technical_entry_score.py` and
lifecycle service orchestration remains in `QuantUniverseManager`. No new route
is added.

## UI Impact

No required UI layout change for this implementation. UI data semantics improve
because discover rows no longer substitute source score as lifecycle
candidate_score. Existing labels that show candidate score will now receive the
technical value.

## Integration Impact

AI scanner becomes part of the default discovery run. If AI scanner fails while
other strategies succeed, task status remains completed with failed strategy
diagnostics, matching current partial-success behavior.

## Security Impact

No new credentials, auth rules, secrets, dependencies, or external endpoints.
Diagnostics contain stock identifiers, source audit metadata, market indicators,
and reason codes only.

## Error Handling

Missing/stale technical data blocks entry with technical-data reasons. Source
score never fills score gaps. If AI scanner fails, failure is recorded under
task `failedStrategies`; completed strategies still proceed.

## Compatibility / Migration

No DB migration or old data migration. Clearing DB and rerunning discovery is
the expected validation path. Existing caches may remain on disk but are not
authoritative business state.

## Test Strategy

- Unit tests for technical score formula, confidence, source-score exclusion,
  confirmation cap, penalties, and missing snapshot blocking.
- Integration-style tests for lifecycle manager candidate ingestion and DB
  payload score breakdown.
- Discovery tests for default AI scanner inclusion and API candidate-score
  fallback removal.
- Real E2E validation through running backend API after clearing DB.

## Standalone Verification Plan

- `python -m pytest -q tests/test_quant_technical_entry_score.py ...`
- Focused discovery/lifecycle tests.
- Real backend `POST /api/v1/discover/actions/run-strategy` with no strategies
  payload, then poll task result and inspect DB/API output.

## Real E2E Test Design

Required by user confirmation in this request.

Runtime target: local backend service on `127.0.0.1:8501` or an available local
port.

Test data:

- Empty local DB files.
- Existing行情 cache preserved.
- Default discovery payload `{ "waitMs": 1000 }`.
- Drill window from `2026-01-01` to current system date.

Assertions:

- Completed strategies include `ai_scanner` or record AI scanner failure while
  other strategies complete.
- Candidate events are persisted in DB.
- Technical snapshot readiness is recorded per candidate.
- Lifecycle `candidate_score` breakdown includes technical components only.
- No source score or source confidence component appears in lifecycle breakdown.
- Quant pool entry decisions use technical score/confidence gates.
- If quant pool has usable entries, live quant drill starts and reaches a
  terminal status or records a concrete blocker.

## Rules Compliance

- `PIR-001`: code paths are listed above.
- `PIR-002`: new code goes to focused modules; existing oversized modules are
  thin integration shims only.
- `PIR-003` / `CFG-005`: DB use is explicit; no new pool or migration.
- `PIR-004`: API semantic changes use existing routes and service boundaries.
- `PIR-005`: discovery remains async.
- `PY-001` through `PY-008`: Python code follows project package layout,
  explicit errors, no secrets.
- `TEST-001` through `TEST-010`: tests use saved parameters, meaningful
  assertions, coverage evidence, and real E2E evidence.

## Source Mapping

| Design Decision | Source | Reason |
|---|---|---|
| Pure technical scoring | `specs/quant-technical-entry/spec.md` | User rejected source score/confidence for quant |
| New scoring module | `PIR-002`, existing oversized lifecycle file | Keep algorithm auditable and small |
| Candidate event payload as prepared DB record | `Prepared Discovery Persistence` requirement | Avoid new schema while persisting prepared evidence |
| AI scanner default inclusion | User request | Ensure AI analysis is in stock discovery |
| Real E2E required | User request in `/sp-goal` message | User explicitly asked to clear DB, run discovery, then drill |

## Spec Gaps

None blocking. The spec intentionally leaves exact DB table shape to design; the
design chooses candidate event payload JSON for this iteration.
