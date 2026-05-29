---
source: openspec
change_id: audit-data-loop-logic-gaps
title: 量化证据与决策溯源闭环
last_synced: 2026-05-29
last_reviewed: 2026-05-29
status: completed
---

# 量化证据与决策溯源闭环

## Story / Capability Summary

本能力把股票发现、统一刷新、量化生命周期、实时量化、历史回放、量化演练、信号详情和交易记录之间的数据证据串成一条可追溯链路。用户可以看到候选为什么可入池或被阻止、刷新后是否重新评估、信号为什么 BUY/SELL/HOLD/ignored、交易使用了什么仓位和 slot/lot 计划，以及历史回放与实时量化输入上下文有什么差异。

## User-Facing Behavior

- 发现股票列表显示 prepared evidence：发现批次、候选股票、发现来源、行情技术快照状态、量化技术入池分、技术置信度、门禁结论、刷新状态和证据时间。
- 未准备的 raw selector 结果只能显示为 stale/unprepared，不会伪装成可自动量化的候选。
- 统一刷新补齐本地行情技术 artifact 后，会重新评估之前因 missing/stale technical snapshot 被阻止或 recommended-only 的候选。
- 信号详情展示 checkpoint/决策时间、行情技术 artifact 状态、策略 profile、研究上下文使用或省略原因、信号拆解、门禁结果和最终 action。
- 交易详情展示关联信号、lot/slot 计划、执行数量、执行价格、费用、缺失原因和执行诊断。
- 历史回放和量化演练任务显示 checkpoint 覆盖摘要，并披露研究上下文因 as-of 安全被省略的原因。
- UI 时间按系统本地时间展示，不新增 `checkpointAtUtc`、`updatedAtUtc` 等 UTC 双字段。

## Workflow

1. 发现策略产出 raw candidate rows。
2. 发现 hydration 将 raw rows 与本地 runtime 行情技术数据结合。
3. 如果 runtime entry 已 ready 但缺少 `artifact_ref`，系统先写入本地 `market_technical_artifact`。
4. `evidence_service` 基于 artifact-backed row 生成 prepared evidence 和量化技术入池分。
5. 生命周期 ingestion 写入 candidate events 和 candidate state。
6. 统一刷新成功后，`candidate_re_evaluation` 读取本地候选事件，重新评估数据阻塞候选。
7. 信号、交易、ignored 信号和回放任务报告通过 shared provenance/coverage helper 生成 UI/API 证据。

## Rules Applied

- OpenSpec 行为变更先有 proposal/spec/design/tasks，再实现和完成。
- 新增事实链路优先复用本地 artifact，不让 runtime cache、candidate payload 或 source score 充当量化事实源。
- 文件大小控制：新业务逻辑放在小模块，旧大文件只做窄集成。
- API 使用现有路径扩展字段，不新增 endpoint family。
- 证据 payload 不暴露密钥、凭证、provider 私有地址或原始异常堆栈。

## Design Summary

核心设计是建立 evidence/provenance 服务层：

- `app/quant_sim/evidence_service.py` 负责 prepared evidence 和分数语义。
- `app/quant_sim/candidate_re_evaluation.py` 负责刷新后候选重评。
- `app/quant_sim/decision_provenance.py` 负责信号/交易溯源。
- `app/quant_sim/replay_coverage.py` 负责历史回放/演练 checkpoint 覆盖。
- `app/gateway/page_market_artifact_projection.py` 负责页面数据从本地 artifact 投影。

设计保持 source score 和 candidate score 分离：`sourceScore/sourceConfidence` 只表示发现来源审计信息；`candidateScore/candidateConfidence` 表示量化技术入池分和技术置信度。

## Design Review Evidence

`design-review.md` 已补齐并确认：

- prepared evidence、刷新重评、decision provenance、score/state 语义、回放覆盖均有设计和实现路径。
- runtime ready 数据缺 artifact 时会先 materialize 本地 artifact，再投影给页面和重评。
- 业务时间使用本地时间口径。
- 当前工具策略不允许在用户未明确要求时主动 spawn 子代理，因此独立评审采用 main-thread fallback，并记录原因。

## Customer / User Confirmations

- 用户在 2026-05-17 确认继续 `audit-data-loop-logic-gaps` 的最小切片。
- 用户确认 backend logic、API 采用现有路径扩展、UI 功能描述、真实 E2E 和浏览器/UI QA 需要覆盖。
- 用户在后续 review 中强调取数据必须使用本地时间/本地事件口径，本次修复已按本地时间和本地 artifact 事实源收敛。

## Implemented Code Paths

- prepared evidence:
  - `app/quant_sim/evidence_models.py`
  - `app/quant_sim/evidence_service.py`
  - `app/discover/candidate_artifact.py`
  - `app/gateway/quant_universe_entry.py`
