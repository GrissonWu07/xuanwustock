# Change: 统一行情技术 Artifact

## Why

当前实时量化、发现入池、信号生成、历史回放和实时量化演练使用的行情/技术指标来源分散。系统可以从 runtime artifact、candidate event payload、signal `market_snapshot`、replay snapshot provider 等位置取得数据，但缺少统一的 checkpoint 事实层。

这会导致：

- 同一股票同一 checkpoint 的数据口径难以复查。
- `candidate_score`、后续 `outcome_score` 和 `outcome_feedback_score` 难以复算。
- replay/drill 可能误用 live 最新数据，产生未来函数风险。
- 信号详情和生命周期诊断很难解释“当时使用了哪份行情技术数据”。

## What Changes

新增统一的 `market_technical_artifact` 行为：

- 按股票、市场、checkpoint、timeframe、版本记录当时可见的行情和技术指标。
- 支持 live、replay、drill 数据域隔离。
- live refresh、replay checkpoint、drill checkpoint 都写入同一语义的 artifact。
- candidate entry 和 signal generation 通过 `artifact_ref` 引用该事实层。
- 缺失 artifact 时输出明确缺失原因，不得静默使用 live 最新行情。

## Scope

- 统一 artifact identity 和字段语义。
- live 刷新写入 live artifact。
- replay/drill checkpoint 写入 run-scoped artifact。
- candidate entry 和 signal generation 至少通过 artifact_ref 使用行情技术事实。
- 诊断输出包含 artifact_ref、domain/run/checkpoint/timeframe/status/missing reason。
- 明确旧来源角色迁移边界。

## Out of Scope

- 不实现 `outcome_score`。
- 不实现 `outcome_feedback_score`。
- 不重写 `candidate_score` 公式。
- 不调整交易策略。
- 不实现发现来源评分。
- 不做全市场每 checkpoint 存储。
- 不做大规模 UI 页面重设计。

## Impact

- Backend: 需要统一 artifact writer/reader 服务和持久化。
- Data: 需要新增或统一 live 与 replay/drill artifact 存储。
- API/UI: 需要在现有诊断响应中暴露 artifact_ref 和缺失原因。
- Replay/Drill: 需要 run-scoped artifact，禁止回退到 live latest。
- Future changes: `signal-outcome-scoring` 将依赖该事实层。

## Rules Applied

- OpenSpec 阶段分离：本阶段不写代码、不创建 tasks。
- 数据库决策必须在 design 中明确。
- 本地开发数据库使用 SQLite；实现/部署阶段目标为 MySQL；连接池最大不超过 100。
- 行为必须可通过真实 job/API/UI 边界验证。
- 中文和技术字段说明必须保持 UTF-8，无 mojibake。
- 测试设计后续需要覆盖至少 85% 受影响代码。

## Risks

- artifact 数据量增长。
- `checkpoint_at`、`computed_at`、`data_version`、`indicator_version` 语义混淆。
- replay/drill 性能受影响。
- 旧 runtime artifact 被误当事实源。
- 缺失 artifact 时若静默 fallback，会重新引入未来函数风险。

## Open Questions

- 是否需要保留 `stock_runtime_snapshot` 给 UI 继续读取，还是完全迁移到 artifact 派生。
- recent checkpoint 历史窗口是否在本 change 中保存为压缩字段，还是只保存聚合结构字段。
