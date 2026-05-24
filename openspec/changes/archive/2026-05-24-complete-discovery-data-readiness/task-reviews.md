# Task Reviews: 完整股票发现数据就绪

## 任务 1.1 修复 AI Scanner 测试隔离和排序稳定性

### 实施摘要

- 更新 `tests/test_ai_stock_scanner.py`，在 AI Scanner 测试中显式注入 `history_provider=lambda code: pd.DataFrame()`。
- 对相同输入连续运行两次 `scanner.scan()`，断言候选顺序稳定为 `["688111", "000001"]`。
- 未修改生产 AI Scanner 调用链。

### 验证

- `python -m pytest -q tests/test_ai_stock_scanner.py`
  - 结果：`8 passed in 8.50s`
- 覆盖参数文件：`openspec/changes/complete-discovery-data-readiness/test-params/ai-scanner-stable-order.md`

### Alignment Review Round 1

- 检查范围：`spec.md` 的 AI Scanner 外部 IO 隔离与稳定排序场景、`design.md` 的测试策略、`tasks.md` 1.1、`TEST-002/003/008`。
- 结果：通过。
- Findings：无。

### Security Review Round 1

- 检查范围：真实外部 IO、凭据、日志、依赖、配置、网络访问。
- 结果：通过。测试使用 fake provider，不需要真实 token，不输出敏感信息。
- Findings：无。

## 任务 1.2 统一 non-ready/stale 快照门禁和评分行为

### 实施摘要

- 更新 `app/quant_sim/technical_entry_score.py`：当快照显式为 `stale`、`stale_unprepared` 或 ready 标记缺少必要时间时，直接返回 blocking zero result，`candidate_score=0.0` 且 `candidate_confidence=0.0`。
- 更新 `app/quant_sim/candidate_entry_gate.py`：移除按 source family 放宽或收紧的旧门禁，保留统一的 discovery 完整快照门禁、流动性门禁和下跌结构门禁。
- 清理旧 source-family 私有 helper，避免保留不可达分支。
- 更新 scorer/gate/lifecycle 相关断言，确认缺失或 stale 快照不可用来源分替代技术分。

### 验证

- `python -m pytest -q tests/test_quant_technical_entry_score.py tests/test_quant_universe_lifecycle_manager.py::test_low_price_event_uses_source_agnostic_downtrend_gate tests/test_quant_universe_lifecycle_manager.py::test_research_event_uses_source_agnostic_downtrend_gate`
  - 结果：`12 passed`
- `python -m pytest -q tests/test_discover_market_snapshot.py::test_entry_gate_blocks_discovery_score_without_technical_snapshot tests/test_discover_market_snapshot.py::test_entry_gate_allows_complete_discovery_snapshot_to_continue`
  - 结果：`2 passed`
- `python -m pytest -q tests/test_quant_universe_lifecycle_manager.py tests/test_discover_market_snapshot.py tests/test_discover_lifecycle_scoring.py tests/test_discover_refresh_hydration.py`
  - 结果：`118 passed`
- 覆盖参数文件：`openspec/changes/complete-discovery-data-readiness/test-params/non-ready-snapshot-gate.md`

### Alignment Review Round 1

- 检查范围：完整快照 ready 口径、stale 不扣分继续评分、来源无关自动入池门禁、`PIR-001/002`、`PY-001/003/007`、`TEST-001/002/003`。
- 结果：发现 1 个覆盖率证据不足问题。
- Finding A1：初次覆盖率命令只覆盖 85%，低于 90%。

### Fix A1

- 扩大相关测试集并清理已不可达的旧 source-family helper。
- 重新运行覆盖率命令，结果达到 90.69%。

### Alignment Review Round 2

- 检查范围：修复后代码、测试、覆盖率、文件大小。
- 结果：通过。
- Findings：无开放项。

### Security Review Round 1

- 检查范围：输入 payload 解析、错误原因输出、敏感数据、数据库/API/异步影响。
- 结果：通过。变更不新增外部 IO、凭据、权限或日志敏感字段；blocking reason 为机器可读业务状态。
- Findings：无。

