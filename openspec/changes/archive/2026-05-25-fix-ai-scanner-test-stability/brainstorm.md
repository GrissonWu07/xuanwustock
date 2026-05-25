# Brainstorm: AI Scanner 测试隔离与排序稳定性

## Problem

股票发现后端曾在 `tests/test_ai_stock_scanner.py::test_ai_stock_scanner_selects_candidates_from_hot_sector_constituents` 出现失败：候选排序从预期 `688111, 000001` 变成 `000001, 688111`，并且测试路径触发真实 AkShare 历史行情请求失败。

这说明 AI Scanner 的单元测试边界和排序语义存在风险：普通回归测试不应依赖外部行情服务，候选排序也不能依赖隐式 DataFrame 顺序或并列分数时的偶然行为。

## Product Challenge

AI Scanner 是股票发现链路的一部分，后续会影响发现结果展示、prepared evidence、候选事件和量化入池判断。发布前测试必须稳定证明同一输入能得到同一候选顺序，而且外部行情不可用时不会让普通单元测试变成环境依赖测试。

## User Scenarios

- 发布流水线在无网络、AkShare 不稳定或本地缓存为空时运行 AI Scanner 单元测试，测试仍然稳定通过。
- 开发者调整 AI Scanner 评分权重或技术指标逻辑时，排序变化必须由明确测试暴露，而不是被偶然顺序掩盖。
- 需要验证真实行情拉取链路时，测试应作为显式 integration/E2E 入口运行，而不是混入普通单元测试。

## Scope

- AI Scanner 普通单元测试隔离真实历史行情 IO。
- AI Scanner 候选排序使用明确、稳定、可审计的排序键。
- 增加防回归测试，覆盖重复执行顺序一致、并列排序稳定、单元测试不触发真实行情客户端。
- 保留生产路径的真实行情和 fallback 能力，但只在显式 provider/market client 路径下使用。

## Out of Scope

- 不调整股票发现业务策略、选股阈值或主题权重。
- 不修改生命周期入池门禁、实时量化、历史回放或 UI。
- 不重构 AkShare、TDX 或统一刷新链路。
- 不做数据库 schema 或数据迁移。

## Smallest Useful Slice

在现有 `AIStockScanner` 和 `tests/test_ai_stock_scanner.py` 上完成最小修复：补充排序 tie-breaker，补充不触发真实历史行情 IO 的防回归测试，并确认相关测试和覆盖率通过。

## Rejected / Deferred Scope

- 将所有发现策略统一改造成 prepared artifact：已属于其他 active change，不纳入本修复。
- 新增真实 AkShare 集成测试：本问题是普通单元测试污染，真实外部 IO 可在后续 integration change 中单独设计。
- 重新定义 AI Scanner 评分公式：排序稳定不要求改变业务评分，只要求同分和重复运行可预测。

## Candidate Requirements

- AI Scanner 单元测试 SHALL 能通过注入历史行情 provider 或 fake market client 完全隔离真实 AkShare/TDX IO。
- AI Scanner 对同一输入 SHALL 返回稳定候选顺序，重复执行结果一致。
- AI Scanner 在候选最终排序并列时 SHALL 使用明确 tie-breaker，而不是依赖隐式行顺序。
- 普通单元测试 SHALL 覆盖真实行情客户端不被调用的失败用例。

## Alternative Solutions

- 只修改测试注入空 `history_provider`：能解决当前失败，但不能防止最终排序并列带来的未来漂移。
- 只固定排序 tie-breaker：能稳定排序，但不能防止测试误触外部 IO。
- 将真实行情集成测试从单元测试拆出：方向正确，但需要另一个更大的 integration scope；本次先封住单元测试边界。

## Recommended Direction

沿用现有 `history_provider`、`market_client` 注入模式，补充测试隔离断言；在 `_rank_rows()` 最终排序中加入稳定 tie-breaker，例如 `scanner_score`、`sector_score`、`technical_score`、`preliminary_score`、原始候选顺序或股票代码。具体字段顺序由 design 固化，避免改变业务主评分的含义。

## Impacted Modules

- `app/discover/ai_stock_scanner.py`
- `tests/test_ai_stock_scanner.py`
- `openspec/changes/fix-ai-scanner-test-stability/*`
- `docs/wiki/ai-scanner-test-stability.md`（完成阶段生成）

## Risks

- 当前本地用例已经通过，说明失败可能来自旧 commit、远端 CI 或另一运行环境；本 change 需要把重点放在防回归，而不是假设当前 HEAD 必然失败。
- 如果 tie-breaker 选择不当，可能改变部分同分候选的展示顺序；需要明确这是稳定性规则，不是策略调优。
- 如果测试只断言 happy path，仍可能漏掉未注入 provider 时的真实 IO 污染。

## Open Questions

- 并列排序最终 tie-breaker 是否应该保留原始候选顺序优先，还是股票代码优先？推荐保留原始候选顺序后再用股票代码兜底，避免不必要改变业务排序。
- 是否需要单独保留真实行情集成测试？本 change 建议不做，仅在 completion 中记录后续可选项。

## Suggested Change ID

`fix-ai-scanner-test-stability`
