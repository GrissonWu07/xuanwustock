# Design: audit-data-loop-logic-gaps

## Current Behavior

- 股票发现任务会运行策略、保存 latest candidate artifact、触发统一股票刷新、从 runtime entries hydrate 结果，再调用生命周期 ingestion。
- prepared 数据事实分散在 artifact、runtime snapshot、candidate event payload、stock universe state 中，没有一个可长期引用的 evidence 对象。
- 技术入池分主路径已经切到纯技术评分，但旧 `source_score/confidence` 仍出现在候选 payload、审计字段和部分排序语义中。
- 被 missing/stale technical snapshot 阻止的候选，在后续刷新成功后是否自动重评没有明确闭环。
- 信号详情已有结构化 explainability，但没有统一 decision provenance 模型覆盖候选 evidence、market snapshot、context omitted_reason、仓位计划、slot/lot 和交易执行。
- 历史回放/演练会准备历史数据并输出聚合准备结果，但还没有面向 checkpoint 覆盖的可观察证明。
- OpenSpec active change `quant-technical-entry-score` 的 review evidence 与当前已修复测试状态不一致。

## Target Behavior

- 发现候选在任务完成后产生权威 prepared evidence；发现 API、生命周期 ingestion、实时量化候选视图引用同一类 evidence。
- raw selector fallback 只能显示 stale/unprepared，不参与自动入池。
- 统一股票刷新补齐 technical snapshot 后，之前因数据缺失被阻止的候选会自动重评，并记录重评时间、结果和去重状态。
- 信号详情、交易详情、ignored 信号统计都能展示 decision provenance。
- UI/API 明确区分来源审计分、量化技术入池分、技术置信度、信号融合分、信号置信度和研究上下文分。
- 历史回放/演练输出 checkpoint 覆盖摘要和实时/回放上下文差异。
- 当前 change 完成时，review/wiki/archive 证据与实际验证状态一致；相关 active change 状态被明确处理。

## Architecture Impact

- 新增证据域服务，负责 prepared candidate evidence、candidate re-evaluation markers、decision provenance payload 的读写和归一化。
- 发现、刷新、生命周期、信号详情和交易详情通过证据域服务共享语义，避免每个页面独立拼字段。
- 不新增独立前端路由；在现有 `/discover`、`/live-sim`、`/his-replay`、`/signal-detail/:signalId` 中加入证据字段和详情显示。
- 不新增独立后台长任务类型；复用发现任务、统一刷新任务、历史回放/演练任务和现有 signal/trade APIs。

## Generated Code Paths

| Feature Point | Recommended Paths |
|---|---|
| Prepared evidence model/service | `app/quant_sim/evidence_models.py`, `app/quant_sim/evidence_repository.py`, `app/quant_sim/evidence_service.py` |
| Discovery handoff | `app/discover/discover.py`, `app/discover/candidate_artifact.py`, `app/gateway/quant_universe_entry.py` |
| Refresh re-evaluation | `app/stock_refresh_scheduler.py`, `app/quant_sim/candidate_re_evaluation.py` |
| Decision provenance | `app/quant_sim/decision_provenance.py`, `app/gateway/signal_detail.py`, `app/gateway/trades.py`, `app/gateway/live_sim.py`, `app/gateway/his_replay.py` |
| Replay coverage | `app/quant_sim/replay_coverage.py`, `app/gateway/his_replay.py` |
| UI models and rendering | `ui/src/lib/page-models.ts`, `ui/src/features/discover/discover-page.tsx`, `ui/src/features/quant/live-sim-page.tsx`, `ui/src/features/quant/signal-detail-page.tsx`, `ui/src/features/quant/his-replay-page.tsx` |
| Tests | `tests/test_quant_evidence_provenance.py`, `tests/test_discover_refresh_hydration.py`, `tests/test_quant_universe_gateway.py`, `tests/test_quant_replay_engine.py`, `ui/src/tests/discover-page.test.tsx`, `ui/src/tests/live-sim-page.test.tsx`, `ui/src/tests/signal-detail-page.test.tsx`, `ui/src/tests/his-replay-page.test.tsx` |
| Docs/wiki/review | `docs/wiki/quant-evidence-provenance.md`, current change review artifacts, related active change review evidence |

