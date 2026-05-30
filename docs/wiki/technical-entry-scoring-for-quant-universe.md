---
source: openspec/changes/quant-technical-entry-score
title: 量化股票技术入池评分
last_synced: 2026-05-29
last_reviewed: 2026-05-29
status: completed
---

# 量化股票技术入池评分

## 能力摘要

量化生命周期的 `candidate_score` 已改为纯技术入池分，`candidate_confidence` 已改为纯技术数据置信度。发现来源、AI 推荐分、source confidence、来源名称、来源数量和展示文案只作为审计和解释信息保留，不再影响自动入池、生命周期状态或量化入口判断。

本能力解决的问题是：股票发现可以提出候选，但是否进入量化必须由当时可见的行情和技术结构决定，不能因为“来自某个发现来源”或“来源分高”就自动抬高量化评分。

## 用户可见行为

- 发现/研究/AI 输出的股票会保留来源说明，但量化入池显示的分数来自技术结构。
- 技术入池分解释包含趋势结构、动量、量能流动性、确认度、风险质量和惩罚项。
- 技术数据缺失、过期、字段不完整或流动性不足时，自动入池会被阻断，并返回明确 reason code。
- AI scanner 已纳入默认发现流程；如果 AI 失败但其他发现策略成功，任务仍可完成并记录失败策略。
- 发现任务完成后，准备好的候选事件写入数据库，后续生命周期、实时量化、历史回放和实时量化演练读取同一份准备证据。

## 工作流

1. 发现/研究模块生成候选股票和来源审计信息。
2. 系统刷新并准备对应的行情技术数据。
3. 候选事件持久化到数据库，包含技术快照、entry gate、`candidate_score`、`candidate_confidence` 和 breakdown。
4. `QuantUniverseManager` 根据技术入池分和技术置信度决定是否进入量化状态。
5. 实时量化、历史回放和实时量化演练复用同一评分语义，不再读取来源分作为量化分。

## 评分口径

`candidate_score` 的输入只允许来自行情和技术指标：

- 趋势结构：价格相对 MA20/MA60、MA5/MA10/MA20 排列、MA20 斜率、趋势标签一致性。
- 动量：MACD、RSI 构造性、短中期均线动量。
- 量能与流动性：成交额门槛和量比。
- 确认度：连续站稳、突破回踩确认；只有当前单点快照时确认分最高 0.50。
- 风险质量：与 MA20/MA60 的距离、RSI 是否过热、量能是否异常。
- 惩罚项：过度偏离、过热追涨、数据过期。

`candidate_confidence` 的输入只允许来自技术数据质量：

- 技术字段覆盖率。
- 快照新鲜度。
- 指标一致性。
- 历史深度。

## 数据和 API 口径

- 候选事件 `payload_json` 是发现完成后的准备证据来源。
- 量化状态 `snapshot_json.candidate_score_breakdown` 保存技术评分解释。
- 现有发现、研究、实时量化和演练 API 继续使用原路径，但字段语义改变：
  - `candidate_score` 表示量化技术入池分。
  - `candidate_confidence` 表示技术数据置信度。
  - 来源分和来源置信度只作为 audit/source 字段展示。
- artifact-backed signal 的 `market_snapshot` 只持久化 artifact 诊断字段；非 artifact 的旧手工/测试信号只保留执行所需的最小交易可行性字段。

## 关键实现

- [app/quant_sim/technical_entry_score.py](/C:/Projects/githubs/aiagents-stock/app/quant_sim/technical_entry_score.py)
- [app/quant_sim/quant_universe_lifecycle.py](/C:/Projects/githubs/aiagents-stock/app/quant_sim/quant_universe_lifecycle.py)
- [app/quant_sim/candidate_entry_gate.py](/C:/Projects/githubs/aiagents-stock/app/quant_sim/candidate_entry_gate.py)
- [app/discover/discover.py](/C:/Projects/githubs/aiagents-stock/app/discover/discover.py)
- [app/gateway/quant_universe_entry.py](/C:/Projects/githubs/aiagents-stock/app/gateway/quant_universe_entry.py)
- [app/quant_sim/engine.py](/C:/Projects/githubs/aiagents-stock/app/quant_sim/engine.py)
- [app/quant_sim/signal_center_service.py](/C:/Projects/githubs/aiagents-stock/app/quant_sim/signal_center_service.py)

## 验证记录

- `python -m pytest tests/test_quant_technical_entry_score.py --cov=app.quant_sim.technical_entry_score --cov-report=term-missing --cov-fail-under=90 -q`
  - 结果：`14 passed`，覆盖率 `96.25%`。
- 相关发现/生命周期/演练集成套件：
  - 结果：`179 passed`。
- 全量回归：
  - `python -m pytest -q`
  - 结果：`881 passed, 1 skipped, 15 warnings`。

## 注意事项

- 不要把发现来源分、AI 推荐文本或来源数量接回量化入池分。
- 旧手工路径没有 artifact 时可继续生成实时信号，但 artifact-required 的回放、缺失验证和事实层入口必须返回缺失原因。
- 时间字段按本地业务时间解析和持久化，不再把 `Z` 后缀转换成 UTC 时间。
- 页面展示可以保留来源说明，但“量化分”“技术置信度”“入池阻断原因”必须来自准备后的技术证据。
