# Market Technical Artifact Design

## Current Behavior

行情和技术指标当前分散在多个位置：

- `stock_universe.latest_price` 和 `metadata_json` 保存最新值和股票池状态。
- `stock_runtime_snapshot` 通过 selector result store 保存实时刷新后的 latest runtime entries。
- `prepare_discovery_market_snapshot()` 生成发现入池用 30m 技术快照。
- discovery candidate artifact 和 `stock_universe_candidate_events.payload_json` 可能携带完整技术字段。
- signal `strategy_profile.market_snapshot` 保存信号生成时传入的行情快照。
- replay/drill snapshot provider 按 checkpoint 临时提供历史 snapshot。
- `LocalMarketDataStore` 是 provider 数据的 parquet local-first cache。

缺少统一、可引用、可隔离的 checkpoint 事实层。

## Target Behavior

新增统一 `market_technical_artifact` 语义：

- live、replay、drill 使用同一字段 schema。
- live 与 run 数据物理隔离。
- candidate entry 和 signal generation 通过 `artifact_ref` 引用事实层。
- runtime snapshot、candidate payload、signal market_snapshot 只能保存 `artifact_ref` 和轻量诊断；完整技术字段从 artifact reader 查询。
- replay/drill 禁止 fallback 到 live latest。

`quant-technical-entry-score` 的 prepared discovery persistence 语义同步调整：prepared candidate record 不再以 payload 内完整技术字段作为权威技术事实，而是保存 `artifact_ref` 和轻量诊断；完整技术事实通过 artifact reader 读取。

统一流程约束：

| Flow | Role | Required Artifact Domain | Allowed Data Use | Forbidden Bypass |
|---|---|---|---|---|
| 实时刷新 | producer | `live` | provider/local cache -> normalize -> write live artifact；runtime snapshot 从 artifact 派生 | 刷新后只写 runtime snapshot 而不写 artifact |
| 实时量化 | consumer | `live` | artifact reader -> lifecycle/signal/execution diagnostics | 直接读取 runtime snapshot、candidate payload、provider cache 或临时远程行情作为决策事实 |
| 工作台 / 发现股票 / 研究 / 实时量化页面 | consumer | `live` | live artifact 或 artifact 派生投影 -> 页面 API | 页面 API 各自直接读取 runtime snapshot、candidate payload 或 provider cache 作为权威行情技术事实 |
| 实时量化演练 | producer + consumer | `drill` | checkpoint provider -> run-scoped artifact -> 同一套实时量化生命周期/信号逻辑 | fallback 到 live artifact/runtime snapshot |
| 历史回放 | producer + consumer | `replay` | replay snapshot provider -> run-scoped artifact -> 回放信号/交易/诊断 | fallback 到 live artifact/runtime snapshot/current provider cache |

实现时应把 artifact reader 作为所有决策入口的公共依赖；旧数据源只能作为 artifact producer 的输入或 UI 派生缓存。

## Architecture Impact

新增 focused service 边界：

- `MarketTechnicalArtifactRef`：artifact 身份对象。
- `MarketTechnicalArtifactData`：artifact 数据对象。
- `MarketTechnicalArtifactService`：writer/reader/normalizer。
- live writer：实时刷新写 live artifact。
- run writer：replay/drill checkpoint 写 run artifact。
- reader：candidate、signal、diagnostic 按 ref 读取 artifact。

## Generated Code Paths

建议新增：

- `app/quant_sim/market_technical_artifact.py`
- `tests/test_market_technical_artifact.py`

建议修改：

- `app/stock_refresh_scheduler.py`
- `app/discover/market_snapshot.py`
- `app/discover/candidate_artifact.py`
- `app/quant_sim/db.py`
- `app/quant_sim/quant_universe_lifecycle.py`
- `app/quant_sim/engine.py`
- `app/quant_sim/replay_service.py`
- signal detail / gateway diagnostics modules
- workbench, discover, research, and live quant gateway modules that hydrate current market/technical display data

## Reuse / Common Logic Plan

- 复用 `prepare_discovery_market_snapshot()` 的指标准备能力，但其输出不再作为权威 payload，而是写 artifact 并返回 `artifact_ref`。
- 复用 replay/drill snapshot provider 的历史数据获取能力，但将结果落为 run-scoped artifact。
- 复用 `LocalMarketDataStore` 作为 provider cache，不把它提升为 artifact。
- 复用现有 `market_snapshot` dict 字段名作为 artifact schema 的输入来源，避免重复指标计算。
- 实时量化、实时量化演练和历史回放 SHALL 复用同一个 artifact reader 接口，只通过 domain/run 参数切换数据域，不复制三套行情技术读取逻辑。
- 工作台、发现股票、研究、实时量化页面 SHALL 复用 live artifact reader 或 artifact-derived projection，不能各自直接读取旧 runtime snapshot/cache 作为权威事实源。

