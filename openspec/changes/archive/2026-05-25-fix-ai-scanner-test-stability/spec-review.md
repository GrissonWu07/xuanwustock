# Spec Review: AI Scanner 测试隔离与排序稳定性

## Summary

Proposal 和 spec 聚焦 AI Scanner 单元测试外部 IO 隔离、候选排序稳定性、原始 bug entry regression。未引入 UI/API/DB/config 行为。

## Brainstorm Alignment

已覆盖 brainstorm 中的核心问题：排序漂移和真实 AkShare 历史数据请求污染。

## Brainstorm Confirmation

`brainstorm-review.md` 已记录用户明确回复“确认”，并经 independent re-review 返回 no blocking findings。

## Context Alignment

spec 使用当前代码上下文：`history_provider`、`market_client` 注入和 `_rank_rows()` 排序。active changes 边界已经在 `context.md` 中说明。

## Rule Alignment

- `TEST-008`: 通过 requirement 明确单元测试不得触发真实历史行情 IO。
- `TEST-003`: regression 测试断言原始 bug entry 的业务顺序和 no-real-IO。
- `PY-005`: 外部 IO 只能通过显式 provider/client 边界进入。

## Requirement Quality

Requirement 使用可观察行为描述，不包含内部文件路径和实现细节。测试入口是 AI Scanner 单元测试和 bug-entry regression test。

## Scenario Coverage

- 覆盖注入 history provider 时不访问 market client。
- 覆盖 fake market client 作为唯一 IO 边界。
- 覆盖重复扫描顺序稳定。
- 覆盖最终分数并列 tie-break。
- 覆盖原始 hot sector test。

## Standalone Verifiability

可通过 `pytest tests/test_ai_stock_scanner.py` 和 coverage 命令独立验证。

## E2E-Verifiable Behavior

本变更是 backend bug-entry/unit-level behavior，无 API/UI/DB 侧效应。真实 E2E 不适用，设计阶段需记录用户确认。

## Out-of-Scope or Implementation Leakage

没有把 quant entry score、prepared evidence、UI 或真实 AkShare integration test 纳入 spec。tie-breaker 只定义为显式 deterministic fields，不在 spec 中规定具体内部字段顺序，具体字段由 design 决定。

## Independent Review Thread

- 审查者：子代理 `019e5fb9-76a0-7f42-b44f-6cc6c38a7b54`，只读审查，未编辑文件。
- Findings:
  - P1: `design-review.md` 仍记录 independent review 未完成，必须写回 findings、response 和 closure。
  - P2: `design.md` 没有固化完整 tie-breaker 字段顺序、方向和兜底字段。
  - P3: `spec.md` 正文使用英文，不符合项目默认中文文档规则。

## Main Thread Finding Response

- P3 spec 英文：已将 `spec.md` requirement 和 scenario 正文改为中文，保留 OpenSpec 关键字 `SHALL`。
- P1/P2 主要落在 design/design-review，见 `design-review.md` closure。

## Finding Closure

Spec main review：通过。
Independent review round 1：发现 1 个 P1、1 个 P2、1 个 P3。
Main-thread fixes：spec 中文化；design 固化完整 tie-breaker；design-review 写回 independent review findings/response/closure。
Independent re-review：子代理 `019e5fbc-df88-7761-b9f4-88ff365afe18` 返回 no blocking findings。
Unresolved blocking findings：0。

## Required Fixes Before Design

无。
