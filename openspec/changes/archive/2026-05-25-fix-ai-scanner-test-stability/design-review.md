# Design Review: AI Scanner 测试隔离与排序稳定性

## Summary

设计为窄范围 backend bug-entry 修复：复用现有 provider/client 注入边界，增加 AI Scanner 最终排序 tie-breaker 和单元测试防回归。无 API、UI、DB、配置或真实 E2E。

## Spec Alignment

设计覆盖全部 spec requirements：

- Unit tests isolate historical market IO。
- Candidate ranking is stable。
- Regression tests prove original bug entry。

## Design Completeness

包含当前行为、目标行为、代码路径、测试策略、standalone verification、E2E 决策和 customer confirmation。无缺失设计决策。

## Source Mapping

`design.md` 已列出 source mapping，决策与用户问题、当前代码和规则一致。

## Customer Confirmation Gates

- Brainstorm/context：已确认。
- Backend logic：已确认。
- UI mockup/function：不适用。
- API path/parameters：不适用。
- Configuration parameters：不适用。
- E2E decision：无需真实 E2E，已在 design 中记录为用户确认的窄范围 bug-entry 决策。

## Implementation Standards

- 文件大小：目标文件当前小于 1000 行，窄改。
- 参数：不新增 public 方法，无 >5 参数风险。
- 复用：复用现有注入边界和评分函数。
- Scope：不引入 fallback/compatibility/out-of-spec 行为。

## Comment / Logging / Traceability Review

设计允许一条简短排序稳定性注释。无需新增日志；无 trace_id 上下文。

## Encoding / No-Mojibake Review

新增文档为中文 UTF-8；测试 fixture 沿用现有中文股票名称，需在最终验证检查无乱码。

## Verification and E2E Readiness

Standalone verification 命令明确。真实 E2E 不适用，理由充分：无 API/UI/DB/job/external-service production path 变化。

## API / Database / IO / Async Review

无 API、DB、async 变更。IO 仅涉及测试隔离和 provider/client 边界。

## UI Mockup / Browser QA Review

不适用。无 UI 变更。

## Rule Alignment

对齐 `PIR-001`、`PIR-002`、`TEST-003`、`TEST-008`、`PY-005`、`ENC-001`。

## Task Readiness

可以进入 `/sp-tasks`：任务应聚焦测试参数、防回归测试、排序 tie-break、验证和 review evidence。

## Independent Review Thread

- 审查者：子代理 `019e5fb9-76a0-7f42-b44f-6cc6c38a7b54`，只读审查，未编辑文件。
- Findings:
  - P1: `design-review.md` 仍记录 independent review 未完成，不能进入 `/sp-tasks`，必须写回 findings、main-thread response 和 closure。
  - P2: `design.md` 只写“已有分数字段和原始候选顺序字段”，未固化完整 tie-breaker 字段顺序、方向和最终兜底字段。
  - P3: `spec.md` 正文整体使用英文，项目规则要求 OpenSpec 文档默认中文，除非用户显式要求英文。

## Main Thread Finding Response

- P1 independent review closure 未写回：已将 independent review findings、response 和 closure 写入 `spec-review.md` 与 `design-review.md`。
- P2 tie-breaker 未固化：已在 `design.md` Target Behavior、Reuse / Common Logic Plan、Source Mapping 明确排序键为 `scanner_score desc -> sector_score desc -> technical_score desc -> preliminary_score desc -> original_candidate_order asc -> 股票代码 asc`。
- P3 spec 英文：已将 spec 正文改为中文，保留 OpenSpec 关键字 `SHALL`。

## Finding Closure

Main-thread review：通过。
Independent review round 1：发现 1 个 P1、1 个 P2、1 个 P3。
Main-thread fixes：已完成。
Independent re-review：子代理 `019e5fbc-df88-7761-b9f4-88ff365afe18` 返回 no blocking findings。
Unresolved blocking findings：0。

## Required Fixes Before /sp-tasks

无。可以进入 `/sp-tasks`。