## Requirement Scope / Compatibility / Fallback

本 change 不要求兼容旧记录的完整复算。

旧 candidate/signal/replay 记录没有 `artifact_ref` 时：

- 诊断显示 `missing_artifact_reference`。
- 不得静默使用当前行情回填。

不添加未要求的 fallback 或兼容分支。replay/drill 缺 artifact 时返回缺失原因，不 fallback live latest。

## Method / Function Parameter Plan

禁止新增超过 5 个输入参数的方法。

使用命名数据对象：

- `MarketTechnicalArtifactRef`
- `MarketTechnicalArtifactData`
- `ArtifactWriteRequest`
- `ArtifactQuery`

## Code Comments / Logging / Traceability Plan

需要注释：

- `checkpoint_at` 与 `computed_at` 区别。
- `data_version` 与 `indicator_version` 区别。
- replay/drill 禁止 live fallback 的原因。

日志事件：

- artifact write success/failure
- artifact missing
- artifact read by candidate/signal/replay
- legacy source converted to artifact_ref

日志字段：

- `trace_id`
- `artifact_domain`
- `run_id`
- `run_type`
- `stock_code`
- `market`
- `checkpoint_at`
- `timeframe`
- `data_version`
- `source_status`
- `missing_fields`

不得记录凭证、token、原始敏感请求/响应。

## Encoding / No-Mojibake Plan

新增中文 reason、诊断字段说明和测试数据必须使用 UTF-8。

验证：

- 文档中文可读。
- JSON payload 使用 `ensure_ascii=False` 但保持 UTF-8。
- UI/API reason code 使用 ASCII 稳定码，展示文案走 i18n。

## File Size / Split Plan

新增 `market_technical_artifact.py` 必须低于 1000 行。

如果 `app/quant_sim/db.py` 修改过大，实施阶段应优先将 SQL/row mapping 收敛到小方法，避免继续扩大大文件复杂度。

## Data Impact

逻辑字段：

- identity：artifact_ref、domain、run_id、run_type、stock_code、market、checkpoint_at、timeframe、data_version
- market：open、high、low、close、latest_price、prev_close、volume、amount、turnover_rate、volume_ratio
- moving averages：ma5、ma10、ma20、ma60、ma20_slope
- momentum：rsi、macd、macd_signal、macd_histogram
- structure：trend、price_vs_ma20、price_vs_ma60、ma_stack、above_ma20_checkpoints、retest_confirmed
- tradability：is_suspended、is_limit_up、is_limit_down、liquidity_ready
- quality：provider、indicator_version、source_status、missing_fields、computed_at

持久化字段分层：

- identity / 查询列：`artifact_ref`、`artifact_domain`、`run_id`、`run_type`、`stock_code`、`market`、`checkpoint_at`、`timeframe`、`data_version`
- 状态 / 诊断列：`provider`、`indicator_version`、`source_status`、`reason_code`、`computed_at`
- 高频筛选列：`latest_price`、`close`、`ma20`、`ma20_slope`、`rsi`、`macd`、`volume_ratio`、`is_suspended`、`is_limit_up`、`is_limit_down`、`liquidity_ready`
- JSON 字段：`market_json` 保存 open/high/low/prev_close/volume/amount/turnover_rate 等完整行情；`indicator_json` 保存 ma5/ma10/ma60/macd_signal/macd_histogram 等完整指标；`structure_json` 保存 trend/price_vs_ma20/price_vs_ma60/ma_stack/above_ma20_checkpoints/retest_confirmed；`quality_json` 保存 missing_fields 和 provider diagnostics

外部 API SHALL 返回 spec 要求的完整字段集合；实现可从列和 JSON 组合响应。新增指标优先进入 JSON，只有进入查询、排序、过滤或高频诊断路径的字段才提升为独立 column。

版本与时间语义：

- `checkpoint_at`：artifact 对应的市场/回放 checkpoint 时间，是事实有效时间。
- `computed_at`：系统生成或写入 artifact 的 UTC 时间，不得用于替代 checkpoint 时间。
- `data_version`：artifact schema/数据版本，默认建议 `mta_v1`。
- `indicator_version`：技术指标算法版本，默认沿用现有 indicator version；若缺失则写入明确缺失状态。

`artifact_ref` 序列化：

