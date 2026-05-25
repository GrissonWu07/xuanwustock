# Change: AI Scanner 测试隔离与排序稳定性

## Why

AI Scanner 是股票发现链路的候选来源之一。此前后端单测曾出现候选顺序漂移，并在普通单元测试中触发真实 AkShare 历史行情请求失败。该问题会降低 CI 和发布回归的可信度，也会让发现结果排序变化难以区分是业务评分变化还是偶然排序漂移。

## What Changes

- 固化 AI Scanner 单元测试不得触发真实历史行情 IO。
- 固化 AI Scanner 同一输入的候选排序必须稳定。
- 为最终排序增加明确 tie-break 语义，避免同分结果依赖隐式行顺序。
- 增加防回归测试和 test parameter evidence。

## Scope

- `AIStockScanner` 候选排序稳定性。
- `AIStockScanner` 单元测试历史行情 IO 隔离。
- 防回归测试和覆盖率证据。
- OpenSpec review、wiki、completion、archive 证据。

## Out of Scope

- 不调整股票发现策略、阈值、AI 主题提取权重或量化入池评分。
- 不修改 discovery API、lifecycle ingestion、prepared evidence、UI、DB schema 或配置项。
- 不新增真实 AkShare/TDX integration test。
- 不迁移历史数据。

## Impact

- 发布回归测试在无网络或外部行情服务异常时仍可验证 AI Scanner 基础行为。
- 同分或重复运行情况下的候选顺序变得可预测。
- 下游 discovery evidence 和量化入池逻辑可以建立在更稳定的 AI Scanner 输出上。

## Rules Applied

- `PIR-001`: 行为变更通过 OpenSpec。
- `PIR-002`: 修改代码文件保持 <= 1000 行。
- `TEST-003`: 测试必须有业务意义，断言排序和 IO 隔离。
- `TEST-008`: 普通单元测试必须隔离外部 IO。
- `PY-005`: 外部 IO 边界必须可控。
- `ENC-001`: 新增文档和测试参数不得出现 mojibake。

## Risks

- 当前本地单测已经通过，实际代码改动可能很小；主要价值在防回归和明确排序语义。
- 稳定 tie-break 可能改变历史同分候选顺序；设计需选择最小业务影响的 tie-break。

## Open Questions

- 真实 AkShare/TDX integration test 是否需要后续单独设计：本变更不纳入。