## Reuse / Common Logic Plan

- Reuse existing discovery hydration and technical snapshot readiness logic instead of creating a second readiness checker.
- Reuse `calculate_technical_entry_score()` and existing lifecycle gate outputs; do not reintroduce source-score entry scoring.
- Reuse existing gateway page snapshots and action routes; extend response payloads rather than adding a new endpoint family.
- Reuse `_system_time_text()`/market time helpers for UI-facing timestamps.
- Extract new provenance builders into small modules instead of adding more logic to oversized files.

## Requirement Scope / Compatibility / Fallback

- Scope is limited to the five user-confirmed items.
- No migration of old data is required. Old rows without evidence may be displayed as legacy/unavailable where necessary.
- Raw selector fallback remains only as stale/unprepared display data.
- Source score may remain in audit payloads but must not be a fallback for quant technical entry score.
- Replay stock-analysis context reconstruction is not required; explicit omitted_reason disclosure is required.

## Method / Function Parameter Plan

- New service methods should accept named dataclass/TypedDict-style request objects when more than five inputs are needed.
- Candidate evidence write path should use a `PreparedEvidenceInput` object.
- Re-evaluation should use a `CandidateReevaluationRequest` object.
- Decision provenance should use a `DecisionProvenanceInput` object.
- Avoid new untyped `dict` bags except at API boundary mapping points where existing page snapshot models already use JSON-like payloads.

## File Size / Split Plan

- New files must stay below 1000 lines.
- Avoid modifying `app/quant_sim/db.py`, `app/quant_sim/replay_service.py`, `app/quant_sim/quant_universe_lifecycle.py`, and `app/quant_sim/signal_center_service.py` unless a split is performed first.
- If implementation must touch an existing oversized file, the task must first extract the relevant behavior into a new module and leave only a minimal delegation call.
- `app/discover/discover.py` is close to 1000 lines; implementation must keep changes minimal or move new logic into `app/quant_sim/evidence_service.py`.

## Data Impact

- A persistent prepared evidence record is required for current and future candidates.
- Evidence must contain enough fields to satisfy API/UI/provenance behavior: run, stock, source, as-of time, technical readiness, technical score/confidence, entry gate, refresh status, and latest evaluation result.
- Decision provenance may be stored as a normalized payload linked to signal/trade identifiers or reconstructed from existing signal/trade plus evidence references, but user-facing behavior must be stable.
- No historical data migration is required.

## Database Decision

- Database is required.
- Development-stage local behavior uses SQLite through the existing runtime default database.
- Implementation/deployment-stage behavior must support MySQL through the existing DB runtime.
- New DB access must use the common runtime/repository path and bounded connection pool. Maximum pool size must be <= 100.
- Existing temp replay/drill DBs may remain SQLite when they are explicitly temporary task-local stores.
- Schema initialization must be traceable and reviewable; no destructive migration or old-data conversion is required.

## Backend Logic Confirmation

Confirmed by user on 2026-05-17 with "没问题，实现把".

Proposed backend decisions:

- Use a prepared evidence authority for discovery candidates.
- Re-evaluate data-blocked candidates after successful unified refresh.
- Expose decision provenance through existing signal/trade/detail snapshots.
- Treat replay stock-analysis context as omitted unless point-in-time context exists.
- Keep DB runtime broad cleanup out of scope except for new evidence persistence.

## API Impact

Existing APIs are extended; no new API path is proposed.