## 任务 1.3 验证发现 API E2E 和全量回归

### 实施摘要

- 使用现有 FastAPI `TestClient` 覆盖发现 API 和研究输出进入量化生命周期的数据流。
- 更新 `tests/test_ui_backend_api_dataflow.py` 的研究输出断言：没有完整技术快照的研究输出保持 `inactive`，`candidate_score=0.0`，`candidate_confidence=0.0`，底层阻断原因保留为 `missing_technical_snapshot`。
- 未新增 API 路径、请求参数或 UI 行为。

### 验证

- `python -m pytest -q tests/test_ui_backend_api_actions.py::test_discover_run_strategy_executes_real_selector_runners_and_persists_results tests/test_ui_backend_api_actions.py::test_discover_run_strategy_auto_trial_promotes_discovered_stocks tests/test_ui_backend_api_dataflow.py::test_backend_api_dataflow_from_discover_and_research_to_watchlist_and_quant_pool tests/test_ui_backend_api_dataflow.py::test_backend_api_research_run_module_persists_real_snapshot`
  - 结果：`4 passed in 5.06s`
- `python -m pytest -q tests/test_ai_stock_scanner.py tests/test_quant_technical_entry_score.py tests/test_quant_universe_lifecycle_manager.py tests/test_discover_market_snapshot.py tests/test_discover_lifecycle_scoring.py tests/test_discover_refresh_hydration.py tests/test_ui_backend_api_actions.py::test_discover_run_strategy_executes_real_selector_runners_and_persists_results tests/test_ui_backend_api_actions.py::test_discover_run_strategy_auto_trial_promotes_discovered_stocks tests/test_ui_backend_api_dataflow.py::test_backend_api_dataflow_from_discover_and_research_to_watchlist_and_quant_pool tests/test_ui_backend_api_dataflow.py::test_backend_api_research_run_module_persists_real_snapshot`
  - 结果：`140 passed in 17.35s`
- 覆盖率：`python -m pytest -q ... --cov=app.quant_sim.technical_entry_score --cov=app.quant_sim.candidate_entry_gate --cov-report=term-missing --cov-fail-under=90`
  - 结果：`140 passed`，总覆盖率 `90.69%`，达到 `--cov-fail-under=90`。
- 全量后端：`python -m pytest -q`
  - 结果：`807 passed, 1 skipped, 15 warnings in 138.06s`
- 覆盖参数文件：`openspec/changes/complete-discovery-data-readiness/test-params/discover-api-data-readiness-e2e.md`

### Alignment Review Round 1

- 检查范围：API E2E 真实路由边界、discover/research 数据流、全量后端回归、`PIR-004/005`、`TEST-010`。
- 结果：通过。
- Findings：无。

### Security Review Round 1

- 检查范围：API 输入输出、异步任务边界、fake provider 隔离、数据库测试隔离、敏感数据。
- 结果：通过。E2E 使用临时 SQLite 测试库和 fake provider，不访问生产凭据或共享数据。
- Findings：无。

## 实施标准证据

- 数据库：未新增数据库能力、字段或迁移；测试使用临时 SQLite。
- API：未新增 OpenAPI 路径或请求参数；现有 Controller/Service 分层不变。
- API IO / async：发现 action 保持现有异步任务语义；本变更不新增耗时同步 API。
- 文件长度：
  - `app/quant_sim/candidate_entry_gate.py`: 199 行。
  - `app/quant_sim/technical_entry_score.py`: 479 行。
  - `tests/test_ai_stock_scanner.py`: 241 行。
  - `tests/test_quant_technical_entry_score.py`: 215 行。
  - `tests/test_ui_backend_api_dataflow.py`: 810 行。
  - `tests/test_quant_universe_lifecycle_manager.py`: 2760 行，属于既有大型测试文件；本变更仅为保持现有回归点做窄范围断言更新，未新增新的大型生产文件。后续如单独治理测试结构，应拆分该文件。
- UI/Browser：不适用，本变更未修改 UI 代码或交互。

## 开放 Findings

无。
