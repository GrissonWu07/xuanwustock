# Brainstorm Review: 完整股票发现数据就绪

## Summary

已完成 `/sp-brainstorm` 阶段产物：

- `brainstorm.md`
- `context.md`
- `brainstorm-review.md`

本阶段没有创建 proposal、spec、design、tasks，也没有修改代码。

## Requirement Alignment

用户输入聚焦两个问题：

1. 股票发现不完整，AI Scanner 全量测试失败。
2. ready 口径没有统一成完整数据快照。

`brainstorm.md` 已覆盖：

- AI Scanner 排序稳定性和测试隔离。
- 完整数据快照 readiness。
- 缺失或 stale 核心行情/技术数据不得进入评分内核。
- 自动入池只看数据完整性与技术分/置信度阈值，不按策略来源加减条件。

对齐结果：通过。

## Context Alignment

`context.md` 已记录：

- OpenSpec workflow 来源。
- 项目规则和测试规则。
- active changes 与 archived wiki。
- 相关代码和测试路径。
- 当前实现与用户最新口径的冲突。

对齐结果：通过。

## Rule Alignment

已遵守：

- `sp-brainstorm` 只写 brainstorm/context/review。
- 未创建 `proposal.md`。
- 未创建 `specs/<capability>/spec.md`。
- 未创建 `design.md`。
- 未创建 `tasks.md`。
- 未修改生产代码或测试代码。
- 已读取 `openspec/AGENTS.md`、`openspec/project.md`、`docs/ai-context/source-index.md` 和相关 rules。

对齐结果：通过。

## Scope Risks

- 如果后续 spec 直接修改 `quant-technical-entry-score` 的 stale penalty 语义，会影响实时量化、历史回放、演练和发现共用的评分路径。
- 若完整行情字段定义过宽，发现任务 ready 数量可能显著下降。
- 如果仍保留 source-family gate，可能继续和“入池只看数据完整和技术分达标”的用户口径冲突。
- 如果只修 AI Scanner 测试，不改 readiness 契约，会关闭测试失败但无法解决产品完整性问题。

## Missing Context

非阻塞但需在 `/sp-spec` 前确认或在 spec 中明确默认：

- 完整行情字段是否包括涨跌幅、成交量、换手率、开高低、昨收。
- Freshness 应按 30m TTL、交易日、还是 checkpoint as-of 语义判断。
- 基础资料字段是否阻止技术评分，还是只作为非核心诊断子状态。
- UI 是否新增 `data_snapshot_status`，还是沿用 `technical_snapshot_status` 并扩展语义。

## Customer Confirmation

已确认。

确认依据：用户在收到 brainstorm 产物后，于 2026-05-24 直接触发 `[$sp-goal]`，要求从当前 OpenSpec 阶段继续完成剩余 workflow。该指令视为确认 `complete-discovery-data-readiness` 的 brainstorm 方向并允许进入 `/sp-spec`。

需要用户确认的建议方向：

- 使用 `complete-discovery-data-readiness` 作为 change-id。
- 后续 `/sp-spec` 以“完整数据快照 ready + AI Scanner 稳定性”为一个变更。
- 技术评分内核前置完整性校验；缺失或 stale 核心行情/技术数据不计算。
- 自动入池不按策略来源放宽或收紧，只看完整数据快照和技术分/置信度阈值。

## Required Follow-Up Before /sp-spec

- 用户确认 brainstorm 方向。
- 若用户要求基础资料也作为硬 ready 条件，需要在 `/sp-spec` 前明确。
- 若用户要求保留 source-family 特殊门禁，需要解决与当前口径的冲突。
- 确认后再进入 `/sp-spec complete-discovery-data-readiness`。
