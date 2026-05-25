# Context: AI Scanner 测试隔离与排序稳定性

## Sources Read

- `AGENTS.md`
- `openspec/AGENTS.md`
- `openspec/project.md`
- `docs/ai-context/source-index.md`
- `docs/rules/testing-standards.md`
- `docs/rules/python-code-standards.md`
- `docs/rules/project-implementation-standards.md`
- `docs/rules/ai-workflow-quality-standards.md`
- `docs/rules/logging-standards.md`
- `docs/rules/encoding-standards.md`
- `docs/wiki/stock-discovery-data-readiness.md`
- `openspec/changes/archive/2026-05-24-complete-discovery-data-readiness/context.md`
- `openspec/changes/audit-data-loop-logic-gaps/proposal.md`
- `openspec/changes/quant-technical-entry-score/proposal.md`
- `app/discover/ai_stock_scanner.py`
- `tests/test_ai_stock_scanner.py`

## Existing Specs

- `quant-technical-entry-score` 关注量化技术入池分和 prepared discovery candidates，和本问题有发现链路上下游关系，但不定义 AI Scanner 单元测试排序。
- `audit-data-loop-logic-gaps` 关注量化数据证据闭环，和本问题共享“发现结果必须可信”的背景，但范围更大。
- 已归档 `complete-discovery-data-readiness` 记录了 AI Scanner 单元测试曾触发真实外部行情 IO，并建议通过 fake history provider/fake market client 和稳定排序规则修复。

### Active Change Boundary

- `quant-technical-entry-score` 已定义 AI Scanner 可进入默认 discovery、prepared discovery handoff、candidate score 纯技术化。本变更不修改 discovery 默认策略、不修改 prepared DB handoff、不修改 candidate score/confidence 语义，只保证 AI Scanner 自身单元测试不触发真实历史行情 IO，并保证其候选排序在同分/重复运行时稳定。
- `audit-data-loop-logic-gaps` 已定义 discovery evidence authority、refresh re-evaluation、decision provenance 和 UI/API 分数口径。本变更不新增 evidence 对象、不改 discovery API/生命周期 ingestion、不改 UI，只修正 AI Scanner 排序和测试边界。后续如果 active change 需要引用 AI Scanner 输出，可以把本变更视为上游稳定性前提。
- 因此 active changes 与本变更没有行为冲突：它们处理发现结果进入量化证据链后的语义，本变更处理 AI Scanner 产生结果时的测试隔离和稳定输出。

## Existing Code Patterns

- `AIStockScanner.__init__()` 已支持 `history_provider`、`fallback_history_provider`、`market_client` 注入。
- `AIStockScanner.scan()` 调用 `_top_sectors()`、`_sector_stock_rows()`、`_extract_themes()`、`_rank_rows()`。
- `_history_frame()` 在有 `history_provider` 时直接使用注入 provider；未注入时会创建 `AkshareLocalClient()` 拉取真实历史行情。
- `_rank_rows()` 当前先按 `preliminary_score` 排序去重，再计算 technical/theme/final score，最后按 `scanner_score` 排序。
- 当前本地 `test_ai_stock_scanner_selects_candidates_from_hot_sector_constituents` 已注入空 `history_provider`，且本地运行通过；但最终排序仍缺少显式并列 tie-breaker。

## Wiki / Standard Rules Applied

- `stock-discovery-data-readiness` 记录 AI Scanner 单元测试必须稳定并隔离真实外部历史行情 IO。
- `TEST-003` 要求测试断言有实际业务意义，不能只验证初始化。
- `TEST-008` 要求 Python 测试隔离外部 IO。
- `PY-005` 要求外部 IO 边界明确、可控。
- `PIR-001` 要求行为变更通过 OpenSpec。
- `PIR-002` 要求生成/修改代码文件不超过 1000 行。

## Project Rules Applied

- 生成 OpenSpec 文档使用中文。
- 本变更不涉及 UI、API、DB schema、配置项或迁移。
- 实现阶段需要先写防回归测试，再做最小代码修改。
- 后续 review 需要覆盖测试隔离、排序稳定、文件大小、无 mojibake、无敏感日志暴露。

## Conflicts

- 当前本地测试已通过，但用户报告的失败说明旧环境或 CI 曾触发真实 AkShare 请求。上下文应记录为“防回归修复”，而不是继续假设当前本地必现。
- 已归档 discovery readiness change 已经提到 AI Scanner 问题，但没有单独固化排序稳定 requirement；本 change 是窄范围补齐。
- Active changes 可能继续改 discovery handoff 或 evidence 字段；本 change 不触碰这些下游路径，避免与 active change 的 DB/API/UI scope 冲突。

## Context Gaps

- 远端失败发生的具体 commit 和日志未在本轮上下文中直接读取。
- 真实 AkShare/TDX integration 测试是否需要长期保留，当前没有用户确认；本 change 不纳入。
- 并列排序字段优先级没有现成 spec，需要在本 change design 中明确。

## Design Implications

- 设计应选择最小代码路径：只修改 `AIStockScanner._rank_rows()` 和相关测试。
- 排序稳定规则应尽量不改变业务主评分，只在并列或接近并列时提供确定性。
- 测试应显式证明未注入 provider 时可被 fake market client 接管，注入 provider 时不会触达 market client。
- 不新增数据库、API、UI、配置和异步 job 行为。
