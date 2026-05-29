# Design: 本地时间持久化

## Workflow Lane

full

## Lightweight Design Scope

Not lightweight. Persistence, API, UI, replay/drill, artifact, scheduler, and tests are affected.

## Current Behavior

The system has mixed local and UTC semantics:

- Replay/drill tables include `checkpoint_at` and `checkpoint_at_utc`.
- Artifact adapters and store paths use `format_utc_iso_z()` / `utc_now_iso_z()`.
- Gateway responses include `updatedAtUtc` and convert display time separately.
- Tests assert UTC `Z` timestamps.
- Local provider Parquet cache is separate and should survive reset/rebuild.

## Target Behavior

- Project-owned business timestamps are persisted as deployment-local `YYYY-MM-DD HH:mm:ss`.
- `checkpoint_at` is the only checkpoint key.
- API/UI expose local time only.
- DB rebuild removes UTC columns and UTC fallback logic.
- Local Parquet/provider cache remains untouched; boundary readers normalize timestamps when writing project-owned DB/artifact/API data.

## Architecture Impact

Introduce a small shared local-time utility surface and route all project-owned timestamp creation/normalization through it. Existing UTC helpers must be removed from changed project-owned persistence paths. Provider cache readers remain source-format tolerant and normalize only when producing project-owned rows.

## Generated Code Paths

Planned affected paths:

- `app/quant_sim/time_utils.py`: local-time helper API and removal/deprecation of project-owned UTC helper use.
- `app/quant_sim/db.py`: schema, CRUD, indexes, query order/filter, signal extraction, run lifecycle tables. Because the file is oversized, implementation SHOULD use thin edits plus focused helper modules when feasible.
- `app/quant_sim/market_technical_artifact.py`, `app/quant_sim/market_technical_artifact_store.py`, `app/quant_sim/replay_artifact_adapter.py`, `app/stock_refresh_artifact_writer.py`: artifact `checkpoint_at` and `computed_at` local semantics.
- `app/quant_sim/replay_service_historical.py`, `app/quant_sim/replay_service_drill.py`, `app/quant_sim/replay_service_drill_candidates.py`, `app/quant_sim/live_quant_drill_candidates.py`, `app/quant_sim/profit_gap_attribution.py`: no UTC checkpoint generation or fallback.
- `app/quant_sim/portfolio_service.py`, `app/quant_sim/scheduler.py`, `app/stock_refresh_scheduler.py`, `app/quant_sim/quant_universe_lifecycle.py`: project-owned time writing and comparison using local utilities.
- `app/gateway/live_sim.py`, `app/gateway/his_replay.py`, `app/gateway/*artifact*`, `app/gateway/*signal*`: payload and display fields local only.
- `ui/src/lib/page-models.ts`, affected UI pages/locales/tests: remove UTC field expectations.
- Tests under `tests/`: replace UTC assertions with local-time assertions and cache preservation checks.

## Reuse / Common Logic Plan

- Reuse existing parsing concepts in `time_utils.py`, but expose local-first helpers instead of duplicating formatting per service.
- Reuse `LocalMarketDataStore` and Parquet cache paths unchanged.
- Artifact adapters and gateway formatters SHALL call shared local-time helpers rather than implementing ad hoc string conversion.

## Requirement Scope / Compatibility / Fallback

- Scope is exact: project-owned DB/API/UI timestamps become local-time.
- No old schema migration.
- No UTC fallback or compatibility branch.
- No provider cache mutation.

## Method / Function Parameter Plan

No new function should exceed five parameters. For bulk normalization or DB writes that need multiple time fields, use a named request/data object with explicit fields rather than loose `dict` expansion.

## Code Comments / Logging / Traceability Plan

- Add comments only where the boundary is non-obvious, especially “provider cache time is normalized when entering project-owned persistence”.
- DB rebuild/reset and time-normalization diagnostic logs SHOULD include `trace_id` when request/job context exists.
- Logs must not include credentials, raw provider payloads, or sensitive request bodies.

## Encoding / No-Mojibake Plan

All generated docs, Chinese UI strings, test names, and payload assertions use UTF-8. Tests that touch Chinese text or API payloads must assert readable text and no mojibake.

## File Size / Split Plan

- `app/quant_sim/db.py` baseline: 8083 lines. Implementation may make thin schema/query edits to finish functionality, but new substantive logic SHOULD be placed in focused modules/helpers.
- `app/gateway/his_replay.py` baseline: 1244 lines. Avoid adding large blocks; prefer focused helper/projection functions if substantial mapping is needed.
- `app/quant_sim/time_utils.py` baseline: 79 lines and is the preferred place for shared formatting helpers.
- New or modified files must remain <= 1000 lines unless already oversized; oversized files must not grow with avoidable new logic.

## Data Impact

- SQLite development DB and deployment DB schema remove project-owned UTC checkpoint columns.
- Run-scoped tables and live tables use local `checkpoint_at`.
- Existing DB data is not migrated and will be reset/recreated.
- `data/local_sources/**` Parquet/provider cache is preserved.

## Database Decision

Database change is required.

- Development-stage behavior: SQLite.
- Deployment-stage behavior: current project deployment DB path; future MySQL-compatible intent must avoid SQLite-only semantics where new schema is designed.
- Connection pool maximum must remain <= 100 when a pooled DB implementation is used.

## Backend Logic Confirmation

Goal-mode decision record: user confirmed backend behavior in brainstorm phase:

- Use current deployment local time for all involved time fields.
- Remove `updatedAtUtc/checkpointAtUtc`.
- Rebuild DB instead of migration.
- Preserve local Parquet/cache data.

