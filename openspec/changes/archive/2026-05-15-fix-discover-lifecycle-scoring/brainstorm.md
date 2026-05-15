# Brainstorm: Fix Discover Lifecycle Scoring

## Problem

股票发现已经能执行并把候选写入 `stock_universe` 与 `stock_universe_candidate_events`，但发现结果没有稳定携带量化生命周期需要的结构化字段。当前生产数据里 `source_score=0`、`confidence=0`、`trend=neutral`，导致生命周期候选分数只有 `0.075`，低于 aggressive 档位 `trial_threshold=0.50`，发现结果不会自动进入 `trial`。

AI 选股尤其明显：`AIStockScanner` 原始结果计算了 `scanner_score`、`technical_score`、`theme_score`、`technical_reasons`，但 `_run_ai_scanner_strategy` 重新组装 DataFrame 时丢掉这些字段，只把得分拼进 `reason` 文本。生命周期门控不解析 `reason` 文本，所以 AI 选股被标记为 `recommended_only`，原因是 `ai_requires_technical_confirmation`。

## User Scenarios

- 用户执行股票发现后，系统应把发现候选的结构化评分、置信度、趋势和技术确认传入量化生命周期。
- 用户查看发现页时，应能看到候选是否已入池、推荐展示、被阻断或仍待处理的真实状态。
- 用户打开实时量化时，应看到符合生命周期规则的发现候选进入量化池；不符合规则的候选应保留明确阻断原因。
- 用户排查某只股票为什么没有入池时，应能从候选事件和 UI 字段定位是分数不足、置信度不足、技术确认不足、容量限制还是数据不足。

## Scope

- 修复发现结果到生命周期候选事件的数据契约。
- 保留 AI scanner 的结构化输出，不再只保留展示字段。
- 为非 AI 发现策略生成统一的 `source_score`、`confidence`、`trend` 和必要技术/数据质量字段。
- 让 `ingest_lifecycle_entry_rows` 写入的候选事件能够表达真实评分和门控证据。
- 增加测试，覆盖发现结果入生命周期时 `source_score/confidence/technical_confirmation_count` 不被归零。

## Out of Scope

- 不降低生命周期入池阈值。
- 不把来源名称本身当作加分项。
- 不保证每个发现候选都自动入池；生命周期规则仍应决定是否入池。
- 不改变实时量化买卖决策逻辑。
- 不改变人工从 UI 批量纳入量化的行为，除非后续 spec 明确要求统一人工入池事件。

## Candidate Requirements

- AI scanner 输出进入发现持久化时必须保留 `scanner_score`，并映射为发现行的 `score/source_score`。
- AI scanner 输出必须提供 `confidence`，建议由技术数据可用性、主题匹配和技术评分完整度计算，范围归一化到 `0.0..1.0`。
- AI scanner 输出必须提供 `trend` 和 `technical_confirmation_count`，技术确认至少覆盖价格站上 MA20、MA20 斜率、均线结构、MACD 等现有门控可识别字段。
- 发现行映射必须保留 `technical_score`、`theme_score`、`technical_reasons`、`ma5/ma10/ma20/ma20_slope/ma60/amount/volume_ratio/rsi/macd` 等量化证据字段。
- 非 AI 发现策略必须产出稳定的 `source_score` 和 `confidence`。建议基于排名、数据完整度、成交额/流动性、财务指标完整性和策略命中强度计算，而不是基于来源名称硬编码加分。
- 候选事件入库后，`payload_json.entry_gate` 应反映门控真实结果；有技术确认的 AI 候选不应仅因为字段丢失进入 `recommended_only`。
- 发现任务结果中的 `quantAutoEntry` 应可用于诊断 promoted/eligible/skipped 的数量和原因。

## Alternative Solutions

### Option A: Preserve And Normalize Scores At Discover Boundary

在 `app/discover/discover.py` 增加发现行标准化层，把各策略输出统一映射为生命周期字段。AI scanner 直接保留原始结构化字段，其他策略通过 rank/data-quality 评分补齐。

优点：改动集中，生命周期规则保持稳定；便于测试发现到候选事件的数据契约。

缺点：需要认真定义每个策略的评分含义，避免不同策略分数不可比。

### Option B: Parse Existing Reason Text

从 `reason` 文本里解析 `扫描得分`、`technical_score`、`technical=...`。

优点：改动小，可快速补救当前 AI scanner。

缺点：文本解析脆弱，和“结构化字段作为量化契约”的方向冲突；不适合其他策略。

### Option C: Lower Lifecycle Threshold Or Add Source-Based Bonus

降低 `trial_threshold`，或给 `AI选股/主力选股/低价擒牛` 等来源加固定分。

优点：能让更多股票入池。

缺点：掩盖数据契约问题，容易让没有证据的候选入池；也违反现有代码注释“来源身份不加分”的规则。

## Recommended Direction

推荐 Option A。修复点应该放在发现结果标准化和 AI scanner 输出保真上，而不是调生命周期阈值。生命周期的核心假设是“发现/研究输出显式 recommendation score 和 confidence”；当前生产选择器没有稳定履行这个契约。

建议分两层实现：

1. 定义发现候选标准字段：`score/source_score`、`confidence`、`trend`、`technical_confirmation_count`、技术指标和数据质量证据。
2. 每个策略适配到标准字段：AI scanner 使用已有结构化分数；其他策略使用排名和数据质量规则生成分数，同时保留原始列用于审计。

## Impacted Modules

- `app/discover/discover.py`
- `app/discover/ai_stock_scanner.py`
- `app/gateway/quant_universe_entry.py`
- `app/quant_sim/candidate_entry_gate.py`
- `app/quant_sim/quant_universe_lifecycle.py`
- `tests/test_ai_stock_scanner.py`
- `tests/test_ui_backend_api_actions.py`
- `tests/test_research_watchlist_integration.py`
- Potentially new focused tests for discover candidate scoring.

## Risks

- 分数定义不严谨会让候选过多自动入池，影响实时量化池质量。
- 如果非 AI 策略用排名分补齐，可能把“低估值/小市值”这类不同语义的候选变得不可比。
- 使用技术指标补齐字段可能引入额外数据访问成本，发现任务耗时可能增加。
- 当前已存在人工批量纳入量化路径直接写 `active`，这和生命周期事件路径不完全一致；本 change 不处理该行为会留下审计不统一问题。
- 生产环境已有旧候选事件，其历史 `source_score/confidence=0` 不迁移；新发现任务后才体现修复效果。

## Open Questions

- 非 AI 发现策略的初始评分是否接受基于“排名 + 数据完整度 + 流动性”的启发式分数，还是必须由各 selector 直接产出业务分？
- AI scanner 的 `confidence` 应该如何定义：技术指标覆盖率、主题匹配、新闻/LLM 可用性、还是综合？
- 是否需要让发现页展示 `score/confidence/technical_confirmation_count`，便于用户理解入池原因？
- 是否要在同一个 change 内统一人工批量纳入量化的事件记录，还是另开 change？
- 对已有 `source_score=0` 的历史候选事件，是否完全不迁移，仅要求下一轮发现修正？

## Suggested Change ID

`fix-discover-lifecycle-scoring`
