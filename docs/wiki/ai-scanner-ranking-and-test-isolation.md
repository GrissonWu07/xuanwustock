---
source: openspec
change_id: fix-ai-scanner-test-stability
title: AI Scanner 排序与测试隔离
last_synced: 2026-05-25
last_reviewed: 2026-05-25
status: completed
---

# AI Scanner 排序与测试隔离

## Story / Capability Summary

本变更修复 AI Scanner 单元测试稳定性问题：普通单元测试不得触发真实 AkShare、TDX 或本地历史行情客户端；相同输入和同分候选必须得到确定性排序。

## User-Facing Behavior

用户侧没有 UI 或 API 行为变化。发布回归更稳定，AI Scanner 的候选输出在同分和重复运行时更可预测。

## Workflow

AI Scanner 仍按原流程获取板块、候选、主题和技术评分。变化点只在 final candidate ranking：主排序仍是 `scanner_score`，并增加明确 tie-breaker：

```text
scanner_score desc
sector_score desc
technical_score desc
preliminary_score desc
original_candidate_order asc
股票代码 asc
```

测试侧通过 `history_provider` 或 fake market client 隔离历史行情 IO，避免普通单元测试访问真实外部行情服务。

## Rules Applied

- `TEST-008`: 单元测试隔离外部 IO。
- `TEST-003`: 测试断言真实业务行为，不只验证初始化。
- `PY-005`: 外部 IO 边界必须可控。
- `PIR-002`: 修改文件保持小于 1000 行。

## Design Summary

实现复用现有 `AIStockScanner` 注入边界，不新增依赖、配置、数据库、API 或 UI。`_candidate_order` 在进入 final scoring 前生成，只用于同分排序，返回结果前删除。

## Design Review Evidence

Spec/design 独立审查发现并关闭了三个问题：review closure 未写回、tie-breaker 字段顺序未固化、spec 语言不是默认中文。修复后 re-review 返回 no blocking findings。

## Customer / User Confirmations

用户在 2026-05-25 明确回复“确认”，作为 brainstorm/context、后端逻辑和无需真实 E2E 的确认。

## Implemented Code Paths

- `app/discover/ai_stock_scanner.py`
- `tests/test_ai_stock_scanner.py`

## API / Data / UI Impact

无 API、DB schema、持久化数据或 UI 改动。生产历史行情 fallback 链路保持不变。

## Database / API IO / Async Notes

不适用。本变更不新增数据库访问、API IO 或异步任务。

## Security and Permissions

无认证、授权、租户隔离或敏感数据变化。测试隔离减少了单元测试对真实外部行情服务的意外访问风险。

## Logging and Traceability

没有新增日志；无 `trace_id` 上下文。新增一条排序稳定性注释。

## Encoding and Text Quality

OpenSpec、测试参数和 wiki 使用可读中文；代码和测试 fixture 未发现 mojibake。

## Validation Evidence

```powershell
python -m pytest -q tests/test_ai_stock_scanner.py
# 21 passed

python -m pytest -q tests/test_ai_stock_scanner.py --cov=app.discover.ai_stock_scanner --cov-report=term-missing --cov-fail-under=85
# 21 passed, coverage 85.71%
```

## Test Parameter and Coverage Evidence

测试参数保存在 `openspec/changes/fix-ai-scanner-test-stability/test-params/ai-scanner-stability.md`。覆盖率达到 `85.71%`，超过 85% 门禁。

## Requirement Counterexample Evidence

- market client sentinel 被调用即失败，证明 injected history provider 隔离真实历史行情 IO。
- final score 相等但 sector score 不同，证明 `sector_score` tie-break 生效。
- `scanner_score`、`sector_score`、`technical_score`、`preliminary_score` 全部相等，且输入顺序与股票代码升序冲突，证明 `_candidate_order` tie-break 未被遮蔽。

## Masked-Test Analysis

关键 tie-break 测试显式断言前置排序键相等，避免被更早的分数差异遮蔽。no-real-IO 测试使用会抛错的 sentinel，避免真实 IO 回归被吞掉。

## Broad-Qualifier Audit

`相同输入`、`相同最终分数`、`不得调用真实历史 IO`、`只调用 fake market client` 和 `显式 tie-breaker` 均有对应测试覆盖。

## Standalone Verification Evidence

Standalone verification 通过 `tests/test_ai_stock_scanner.py` 完成；本变更不需要真实 API/UI/E2E。

## Real E2E Evidence

不适用。用户确认这是后端 bug-entry/unit-level determinism 修复，无 API、UI、DB 或 job 边界变化。

## Browser / UI QA Evidence

不适用。无 UI 改动。

## Review Evidence

完成一轮主线程 full review 和两个独立 final review threads。独立 review 发现两个问题：Wencai fallback test 可能触发真实历史行情 IO，以及 original-order tie-break 证据被 `preliminary_score` 遮蔽。两项均已修复并 re-review 到 no blocking findings。

## Lessons Learned

AI/外部数据类单元测试必须显式注入 fake provider 或 fixture。排序稳定性测试需要构造同分场景，并确保前置排序键相等，否则 tie-break 断言可能被更早的评分差异遮蔽。

## Source Mapping

| Source | Usage |
|---|---|
| 用户问题 | 定义排序漂移和真实 AkShare 请求污染的 bug entry |
| `tests/test_ai_stock_scanner.py` | 回归测试和覆盖率证据 |
| `app/discover/ai_stock_scanner.py` | 最小实现位置 |
| `docs/rules/testing-standards.md` | 测试隔离和覆盖率门禁 |
