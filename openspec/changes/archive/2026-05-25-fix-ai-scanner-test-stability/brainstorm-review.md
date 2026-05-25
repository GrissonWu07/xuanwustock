# Brainstorm Review: AI Scanner 测试隔离与排序稳定性

## Summary

已根据用户确认的 brainstorm/context 草案创建本阶段文档。范围聚焦 AI Scanner 单元测试隔离真实历史行情 IO，以及候选排序稳定性防回归。

## Requirement Alignment

- 对齐用户指出的失败：候选顺序从 `688111, 000001` 漂移到 `000001, 688111`。
- 对齐用户指出的真实 AkShare 请求污染：普通单元测试不得触发真实外部历史行情。
- 没有扩大到股票发现全链路、量化入池、UI 或数据库。

## Context Alignment

- 已读取相关规则、wiki、归档 change、active change 和当前实现。
- 已记录当前本地用例通过但仍有 tie-break 风险。
- 已记录与 active changes 的关系和边界。

## Rule Alignment

- 满足 `sp-brainstorm`：先在会话中给出草案，用户随后通过 `/sp-goal` 继续，视为确认草案。
- 满足 `TEST-008`：后续必须隔离外部 IO。
- 满足 `PIR-001`：行为变更进入 OpenSpec。

## Scope Risks

- 风险：把真实 integration 测试也纳入会扩大范围。处理：明确 out of scope。
- 风险：排序稳定修复被误解为策略调优。处理：后续 spec/design 只定义稳定 tie-break，不调整主评分公式。

## Missing Context

- 未直接读取远端 CI 的原始失败日志。
- 未确认是否需要单独真实 AkShare integration 测试；本 change 记录为后续可选项。

## Independent Review Thread

- 状态：已运行。
- 审查者：子代理 `019e5fa3-60be-7441-9a17-99225c6e4aba`，只读审查，未编辑文件。
- Findings:
  - P1: `brainstorm-review.md` 仍记录 independent review 未完成，必须写回 findings、response 和 closure 后才能 `/sp-spec`。
  - P1: customer confirmation 证据不够硬，不能只把 `/sp-goal` 和“给了”子代理权限视为内容确认。
  - P2: active changes 冲突记录偏薄，需要补强 `quant-technical-entry-score` 与 `audit-data-loop-logic-gaps` 的边界说明。
  - P3: 范围对齐用户问题，未明显过度扩展；必需章节齐全。

## Main Thread Finding Response

- P1 independent review 未完成记录：已将 independent review findings 写入本文件，并在 Finding Closure 中记录处理结果。
- P1 customer confirmation 证据不足：用户在 review 后明确回复“确认”，作为当前 brainstorm/context 草案确认。此确认发生在创建文件后，但在进入 `/sp-spec` 前；主线程未在确认前创建 proposal/spec/design/tasks/code。当前记录用于关闭进入 `/sp-spec` 的确认门禁。
- P2 active changes 边界不足：已在 `context.md` 增加 Active Change Boundary，明确本变更不修改 quant entry score、prepared evidence、discovery API、lifecycle ingestion 或 UI。

## Finding Closure

- Main-thread review：通过，未发现阻塞项。
- Independent review round 1：发现 2 个 P1、1 个 P2。
- Main-thread fixes：补充用户明确确认证据，补强 active changes 边界，写回 independent review findings/response/closure。
- Unresolved blocking findings：0。

## Customer Confirmation

- 用户先通过 `/sp-brainstorm` 提供问题陈述。
- 主线程已在会话中提供 `brainstorm.md` 与 `context.md` 草案。
- 独立 review 指出确认不够硬后，用户明确回复“确认”。本 review 记录该回复为对当前 `brainstorm.md` / `context.md` 草案以及继续后续 `/sp-goal` 阶段的确认。

## Required Follow-Up Before /sp-spec

- 无。brainstorm 阶段可进入 `/sp-spec`。