```text
mta:v1|domain={domain}|run_id={run_id}|run_type={run_type}|market={market}|stock_code={stock_code}|checkpoint_at={checkpoint_at_utc}|timeframe={timeframe}|data_version={data_version}
```

- `domain`：`live`、`replay`、`drill`
- live artifact 的 `run_id` 和 `run_type` 在 `artifact_ref` 中固定为 `live`，DB identity 中不参与 live 唯一约束
- replay/drill artifact 的 `run_id` 和 `run_type` 必须来自对应 run
- `checkpoint_at_utc`：UTC ISO-8601 Z 格式，例如 `2026-01-05T02:00:00Z`
- 各字段值在 path/query 传输时必须 URL-safe 编码；解析时按 `|` 分段、按 `key=value` 读取，不允许依赖字段顺序之外的猜测

实现可在 DB 内使用自增主键，但对外和跨表引用必须使用稳定 `artifact_ref`。`artifact_ref` 解析失败时返回 `invalid_artifact_ref`。

## Database Decision

需要数据库。

开发阶段本地行为使用 SQLite。实现/部署阶段目标为 MySQL。连接池最大 size 不超过 100。

建议物理隔离：

- live DB：`market_technical_artifacts`
- replay DB：`sim_run_market_technical_artifacts`

两个表共享字段 schema。replay/drill 表额外强制 `run_id`、`run_type`。

字段布局采用“关键列 + JSON 扩展”：

- 必须列化：identity、状态、时间版本、常用过滤和核心指标字段。
- 必须 JSON 化：低频指标、结构细节、缺失字段列表、provider 诊断细节。
- 不允许把所有指标无差别展开为 column。
- 不允许只保存 JSON 而缺少 identity/status/index 所需列。

唯一约束：

- live：`artifact_domain, stock_code, market, checkpoint_at, timeframe, data_version`
- run：`artifact_domain, run_id, run_type, stock_code, market, checkpoint_at, timeframe, data_version`

`artifact_ref` 必须唯一。

## Backend Logic Confirmation

用户已确认（2026-05-27）：

- 本 change 只建立统一行情技术 artifact，不改交易策略。
- live/replay/drill 数据隔离。
- replay/drill 缺 artifact 不 fallback live latest。
- 实时刷新、实时量化、实时量化演练和历史回放都必须基于 artifact writer/reader；runtime snapshot/provider cache 不能作为决策事实绕过 artifact。
- 工作台、发现股票、研究、实时量化页面展示 live 行情技术口径时，也必须基于 live artifact 或 artifact 派生投影。
- candidate/signal 保存 `artifact_ref`，完整指标从 artifact 查。
- `stock_runtime_snapshot` 只作为 live artifact 派生 export。
- `quant-technical-entry-score` 的 prepared candidate record 改为 artifact_ref 权威，不再让 payload 完整技术字段作为权威事实。

## API Impact

采用新增内部诊断 API，并扩展现有 signal/replay/live diagnostics。

新增 API：

| Method | Path | Query / Body | Purpose |
|---|---|---|---|
| GET | `/api/v1/quant/market-technical-artifacts/{artifact_ref}` | path: URL-encoded `artifact_ref` | 查询单个 artifact 诊断 |
| GET | `/api/v1/quant/market-technical-artifacts` | query: `domain`, `stock_code`, `market`, `checkpoint_at`, `timeframe`, `data_version`; 当 `domain=replay` 或 `domain=drill` 时额外必填 `run_id`, `run_type`; 当 `domain=live` 时不得传 `run_id`, `run_type` | 按完整 identity key 查询 artifact |

扩展响应：

- signal detail 返回 `artifact_ref`、artifact status、missing reason。
- replay/drill diagnostics 返回 run artifact status。

artifact API 响应至少包含：

- `artifact_ref`
- `domain`
- `run_id`
- `run_type`
- `stock_code`
- `market`
- `checkpoint_at`
- `timeframe`
- `data_version`
- `indicator_version`
- `source_status`
- `reason_code`
- `missing_fields`
- artifact 字段集合

## OpenAPI / Backend Layering

Controller：

- 只负责参数校验和响应映射。

Service：

- artifact ref 解析。
- artifact 查询。
- artifact 写入。
- missing reason 生成。

Repository/DB：

- 表读写、唯一约束、幂等 upsert。

长耗时操作：

- artifact 生成跟随现有 refresh/replay/drill job，不在 API 请求线程里批量生成。

## API Path / Parameter Confirmation

用户已确认（2026-05-27）：

