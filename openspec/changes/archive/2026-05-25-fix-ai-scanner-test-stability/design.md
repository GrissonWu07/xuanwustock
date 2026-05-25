# Design: AI Scanner 测试隔离与排序稳定性

## Current Behavior

`AIStockScanner` 已支持 `history_provider`、`market_client` 和 `fallback_history_provider` 注入。当前 hot sector 单测已注入空 `history_provider`，本地运行通过。`_history_frame()` 未注入 provider 时会创建真实 `AkshareLocalClient()`。`_rank_rows()` 最终只按 `scanner_score` 降序排序，最终同分时缺少显式 tie-breaker。

## Target Behavior

- 注入 `history_provider` 时，技术评分只使用该 provider，不触发 market client 或真实 local client。
- 未注入 `history_provider` 但注入 fake `market_client` 时，历史行情只通过 fake client 获取。
- 最终候选排序保持业务主评分优先，同时增加显式稳定 tie-breaker：`scanner_score desc -> sector_score desc -> technical_score desc -> preliminary_score desc -> original_candidate_order asc -> 股票代码 asc`。
- 原始 hot sector 用例继续稳定返回 `688111`, `000001`。

## Architecture Impact

无架构扩展。继续使用 `AIStockScanner` 现有注入边界。只在排序和测试覆盖处做窄改。

## Generated Code Paths

- `app/discover/ai_stock_scanner.py`
- `tests/test_ai_stock_scanner.py`
- `openspec/changes/fix-ai-scanner-test-stability/test-params/*.md`
- `openspec/changes/fix-ai-scanner-test-stability/task-reviews.md`
- `openspec/changes/fix-ai-scanner-test-stability/review.md`

## Reuse / Common Logic Plan

复用现有 `_preliminary_score()`、`_weighted_score()`、`_history_frame()` 和 test fake classes。排序不新增重复评分逻辑，只在 `_rank_rows()` 中使用已有分数字段和原始候选顺序字段。

最终排序键固定为：

```text
scanner_score desc
sector_score desc
technical_score desc
preliminary_score desc
original_candidate_order asc
股票代码 asc
```

其中 `original_candidate_order` 来源于进入 final scoring 前的候选顺序，用于保持同分候选的业务来源顺序；股票代码只作为最终兜底，避免完全依赖 DataFrame 的隐式稳定排序。

## Requirement Scope / Compatibility / Fallback

本变更只实现 spec 中定义的单元测试隔离和排序稳定。不新增 fallback，不改变生产历史行情 fallback 链路，不改变评分公式、AI 主题提取、discovery 默认策略、prepared evidence、量化入池或 UI。

## Method / Function Parameter Plan

不新增 public 方法。若需要内部 helper，参数必须 <= 5。当前预计只调整 `_rank_rows()` 内部排序字段，不需要新数据对象。

## Code Comments / Logging / Traceability Plan

排序 tie-break 是非显而易见的稳定性规则，代码中可加入一条简短注释说明该排序用于避免同分候选依赖 DataFrame 隐式顺序。无需新增日志；测试隔离不应产生运行时日志变化。无 `trace_id` 上下文。

## Encoding / No-Mojibake Plan

新增/修改文档使用中文 UTF-8，代码和测试保持 ASCII 或既有中文 fixture 文本。验证时运行 pytest，并人工检查新增 OpenSpec/test-params 文档无乱码。

## File Size / Split Plan

`app/discover/ai_stock_scanner.py` 和 `tests/test_ai_stock_scanner.py` 当前均小于 1000 行；本变更为窄改，不需要拆分。

## Data Impact

无持久化数据影响。无 DB schema、缓存、数据迁移。

## Database Decision

不需要数据库。

## Backend Logic Confirmation

用户已确认当前 brainstorm/context 并要求继续。后端逻辑决策：

- 只修 AI Scanner 测试隔离和排序稳定。
- 不调整业务评分公式和下游量化入池。
- 不新增真实外部 IO 测试。

确认状态：用户在 2026-05-25 回复“确认”，并要求继续。

## API Impact

无 API 新增或变更。

## OpenAPI / Backend Layering

不适用。无 API、Controller、Service 变更。

## API Path / Parameter Confirmation

