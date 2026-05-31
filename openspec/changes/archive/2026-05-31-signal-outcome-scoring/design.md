# Design: 信号 Outcome 评分与成熟反馈闭环

## Workflow Lane

full

## Lightweight Design Scope

不适用。该变更涉及数据库、API、UI、交易决策、历史回放、实时量化演练和实时量化，因此使用 full workflow。

## Current Behavior

系统已有 `market_technical_artifact` 事实层、技术入池 `candidate_score`、BUY/SELL 信号、执行诊断、收益差异归因、实时量化生命周期和回放/演练隔离表。但信号发出后的真实行情结果没有统一 outcome 评分。当前复盘依赖最终盈亏、交易记录、手工检查和局部诊断，不能稳定反哺 `stock_execution_feedback`、`portfolio_execution_guard` 或 lifecycle。

## Target Behavior

- BUY / SELL 信号在 `3 / 5 / 10 checkpoints` 后生成 outcome 记录。
- outcome 记录只从 `market_technical_artifact` 读取信号 checkpoint 和未来窗口事实。
- outcome 聚合生成 `outcome_feedback_score`，仅在成熟后影响未来交易。
- live/replay/drill 算法一致、持久化隔离。
- 信号详情、run 结果和生命周期诊断显示 outcome 与反馈影响。

## Architecture Impact

新增三个逻辑层：

1. `SignalOutcomeScoringService`：从 signal + artifact window 计算 horizon outcome。
2. `OutcomeFeedbackAggregator`：按 stock/profile/domain/run 聚合 matured outcome。
3. `OutcomeFeedbackAdapter`：把聚合反馈注入 stock execution feedback、portfolio execution guard 和 lifecycle gate。

`market_technical_artifact` 继续作为事实来源，不新增行情事实表。

## Generated Code Paths

### 数据与服务

- `app/quant_sim/signal_outcome_scoring.py`：新增 BUY/SELL outcome 计算、horizon maturity 判断、score 公式。
- `app/quant_sim/outcome_feedback.py`：新增成熟 outcome 聚合和交易反馈映射。
- `app/quant_sim/db.py`：新增 live/run outcome 表、CRUD、summary 查询、strategy profile 默认配置。
- `app/quant_sim/market_technical_artifact_store.py`：扩展按 window 查询 artifact 的 repository 方法。
- `app/quant_sim/replay_service_historical.py`、`app/quant_sim/replay_service_drill.py`：run 完成或 checkpoint 后调用 run-scoped outcome scoring。
- `app/quant_sim/scheduler.py`：live 定时任务中扫描 matured live signals。

### 决策消费

- `app/quant_sim/stock_execution_feedback.py`：接收 outcome feedback summary，调整降仓/强确认/probe cooldown。
- `app/quant_sim/portfolio_execution_guard.py`：接收 outcome feedback summary，调整 weak BUY 优先级、batch cap 和风险 gate。
- `app/quant_sim/quant_universe_lifecycle.py`：恢复、降频、出池和 probe 失败判断读取 matured outcome feedback。
- `app/quant_sim/signal_center_service.py`：把 outcome feedback 诊断写入 signal strategy profile / execution diagnostics。

### API / UI

- `app/gateway/signal_detail.py`：信号详情返回 outcome rows 和 feedback summary。
- `app/gateway/his_replay.py`：历史回放 run 结果返回 outcome summary。
- `app/gateway/live_sim.py`：实时量化演练/实时量化返回 outcome summary。
- `ui/src/features/quant/signal-detail-page.tsx`：展示 outcome by horizon。
- `ui/src/features/quant/his-replay-page.tsx`：展示 run outcome 汇总。
- `ui/src/features/quant/live-sim-page.tsx`：展示 drill/live outcome 汇总。
- `ui/src/features/settings/strategy-config-page.tsx`：展示 outcome feedback 配置。
- `app/locales/*.json`、`ui/src/locales/*.json`：新增 UI 文案。

## Reuse / Common Logic Plan

- 复用 `MarketTechnicalArtifactStore` 和 `MarketTechnicalArtifactRef` 作为唯一行情技术事实入口。
- 复用 `QuantSimDB` 的 live/replay 数据隔离模式，run-scoped 表携带 `run_id` 和 `run_type`。
- 复用现有 signal detail、his replay、live sim API response builders，不新增重复页面数据服务。
- 复用 `stock_execution_feedback`、`portfolio_execution_guard` 和 lifecycle 现有 gate 结构，新增 outcome feedback 字段，不复制 gate 逻辑。

