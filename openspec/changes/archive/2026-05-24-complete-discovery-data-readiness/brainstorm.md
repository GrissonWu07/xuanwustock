# Brainstorm: 完整股票发现数据就绪

## Problem

股票发现当前还不能算完整：

- AI Scanner 全量测试失败，候选排序不稳定，并且单元测试路径意外触发真实历史行情回源。
- 股票发现的 `ready` 口径仍偏向“技术快照字段完整”，没有统一表达“发现候选可被量化评分内核消费的完整数据快照”。
- 当前实现里 stale 技术数据仍可能进入评分内核并被扣分，而用户明确要求核心行情/技术数据缺失或过期时不应计算。

这会造成用户看到“发现成功”或“ready”，但后续自动入池、实时量化或演练使用的数据并不一定符合完整性要求。

## Product Challenge

股票发现的目标不是只展示候选，而是生成可被量化生命周期可靠消费的候选集合。用户需要相信：

- AI 发现结果排序稳定、测试可重复；
- 发现候选在进入量化判断前已经准备好完整、未过期的行情和技术指标；
- 缺数据、过期数据、外部数据源失败不会被降权掩盖，而会明确阻止计算并暴露原因；
- API、UI、生命周期入口使用同一个数据就绪定义。

## User Scenarios

1. 用户运行默认股票发现，AI Scanner 参与候选生成。
2. 发现任务完成后，用户查看发现页，看到每个候选是否是完整数据快照 ready。
3. 某候选缺少行情字段、技术指标、快照时间、provider、timeframe 或 indicator version 时，系统显示不可量化原因，不计算技术入池分。
4. 某候选技术快照过期时，系统显示 stale，不进入评分内核。
5. 自动入池只在完整且新鲜的数据快照上执行，且只看技术分和技术置信度是否达标。
6. 单元测试和全量测试不依赖真实 AkShare/TDX 网络数据，AI Scanner 排序可重复。

## Scope

本变更候选范围应覆盖：

- 股票发现 AI Scanner 排序稳定性和测试隔离。
- 股票发现 prepared evidence 的统一数据快照 ready 口径。
- 自动入池前的数据完整性门禁。
- 技术评分内核调用前的输入校验边界。
- 发现 API/UI 对完整、缺失、过期、失败原因的表达。
- 测试参数和覆盖：AI Scanner、snapshot readiness、candidate entry gate、discover API、UI diagnostics。

## Out of Scope

- 不调整买卖信号融合算法。
- 不调整资金槽、lot、slot 分配算法。
- 不调整历史回放收益策略参数。
- 不删除或迁移老数据。
- 不改实时监控隐藏路由。
- 不把基础资料字段作为技术评分内核的输入。

## Smallest Useful Slice

最小可用切片：

1. 固定 AI Scanner 单元测试不触发真实网络 IO，并保证相同输入排序稳定。
2. 定义 `discovery_data_ready` 或等价字段：完整行情和技术快照 ready 且未过期。
3. 缺失或 stale 时，候选不计算 `candidate_score/candidate_confidence`，返回 blocking reason 和 missing/stale 诊断。
4. Discover API/UI 显示完整数据快照状态。
5. 后端全量 pytest 中 AI Scanner 失败被关闭。

## Rejected / Deferred Scope

- 不采用“缺基础数据就乘质量系数降权”的方案。用户已明确否定：核心数据缺失时应阻止计算。
- 不按策略来源决定是否自动入池。用户已明确自动入池只看数据是否完整、技术分是否满足要求。
- 不只检查名称、行业、总市值、PE、PB。用户已明确完整性应包含行情和技术指标。
- 不把发现来源分、AI scanner score、source confidence 填到量化技术分。

## Candidate Requirements