| Method | Path | Parameters | Impact |
|---|---|---|---|
| GET | `/api/v1/discover` | existing query: `search`, `page`, `pageSize`, strategy/filter fields already supported by page query | Add evidence fields and score/status labels in snapshot rows/task summary. |
| POST | `/api/v1/discover/actions/run-strategy` | existing body for selected strategies/top count | Task result includes prepared evidence and refresh/auto-entry summaries. |
| GET | `/api/v1/tasks/{task_id}` | `task_id` path | Discovery task result exposes evidence preparation summary. |
| GET | `/api/v1/quant/live-sim` | existing table query | Candidate rows and counts expose evidence/state semantics. |
| GET | `/api/v1/quant/live-sim/signals` | existing query | Include ignored signal provenance fields where available. |
| GET | `/api/v1/quant/live-sim/trades` | existing query: `page`, `pageSize`, `action`, `stock` | Include trade provenance fields or detail payload reference. |
| GET | `/api/v1/quant/signals/{signal_id}` | `signal_id`, query `source`, `refresh_market` | Add decision provenance section. |
| GET | `/api/v1/quant/his-replay` | existing query | Add task/run coverage summary where available. |
| GET | `/api/v1/quant/his-replay/progress` | existing query | Add checkpoint coverage/context parity fields for active run. |

## OpenAPI / Backend Layering

- OpenAPI contract must document response-field additions for existing APIs.
- Existing gateway functions remain transport/controller boundary.
- New evidence/provenance modules act as service/repository boundary.
- Controllers/gateways should only map request/query and response shapes; evidence preparation, re-evaluation, and provenance building belong in service modules.

## API Path / Parameter Confirmation

Confirmed by user on 2026-05-17 with "没问题，实现把".

Proposed API decision: do not add new API paths; extend existing paths and parameters above.

## UI Impact

- `/discover`: show evidence readiness and quant technical entry score/confidence without exposing source score as quant score.
- `/live-sim`: keep all stocks visible with scrolling; clarify status counts and candidate evidence details.
- `/signal-detail/:signalId`: add a decision evidence section.
- `/his-replay`: show checkpoint coverage and context parity in task/progress/report sections.
- UI tables should avoid raw UTC; display system-time strings only.

## UI Mockup / Functional Description

Mockup artifact: `openspec/changes/audit-data-loop-logic-gaps/mockups/evidence-provenance-ui.md`.

Confirmed by user on 2026-05-17 with "没问题，实现把".

## Configuration Parameter Confirmation

No new configuration parameters are proposed.

If implementation discovers a need for configurable thresholds or feature flags, it must return to design confirmation before coding them.

## Integration Impact

- Discovery strategy integrations keep their existing outputs.
- Unified stock refresh remains the integration point for latest quote/technical snapshots.
- Replay/drill historical data provider remains the integration point for checkpoint data.
- No new external service is introduced.

## Security Impact

- Evidence and provenance may expose internal reasoning. API responses must not expose secrets, raw credentials, model keys, or private endpoints.
- Signal/trade provenance should avoid logging full request payloads when they may contain sensitive config.
- MySQL/SQLite runtime selection must not allow user-controlled paths or connection strings through API input.
- UI should display safe identifiers and reason codes, not raw exception traces.

## Error Handling

- Missing evidence should render as `unavailable`, `legacy`, `missing_technical_snapshot`, or `stale_unprepared`, not crash the page.
- Refresh re-evaluation failures should record reason and leave current lifecycle state unchanged unless a new valid evaluation exists.
- Provenance lookup failure should degrade to an explicit missing reason in detail views.
- Replay coverage missing data should record skipped/blocked reason.

## Compatibility / Migration

- No migration of old data is required.
- Existing rows without evidence remain readable.
- New evidence records start from post-change tasks/runs.
- Related active OpenSpec cleanup must not claim old archive completion if gates are not met.

## Test Strategy

- Backend unit/integration tests for evidence persistence, source-score exclusion, refresh re-evaluation, decision provenance mapping, replay coverage mapping.
- UI tests for discover, live-sim, signal-detail, his-replay rendering.
- Real API E2E for at least discovery prepared evidence and refresh-to-lifecycle handoff.
- Browser/UI QA for affected pages when local frontend target is runnable.
- Full regression: backend pytest and UI test/build after implementation.

## Standalone Verification Plan

- Run focused backend tests for evidence/provenance modules and gateway response mapping.
- Run focused UI tests for affected pages.
- Use explicit test parameter files under this change.
- Verify that no changed/affected code coverage is below 90% per project AGENTS requirement; sp-goal minimum 85% is weaker and not used here.