## Requirement Scope / Compatibility / Fallback

本变更不做旧数据 backfill。旧信号没有 artifact 或 future artifact 时，outcome 记录为 skipped/partial 诊断，不用当前 live 数据补齐。

禁止新增兼容分支把 source score 或 signal payload 中的旧行情字段作为权威 outcome 输入；只允许在测试 fixture 中构造 artifact。

## Method / Function Parameter Plan

新增方法超过 5 个输入时使用命名数据对象：

- `OutcomeScoringRequest`
- `OutcomeHorizonRequest`
- `OutcomeFeedbackRequest`
- `OutcomeFeedbackSummary`

禁止使用未约束 `dict` 作为跨模块参数。输入可以在 API boundary 处是 dict，但服务层必须转换为显式 dataclass 或 TypedDict。

## Code Comments / Logging / Traceability Plan

需要注释：

- BUY/SELL score 公式和 SELL outcome 非简单涨跌判断。
- matured-only 防未来函数规则。
- replay/drill run-scoped 隔离规则。

需要结构化日志：

- `signal_outcome_scoring_started`
- `signal_outcome_scoring_completed`
- `signal_outcome_scoring_skipped`
- `outcome_feedback_applied`

字段：`trace_id`、`run_id`、`run_type`、`signal_id`、`stock_code`、`horizon_key`、`matured_at`、`scoring_version`、`reason_code`。不得记录密钥、凭证、原始 provider 响应或大体积 K 线数组。

## Encoding / No-Mojibake Plan

新增文档、测试参数、中文 UI 文案和日志说明使用 UTF-8。实现和 review 需要检查新增中文文案无乱码；JSON locale 文件必须能被前端测试读取。

## File Size / Split Plan

新增 `signal_outcome_scoring.py` 和 `outcome_feedback.py`，每个文件控制在 1000 行内。`db.py` 已超过 1000 行，实施时只做必要 schema/CRUD 增量；如新增逻辑过多，提取到独立 repository/helper 模块。

## Data Impact

新增 live 表和 run-scoped 表，字段采用关键列 + JSON 明细：

- `signal_outcome_scores`
  - `id`
  - `domain`
  - `signal_id`
  - `stock_code`
  - `action`
  - `horizon_checkpoints`
  - `signal_checkpoint_at`
  - `matured_at`
  - `source_artifact_ref`
  - `outcome_score`
  - `status`
  - `reason_code`
  - `metrics_json`
  - `formula_json`
  - `created_at`
  - `updated_at`
- `sim_run_signal_outcome_scores`
  - 上述字段加 `run_id`、`run_type`
- `outcome_feedback_scores`
  - `domain`
  - `stock_code`
  - `profile_id`
  - `as_of_checkpoint`
  - `feedback_score`
  - `sample_count`
  - `buy_avg_score`
  - `sell_avg_score`
  - `latest_matured_at`
  - `summary_json`
- `sim_run_outcome_feedback_scores`
  - 上述字段加 `run_id`、`run_type`

`metrics_json` 保存原始 MFE/MAE、target、invalidated、T+1、delay、market alignment 等；不重复保存完整行情指标。

## Database Decision

需要数据库。开发阶段使用 SQLite；部署阶段遵循项目 MySQL 目标；数据库访问继续通过项目 DB runtime/连接池封装，最大连接池不超过 100。

## Backend Logic Confirmation

`/sp-goal` goal-mode decision record：

- BUY/SELL 都要评分。
- outcome 只能通过成熟历史聚合影响未来交易。
- `candidate_score` 不被 outcome 覆盖。
- `source_score/source_confidence/multi_source_bonus` 不进入量化评分和交易决策。
- `market_technical_artifact` 是 outcome 事实来源。

来源：`brainstorm.md`、`brainstorm-review.md`、用户对话确认、已归档 `market-technical-artifact` 和 `quant-technical-entry-score`。

## API Impact

新增/扩展内部 API：

