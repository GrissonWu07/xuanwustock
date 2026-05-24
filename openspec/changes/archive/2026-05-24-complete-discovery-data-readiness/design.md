# Design: 完整股票发现数据就绪

## Current Behavior

- AI Scanner 的部分单元测试没有注入 history provider，实际运行时会进入默认历史行情获取路径，导致全量测试依赖真实外部行情 IO。
- 技术评分内核缺少核心技术字段时会返回 zero result，但遇到 `technical_snapshot_status=stale` 时仍计算分数，只加 `stale_data_penalty`。
- discovery entry gate 会检查技术快照字段，但还保留按 source family 分支的额外门禁，例如 low_price、research、main_force 等。

## Target Behavior

- AI Scanner 单元测试必须显式注入 fake/fixture history provider，默认单元测试不触发真实 AkShare/TDX 历史行情 IO。
- 数据快照缺失、failed、incomplete、stale 或 stale_unprepared 时，评分内核返回 blocking zero result，不继续扣分评分。
- 自动入池门禁只使用统一数据 ready、流动性/下跌结构公共门禁、技术分和技术置信度阈值，不按发现来源放宽或收紧。

## Architecture Impact

- 不新增服务边界。
- 复用现有 `candidate_entry_gate`、`technical_entry_score` 和 discovery/AI scanner 测试。
- 将 source-family gate 收敛为 source-agnostic common gate。

## Generated Code Paths

- `app/quant_sim/technical_entry_score.py`: stale/non-ready 快照硬阻断。
- `app/quant_sim/candidate_entry_gate.py`: 去除自动入池的 source-family 差异门禁。
- `tests/test_quant_technical_entry_score.py`: 更新 stale 行为断言。
- `tests/test_quant_universe_lifecycle_manager.py`: 更新来源差异门禁断言。
- `tests/test_ai_stock_scanner.py`: 隔离 AI Scanner 默认单元测试外部 history IO，并断言稳定排序。
- `tests/test_discover_market_snapshot.py` 或相关测试：保持 missing snapshot gate 行为。

## Reuse / Common Logic Plan

- 复用 `_discovery_technical_snapshot_gate` 做 discovery 快照字段完整性判断。
- 复用 `_common_gate` 做价格、成交额、下跌结构等来源无关公共门禁。
- 复用 `calculate_technical_entry_score` 作为唯一技术分计算入口。
- 不新增重复 readiness 解析逻辑；stale/non-ready 先在 scoring 内核入口统一返回 zero result。

## Requirement Scope / Compatibility / Fallback

- 不保留按 source family 放宽或收紧自动入池的兼容分支。
- 不用 source score/source confidence 作为 candidate score fallback。
- 不把基础资料字段加入技术评分内核输入。
- 不扩大完整行情字段集合；本变更使用现有核心快照字段集。

## Method / Function Parameter Plan

- 不新增超过 5 个参数的函数。
- 不新增宽泛 dict 参数作为新公共接口。
- 现有事件 payload 仍是已存在的业务数据载体，不在本变更扩大其 schema。

## File Size / Split Plan

- 预计修改文件均小于 1000 行。
- 不修改大型 `discover.py` 或 `replay_service.py`。
- 若测试文件超过 1000 行，不在本变更修改该文件；当前目标测试文件均低于限制。

## Data Impact

- 不新增数据库字段。
- 不迁移历史数据。
- candidate event payload 中已有 readiness/status 字段继续作为可观察诊断。

## Database Decision

本变更不需要新增数据库能力。现有 SQLite/MySQL runtime 和连接池保持不变。

## Backend Logic Confirmation

已确认。用户在 2026-05-24 触发 `sp-goal` 继续 workflow；结合前置讨论，确认后端逻辑为：

- 核心行情/技术数据缺失或 stale 不计算；
- 自动入池不按策略来源改变门禁；
- AI Scanner 测试必须隔离真实行情 IO。

## API Impact

不新增 API，不修改 API 路径或请求参数。现有发现 API 返回的 readiness/blocking reason 语义会更严格。

## OpenAPI / Backend Layering

- Controller：现有 `app/gateway_api.py` 发现 API 不变。
- Service/Domain：`candidate_entry_gate` 和 `technical_entry_score` 承担业务门禁与评分。
- OpenAPI 变化：无新增路径；响应语义为兼容性收紧。

## API Path / Parameter Confirmation

已确认不新增或修改 API 路径/参数。