- 新增 `GET /api/v1/quant/market-technical-artifacts/{artifact_ref}`，path 参数为 URL-encoded `artifact_ref`。
- 新增 `GET /api/v1/quant/market-technical-artifacts`，live 查询必填 `domain, stock_code, market, checkpoint_at, timeframe, data_version`，run 查询额外必填 `run_id, run_type`。
- 扩展现有 signal/replay/live diagnostics 返回 `artifact_ref`、`source_status`、`reason_code`、`missing_fields`。

## UI Impact

无新增完整页面。

现有 UI 只需在信号详情、回放/演练诊断、候选入池诊断中展示最小字段：

- `artifact_ref`
- domain
- run_id/run_type
- checkpoint_at
- timeframe
- source_status
- missing reason

工作台、发现股票、研究、实时量化页面的 live 行情/技术显示数据应从 live artifact 或 artifact-derived projection 取得。页面无需展示完整 artifact，但关键诊断入口需要能追踪到 `artifact_ref`。

## UI Mockup / Functional Description

不需要独立 mockup。功能描述：

- 在已有详情/诊断区域增加一行“行情技术数据引用”。
- 缺失时显示明确原因，例如 `missing_artifact_reference` 或 `missing_artifact`。
- 不展示完整指标列表，避免页面膨胀。

用户已确认（2026-05-27）：本 change 不做新页面，只做现有诊断增强。

## Configuration Parameter Confirmation

本 change 不新增策略配置参数。

固定枚举常量：

- artifact domain 枚举：`live`, `replay`, `drill`
- run_type 枚举：`historical_replay`, `live_quant_drill`
- source_status：`ready`, `partial`, `missing`, `source_failed`, `stale`, `invalid`
- reason_code：`ok`, `missing_artifact`, `missing_artifact_reference`, `incomplete_artifact`, `source_failed`, `run_scope_required`, `invalid_artifact_ref`, `stale_artifact`, `field_missing`, `source_status_not_ready`

状态分工：

| Field | Meaning | Example |
|---|---|---|
| `source_status` | artifact 自身的数据质量状态 | `ready`, `partial`, `stale` |
| `reason_code` | 本次请求、诊断或决策使用 artifact 时的结果原因 | `ok`, `missing_artifact`, `run_scope_required` |

用户已确认（2026-05-27）：不引入可调配置，仅使用固定枚举。

## Integration Impact

- 与 `signal-outcome-scoring`：后者依赖 artifact_ref。
- 与 `quant-technical-entry-score`：candidate score 继续纯技术，技术事实改由 artifact 提供。
- 与 provider cache：`LocalMarketDataStore` 保持 provider cache 角色。
- 与实时量化演练：演练继续复用实时量化生命周期和信号逻辑，但行情技术事实来源切换为 drill run-scoped artifact。
- 与历史回放：回放信号和交易诊断统一引用 replay run-scoped artifact。

## Security Impact

artifact 不应包含凭证、token、账户信息。

API 查询只暴露行情技术事实和诊断，不暴露内部路径、provider 密钥或原始敏感响应。

## Error Handling

- artifact 缺失：`missing_artifact`
- artifact ref 缺失：`missing_artifact_reference`
- artifact ref 无法解析：`invalid_artifact_ref`
- 字段不完整：`incomplete_artifact`
- 数据源失败：`source_failed`
- artifact 过期：`stale_artifact`
- replay/drill 试图使用 live latest：应阻断并记录 `run_scope_required`

## Compatibility / Migration

不做旧数据静默迁移。

旧记录无 `artifact_ref` 时只展示缺失引用。

项目当前仍处于未上线/可重建阶段，但本设计不依赖自动兼容旧数据。

## Test Strategy

测试覆盖：

- live artifact write/read。
- live refresh 写 artifact 后 runtime snapshot 仅派生展示。
- live quant lifecycle/signal 通过 live artifact reader 获取事实。
- replay/drill run-scoped artifact write/read。
- drill 复用 live quant 逻辑但读取 drill artifact。
- history replay 读取 replay artifact。
- replay/drill 不 fallback live latest。
- candidate/signal diagnostics 包含 artifact_ref。
- 缺失 artifact 输出明确 reason。
- source score/confidence 不进入 artifact。
- multi_source_bonus 不进入 artifact。
- artifact_ref serialization/parse。
- `checkpoint_at`、`computed_at`、`data_version`、`indicator_version` 语义验证。
- reason_code/source_status 枚举输出。
- runtime snapshot 单向派生。

## Project-Code Test Boundary

测试聚焦项目代码：

- artifact ref 构造和解析。
- artifact upsert/read/missing behavior。
- adapter 从现有 snapshot 转为 artifact。
- candidate/signal/replay 消费 artifact_ref。