不适用。无 API path、path parameter、query parameter、request body 或 response contract 变更。

## UI Impact

无 UI 变更。

## UI Mockup / Functional Description

不适用。无 UI 行为或布局变化。

## Configuration Parameter Confirmation

不适用。无配置参数新增或变更。

## Integration Impact

普通单元测试继续隔离真实 AkShare/TDX。生产路径保留真实 market client 与 fallback provider 行为，不新增 integration 行为。

## Security Impact

无认证、授权、租户隔离、敏感数据、凭据或外部 endpoint 变更。测试 sentinel 不记录 secrets。

## Error Handling

注入 provider 返回空历史数据时，技术评分继续走既有 `technical_data_unavailable` 中性分路径。fake market client 如果被错误调用应让测试失败。

## Compatibility / Migration

无迁移。无老数据兼容处理。

## Test Strategy

- 新增或调整 `tests/test_ai_stock_scanner.py` 中的 regression tests。
- 验证 original hot sector test。
- 验证注入 provider 不调用 market client sentinel。
- 验证 final score tied candidates 使用稳定 tie-breaker。
- 运行 focused coverage，要求 changed/affected code coverage >= 85%。

## Standalone Verification Plan

- `python -m pytest -q tests/test_ai_stock_scanner.py`
- `python -m pytest -q tests/test_ai_stock_scanner.py --cov=app.discover.ai_stock_scanner --cov-report=term-missing --cov-fail-under=85`

## Real E2E Test Design

用户确认本变更无需真实 E2E。理由：这是 AI Scanner backend bug-entry 和 unit-level determinism，不涉及 API、UI、DB、任务调度或外部服务生产调用。真实外部 AkShare integration test 属于 out of scope。

## Multi-Lens Planning Review

- Product: 保证股票发现回归稳定，减少发布误报。
- Design: 不改变用户可见 UI。
- Engineering: 最小代码变更，复用现有注入边界。
- DevEx: 单测不依赖外部行情，CI 更稳定。
- Security: 不新增敏感数据或权限面。
- QA: 覆盖原始 bug entry、no-real-IO、tie-break。

## Browser / UI QA Plan

不适用。无 UI 变更。

## Project Learning Candidates

可记录：AI Scanner 或类似发现策略的普通单元测试必须通过 provider/fake client 隔离外部行情 IO，排序测试需要覆盖重复执行和并列 tie-break。

## Customer Confirmation

- Brainstorm/context：用户 2026-05-25 回复“确认”。
- Backend logic：用户 2026-05-25 回复“确认”，并要求继续。
- UI mockup/function：不适用。
- API paths/parameters：不适用。
- Configuration parameters：不适用。
- E2E decision：本设计记录无需真实 E2E；用户 2026-05-25 的“确认”覆盖本窄范围后端 bug-entry 决策。

## Rules Compliance

- `PIR-001`: 已列出 code paths。
- `PIR-002`: 文件大小低风险，计划验证。
- `TEST-003`: 测试断言排序和 IO 隔离。
- `TEST-008`: 单元测试隔离外部 IO。
- `PY-005`: 历史行情 IO 只通过显式 provider/client 边界。
- `ENC-001`: 文档和测试参数需无 mojibake。

## Source Mapping

| Design Decision | Source | Reason |
|---|---|---|
| 只修 AI Scanner 测试隔离和排序稳定 | 用户问题、brainstorm scope | 用户指出的唯一后端失败集中在 AI Scanner 单测 |
| 使用 provider/fake client 隔离历史行情 IO | `AIStockScanner.__init__()` 现有注入参数、`TEST-008` | 复用现有可测试边界，不引入新架构 |
| 最终排序增加显式 tie-breaker：`scanner_score desc -> sector_score desc -> technical_score desc -> preliminary_score desc -> original_candidate_order asc -> 股票代码 asc` | `_rank_rows()` 当前只按 `scanner_score` 排序、用户排序失败 | 防止同分或重复运行时排序漂移，同时保留业务来源顺序优先 |
| 不新增 API/UI/DB/config | brainstorm out of scope、当前 bug entry | 保持窄修复，避免与 active changes 冲突 |

## Spec Gaps

无。Spec 足以支持当前任务实现。