## Real E2E Test Design

Confirmed by user on 2026-05-17 with "没问题，实现把".

Proposed required real E2E:

- Start local backend test server.
- Clear local DB data only, not caches.
- Trigger `POST /api/v1/discover/actions/run-strategy` with AI scanner included.
- Poll `GET /api/v1/tasks/{task_id}` until completed.
- Assert `GET /api/v1/discover` returns candidates with prepared evidence, ready/missing statuses, and no source-score fallback.
- Trigger or simulate unified refresh for a previously blocked candidate and assert re-evaluation becomes visible.
- Start a small historical replay or live drill over bounded stocks/date range and assert checkpoint coverage/provenance appears.

## Multi-Lens Planning Review

- Product: supports user questions about why candidates enter/skip and why trades happen.
- Design: keeps table surfaces compact; details hold provenance.
- Engineering: centralizes evidence/provenance logic in new modules.
- DevEx: avoids adding behavior to oversized files where possible.
- Security: avoids exposing secrets and raw exception traces.
- QA: creates explicit params and E2E entry points.

## Browser / UI QA Plan

Confirmed by user on 2026-05-17 with "没问题，实现把".

Proposed:

- Use project UI runner/unit tests for component assertions.
- Use Browser or Playwright against local `/discover`, `/live-sim`, `/signal-detail/:signalId`, `/his-replay`.
- Assert no raw UTC table values, evidence labels render, status counts match rows, detail sections are present.

## Project Learning Candidates

- Evidence/provenance should become a reusable project pattern for future quant debugging features.
- UI should keep compact tables and move diagnostic detail to row/detail sections.
- OpenSpec review evidence should be updated in the same change that fixes stale failures.

## Customer Confirmation

Confirmed:

- User confirmed on 2026-05-17 to proceed with `audit-data-loop-logic-gaps` and the five-point smallest useful slice.

Confirmed before implementation:

- Backend logic decisions.
- API path/parameter decision to extend existing APIs only.
- UI mockup/function description.
- Real E2E and browser UI QA required decision.

## Rules Compliance

- PIR-001: This design is derived from confirmed OpenSpec brainstorm/spec artifacts.
- PIR-002: File size plan avoids or splits oversized modules.
- PIR-003/CFG-005: Database required; SQLite/MySQL and pool <=100 are mandatory.
- PIR-004/PIR-005: Existing APIs are documented; discovery/replay long work remains async.
- PY-001..PY-011: New Python modules follow existing package layout, typing, error handling, and no secret logging.
- TEST-001..TEST-010: Tasks require explicit parameters, meaningful assertions, coverage, and review evidence.

## Source Mapping

| Design Decision | Source | Reason |
|---|---|---|
| Prepared evidence authority | `brainstorm.md`, `quant-evidence-provenance/spec.md` | Fix discovery-to-lifecycle fact splitting. |
| Re-evaluate data-blocked candidates after refresh | `brainstorm.md`, `quant-evidence-provenance/spec.md` | Close missing/stale data loop. |
| Existing APIs extended, no new endpoint family | `ui/src/lib/api-client.ts`, `app/gateway_api.py` | Matches current page snapshot/action architecture. |
| Signal/trade provenance in detail payloads | `quant-evidence-provenance/spec.md`, `app/gateway/signal_detail.py` | Supports user-facing attribution without cluttering tables. |
| Replay context omitted disclosure | `docs/superpowers/specs/2026-04-24-historical-replay-asof-data-protocol.md`, `docs/superpowers/specs/2026-04-25-stock-analysis-live-sim-fusion-design.md` | Preserve as-of safety while explaining live/replay differences. |
| DB runtime bounded pool | `PIR-003`, `CFG-005` | Required for new persistence. |
| OpenSpec closure evidence | `openspec-governance/spec.md`, `sp-complete` rules | Prevent stale review/test status. |

## Spec Gaps

No blocking spec gap found.

Potential future spec not included here: full point-in-time stock analysis context reconstruction for historical replay.