- refresh re-evaluation:
  - `app/quant_sim/candidate_re_evaluation.py`
  - `app/stock_refresh_scheduler.py`
- artifact-backed page projection:
  - `app/gateway/page_market_artifact_projection.py`
  - `app/stock_refresh_artifact_writer.py`
- decision/trade provenance:
  - `app/quant_sim/decision_provenance.py`
  - `app/gateway/signal_detail.py`
  - `app/gateway/signal_table.py`
  - `app/gateway/trades.py`
  - `app/gateway/live_sim.py`
  - `app/gateway/his_replay.py`
- replay coverage:
  - `app/quant_sim/replay_coverage.py`
  - `app/gateway_api.py`
- UI:
  - `ui/src/lib/page-models.ts`
  - `ui/src/features/discover/discover-page.tsx`
  - `ui/src/features/quant/live-sim-page.tsx`
  - `ui/src/features/quant/signal-detail-page.tsx`
  - `ui/src/features/quant/his-replay-page.tsx`
  - `ui/src/features/quant/quant-entry-controls.tsx`

## API / Data / UI Impact

- `GET /api/v1/discover`、发现任务结果和量化候选视图新增 prepared evidence 和 score semantics 字段。
- `GET /api/v1/quant/live-sim`、signals/trades 相关视图暴露 decision provenance。
- `GET /api/v1/quant/his-replay` 和 progress/report 视图暴露 checkpoint coverage/context parity。
- UI 标签使用“量化技术入池分”和“技术置信度”，不再用模糊的 `Score/Confidence` 表示入池依据。

## Database / API IO / Async Notes

- 本变更复用已有 SQLite/MySQL runtime 路径，不做历史数据迁移。
- 统一刷新和发现任务仍走已有异步任务链路。
- 刷新重评读取本地候选事件和本地 artifact，不新增外部 IO。
- 本地 artifact 是后续评分、页面、重评和诊断的事实来源。

## Security and Permissions

- API 不暴露密钥、token、账号、provider 私有 endpoint 或原始异常堆栈。
- provenance 只暴露业务解释所需的 reason code、状态、分数、artifact_ref、slot/lot/fee 摘要。
- 本变更未新增授权边界、用户可控 DB 路径或外部连接配置。

## Logging and Traceability

- 刷新写 artifact 使用 trace id，如 `stock-refresh:<reason>`。
- candidate re-evaluation summary 记录 `updatedAt`、`attempted`、`ingested`、`blocked`、`skipped`。
- 信号和交易通过 provenance payload 提供可追溯字段，而不是依赖日志人工拼接。

## Encoding and Text Quality

- 文档和 UI 文案使用中文为主，代码标识符、API 路径和 reason code 保持英文。
- UI 新增文案已在 `ui/src/locales/zh-CN.json`、`ui/src/locales/en-US.json`、`app/locales/zh-CN.json`、`app/locales/en-US.json` 中补齐。
- 验证过程未发现 mojibake 或错误转码问题。

## Validation Evidence

已执行并通过：

```powershell
python -m pytest tests/test_quant_evidence_provenance_helpers.py tests/test_discover_refresh_hydration.py -q
python -m pytest tests/test_quant_technical_entry_score.py -q
python -m pytest tests/test_quant_universe_lifecycle_manager.py -q
python -m pytest tests/test_market_technical_artifact.py -q
python -m pytest tests/test_ui_backend_api_contract.py -q
python -m pytest tests/test_ui_backend_api_actions.py::test_page_tables_render_system_time_instead_of_utc_strings tests/test_ui_backend_api_actions.py::test_stock_analysis_records_persist_local_time_and_render_system_time -q
python -m pytest tests/test_market_technical_artifact_pages.py tests/test_market_technical_artifact_candidate_entry.py -q
python -m pytest tests/test_discover_lifecycle_scoring.py -q
npm test -- --run src/tests/discover-page.test.tsx src/tests/live-sim-page.test.tsx
```

旧 review 中记录的完整验证也已通过：

- focused backend regression: `100 passed, 13 warnings`
- focused new-module coverage: `96%`
- affected frontend tests: `30 passed`
- frontend build: passed with existing Vite chunk-size warning
- local HTTP E2E: `/api/v1/discover` 返回 ready prepared evidence 和系统本地时间输出

## Test Parameter and Coverage Evidence

测试参数记录保存在 `.agent/workdir/sp-openspec/audit-data-loop-logic-gaps/test-params/`，覆盖：

- discovery prepared evidence
- refresh re-evaluation
- decision provenance
- replay checkpoint coverage
- score/state semantics
- OpenSpec closure

覆盖率证据来自旧 implementation review：新 affected modules coverage `96%`，超过项目要求。

## Requirement Counterexample Evidence

