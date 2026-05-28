---
source: openspec/changes/archive/2026-05-28-market-technical-artifact
change_id: market-technical-artifact
title: 统一行情技术 Artifact 事实层
last_synced: 2026-05-28
last_reviewed: 2026-05-28
status: completed
---

# 统一行情技术 Artifact 事实层

## 能力概览

`market_technical_artifact` 是量化系统的行情技术事实层。它把实时刷新、发现入池、实时量化、实时量化演练和历史回放中使用的价格、均线、动量、结构、交易可行性和数据质量信息，统一记录为可引用、可复查、按 checkpoint 隔离的 artifact。

核心目标是避免同一只股票在不同模块里各自读取 runtime snapshot、candidate payload、signal market snapshot、provider cache 或 replay snapshot，导致口径不一致、未来函数风险和信号难以解释。

## 用户可见行为

- 信号、候选、回放和演练诊断会带有 `artifact_ref`、`source_status`、`reason_code` 和 `missing_fields`。
- 用户或系统可以通过 `artifact_ref` 查询当时使用的行情技术事实。
- 工作台、发现股票、研究和实时量化页面展示 live 口径数据时，使用 live artifact 或 artifact-derived projection。
- 历史回放和实时量化演练只读取 run-scoped artifact，不会 fallback 到当前 live 最新行情。
- 缺失 artifact 时系统返回明确原因，例如 `missing_artifact_reference`、`missing_artifact`、`run_scope_required` 或 `invalid_artifact_ref`，不会静默用当前行情补齐。

## 数据域和隔离

Artifact 按 domain 隔离：

- `live`：实时刷新和实时量化使用的当前事实层。
- `replay`：历史回放 run 内的 checkpoint 事实层。
- `drill`：实时量化演练 run 内的 checkpoint 事实层。

live artifact 存放在 `market_technical_artifacts`。回放和演练 artifact 存放在 `sim_run_market_technical_artifacts`，并强制携带 `run_id` 和 `run_type`。

## Artifact 身份

Artifact 使用稳定的 `artifact_ref` 跨表引用，包含：

- `domain`
- `run_id`
- `run_type`
- `market`
- `stock_code`
- `checkpoint_at`
- `timeframe`
- `data_version`

`checkpoint_at` 是行情技术事实对应的市场时间，`computed_at` 是系统写入 artifact 的时间。两者不能互相替代。

## 字段分层

实现采用“关键列 + JSON 扩展”：

- 查询和高频诊断字段列化，例如 `artifact_ref`、`stock_code`、`checkpoint_at`、`latest_price`、`close`、`ma20`、`ma20_slope`、`rsi`、`macd`、`volume_ratio`、`source_status`、`reason_code`。
- 完整行情、指标、结构、质量诊断放入 JSON 字段，例如 `market_json`、`indicator_json`、`structure_json`、`quality_json`。

这样既能支持查询和诊断，又避免把所有指标无差别展开成列。

## 核心流程

1. 实时刷新从 provider/local cache 准备行情技术数据。
2. 刷新结果写入 live artifact。
3. runtime snapshot 只作为从 live artifact 派生的展示缓存。
4. 发现股票和研究结果在进入量化候选时保存 `artifact_ref` 和轻量诊断。
5. 实时量化扫描、生命周期评估和信号生成通过 artifact reader 读取事实层。
6. 历史回放和实时量化演练在每个 checkpoint 写入 run-scoped artifact。
7. 信号详情、页面 API 和诊断 API 通过 artifact store 查询事实，不再临时 provider fetch。

## API

新增 artifact 查询诊断入口：

- `GET /api/v1/quant/market-technical-artifacts/{artifact_ref}`
- `GET /api/v1/quant/market-technical-artifacts`

完整 key 查询 live artifact 时需要 `domain, stock_code, market, checkpoint_at, timeframe, data_version`。

完整 key 查询 replay 或 drill artifact 时还需要 `run_id, run_type`。

API 只查询已有 artifact，不生成 artifact，不触发 provider 拉取。

## 页面和诊断

以下页面 API 使用 live artifact 或 artifact-derived projection：

- 工作台
- 发现股票
- 研究
- 实时量化

页面不新增大块 UI，只返回最小诊断字段，便于追踪：

- `artifact_ref`
- `source_status`
- `reason_code`
- `missing_fields`
- `marketTechnicalBacked`

## 规则和边界

- `source_score`、`source_confidence`、`multi_source_bonus` 不进入行情技术 artifact。
- candidate payload 和 signal market snapshot 不再保存完整权威行情技术字段。
- provider cache 可以作为 artifact producer 输入，但不能作为决策事实直接消费。
- replay/drill 缺少 run artifact 时，必须返回 run-scoped missing reason，不能读取 live。
- 旧记录没有 `artifact_ref` 时不做 backfill，不用当前行情补齐。

## 验证证据

实现阶段记录的主要验证：

- `openspec validate market-technical-artifact --strict` 通过。
- broad regression：`292 passed`。
- artifact-focused coverage：`69 passed`，覆盖率 `92%`。
- follow-up targeted tests：`3 passed`。
- 两条独立最终复审线程均 PASS，无剩余 P1/P2。

## 相关代码

主要后端模块：

- `app/quant_sim/market_technical_artifact.py`
- `app/quant_sim/market_technical_artifact_store.py`
- `app/stock_refresh_artifact_writer.py`
- `app/quant_sim/lifecycle_artifact_adapter.py`
- `app/quant_sim/replay_artifact_adapter.py`
- `app/quant_sim/quant_universe_artifact_db.py`
- `app/gateway/market_technical_artifacts.py`
- `app/gateway/artifact_diagnostics.py`
- `app/gateway/page_market_artifact_projection.py`

主要测试：

- `tests/test_market_technical_artifact.py`
- `tests/test_market_technical_artifact_candidate_entry.py`
- `tests/test_market_technical_artifact_pages.py`
- `tests/test_market_technical_artifact_store_isolation.py`
- `tests/test_market_technical_artifact_replay_missing.py`
- `tests/test_live_quant_drill_service_candidate_events.py`

## 后续扩展

后续 `candidate_score`、`outcome_score` 和 `outcome_feedback_score` 应基于 `artifact_ref` 复算当时可见的行情技术事实，避免继续从分散 payload 或最新行情读取指标。
