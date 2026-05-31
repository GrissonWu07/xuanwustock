---
source: openspec/changes/signal-outcome-scoring
title: 信号 Outcome 评分与成熟反馈闭环
last_synced: 2026-05-31
last_reviewed: 2026-05-31
status: completed
change_id: signal-outcome-scoring
---

# 信号 Outcome 评分与成熟反馈闭环

## 能力摘要

信号 outcome 评分把 BUY/SELL 发出后的真实行情表现沉淀为可查询、可解释、可聚合的数据。系统会在 3、5、10 个 checkpoint horizon 成熟后，根据 `market_technical_artifact` 事实层计算 outcome score，并把成熟 outcome 聚合为股票级反馈，反哺后续执行反馈、组合执行 guard 和量化生命周期。

该能力解决的问题是：量化系统不再只看当时的信号强弱，也能复盘信号发出之后是否真的被行情验证，并在未来同股交易中按成熟证据降仓、提高确认门槛或记录冷却原因。

## 用户可见行为

- 信号详情页展示 BUY/SELL outcome 明细，包括 horizon、得分、成熟状态、关键指标和 skipped/partial reason。
- 历史回放和实时量化页面展示 outcome 汇总，包括成熟样本数、BUY/SELL 平均分、重复弱信号和贡献股票。
- 策略配置页提供 `signal_outcome_policy` 配置组，可调整 horizon、目标收益、失效阈值、反馈样本数、lookback 和仓位倍率下限。
- 实时量化、历史回放和实时量化演练使用同一套评分算法，但 outcome 和 feedback 数据按 live/run 隔离，不互相污染。

## 工作流

1. 信号生成时记录 checkpoint、动作、股票、run/domain 和 artifact reference。
2. outcome scoring job 按 horizon 查询同一股票、同一 domain/run 的后续 `market_technical_artifact`。
3. horizon 未成熟或 artifact 缺失时写入 skipped/partial diagnostic，不读取实时最新数据兜底。
4. horizon 成熟后计算 BUY 或 SELL outcome score，并保留 MFE/MAE、避免回撤、错过涨幅、MA20 跌破、T+1 放大等原始指标。
5. `OutcomeFeedbackAggregator` 只聚合 `matured_at <= current_checkpoint` 的历史 outcome。
6. 后续信号评估时，成熟反馈通过独立 `outcome_feedback` 字段进入执行反馈、组合 guard 和生命周期诊断，不覆盖 `candidate_score`。

## 规则应用

- `candidate_score` 仍是事前技术入池分，不被 outcome 覆盖。
- `source_score`、`source_confidence`、来源类型、来源数量和 `multi_source_bonus` 不参与 outcome 评分、feedback 聚合或交易决策。
- outcome 只读取 `market_technical_artifact`，不得 fallback 到 live latest、runtime snapshot 或 provider cache。
- live/replay/drill 数据隔离：run-scoped outcome 必须带 `run_id` 和 `run_type`。
- feedback consumption 必须成熟后才可用，禁止当前信号读取自己的未来表现。

## 设计摘要

核心实现分三层：

- `SignalOutcomeScoringService`：负责 horizon maturity 判断、artifact window 查询、BUY/SELL outcome 公式和持久化。
- `OutcomeFeedbackAggregator`：负责按 stock/profile/domain/run 聚合成熟 outcome，输出股票级反馈。
- 反馈消费层：`stock_execution_feedback`、`portfolio_execution_guard`、`signal_center_service` 和 run/live scoring entrypoint 读取成熟反馈并写入诊断。

关键数据表：

- `signal_outcome_scores`
- `sim_run_signal_outcome_scores`
- `outcome_feedback_scores`
- `sim_run_outcome_feedback_scores`

## API / 数据 / UI 影响

新增或扩展 API：

- `GET /api/v1/quant/outcomes/signals/{signal_id}`
- `GET /api/v1/quant/outcomes/runs/{run_id}`
- `POST /api/v1/quant/outcomes/runs/{run_id}/score`
- `POST /api/v1/quant/outcomes/live/score-matured`
- 信号详情、历史回放、实时量化 payload 增加 outcome summary 或 outcome rows。

前端新增：

- `OutcomeSummaryCard`
- 信号详情 outcome horizon 区块
- 历史回放/实时量化 outcome 汇总卡片
- 策略配置 outcome feedback 配置项

## 安全与权限

本变更不新增外部 provider 调用，不暴露 provider 原始响应、凭证、token、session 或大体积原始 K 线数组。API 只返回项目内信号、股票、run 和 outcome 诊断字段。日志只允许记录 `trace_id`、`run_id`、`run_type`、`signal_id`、`stock_code`、`horizon_key`、`matured_at`、`scoring_version` 和 reason code。