## API Impact

Changed API response behavior:

- Live quant snapshot no longer returns `updatedAtUtc`.
- Historical replay and drill detail/list payloads no longer return `checkpointAtUtc` or derive display fields from UTC.
- Artifact/signal diagnostic APIs return local `checkpointAt` and `updatedAt` only where relevant.

No new API paths are required.

## OpenAPI / Backend Layering

No new OpenAPI path is introduced. Existing Controller/Gateway functions should delegate time formatting to shared service/helper logic and avoid embedding conversion rules in route handlers.

## API Path / Parameter Confirmation

Goal-mode record: no new paths or parameters. Existing payload fields are changed by removing UTC variants and making local-time fields authoritative.

## UI Impact

UI page models and display code must stop expecting UTC variants. UI should render the already-local values directly, without showing “UTC/market/system timezone” helper text for these fields.

## UI Mockup / Functional Description

No visual layout change or mockup is required. Functional UI change: time fields in live quant/replay/drill pages display a single local time value; UTC-specific fields or labels disappear.

## Configuration Parameter Confirmation

No new configuration parameter is introduced. The time zone is the deployment local environment for this change.

## Integration Impact

Provider integrations and Parquet cache remain unchanged. Boundary adapters normalize time only when creating project-owned artifacts/signals/trades/API data. Tests must not assert third-party provider behavior.

## Security Impact

No authentication or authorization change. Risk is data exposure through logs during rebuild/time diagnostics; logs must avoid raw provider payloads and sensitive data.

## Error Handling

- Invalid timestamp inputs at project-owned persistence boundaries should fail clearly in tests/jobs rather than silently falling back to UTC.
- Cache read failures retain existing provider/cache error handling and are not part of this change.

## Compatibility / Migration

No migration and no compatibility fallback. Deployment/local validation deletes and recreates business DBs. Parquet/provider cache remains intact.

## Test Strategy

- Backend unit/integration tests for local-time helper formatting/parsing.
- DB tests for absence of `checkpoint_at_utc` in new schema and local `checkpoint_at` on run-scoped rows.
- Replay/drill tests for direct joining of artifact/signal/lifecycle by local `checkpoint_at`.
- API tests for absence of `updatedAtUtc`/`checkpointAtUtc`.
- Cache preservation test showing reset/rebuild does not delete `data/local_sources/**/*.parquet`.
- UI model/tests updated to local-only fields.

## Project-Code Test Boundary

Tests target project-owned time normalization, schema, API payloads, and job behavior. Parquet tests may use local fixtures but must not test pandas/pyarrow/provider correctness as the primary target.

## Standalone Verification Plan

- Run targeted pytest suites around DB, replay/drill DB, artifact, live-sim API, his-replay API, and cache preservation.
- Run one short historical replay and one short live quant drill on rebuilt local DB when runtime permits.
- Use API/test client to inspect payload fields and confirm no `*Utc` fields.

## Real E2E Test Design

Real E2E is required for at least one backend job/API flow because this change affects observable replay/drill/API behavior.

- Runtime target: local backend test server or project test client.
- Flow 1: rebuild local DB, run short live quant drill, query run detail, assert local-only checkpoint fields and no UTC variants.
- Flow 2: run short historical replay, query his-replay detail, assert local-only checkpoint fields and artifact/signal join.
- UI/browser QA: required only if frontend code changes are runnable; open live quant/replay pages and assert no UTC-specific labels or fields.

## Multi-Lens Planning Review

- Product: matches user need to make replay/drill/trade explanations use one time concept.
- Design: no layout change; UI copy simplified.
- Engineering: central helper prevents reintroducing ad hoc conversions.
- Developer Experience: fewer dual-field queries and easier artifact/signal joins.
- Security: no new data exposure; logging constraints apply.
- QA: E2E and DB-level checks required because unit tests alone can be masked.

## Browser / UI QA Plan

If frontend is changed and a runnable target exists, use the project-approved browser or UI runner to visit live quant and his-replay pages and verify:

- displayed time fields are readable local times;
- no UTC labels/fields appear;
- pages still load with rebuilt DB.

## Project Learning Candidates

Potential wiki/learning after completion: “provider cache is not business persistence; time normalization belongs at the project-owned persistence boundary.”

## Customer Confirmation / Goal-Mode Decision Record

Recorded from `/sp-goal` flow:

- Backend logic: local-time only for project-owned persistence.
- API: remove UTC variants from existing responses; no new endpoints.
- UI: show single local-time values; no mockup needed.
- Configuration: no new configuration; deployment local time is authoritative.
- E2E: required for backend job/API flow; UI QA required if frontend changed and runnable.
- Cache: Parquet/provider cache preserved.

## Rules Compliance

This design follows OpenSpec phase rules, project implementation standards, Python/config/testing/logging/encoding rules, and the user-confirmed no-compatibility/no-migration constraints.

## Source Mapping

| Design Decision | Source | Reason |
|---|---|---|
| Use deployment-local time only | User confirmation in brainstorm-review | Direct product requirement |
| Remove `checkpoint_at_utc` / `updatedAtUtc` | User confirmation and `rg` context | Eliminates join/display dual semantics |
| Preserve Parquet cache | User clarification and local-market-data docs | Cache is data source, not business DB |
| No migration, rebuild DB | User confirmation | Project not launched; simpler and avoids compatibility |
| E2E required | Spec scenarios and rules | Job/API behavior must be observable |

## Spec Gaps

None currently. Future multi-market time-zone persistence is intentionally out of scope.
