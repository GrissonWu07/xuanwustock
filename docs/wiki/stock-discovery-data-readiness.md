---
change_id: complete-discovery-data-readiness
title: 股票发现数据就绪门禁
---

# 股票发现数据就绪门禁

## Story / Capability Summary

股票发现候选进入量化生命周期前，必须具备完整且 ready 的行情和技术快照。AI Scanner 单元测试必须稳定、隔离真实外部行情 IO。自动入池门禁只看数据完整性、公共风险门禁、技术分和技术置信度，不按发现来源调整规则。

## User-Facing Behavior

- 完整 ready 快照的发现候选可以继续计算 `candidate_score` 和 `candidate_confidence`。
- 缺失核心行情、技术指标、快照时间、provider、timeframe 或 indicator version 的发现候选不会被有效评分。
- stale、stale_unprepared、failed、incomplete 等非 ready 快照不会继续以扣分方式评分，而是直接给出 blocking reason。
- 发现来源、source score、source confidence 和来源文本不会替代技术评分，也不会放宽或收紧自动入池门禁。

## Workflow

1. 发现策略产生候选。
2. 候选 payload 携带行情和技术快照字段。
3. `candidate_entry_gate` 对 discovery 候选执行完整快照 ready 检查。
4. `technical_entry_score` 对 ready 快照计算技术入池分和技术置信度。
5. 生命周期管理器根据统一门禁和评分决定是否进入试跑、量化或保持 inactive/blocked。

## Rules Applied

- `PIR-001`: OpenSpec design/tasks 记录目标代码路径。
- `PIR-002`: 修改生产代码文件低于 1000 行。
- `PIR-003`: 不新增数据库能力。
- `PIR-004`: 不新增 API；现有发现 API 响应语义收紧。
- `PIR-005`: 发现任务保持现有异步执行。
- `PY-005`, `TEST-008`: AI Scanner 单元测试隔离真实外部行情 IO。
- `TEST-001`: changed/affected production modules 覆盖率达到 90.69%。
- `TEST-002`, `TEST-003`, `TEST-010`: 测试参数、行为断言和 review evidence 已记录。

## Design Summary

- `app/quant_sim/candidate_entry_gate.py` 保留统一 discovery 快照完整性门禁和公共门禁，移除旧 source-family 分支。
- `app/quant_sim/technical_entry_score.py` 在评分入口处理 non-ready/stale 快照，返回 zero result 和 blocking reason。
- `tests/test_ai_stock_scanner.py` 为 AI Scanner 注入 fake history provider 并验证稳定排序。
- 生命周期和 API 数据流测试验证缺数据不能通过 source score 或研究来源自动入池。

## API / Data / UI Impact

- API：无新增路径、请求参数或 OpenAPI schema。
- Data：无新增数据库字段或迁移。
- UI：无布局和交互变更；现有 UI 可继续展示候选状态、分数和 blocking reason。

## Security and Permissions

本变更不新增认证、授权、凭据、外部 token 或敏感日志输出。测试使用 fake provider 和临时 SQLite，避免真实环境副作用。

## Operational Notes

- 股票发现候选如果显示 `candidate_score=0.0` 且阻断原因为 `missing_technical_snapshot`，优先检查发现后的行情和技术快照准备链路。
- 如果快照状态为 stale，应重新刷新行情和技术指标，而不是降低阈值或使用来源分兜底。
- AI Scanner 相关测试新增时必须显式提供 history provider 或 fixture。

## Validation Evidence

- `python -m pytest -q tests/test_ai_stock_scanner.py`：`8 passed`。
- 相关 API/生命周期/发现子集：`140 passed`。
- 覆盖率：`app.quant_sim.technical_entry_score` + `app.quant_sim.candidate_entry_gate` 总覆盖率 `90.69%`，达到 `--cov-fail-under=90`。
- 全量后端：`python -m pytest -q`，`807 passed, 1 skipped, 15 warnings`。

## Source Mapping

| Capability | Implementation | Evidence |
|---|---|---|
| 完整快照 ready 门禁 | `app/quant_sim/candidate_entry_gate.py` | `tests/test_discover_market_snapshot.py` |
| stale/non-ready zero result | `app/quant_sim/technical_entry_score.py` | `tests/test_quant_technical_entry_score.py` |
| 来源无关自动入池门禁 | `app/quant_sim/candidate_entry_gate.py` | `tests/test_quant_universe_lifecycle_manager.py` |
| AI Scanner 测试隔离和排序稳定 | `tests/test_ai_stock_scanner.py` | AI Scanner focused pytest |
| API 数据流验证 | `tests/test_ui_backend_api_actions.py`, `tests/test_ui_backend_api_dataflow.py` | FastAPI TestClient focused pytest |
