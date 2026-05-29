# Change: 打通量化数据证据闭环

## Why

当前系统已经具备股票发现、统一刷新、生命周期入池、实时量化、历史回放、量化演练、交易和 UI 展示等主链路，但多个环节的证据分散在不同 payload、artifact 和状态记录中。用户排查“为什么入池/为什么没入池/为什么买入/为什么亏损/为什么忽略信号”时，仍需要手工拼接发现结果、行情快照、技术指标、策略 profile、信号、仓位、slot/lot 和交易结果。

本变更的目标是把最小可用的数据证据闭环变成可观察行为：发现候选有权威 prepared evidence，刷新成功能重新评估候选，决策和交易能反查 provenance，UI/API 的分数和状态口径不再混淆，OpenSpec 文档和 review evidence 不再滞后于实现。

## What Changes

- 发现任务完成后，每个候选股票都应有可追溯的 prepared evidence，包含发现来源、行情/技术快照状态、量化技术入池分、技术置信度、门禁结论和刷新状态。
- discover API、生命周期入池、实时量化候选视图应读取同一类 prepared evidence 或显示明确引用，不再把未准备 raw selector 结果伪装成可量化候选。
- 被 missing/stale technical snapshot 阻止的候选，在后续统一股票刷新成功后应自动重新评估。
- BUY/SELL/HOLD/ignored 信号及交易详情应暴露 decision provenance，能说明使用的 as-of 数据、策略 profile、研究上下文使用/省略原因、信号拆解、仓位和 slot/lot 计划。
- UI/API 应明确区分发现来源审计分、量化技术入池分、信号融合分、信号置信度、研究上下文分，不再用模糊的 score/confidence。
- 历史回放/量化演练任务应输出 checkpoint 数据覆盖证明，并披露与实时量化输入上下文的差异。
- OpenSpec 完成证据应与实际测试、review 和 wiki/归档状态保持一致。

## Scope

- 股票发现后的 prepared evidence 可观察行为。
- 刷新成功后的候选重评行为。
- 信号/交易 provenance 可观察行为。
- score/state 命名和 UI/API 口径。
- 历史回放/量化演练数据覆盖和上下文差异披露。
- 当前变更及相关已完成变更的 OpenSpec review/complete 证据一致性。

## Out of Scope

- 不调整具体买卖阈值、入池阈值或股票特例规则。
- 不要求历史回放生成或调用实时 LLM/研究上下文。
- 不要求一次性重构全部 DB runtime 或 legacy `_connect()` 调用。
- 不迁移历史数据，不恢复旧数据库。
- 不把 UI 做大规模重设计；只要求与本闭环相关的可观察字段和口径正确。

## Impact

- 用户可以从发现候选、量化池、信号详情、交易详情、历史回放任务报告中看到同一套证据链。
- blocked/recommended_only 候选不会因为一次数据缺失永久停留在不可解释状态。
- 实时量化和历史回放的差异会从隐含实现变成显式任务报告和信号解释。
- 后续亏损复盘、现金过高归因、忽略信号统计会有稳定基础。
- 后续设计需要决定 evidence 持久化机制、API 字段、UI 展示和测试边界。

## Rules Applied

- `PIR-001`: 行为变更必须通过 OpenSpec。
- `PIR-002`: 后续设计和任务必须控制生成/修改文件不超过 1000 行。
- `PIR-003`: 如需新增持久化，设计必须明确 SQLite/MySQL 和连接池 <= 100 的约束。
- `PIR-004`: API 行为和耗时任务必须有 IO/async 设计。
- `PYR-001`, `PYR-002`, `PYR-003`: 后续实现应保持分层、类型化数据对象和可测试边界。
- `CFG-005`: DB 连接池和持久化配置必须显式、可验证。
- `TEST-001`, `TEST-003`, `TEST-004`: 后续验证必须使用有意义断言、明确参数文件和覆盖率证据。

## Risks

- 如果 evidence 只做成 latest artifact 而不是可追溯记录，亏损复盘仍然可能丢失当时证据。
- 如果刷新重评和生命周期 ingestion 边界不清晰，可能重复入池或遗漏重评。
- 如果 provenance 字段过多直接塞入 UI，可能影响页面可读性；设计阶段需要区分详情页、任务报告和表格列。
- 如果 OpenSpec closure 清理和产品行为实现混在一个提交里，review 需要明确区分代码验证和文档治理验证。

## Open Questions

- prepared evidence 的具体持久化形式由 `/sp-tasks` 设计决定，但必须满足可追溯和 API/UI 可引用。
- refresh-triggered 重评由刷新任务直接触发还是生命周期 worker 扫描，由 `/sp-tasks` 设计决定。
- 历史回放是否未来需要 point-in-time stock analysis context 不在本变更强制范围内；本变更要求先明确披露实时/回放差异。
