---
source: "openspec/changes/local-time-persistence"
change_id: "local-time-persistence"
title: "本地业务时间持久化"
last_synced: "2026-05-29"
last_reviewed: "2026-05-29"
status: "active"
---

# 本地业务时间持久化

## Story / Capability Summary

系统自有的业务时间统一保存为部署本地时间文本：`YYYY-MM-DD HH:mm:ss`。实时量化、历史回放、实时量化演练、market technical artifact、信号、交易、生命周期和 API/UI 都使用同一套时间口径。

这次变更的核心目标是消除 `checkpoint_at` / `checkpoint_at_utc`、`updatedAt` / `updatedAtUtc` 这类双字段口径，避免信号、artifact、交易和页面复盘因为 8 小时偏移或字段 fallback 出现关联断裂。

## User-Facing Behavior

- 页面和 API 只展示本地时间字段，不再返回或依赖 `updatedAtUtc`、`checkpointAtUtc`。
- 历史回放和实时量化演练的 checkpoint、信号、交易、生命周期状态和 summary 可以直接用同一个 `checkpoint_at` 关联。
- 数据库重建只针对项目业务 DB；`data/local_sources` 下的 Parquet/K 线/provider cache 不删除、不重写。
- provider cache 中的原始时间只在进入项目自有持久化边界时规范化为本地时间。

## Workflow

1. 行情或缓存数据进入 runtime / artifact producer。
2. 写入项目自有 artifact、信号、交易、生命周期或 API payload 前，统一通过本地时间工具规范化。
3. 项目自有表只写 `checkpoint_at`，不写 `checkpoint_at_utc`。
4. 查询、排序、去重和 join 均使用本地 `checkpoint_at`。
5. UI 直接展示后端返回的本地时间文本，不做 UTC 转换。

## Data Contract

项目自有时间字段使用以下格式：

```text
YYYY-MM-DD HH:mm:ss
```

受影响字段包括但不限于：

- `checkpoint_at`
- `created_at`
- `updated_at`
- `computed_at`
- `executed_at`
- `snapshot_at`
- `occurred_at`
- `evaluated_at`
- `last_run_at`
- `next_run_at`

删除或禁止继续使用的字段/语义：

- `checkpoint_at_utc`
- `checkpointAtUtc`
- `updatedAtUtc`
- `format_utc_iso_z`
- `utc_now_iso_z`
- `COALESCE(checkpoint_at_utc, checkpoint_at)` 这类兼容 fallback

## Backend / API Flow

- `app/quant_sim/time_utils.py` 提供本地时间格式化和解析工具。
- `app/quant_sim/db.py`、replay/drill DB、market technical artifact store 使用本地时间默认值和本地 checkpoint。
- `app/quant_sim/replay_service_historical.py` 和 `app/quant_sim/replay_service_drill.py` 写入本地 checkpoint。
- `app/stock_refresh_artifact_writer.py` 将实时刷新产出的 artifact 写成本地 `checkpoint_at` / `computed_at`。
- `app/gateway/live_sim.py` 和 `app/gateway/his_replay.py` 只返回本地时间 payload。
- `ui/src/lib/page-models.ts` 不再声明 UTC 时间字段。

## Cache Boundary

本地缓存不是业务持久化表。

- Parquet/provider cache 保留 provider/source-native 格式。
- 删除重建业务 DB 时，不删除 `data/local_sources`。
- 不因为本地时间持久化而重写缓存文件。
- 如果 provider/cache 输入带有 `Z` 或来源时间，业务写入边界负责转成本地文本。

这条边界是为了保留 local-first 数据准备性能，同时让业务 DB、交易逻辑和 UI 复盘只使用一个时间概念。

## Verification Evidence

主要验证命令：

```text
python -m compileall -q app
python -m pytest -q tests/test_time_utils.py
python -m pytest -q tests/test_quant_sim_scheduler.py tests/test_stock_refresh_scheduler.py
python -m pytest -q tests/test_quant_universe_lifecycle_manager.py
python -m pytest -q tests/test_market_technical_artifact.py -k "artifact or checkpoint or local"
python -m pytest -q tests/test_ui_backend_api_actions.py -k "live_sim_snapshot_includes_local_time_context or page_tables_render_system_time or stock_analysis_records_persist_local_time_and_render_system_time or his_replay_capital_pool_includes_local_trade_at_same_market_checkpoint"
rg -n "timezone\\.utc|now_utc|_utc|updatedAtUtc|checkpointAtUtc|format_utc_iso_z|utc_now_iso_z|ensure_utc_datetime|checkpoint_at_utc" app ui/src
```

最终聚焦验证结果：

```text
127 passed, 176 deselected, 2 warnings
```

`rg` 对 active code (`app`, `ui/src`) 无 UTC helper / UTC field 命中。

## Operational Notes

- 旧业务数据库不迁移，按部署步骤删除并重建。
- 本地 cache/Parquet 不属于删除重建范围。
- 后续如果重新支持多市场独立时区，应作为新 OpenSpec 变更处理，不应把 UTC/local 双字段兼容重新塞回当前业务表。

## Review Notes

已完成主线程实现审查、对齐审查、安全审查和 fallback 独立审查。审查结论为：本地时间持久化、UTC 字段移除、DB/API/UI 行为、cache 边界与 OpenSpec 对齐，无未关闭阻塞 finding。
