# Change: 信号 Outcome 评分与成熟反馈闭环

## Workflow Lane

full

## Why

当前系统已经能生成候选分、BUY/SELL 信号、执行诊断、历史回放、实时量化演练和收益差异归因，但缺少统一的“信号发出后，行情是否验证了该信号”的事后评分。结果是 strong BUY、weak BUY、SELL、cooling 恢复和 ignored BUY 的好坏仍需要人工复盘，难以稳定反哺后续交易决策。

本变更要把信号 outcome 变成可持久化、可查询、可聚合、可反哺的项目内数据，使系统能回答：这个 BUY 是买早、买晚还是不该买；这个 SELL 是保护收益、卖晚还是卖早；某只股票近期 outcome 差时，后续是否需要降仓、冷却或强确认。

## What Changes

- 为 BUY 和 SELL 信号生成 `3 / 5 / 10 checkpoints` 的成熟 outcome 评分。
- outcome 使用 `market_technical_artifact` 作为事实来源，记录 MFE、MAE、目标命中、失效、MA20 跌破、T+1 放大、延迟成本、市场一致性、重复弱信号等原始指标。
- 生成股票级成熟 outcome 聚合 `outcome_feedback_score`，只允许读取 `matured_at <= current_checkpoint` 的历史 outcome。
- 将成熟 outcome 聚合接入 `stock_execution_feedback`、`portfolio_execution_guard` 和实时量化生命周期恢复/降频/出池逻辑。
- 在信号详情、历史回放、实时量化演练和股票/生命周期诊断 API 中展示 outcome 与反馈原因。
- 明确 `source_score`、`source_confidence`、`multi_source_bonus` 不参与 outcome、candidate、signal quality 或交易决策。

## Scope

- 覆盖 live、historical replay、live quant drill 三个数据域，算法一致、数据隔离。
- 覆盖 BUY 和 SELL 信号。
- 覆盖成熟 outcome 的批量评分、增量评分、聚合反馈和交易决策消费。
- 覆盖后端 API 和现有前端页面的 outcome 展示。
- 复用已完成的 `market_technical_artifact` 事实层，不重新设计行情技术 artifact。

## Out of Scope

- 不做 AI 文本质量评分。
- 不使用发现来源、来源分、来源置信度或多来源数量给股票、信号或 outcome 加分。
- 不用未成熟 outcome 影响当前信号。
- 不用同一次 replay/drill 完成后的全量 outcome 反向污染早期 checkpoint。
- 不做自动调参。
- 不改变 `candidate_score` 的纯技术入池分语义。

## Impact

- 后端新增 outcome 评分与聚合数据模型、服务、API 与调度入口。
- 历史回放和实时量化演练完成后会多一次 outcome 评分任务。
- 实时量化会在定时任务中增量扫描已成熟信号。
- UI 会在信号详情和任务结果页面增加 outcome 汇总与明细。
- 策略配置需要新增 outcome feedback 相关阈值和权重。

## Rules Applied

- `PIR-003`: 本变更需要数据库持久化；本地 SQLite，部署阶段 MySQL，连接池最大不超过 100。
- `PIR-004`: 新增后端 API 需要明确路径、参数和响应语义。
- `PIR-005`: run 完成后的批量 outcome 评分属于耗时任务，应通过 job/run 完成流程异步或后台执行。
- `PIR-006`: 复用 `market_technical_artifact`、现有信号表、执行反馈、组合 guard、生命周期服务，不复制事实层或评分输入。
- `PIR-007` / `TEST-011`: 必须通过 replay/drill/job/API 入口做 standalone verification。
- `PIR-010`: 不添加未要求的兼容分支或 fallback；缺 artifact 必须记录缺失原因。
- `LOG-001`~`LOG-011`: outcome scoring job 和反馈消费需要结构化日志和安全字段。
- `ENC-001`~`ENC-007`: 新增中文文档、UI 文案、日志说明和测试参数使用 UTF-8。

## Risks

- 未来函数风险：必须严格按 `matured_at <= current_checkpoint` 消费 outcome。
- 过拟合风险：少量 outcome 不应大幅改变交易决策，需要最小样本量和衰减。
- SELL outcome 误判风险：SELL 需要区分止损、止盈、技术转弱、弱 SELL 噪音和资金释放。
- 性能风险：run 结束后批量评分可能较慢，需要按 run/signal/horizon 增量、幂等执行。
- 数据缺失风险：停牌、涨跌停、缺 K 线、部分成交、除权除息等必须输出 skipped/partial reason。

## Open Questions

- 无阻塞问题。`/sp-goal` 模式下按已确认 brainstorm 和现有代码证据记录设计决策，不再额外等待用户确认。