- 系统必须把发现候选的数据就绪状态分成可计算和不可计算两类。
- 可计算必须满足完整、未过期的行情/技术快照字段。
- 不可计算必须给出 machine-readable reason，例如 `missing_required_snapshot`、`stale_required_snapshot`、`provider_failed`。
- 技术评分内核只接受已通过完整性校验的快照；调用方不得用 stale penalty 掩盖不可计算输入。
- AI Scanner 的单元测试必须隔离外部行情 IO。
- AI Scanner 对等分或缺历史数据场景必须有稳定排序规则。
- Discover API 和 UI 必须使用相同 readiness 口径。
- 自动入池必须只在 ready 快照上比较 `candidate_score` 和 `candidate_confidence` 阈值。

## Alternative Solutions

### 方案 A：在现有 technical snapshot ready 上补 stale 硬阻断

优点：改动小，容易关闭当前测试失败和 stale 评分问题。

缺点：仍然容易把“technical ready”误解为完整数据 ready；后续基础行情字段和 freshness 语义会继续分散。

### 方案 B：新增统一 Discovery Data Snapshot Readiness 层

优点：把 quote、technical、freshness、provider status、missing fields 统一为一个门禁对象；发现 API、生命周期、UI 都读同一口径。

缺点：需要调整更多测试和 API 字段，必须清理现有 `technical_snapshot_status` 与新状态的关系。

### 方案 C：把 readiness 全部放进评分内核

优点：调用方简单。

缺点：会让评分内核同时承担数据验证、数据质量解释和策略评分，边界变差；也容易再次出现“缺数据被扣分但仍输出 score”的问题。

## Recommended Direction

推荐方案 B。

理由：

- 用户的核心诉求是“完整数据快照 ready”，不是单个字段修补。
- ready 口径必须是 API/UI/生命周期共享契约。
- 技术评分内核应保持纯技术评分，输入完整性由门禁层保证。
- AI Scanner 测试失败可以作为同一变更的首个验收信号，因为它暴露了发现流程外部 IO 隔离不足和排序不稳定。

建议后续 `/sp-spec` 将能力命名为 `discovery-data-readiness`，并修改现有 discovery/quant entry 相关要求，而不是新增与旧要求冲突的并行口径。

## Impacted Modules

- `app/discover/ai_stock_scanner.py`
- `tests/test_ai_stock_scanner.py`
- `app/discover/market_snapshot.py`
- `app/discover/candidate_artifact.py`
- `app/discover/discover.py`
- `app/quant_sim/candidate_entry_gate.py`
- `app/quant_sim/technical_entry_score.py`
- `app/gateway/quant_universe_entry.py`
- `app/quant_sim/evidence_service.py`
- `ui/src/features/discover/discover-page.tsx`
- `ui/src/features/quant/quant-entry-controls.tsx`
- `ui/src/lib/page-models.ts`

## Risks

- 口径收紧后，发现任务 ready 数量可能下降，自动入池数量也可能下降。
- 如果 provider 在非交易时间或节假日返回旧数据，freshness 规则需要明确基于交易日还是自然时间。
- 现有测试中有些 fixture 只构造技术字段，没有完整 metadata，需要批量修正。
- active OpenSpec change `quant-technical-entry-score` 仍记录 stale 作为 penalty，和用户最新口径冲突。
- active OpenSpec change `audit-data-loop-logic-gaps` 使用 prepared evidence，但 readiness 定义仍偏技术快照，需要同步更新。

## Open Questions

1. Freshness 窗口按 30m 快照 TTL 固定，还是按 A 股交易日/当前是否开盘动态判断？
2. “完整行情”除 price、amount、volume_ratio 外，是否必须包含涨跌幅、成交量、换手率、昨收、开高低？
3. 基础资料如总市值、PE、PB 是否作为展示/解释字段，不参与 ready；还是也作为 quote/basic 子状态但不阻止技术评分？
4. AI Scanner 在历史数据缺失时，是否应直接降低候选为 unprepared，而不是用中性 `technical_score=0.5` 排序？
5. UI 是否继续显示旧 `technical_snapshot_status`，还是改名为更准确的 `data_snapshot_status`？

## Suggested Change ID

`complete-discovery-data-readiness`