确认依据：用户触发 `sp-goal` 继续当前 OpenSpec 变更；本设计明确 API path/parameters 为不适用。

## UI Impact

不新增 UI 组件。现有 UI 继续展示 readiness 和 blocking reason。

## UI Mockup / Functional Description

不适用。无 UI 布局或交互变更。

## Configuration Parameter Confirmation

不适用。无新增配置参数。

## Integration Impact

- 单元测试路径不得触发真实外部行情 IO。
- 生产 AI Scanner 默认仍可使用现有 market client/fallback 数据路径。

## Security Impact

- 不新增权限、认证、密钥或外部凭据。
- 日志仍只暴露股票代码和安全错误摘要。

## Error Handling

- non-ready 快照返回 machine-readable blocking reason。
- AI Scanner 测试使用 fake provider 明确表达技术数据是否可用。

## Compatibility / Migration

不迁移旧数据。旧候选如果只有 source score 或 stale 快照，将更明确地显示为不可评分/不可自动入池。

## Test Strategy

- 单元测试：AI Scanner 稳定排序和外部 IO 隔离。
- 单元测试：stale/non-ready 快照返回 zero result。
- 单元测试：不同来源相同快照门禁一致。
- API 测试：发现任务/候选事件不会把 source score 替代技术分。
- 全量后端测试：关闭当前 AI Scanner 失败。

## Standalone Verification Plan

- `python -m pytest -q tests/test_ai_stock_scanner.py tests/test_quant_technical_entry_score.py tests/test_quant_universe_lifecycle_manager.py tests/test_discover_market_snapshot.py`
- `python -m pytest -q`

## Real E2E Test Design

需要真实 API E2E。设计：

- 使用项目支持的 FastAPI `TestClient` 或临时 uvicorn 后端。
- 触发 `POST /api/v1/discover/actions/run-strategy`，使用测试 fake selector/market data 边界。
- 读取 `GET /api/v1/tasks/{task_id}` 和 `GET /api/v1/discover`。
- 断言缺失/non-ready 候选不产生有效 `candidate_score`，ready 候选可继续评分。

确认依据：用户触发 `sp-goal`，要求完成从当前 phase 到 completion 的 workflow。

## Multi-Lens Planning Review

- Product：发现成功必须可信，不能用不完整数据伪装 ready。
- Design：不新增 UI，避免扩大视觉范围。
- Engineering：评分内核保持纯技术评分；门禁前置数据完整性。
- DevEx：AI Scanner 测试不再依赖真实网络，降低全量测试波动。
- Security：不新增敏感数据输出。
- QA：覆盖缺失、stale、来源一致性和全量回归。

## Browser / UI QA Plan

不适用。无 UI 代码或布局变更；前端现有测试不需要因本变更修改。

## Project Learning Candidates

- AI/外部数据类单元测试必须显式注入 fake provider，不能依赖默认真实数据源。
- 数据快照 ready 是门禁，不是评分降权项。

## Customer Confirmation

- Brainstorm：已由用户 2026-05-24 触发 `sp-goal` 确认。
- Backend logic：已确认，见上。
- API path/parameters：不新增或修改，已记录为不适用。
- UI mockup/function：无 UI 变更，不适用。
- Configuration：无新增配置，不适用。
- E2E：需要真实 API E2E，已记录。

## Rules Compliance

- `PIR-001`: 设计列出代码路径。
- `PIR-002`: 修改目标文件预计低于 1000 行。
- `PIR-003`: 无新增数据库。
- `PIR-004`: 无新增 API，响应语义收紧。
- `PIR-005`: 真实发现仍是异步任务。
- `PY-005`, `PY-007`: 外部 IO 显式隔离并诊断。
- `TEST-001`, `TEST-002`, `TEST-003`, `TEST-008`: 测试使用显式参数、有效断言和外部 IO 隔离。

## Source Mapping

| Design Decision | Source | Reason |
|---|---|---|
| non-ready/stale 快照不评分 | 用户最新口径、`context.md` conflicts | 用户明确否定降权继续评分 |
| 自动入池来源无关 | 用户最新口径、`spec.md` | 用户明确入池只看数据完整和技术分 |
| AI Scanner 单测隔离外部 IO | 全量 pytest 失败、`TEST-008` | 当前失败由真实行情回源导致 |
| 不新增 API | `proposal.md` scope | 行为可在现有发现 API 观察 |

## Spec Gaps

无阻塞 spec gap。本变更暂不定义更宽的行情字段集合；后续可单独扩展。
