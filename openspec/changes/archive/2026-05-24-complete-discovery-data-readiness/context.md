# Context: 完整股票发现数据就绪

## Sources Read

- `AGENTS.md`
- `openspec/AGENTS.md`
- `openspec/project.md`
- `docs/ai-context/source-index.md`
- `docs/rules/project-implementation-standards.md`
- `docs/rules/python-code-standards.md`
- `docs/rules/testing-standards.md`
- `docs/rules/configuration-standards.md`
- `docs/standards/backend.md`
- `docs/standards/api.md`
- `docs/standards/testing.md`
- `docs/standards/integration.md`
- `docs/wiki/stock-discovery-technical-snapshot-readiness.md`
- `docs/wiki/stock-discovery-refresh-hydration.md`
- `docs/wiki/discovery-lifecycle-scoring-and-auto-entry-diagnostics.md`
- `docs/wiki/quant-evidence-provenance.md`
- `openspec/changes/audit-data-loop-logic-gaps/specs/quant-evidence-provenance/spec.md`
- `openspec/changes/quant-technical-entry-score/specs/quant-technical-entry/spec.md`
- `openspec/changes/audit-data-loop-logic-gaps/review.md`
- `openspec/changes/quant-technical-entry-score/review.md`
- `app/discover/ai_stock_scanner.py`
- `tests/test_ai_stock_scanner.py`
- `app/discover/market_snapshot.py`
- `app/quant_sim/candidate_entry_gate.py`
- `app/quant_sim/technical_entry_score.py`
- `app/stock_refresh_scheduler.py`
- `app/gateway/quant_universe_entry.py`

## Existing Specs

- `quant-technical-entry-score` 要求 candidate score 只使用行情和技术指标，不使用 source score/source confidence。
- `quant-technical-entry-score` 当前允许 stale 作为 `stale_data_penalty`，这与用户最新要求“没有/过期核心数据不应计算”存在冲突。
- `audit-data-loop-logic-gaps` 要求 discovery prepared evidence 暴露技术快照状态、技术入池分、置信度、门禁结论和刷新状态。
- 已归档 `discover-market-data-snapshot-gate` 定义完整 technical snapshot 字段，并要求缺技术快照阻止自动入池。
- 已归档 `stabilize-discovery-technical-snapshot-flow` 定义发现候选 artifact + runtime hydration 的闭环。

## Existing Code Patterns

- `AIStockScanner.scan()` 调用 `_top_sectors()`、`_sector_stock_rows()`、`_extract_themes()`、`_rank_rows()`。
- `AIStockScanner._rank_rows()` 先按 preliminary score 排序，再为候选计算 technical score，最后按 `scanner_score` 排序。
- `AIStockScanner._history_frame()` 在没有注入 history provider 时会使用 `AkshareLocalClient()` 真实取历史行情，测试失败日志证明单元测试路径发生了外部 IO。
- `app/discover/market_snapshot.py` 使用 `REQUIRED_TECHNICAL_SNAPSHOT_FIELDS` 定义 snapshot ready 字段：price、MA、amount、volume_ratio、RSI、MACD、trend、snapshot_at、provider、timeframe、indicator_version。
- `app/quant_sim/candidate_entry_gate.py` 对 discovery 事件检查 `DISCOVERY_REQUIRED_TECHNICAL_SNAPSHOT_FIELDS`，缺失或 status 非 ready 时阻止。
- `app/quant_sim/technical_entry_score.py` 缺字段时返回 `missing_technical_snapshot` 的 zero result；但 stale 仅作为 `0.10` penalty。
- `app/stock_refresh_scheduler.py` 有 `_has_fresh_technical_snapshot()`，按 `updated_at` 和 `TECHNICAL_SNAPSHOT_TTL_SECONDS` 判断 runtime snapshot 是否新鲜。
- `app/gateway/quant_universe_entry.py` 仍用 `name == code and not industry` 生成 `basic_info_missing`，不代表完整数据快照状态。

## Wiki / Standard Rules Applied

- Wiki 记录了发现候选必须先准备 30m 技术快照，缺字段时阻止自动入池。
- Wiki 记录 raw selector fallback 必须标记 stale/unprepared，不能伪装成 ready。
- Backend/API/Testing/Integration standards 目前是占位文档，未提供额外项目细则。

## Project Rules Applied

- `PIR-001`: 后续设计必须列出受影响代码路径。
- `PIR-002`: 后续实现需要避免继续膨胀 `discover.py`、`technical_entry_score.py` 等文件；必要时提取 readiness 服务。
- `PIR-003` / `CFG-005`: 若新增持久化字段或表，需要明确 SQLite/MySQL runtime 和连接池；brainstorm 阶段不做数据库决策。
- `PIR-004`: 如果 API 字段调整，后续 design/spec 需要明确 OpenAPI 响应字段。
- `PIR-005`: 股票发现和行情准备是外部 IO，应继续通过异步任务执行。
- `PY-005` / `PY-007`: 外部数据源 IO 必须有边界、超时/失败诊断，不能在单元测试中无意触发真实网络。
- `TEST-002` / `TEST-008`: OpenSpec 行为测试应使用显式参数，单元测试必须隔离外部 IO。

## Conflicts

- 用户最新要求：核心行情/技术数据缺失或过期时不应计算。现有 `technical_entry_score.py` 对 stale 仍输出分数，仅扣 `0.10`。
- 用户最新要求：能否入池只看数据完整和技术分达标，不按策略来源放宽/收紧。现有 `candidate_entry_gate.py` 仍保留 source family gate 分支，如 low_price/research/main_force 等。
- 用户最新要求：ready 不能只围绕基础资料，也不能只讨论名称、行业、估值字段。当前 active/archived 文档主要描述 technical snapshot ready，还没有统一 `data_snapshot_ready`。
- 全量测试失败显示 AI Scanner 单元测试触发真实外部行情 IO；这与测试规则 `TEST-008` 冲突。

## Context Gaps

- 完整行情字段清单未最终确定。当前 required technical snapshot 不包括涨跌幅、成交量、换手率、开高低、昨收。
- stale 判断应按自然时间 TTL、交易日 TTL，还是按最近交易 checkpoint 判断，尚未明确。
- 基础资料如总市值/PE/PB 是 ready 的组成部分还是解释性子状态，用户刚才强调不要只看它们，但没有最终说它们是否阻止技术评分。
- UI 字段命名是否保留 `technical_snapshot_status` 以兼容，还是新增 `data_snapshot_status`。
- 是否需要数据库 schema 字段记录新的 readiness 状态，还是继续写 candidate event payload/runtime JSON。

## Design Implications

- 建议后续设计引入独立的 readiness boundary，例如 `DiscoveryDataReadiness` 或 `RequiredSnapshotReadiness`，在评分内核之前执行。
- 技术评分内核应只负责评分，不负责外部 IO、不负责决定 stale 是否可计算。
- `AIStockScanner` 测试应通过 fake history provider 或 fake market client 完全隔离网络。
- 排序应明确 tie-breaker，例如 scanner_score、sector_score、technical_score、原始板块排名、股票代码，以保证稳定。
- Discover API/UI 应显示同一 prepared evidence/readiness 对象，避免页面和生命周期各自解释 ready。
- 后续 spec 必须修改现有 stale penalty 语义，避免与用户要求冲突。