- raw selector fallback 有 source score 但缺技术快照时，候选显示为未准备或 0 分，不允许自动入池。
- source score 高低变化不影响 `calculate_candidate_score()` 输出。
- refresh failed/partial 时保留阻止状态，不静默晋级。
- ignored signal 不会从统计中消失，而是带原因显示。

## Masked-Test Analysis

- source score 禁止 fallback 的测试构造了 high source score + missing prepared evidence，确保不是被 threshold 或 ready gate 掩盖。
- artifact 投影测试构造 runtime/artifact 冲突场景，确认页面取 artifact 值。
- 刷新重评测试从 blocked/recommended-only 事件开始，再补 artifact，证明触发点不是普通候选新增。

## Broad-Qualifier Audit

- “系统 SHALL NOT 使用发现来源分替代量化技术入池分”已覆盖 discover UI、candidate score service、lifecycle manager 和相关 tests。
- “统一刷新成功后重新评估”已从只看最新 discover 事件扩展为读取本地候选事件，避免 narrower source qualifier。
- “UI 不直接显示 UTC 原始格式”已通过 backend contract/time tests 和 active-code scan 验证。

## Decision Chain Trace

候选入池证据链：

1. discovery strategy 产出 raw row。
2. hydration 合并 runtime entry。
3. ready runtime 缺 artifact 时写入本地 `market_technical_artifact`。
4. artifact projection 生成 page/runtime row。
5. `evidence_service` 生成 prepared evidence。
6. lifecycle ingestion 使用 candidate score/confidence 和 gate reason。
7. UI/API 展示 evidence/provenance。

## Evidence Capture Timing Audit

- `evidenceAt`、`updatedAt`、`technical_snapshot_at` 使用系统本地时间格式。
- candidate score/confidence 在 prepared evidence 阶段产生，不在 UI 渲染时从 source score 派生。
- refresh re-evaluation 记录在重新评估发生后，并重新 attach 到 prepared evidence。
- decision provenance 在信号/交易详情读取时从信号、交易和 evidence 引用生成。

## Deterministic Sort Audit

- 本变更不新增用户可见排序语义。
- 现有 lifecycle/candidate 排序未作为本变更完成条件调整。
- 重评读取最近本地候选事件，按既有 DB 查询顺序限制；本次修复重点是 source-agnostic 范围，不改变排序策略。

## Standalone Verification Evidence

Standalone verification 覆盖后端 evidence/re-evaluation/artifact 页面投影、UI 分数展示、本地时间展示、技术入池分语义和 lifecycle manager 行为。

## Real E2E Evidence

旧 implementation review 记录了本地 HTTP E2E：临时 uvicorn 服务和临时 SQLite DB，`GET /api/v1/discover?pageSize=10` 返回 `preparedEvidence.status=ready`、`candidateScore=0.8752`，且未暴露 raw UTC snapshot time。

## Browser / UI QA Evidence

本变更以项目 UI test runner 验证 discover/live-sim UI 行为。历史 review 记录前端 build 通过；当前补丁未启动浏览器服务。

## Review Evidence

- `spec-review.md`: no blocking finding。
- `design-review.md`: no unresolved finding。
- `tasks-review.md`: no blocking finding。
- `task-reviews.md`: all task alignment/security findings closed。
- `review.md`: no unresolved implementation finding。
- completion consistency review: no blocking finding。

## Lessons Learned

- 量化系统的事实源必须是本地 artifact，而不是 runtime cache 或 selector payload。
- source score/confidence 可以用于审计发现来源，但不能参与量化技术入池分。
- 时间口径要在 DB/API/UI 边界统一，避免同一语义出现 local/UTC 双字段。
- OpenSpec process evidence 应保存在 `.agent/workdir`，durable contracts 才进入 archive。

## Source Mapping

| Source | Usage |
|---|---|
| `openspec/changes/audit-data-loop-logic-gaps/specs/quant-evidence-provenance/spec.md` | 用户可观察行为与场景 |
| `openspec/changes/audit-data-loop-logic-gaps/design.md` | API/UI/data/code path 设计 |
| `.agent/workdir/sp-openspec/audit-data-loop-logic-gaps/design-review.md` | 设计闭环评审 |
| `.agent/workdir/sp-openspec/audit-data-loop-logic-gaps/task-reviews.md` | per-task finding closure |
| `.agent/workdir/sp-openspec/audit-data-loop-logic-gaps/review.md` | implementation review |
| `app/quant_sim/evidence_service.py` | prepared evidence implementation |
| `app/quant_sim/candidate_re_evaluation.py` | refresh re-evaluation implementation |
| `app/gateway/page_market_artifact_projection.py` | local artifact projection |
| `ui/src/features/quant/quant-entry-controls.tsx` | UI score semantic labels |