## 日志与可追踪性

关键事件：

- `signal_outcome_scoring_started`
- `signal_outcome_scoring_completed`
- `signal_outcome_scoring_skipped`
- `outcome_feedback_applied`

诊断字段包括 `matured_at`、`source_artifact_ref`、`reason_code`、`metrics_json`、`formula_json` 和 `feedback_score`，用于解释“为什么这次信号有效/无效，以及为什么后续交易被降仓或提高门槛”。

## 验证记录

- `openspec validate signal-outcome-scoring --strict`
  - 结果：通过。
- 后端 outcome focused coverage：
  - `$env:PYTHONPATH='.'; pytest tests\test_signal_outcome_scoring.py tests\test_signal_outcome_feedback.py --cov=app.quant_sim.signal_outcome_scoring --cov=app.quant_sim.outcome_feedback --cov=app.quant_sim.outcome_scoring_entrypoints --cov=app.gateway.outcomes --cov-report=term-missing -q`
  - 结果：`12 passed`，总覆盖率 `94%`。
- 后端回归：
  - `pytest tests\test_stock_execution_feedback.py tests\test_portfolio_execution_guard.py -q`
  - `pytest tests\test_quant_universe_lifecycle_manager.py -q`
  - `pytest tests\test_quant_sim_scheduler.py tests\test_quant_replay_engine.py -q`
  - `pytest tests\test_ui_backend_api_dataflow.py -q`
  - `pytest tests\test_quant_sim_db.py -q`
  - 结果：合计通过。
- 完整 UI 测试：
  - `npm test`
  - 结果：`12 passed` test files，`65 passed` tests。
- UI build：
  - `npm run build`
  - 结果：通过；保留既有 Vite chunk-size warning。

## 需求反例与审计证据

- Counterexample：live domain 存在 artifact、run domain 缺 artifact 时，run outcome 不允许 fallback 到 live artifact；测试覆盖 missing reason。
- Masked-test：反馈消费测试确保前置 action/profile/data gate 通过后才断言 outcome feedback 生效，避免被早期 gate 掩盖。
- Broad-qualifier：`same algorithm`、`only matured`、`SHALL NOT use source score`、`isolated data` 均映射到服务、DB 和测试。
- Decision chain：signal -> artifact window -> maturity gate -> outcome score -> persistence -> feedback aggregate -> guard/lifecycle/API/UI。
- Evidence timing：`matured_at` 在 outcome 持久化前确定，feedback 只读取 `matured_at <= as_of_checkpoint`。
- Deterministic sort：horizon rows 按 horizon 升序；feedback sample 按 `matured_at` 降序并用 id 稳定 tie-break。

## 关键实现

- [app/quant_sim/signal_outcome_scoring.py](/C:/Projects/githubs/aiagents-stock/app/quant_sim/signal_outcome_scoring.py)
- [app/quant_sim/outcome_feedback.py](/C:/Projects/githubs/aiagents-stock/app/quant_sim/outcome_feedback.py)
- [app/quant_sim/outcome_scoring_entrypoints.py](/C:/Projects/githubs/aiagents-stock/app/quant_sim/outcome_scoring_entrypoints.py)
- [app/quant_sim/signal_outcome_policy.py](/C:/Projects/githubs/aiagents-stock/app/quant_sim/signal_outcome_policy.py)
- [app/gateway/outcomes.py](/C:/Projects/githubs/aiagents-stock/app/gateway/outcomes.py)
- [app/gateway_api.py](/C:/Projects/githubs/aiagents-stock/app/gateway_api.py)
- [ui/src/features/quant/outcome-summary-card.tsx](/C:/Projects/githubs/aiagents-stock/ui/src/features/quant/outcome-summary-card.tsx)
- [ui/src/features/quant/signal-detail-page.tsx](/C:/Projects/githubs/aiagents-stock/ui/src/features/quant/signal-detail-page.tsx)
- [ui/src/features/quant/his-replay-page.tsx](/C:/Projects/githubs/aiagents-stock/ui/src/features/quant/his-replay-page.tsx)
- [ui/src/features/quant/live-sim-page.tsx](/C:/Projects/githubs/aiagents-stock/ui/src/features/quant/live-sim-page.tsx)

## 经验总结

事后评分一旦进入交易决策，必须同时满足三个条件：事实来源统一、成熟时间边界清晰、live/run 数据隔离。否则 outcome feedback 很容易变成未来函数或跨任务污染。