不测试第三方行情 provider 正确性。

## Standalone Verification Plan

建议命令：

- `python -m pytest -q tests/test_market_technical_artifact.py`
- 运行本地服务后调用 artifact 查询 API。
- 触发一次 live refresh，验证 artifact 写入和诊断响应。
- 访问工作台、发现股票、研究、实时量化页面对应 API，验证 live 行情/技术数据能追踪到 live artifact。
- 触发一个短 replay/drill run，验证 run-scoped artifact 写入且不读 live latest。

## Real E2E Test Design

建议需要真实 E2E，因为该能力改变 job/API 可观察行为。

E2E 路径：

1. 启动后端。
2. 触发 live refresh 指定股票。
3. 调用 `GET /api/v1/quant/market-technical-artifacts?domain=live&stock_code=<code>&market=<market>&checkpoint_at=<utc>&timeframe=<tf>&data_version=<version>`。
4. 触发短历史回放或实时量化演练。
5. 调用 `GET /api/v1/quant/market-technical-artifacts?domain=<replay|drill>&run_id=<run_id>&run_type=<run_type>&stock_code=<code>&market=<market>&checkpoint_at=<utc>&timeframe=<tf>&data_version=<version>` 查询 run-scoped artifact。
6. 调用 `GET /api/v1/quant/market-technical-artifacts/{artifact_ref}` 验证 artifact_ref 可解析并返回同一 artifact。
7. 验证 signal/candidate diagnostics 包含 artifact_ref、source_status、reason_code。
8. 调用工作台、发现股票、研究、实时量化页面 API，验证 live 行情/技术数据可以追踪到 live artifact 或 artifact-derived projection。
9. 构造缺失 run artifact 或缺少 run_id/run_type 的查询，验证返回 `run_scope_required` 或 `missing_artifact`，且不 fallback live latest。

用户已确认（2026-05-27）：E2E required。

## Multi-Lens Planning Review

Product：

- 解决量化数据口径混乱和可解释性问题。

Design：

- 不新增大 UI，只增强诊断。

Engineering：

- 聚焦事实层，不混入评分和交易。

Developer Experience：

- 后续 score 可统一引用 artifact。

Security：

- 不暴露敏感 provider 信息。

QA：

- 重点验证隔离、防 fallback、缺失诊断。

## Browser / UI QA Plan

若 UI 展示 artifact_ref：

- 在 signal detail 或 replay/drill 诊断页面查看 artifact_ref。
- 验证缺失时显示明确 reason。
- 在工作台、发现股票、研究、实时量化页面验证 live 行情/技术数据能追踪到 live artifact，且页面不因旧 runtime snapshot 缺失而绕过 artifact 读取 provider cache。

不需要截图 mockup。

## Project Learning Candidates

可形成项目经验：

- 决策事实层与评分层分离。
- live/replay/drill 使用同一 schema 但隔离存储。

## Customer Confirmation

用户已确认（2026-05-27）：

- backend logic package。
- API 路径和参数：新增两个 artifact 查询 API，并扩展现有 diagnostics。
- 无独立 UI mockup，仅诊断增强。
- 工作台、发现股票、研究、实时量化页面的 live 行情/技术展示必须基于 live artifact 或 artifact 派生投影。
- 无新可调配置，仅固定枚举。
- DB 落表采用关键字段 column + 指标/结构/质量 JSON 扩展，不要求每个指标都是 column。
- E2E required。

## Rules Compliance

- 遵守 OpenSpec 阶段。
- 遵守 DB 决策要求。
- 遵守 UTF-8/no mojibake。
- 遵守测试和 E2E 决策要求。
- 遵守不写代码、不创建 tasks 的 `/sp-spec` 边界。

## Source Mapping

| Design Decision | Source | Reason |
|---|---|---|
| 拆出独立 artifact change | 用户确认与 brainstorm review | 避免 signal outcome scope 过大 |
| artifact 是事实层不是评分层 | 用户需求、quant-technical-entry-score | 防止 source score 污染 |
| live/replay/drill 隔离 | 用户长期要求、现有 replay 隔离设计 | 防未来函数和数据污染 |
| score 表只引用 artifact | 用户明确要求 | 避免 MA/RSI/MACD 重复存储 |
| provider cache 不等于 artifact | 现有 LocalMarketDataStore | 区分远程缓存和决策事实 |

## Spec Gaps

无 blocking spec gap。

需要用户在确认包里确认：

- 已确认新增 artifact 查询 API 的路径和参数。
- 已确认 E2E required 决策。