| Method | Path | Purpose | Parameters |
|---|---|---|---|
| GET | `/api/v1/quant/signals/{id}` | 扩展现有信号详情，追加 outcome rows 与 feedback summary | `source=live|replay`, `runId?` |
| GET | `/api/v1/quant/outcomes/signals/{id}` | 查询单信号 outcome 明细 | `source`, `runId?`, `horizon?` |
| GET | `/api/v1/quant/outcomes/runs/{run_id}` | 查询 replay/drill run outcome 汇总 | `runType`, `stockCode?` |
| POST | `/api/v1/quant/outcomes/runs/{run_id}/score` | 触发 run outcome scoring | `runType`, `force=false` |
| POST | `/api/v1/quant/outcomes/live/score-matured` | 触发 live matured signal scoring | `asOf?`, `limit?`, `force=false` |

耗时 POST 按现有 job/run action 模式异步执行或返回 accepted/job 状态，不能阻塞长请求。

## OpenAPI / Backend Layering

API contract 在 gateway 层保持清晰请求/响应 schema；Controller/gateway 只解析参数和响应映射，评分逻辑在 `SignalOutcomeScoringService`，聚合逻辑在 `OutcomeFeedbackAggregator`。

## API Path / Parameter Confirmation

`/sp-goal` goal-mode decision record：上述 API 路径和参数来自现有 `/api/v1/quant/signals`、`/api/v1/quant/live-sim`、`/api/v1/quant/his-replay` 模式，并被本 design review 确认。无需额外用户确认。

## UI Impact

UI 只扩展现有页面，不新增顶层导航：

- 信号详情：在决策与执行诊断后增加“信号 outcome”区块，按 horizon 展示 score、关键指标、成熟/跳过原因。
- 历史回放：任务结果里增加 outcome 汇总卡片和按股票贡献表。
- 实时量化/演练：演练结果和实时信号统计中增加 outcome 汇总。
- 策略配置：量化策略配置中新增 outcome feedback 配置组。

## UI Mockup / Functional Description

本变更为现有页面增加小型诊断区块，不需要独立视觉 mockup。功能描述：

- `SignalOutcomePanel`：三行 horizon 卡片，BUY 显示 MFE/MAE/目标/失效，SELL 显示避免回撤/错过涨幅/卖出验证。
- `OutcomeSummaryCards`：run 页显示 mature count、average score、bad BUY count、good SELL count。
- 配置表单沿用现有策略配置控件风格。

## Configuration Parameter Confirmation

`/sp-goal` goal-mode decision record：配置名和值采用 spec 中 `Outcome Configuration` 表，写入策略 profile context 下的 `signal_outcome_policy`。用户已要求不同策略可配置；默认值按 aggressive/stable/conservative 分档。无需额外用户确认。

## Integration Impact

不新增外部 provider。第三方行情 provider 只作为 artifact producer 的上游，本变更不直接调用 provider。

## Security Impact

- API 只返回信号、股票、run 级诊断，不返回凭证、provider 原始响应或大体积原始行情数组。
- POST scoring endpoint 需要沿用现有 quant API 的权限边界。
- 日志禁止输出原始 K 线列表或敏感信息。

## Error Handling

- 缺 artifact：记录 `missing_artifact` / `missing_horizon_artifact`。
- horizon 未成熟：记录 `horizon_not_mature`。
- partial/stale artifact：记录 partial outcome 或 skipped reason。
- 重复执行：按 `signal_id + horizon + domain/run` 幂等 upsert。
- 配置异常：normalize 到 profile 默认值，并记录 safe warning。

## Compatibility / Migration

不 backfill 旧信号。新表创建后只对可见 artifact-backed 信号评分。旧信号详情可显示“暂无 outcome / 缺 artifact”。

## Test Strategy

- 单元测试：BUY/SELL score 公式、matured-only、missing artifact、source score ignored。
- 集成测试：run-scoped scoring 不污染 live；live scoring 不读 replay/drill。
- API 测试：signal detail/outcome endpoints。
- UI 测试：signal detail 和 run pages 显示 outcome。
- 覆盖率：changed/affected outcome scoring 与 feedback 模块 >= 85%。

## Project-Code Test Boundary

测试只验证项目代码：artifact window 读取、outcome 公式、聚合、API 映射和 gate 消费。第三方行情 provider 行为不作为测试目标；使用本地 artifact fixtures。

