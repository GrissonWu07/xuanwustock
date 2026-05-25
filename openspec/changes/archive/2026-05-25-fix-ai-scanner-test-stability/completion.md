# Completion: AI Scanner 测试隔离与排序稳定性

## Summary

本变更完成 AI Scanner 单元测试外部 IO 隔离和候选排序稳定性修复。实现保持窄范围，只修改 AI Scanner final sort tie-breaker 与相关测试。

## Completion Gate Results

- `design-review.md` 无 unresolved blocking findings。
- `tasks.md` 所有任务已完成。
- `task-reviews.md` Alignment Review 和 Security Review 均无 open finding。
- `review.md` 主线程 full review、两个 independent final review threads 和 re-review 均已关闭。
- Coverage: `85.71%`，满足 85% 门禁。

## Independent Review Thread Closure

- Brainstorm independent review: round 1 findings 已修复，re-review no blocking findings。
- Spec/design independent review: round 1 findings 已修复，re-review no blocking findings。
- Final implementation independent review 1: P1/P2 已修复，re-review no blocking findings。
- Final implementation independent review 2: P2 已修复，re-review no blocking findings。

## Task Completion Evidence

- Task 1.1 已完成并标记 `[x]`。
- 实现路径：`app/discover/ai_stock_scanner.py`、`tests/test_ai_stock_scanner.py`。

## Design Review Closure

Design review 已确认 API/UI/DB/config/real E2E 不适用，并确认 tie-breaker 顺序：

```text
scanner_score desc -> sector_score desc -> technical_score desc -> preliminary_score desc -> original_candidate_order asc -> 股票代码 asc
```

## Per-Task Review Closure

`task-reviews.md` 已记录 TDD red/green、standalone verification、coverage、counterexample matrix、masked-test analysis 和 broad-qualifier audit。Unresolved findings: 0。

## Final Review Closure

`review.md` 已记录主线程 full implementation review 和两个 independent final review threads。Unresolved findings: 0。

## Requirement Counterexample Matrix

已覆盖：

- provider present + market client sentinel。
- provider absent + fake market client。
- final score tied + sector score tie-break。
- all earlier sort keys tied + `_candidate_order` before stock-code fallback。

## Masked-Test Analysis

Tie-break 测试显式断言前置排序键相等，避免被更早分数字段遮蔽。no-real-IO 测试用 sentinel 保证错误 IO 会直接失败。

## Broad-Qualifier Audit

`同一输入`、`相同最终分数`、`不得调用真实历史 IO`、`只调用 fake market client`、`显式 tie-breaker` 均有测试证据。

## Wiki Documentation

Wiki created: `docs/wiki/ai-scanner-ranking-and-test-isolation.md`。

## Spec / Design / Code Alignment

实现与 spec/design 对齐，无 out-of-spec behavior。

## Implementation Standards Evidence

- `app/discover/ai_stock_scanner.py`: 891 lines。
- `tests/test_ai_stock_scanner.py`: 591 lines。
- 无新增 dependency、DB、API、UI、config、async。
- 无 public method 参数超限。

## Requirement Scope / Fallback / Parameter Evidence

未新增 fallback 或 compatibility branch。生产历史行情 fallback 保持不变。无新增 public method。

## Comment / Logging / Traceability Evidence

新增一条排序稳定性注释。无新增日志；无 `trace_id` 上下文；无敏感数据记录。

## Encoding / No-Mojibake Evidence

新增中文 OpenSpec、wiki、test-params 和测试 fixture 可读，无 mojibake。

## Project Learning Notes

已更新 `docs/ai-context/project-learnings.md`，记录外部行情类单元测试必须 fake provider/client，以及 tie-break 测试必须避免 masked-test。

## Local Git Commit

待 archive 后创建。

## Final User Report Inputs

- Tests: `python -m pytest -q tests/test_ai_stock_scanner.py` -> `21 passed`。
- Coverage: `python -m pytest -q tests/test_ai_stock_scanner.py --cov=app.discover.ai_stock_scanner --cov-report=term-missing --cov-fail-under=85` -> `21 passed`, `85.71%`。
- Review: zero unresolved findings。

## Archive Target

`openspec/changes/archive/2026-05-25-fix-ai-scanner-test-stability/`

## Blocking Issues

None.