## Standalone Verification Plan

- 后端 API：通过测试 server 或直接 gateway action 调用 outcome endpoints，验证 response 和数据库 side effects。
- Job/run：构造 replay/drill run + artifact fixtures，触发 scoring，验证 outcome rows 和 run summary。
- UI：用现有 Vitest/React tests 验证新增区块渲染和 i18n。

## Real E2E Test Design

E2E required：是。原因是该变更跨信号、artifact、run、API 和 UI。

E2E 设计：

- 后端 job/API E2E：创建临时 DB，插入 run、signals、artifacts，调用 run scoring endpoint，断言 outcome rows、feedback summary、signal detail payload。
- UI E2E/runner：现有 UI test runner 渲染 signal detail 和 his replay/live sim 页面，断言 outcome summary 可见。
- 不调用真实第三方 provider。

## Multi-Lens Planning Review

- Product：直接回答信号是否有效、买早/买晚/卖早/卖晚。
- Design：避免新增复杂页面，只补诊断区块。
- Engineering：复用 artifact，避免未来函数和来源污染。
- Developer Experience：API 与数据字段命名围绕 outcome/feedback，便于复盘。
- Security：不新增 provider 调用，不输出敏感或大体积数据。
- QA：通过 artifact fixtures 使结果可重复。

## Browser / UI QA Plan

如果前端 dev server 可运行，实施阶段应在 `/live-sim`、`/his-replay` 和信号详情路由做浏览器检查；否则以 Vitest UI tests 作为 runner 证据并记录无法运行原因。

## Project Learning Candidates

可记录：凡是事后评分参与未来决策，都必须有 matured-only 证据、run/live 隔离和 source-agnostic 审计。

## Customer Confirmation / Goal-Mode Decision Record

本次由 `/sp-goal` 继续已确认 brainstorm。用户已确认：

- SELL 也需要 outcome。
- outcome 必须影响交易决策。
- 默认 horizon 为 `3 / 5 / 10 checkpoints`。
- `outcome_score` 使用 0-100 并保留原始指标。
- `candidate_score` 是事前技术候选分。
- `source_score/confidence` 没必要，应删除/排除。
- 先统一 artifact，再基于 artifact 做评分。

本 design 依据上述确认记录 API、配置、UI 功能和 E2E 决策，无需额外暂停确认。

## Rules Compliance

- `PIR-001`: 已列 code paths。
- `PIR-002`: 新逻辑拆分新模块，避免继续膨胀大文件。
- `PIR-003`: 已记录数据库决策。
- `PIR-004`/`PIR-005`: 已列 API 和 async/job 处理。
- `PIR-006`: 复用 artifact、signal、feedback、guard、lifecycle。
- `PIR-007`/`PIR-008`: 已设计 standalone 和 E2E。
- `PIR-010`: 禁止 fallback 到 live/current行情。
- `LOG-*`: 已列日志字段和脱敏。
- `ENC-*`: 已列 UTF-8/no-mojibake 验证。

## Source Mapping

| Design Decision | Source | Reason |
|---|---|---|
| 使用 `market_technical_artifact` 作为 outcome 事实来源 | `docs/wiki/market-technical-artifact-fact-layer.md`, brainstorm | 已完成事实层，避免分散 payload 和未来函数 |
| `candidate_score` 不被 outcome 覆盖 | `docs/wiki/technical-entry-scoring-for-quant-universe.md`, brainstorm-review | 保持事前技术分语义 |
| source score/confidence 不参与评分 | brainstorm-review, archived quant technical entry spec | 用户明确要求避免来源误解 |
| live/replay/drill 数据隔离 | market artifact wiki, current replay DB pattern | 防止回放/演练污染实时量化 |
| outcome 通过成熟聚合反哺交易 | brainstorm 用户确认 | outcome 不只是展示，必须参与决策但禁止未来函数 |
| E2E required | `PIR-008`, scope crosses API/UI/job/db | 跨模块行为需要真实入口验证 |

## Spec Gaps

无阻塞 gap。实施中如发现 SELL intent 分类无法从现有信号诊断稳定获取，应在 implementation review 中记录，并只把该字段标记为 `unknown`，不得改变 SELL outcome 主体评分范围。
