# 股票池与统一数据刷新架构设计

Date: 2026-05-08
Status: Implemented baseline; refresh-service consolidation ongoing

Supersedes:

1. `docs/股票数据流说明.md`
2. `docs/superpowers/specs/2026-05-04-portfolio-diagnosis-live-sim-boundary-design.md`

## 当前实现快照

截至 `2026-05-08`，以下内容已经在代码中落地：

1. 统一股票池主表已经切到 `xuanwu_stock.db.stock_universe`。
2. 工作台股票列表已经读取 `watched OR quant_enabled OR registered_position_enabled` 的统一股票池视图，而不是只读 `watched=1`。
3. `WatchlistService` 物理上已经不再使用 `watchlist.db`，而是直接操作 `stock_universe`。
4. `CandidatePoolService` 仍保留兼容命名，但底层已经是 `stock_universe.quant_enabled` 视图。
5. 手工录入股票时，`basic_info_missing` 会同步写入专用列。
6. live-sim 调度默认间隔已经是 `10` 分钟。
7. 实时刷新链路已经对 fresh runtime entry 做 local-first 命中，并对失败股票做冷却跳过。
8. 历史回放已经使用独立 `xuanwu_stock_replay.db`，并在准备阶段走 local-first 历史 K 线/指标复用。

以下内容仍处于“目标态先行、实现逐步收敛”：

1. `StockDataRefreshService` 仍未完全抽成单一统一服务对象，部分刷新逻辑还分布在现有 scheduler 和 provider 适配层里。
2. `portfolio refresh-indicators` 仍保留旧动作名，尚未完全拆成更清晰的数据域动作。
3. 发现股票和研究情报结果仍先写 `selector_results/*.json`，再由用户推进到统一股票池。

## 背景

当前系统里股票对象、行情刷新、技术指标刷新、AI 分析刷新分散在关注池、候选池、持仓诊断、实时模拟、历史回放和多个页面 action 中。结果是同一批股票可能被多个入口反复刷新，尤其是北交所 `920xxx` 这类数据源不稳定的股票，会出现 TDX 超时后反复 fallback 到 Akshare 的情况，拖慢历史回放和实时页面。

本设计把股票池作为核心数据入口，把刷新职责从页面和任务中剥离出来，统一到按数据域编排的刷新服务中。

## 总目标

1. 股票池是系统核心标的集合。持仓诊断、实时量化、历史回放都只能从股票池筛选自己的工作范围。
2. 股票成员关系和数据刷新分离。加入股票池、加入量化、登记持仓不应自动触发全量远程刷新。
3. 实时数据刷新统一编排，按数据域区分行情技术、基础信息、资金流情绪、财务基本面、AI 分析、公司行为和交易规则。
4. 所有远程数据访问必须遵守 local-first：先查本地缓存，缓存满足覆盖范围或 TTL 时直接返回；只有缺口、过期或显式强制刷新时才远程。
5. 历史回放获取历史检查点数据使用独立流程，但仍必须走 local-first 和按缺口远程补齐，不能直接拉实时行情、基础信息或 AI 分析。
6. 清理老刷新任务和旁路调用。页面、scheduler、回放、实时模拟不得直接调用 Akshare、TDX、Tushare。

## 非目标

1. 不合并持仓诊断、实时量化、历史回放三个页面。
2. 不重写已完成的买入分层、组合防守、个股执行反馈、止盈保护、资金槽算法。
3. 不删除历史 spec；已完成 spec 继续作为历史设计记录。
4. 不保留新的独立量化池数据库或持仓池数据库；目标物理模型必须统一到股票池。

## 核心概念

### 股票池

股票池是系统唯一的标的主集合，按股票代码去重。目标物理模型必须提供统一股票池主表，暂称 `stock_universe`，并以股票代码作为唯一主键。

不再允许新代码读取或写入以下表作为股票主数据、量化范围或登记持仓来源：

1. `quant_sim.db.candidate_pool`
2. `portfolio_stocks.db.portfolio_stocks`
3. 独立的“量化池”数据库或“持仓池”数据库

这些旧表不属于目标架构。实现本 spec 时不写兼容层、不做 fallback、不做双写。部署采用重置式切换：创建统一股票池后，实时量化、历史回放、持仓诊断都只从统一股票池读取股票范围。

统一股票池主表必须保存：

1. 股票代码、名称、市场、交易所、行业、板块等基础字段。
2. 用途标签，例如 `watched`、`quant_enabled`、`registered_position_enabled`。
3. 登记持仓所需的用户持仓字段，或通过 `stock_universe_position_profile` 这类统一股票池附属表保存。
4. 最近缓存状态摘要，例如行情技术更新时间、AI 分析更新时间、基础信息更新时间。

### 用途标签

每只股票可以有多个用途标签：

1. `watched`：关注股票，表示用户持续跟踪。
2. `quant_enabled`：量化股票，允许被实时量化和历史回放扫描。
3. `registered_position_enabled`：登记持仓股票，用于持仓诊断。
4. `live_position`：实时模拟账户当前持仓，只作为 live-sim 账户状态派生标签，不作为股票主数据。
5. `replay_position`：某个历史回放任务内的持仓快照，只在指定 run 上下文有效，不作为股票主数据。

### 三个业务面

1. 持仓诊断从股票池筛选 `registered_position_enabled`、`watched`、`live_position` 和必要的 `quant_enabled` 股票，形成诊断列表。
2. 实时量化从股票池筛选 `quant_enabled=true` 的股票，称为“实时量化股票”。
3. 历史回放默认从股票池筛选 `quant_enabled=true` 的股票，启动时冻结为该任务的“回放股票范围”。
4. 历史回放允许在 `quant_enabled=true` 范围内做任务级 `include_symbols` / `exclude_symbols` 筛选；不得引入股票池外或 `quant_enabled=false` 的股票。
5. 历史回放冻结时必须保存任务筛选条件和最终 symbol 列表，用于复现和排查。

底层账户、仓位、成交、信号必须隔离：

1. 登记持仓不写 live-sim 持仓。
2. live-sim 不写 replay 表。
3. his-replay 不写 live-sim 状态表。
4. replay 的股票范围在任务开始时冻结，任务运行中股票池变化不影响当前 run。

## 数据库边界

目标数据库边界：

1. 股票主数据只存在于统一股票池。
2. 量化股票不再有独立候选池表；`quant_enabled=true` 就是量化股票范围。
3. 登记持仓不再有独立持仓池主表；登记持仓是统一股票池上的用途标签和持仓档案。
4. live-sim 继续保留独立账户状态表，例如 `sim_positions`、`sim_trades`、`sim_account`、`strategy_signals`，但这些表不能定义股票池范围。
5. his-replay 继续保留独立任务结果表，例如 `sim_run_positions`、`sim_run_trades`、`sim_run_signals`，但这些表只保存 run 结果，不能定义股票池范围。

部署重置要求：

1. 不迁移旧 `candidate_pool`、`portfolio_stocks`、`watchlist` 数据。
2. 不保留兼容读、兼容写、fallback 或双写逻辑。
3. 部署时删除旧量化池和旧持仓池主表。
4. 新版本启动后只创建和使用统一股票池及其附属表。
5. 需要保留的股票范围由用户重新导入、手工添加，或由发现/研究流程重新写入统一股票池。

部署清库要求：

1. 部署新版本前必须停止服务，避免旧进程继续写旧表。
2. 删除或重置旧 `quant_sim.db` 中的股票范围相关表：`candidate_pool`、`candidate_sources`，以及任何只用于旧量化池成员关系的表。
3. 删除或重置旧 `portfolio_stocks.db`，不再作为持仓池数据库使用。
4. 删除或重置旧 `watchlist.db`，不再作为关注池/股票池数据库使用。
5. 保留 live-sim 账户状态库和 replay 结果库的策略由部署任务显式决定；如果本次部署要求干净环境，则同步删除 `sim_positions`、`sim_trades`、`strategy_signals` 和 `xuanwu_stock_replay.db`。
6. 清库完成后启动新版本，由新版本初始化统一股票池主表和附属表。
7. 清库步骤必须写入部署脚本或部署 runbook，不能依赖人工临时 SQL。
8. 当前部署脚本为 `python scripts/reset_stock_universe_deployment.py --yes --recreate`；它会删除旧股票范围相关 DB、旧持仓 DB、旧关注 DB、live-sim DB、replay DB、SQLite sidecar 和备份文件，并由新版本 schema 重新初始化空主库与空回放库。

## 页面边界

### `/portfolio`

定位：持仓诊断和个股复核。

读取：

1. 股票池聚合视图。
2. 登记持仓。
3. live-sim 持仓摘要。
4. 最近信号摘要。
5. 缓存的行情技术、AI 分析、基础信息。

允许触发：

1. 手动刷新行情技术。
2. 手动刷新 AI 分析。
3. 股票池成员关系变更。
4. 登记持仓变更。

不得触发：

1. 页面打开时自动远程全量刷新。
2. 历史回放数据刷新。
3. live-sim 执行。

### `/live-sim`

定位：实时模拟执行台。

读取：

1. 股票池中 `quant_enabled=true` 的实时量化股票。
2. live-sim 独立账户、持仓、资金槽、成交、信号。
3. 行情技术缓存。

刷新规则：

1. 实时量化调度周期为 10 分钟。
2. 每次调度先请求行情技术域刷新。
3. 行情技术 TTL 为 2 分钟，TTL 内同一股票同一数据域不重复远程拉。
4. 调度只能刷新策略执行必需数据，不能触发 AI 分析。

不得触发：

1. 登记持仓写入。
2. replay 表写入。
3. AI 分析自动刷新。

### `/his-replay`

定位：历史回放执行结果和回放任务管理。

读取：

1. 启动任务时从股票池冻结的回放股票范围。
2. replay 独立库中的 `sim_run_*`。
3. 历史 K 线、历史指标和公司行为缓存。

刷新规则：

1. 历史检查点数据单独获取，不走实时行情接口。
2. 每个股票在任务准备阶段按回放区间一次性准备历史 K 线和指标。
3. 准备历史数据必须 local-first；本地覆盖区间时不远程。
4. 本地 partial 时只补缺口，不能每个 checkpoint 反复远程拉。
5. checkpoint 运行中只读已准备好的历史数据和指标，不远程拉基础信息、实时行情或 AI 分析。

## 数据刷新域

### `market_technical`

内容：

1. 实时行情价格。
2. K 线。
3. 技术指标：MA、MACD、RSI、KDJ、BOLL、成交量均线、量比。
4. 涨跌停状态和可交易约束所需行情字段。

子类型和缓存规则：

1. `quote_realtime`：实时 quote，TTL 为 2 分钟。
2. `kline_intraday`：分钟 K 线，按 bar 时间增量覆盖判断；当前交易日可按最新 bar 补缺口，不套用 2 分钟 TTL 到历史区间。
3. `kline_daily` / `kline_range`：日线和历史区间 K 线，按 `symbol + timeframe + adjust + start + end` 覆盖判断。
4. `indicator_series`：技术指标序列，按 `symbol + source + timeframe + formula_profile + indicator_version + start + end` 覆盖判断。
5. `indicator_snapshot`：当前展示快照，可由最新 `quote_realtime` 和 `indicator_series` 派生；若依赖序列覆盖充分，不单独远程拉。

实时行情刷新使用 `quote_realtime` 的 2 分钟 TTL。历史回放使用 `kline_range` 和 `indicator_series` 的区间覆盖判断，不使用实时 TTL。

历史回放：

1. 使用历史 K 线范围缓存。
2. 使用历史指标范围缓存。
3. 不使用实时 quote。

允许远程：

1. live-sim 调度。
2. 用户手动刷新行情技术。
3. 历史回放准备阶段补历史数据缺口。

不允许远程：

1. 页面打开。
2. AI 分析读取依赖时。
3. checkpoint 执行中。

### `basic_info`

内容：

1. 股票名称。
2. 行业、板块、交易所、市场。
3. 上市日期。
4. 股票类型和涨跌幅限制规则辅助信息。

TTL：30 天，除非用户强制刷新。

允许远程：

1. 手动刷新基础信息。
2. 后台日级基础信息补全任务。
3. 用户明确选择“入池后补全基础信息”时，可以创建低优先级 refresh job。

不允许远程：

1. 历史回放运行中。
2. live-sim 每轮调度中。
3. 页面打开时批量刷新。
4. 股票首次进入股票池的成员关系写入流程中。

股票首次进入股票池只写成员关系。若基础信息缺失，系统可以记录 `basic_info_missing=true` 或创建待处理 refresh job，但默认不立即远程执行。

### `flow_sentiment`

内容：

1. 主力资金流。
2. 龙虎榜。
3. 市场情绪和板块情绪。
4. 新闻摘要或事件热度。

TTL：交易日级别，默认 1 天。

用途：

1. 候选发现。
2. 信号上下文加权。
3. 持仓诊断解释。

不应作为实时量化每 10 分钟调度的必拉数据。实时量化只读取最近快照。

### `fundamental`

内容：

1. 财报指标。
2. PE、PB、市值。
3. 盈利能力、现金流、负债率。

TTL：1 天到财报周期级别。

用途：

1. AI 分析。
2. 持仓诊断。
3. 策略上下文低频加权。

不得在实时量化每轮中远程刷新。

### `ai_analysis`

内容：

1. 多分析师观点。
2. 最终建议。
3. 风险提示。
4. 分析上下文和置信度。

刷新方式：

1. 与行情技术刷新分开。
2. 只允许手动触发、定时日级任务触发，或明确的持仓诊断批量任务触发。
3. AI 分析读取已有行情技术、基础信息、资金流和基本面缓存；默认不反向触发远程行情刷新。

TTL：默认 1 天，可按页面提供“强制重新分析”。

### `corporate_actions`

内容：

1. 除权除息。
2. 分红送转。
3. 停牌复牌。
4. 市场交易时间、T+1、涨跌停规则。

用途：

1. 交易执行硬约束。
2. 历史回放价格和持仓 lot 修正。
3. 实时量化可买可卖判断。

刷新规则：

1. 历史回放按任务区间 local-first 准备。
2. 实时量化按交易日低频刷新。
3. 不和行情 quote 混在一个刷新动作中。

### `membership`

内容：

1. 关注池成员关系。
2. 量化股票标签。
3. 登记持仓标签。
4. live/replay 上下文标签。

刷新方式：

1. 用户操作直接写库。
2. 不触发远程行情。
3. 需要展示价格时读取已有缓存；缓存缺失时显示空值或提示可手动刷新。

## 统一刷新服务

新增或收敛为一个统一服务，暂称 `StockDataRefreshService`。

输入：

1. `symbols`
2. `domain`
3. `mode`: `read_cache` / `refresh_if_stale` / `force_refresh`
4. `context`: `portfolio` / `live_sim` / `his_replay` / `workbench` / `scheduler`
5. `as_of` 或历史区间
6. `allow_remote`
7. `bypass_cooldown`: 仅 admin/debug 可用，默认 `false`

输出：

1. 每个 symbol 的刷新状态。
2. cache status：`hit` / `stale` / `miss` / `partial` / `remote_refreshed` / `remote_failed` / `negative_hit`。
3. 数据时间口径。
4. 失败原因和下次允许远程时间。

硬规则：

1. 服务内部统一做 local-first。
2. 服务内部统一做并发去重。同一 domain、symbol、params 的远程请求同一时间只能有一个。
3. 服务内部统一做失败冷却。远程失败后，在冷却期内不重复远程拉。
4. 调用方不能绕过服务直接远程请求。
5. `force_refresh` 只跳过 TTL 和覆盖 freshness 判断，不跳过并发去重。
6. `force_refresh` 默认不跳过失败冷却；只有 admin/debug 且 `bypass_cooldown=true` 时才允许绕过冷却。

## 老刷新任务处理

### 必须删除或改造的旁路

1. 删除 `WatchlistService.refresh_quotes()` 这类旧 watchlist 刷新入口；统一股票池快照写回由新刷新服务负责。
2. `portfolio refresh-indicators` 不再混合刷新旧 watchlist、行情技术、AI 分析。它拆为：
   - `refresh-market-technical`
   - `refresh-ai-analysis`
3. `stock_analysis_service` 不再默认远程拉行情技术。AI 分析使用刷新服务提供的缓存快照；只有显式 force 且调用方允许远程时才补数据。
4. `his-replay` 不得使用实时 quote 和基础信息刷新链路。回放只用历史数据 provider。
5. `live-sim` 调度不直接调用 Akshare、TDX、Tushare；只调用刷新服务的 `market_technical`。

### 可以复用的能力

1. `LocalMarketDataStore.fetch_range()` 和 `fetch_latest()`。
2. `AkshareLocalClient`、`TdxLocalClient`、`TushareLocalClient` 作为 provider adapter。
3. `TechnicalIndicatorEngine`。
4. `stock_refresh_scheduler` 的调度线程、交易时间判断、批量节流框架。
5. 快照写回逻辑可以复用实现思路，但目标写入表必须是统一股票池，不得写旧 watchlist。
6. 现有 replay 历史数据准备阶段，但需要收敛到统一 local-first contract。

### 需要废弃的行为

1. 页面打开自动全量远程刷新。
2. 一个按钮同时刷新行情、基础信息、AI 分析。
3. 每个 checkpoint 触发远程拉取或重复全量指标计算。准备阶段应预计算/缓存指标序列；checkpoint 阶段按时间索引 lookup。允许从已准备 DataFrame 取 as-of 窗口或 tail window，但不得触发远程或重新计算整段指标。
4. 北交所或失败股票每轮都 TDX 超时再 Akshare fallback。
5. 股票池成员变化自动触发全量行情刷新。

## 调度策略

### 行情技术实时刷新

1. TTL：2 分钟。
2. 默认只刷新 `quant_enabled=true` 且实时量化需要扫描的股票。
3. 手动刷新可以指定股票或当前页面股票。
4. 失败冷却：单 symbol 单 provider 失败后至少冷却 10 分钟；连续失败可指数退避。

### 实时量化

1. 周期：10 分钟。
2. 只在交易时间运行。
3. 每轮先请求 `market_technical`，mode 为 `refresh_if_stale`。
4. 如果行情技术刷新失败，使用仍在可接受 stale 窗口内的本地数据；否则该股票跳过本轮。
5. 不触发 AI 分析、基础信息和资金流远程刷新。

### AI 分析

1. 默认与实时量化解耦。
2. 日级调度或手动触发。
3. 使用已有缓存快照。
4. 缺数据时返回“数据不足”，不隐式发起多域远程刷新。

### 历史回放

1. 启动时冻结回放股票范围。
2. 准备阶段按股票和区间调用历史数据刷新，mode 为 `refresh_if_stale`。
3. 每只股票的历史 K 线和指标在任务内复用。
4. checkpoint 执行阶段不得远程拉任何数据。
5. replay 失败时要明确记录失败股票、数据域、cache status 和 provider。

准备阶段失败处理：

1. 历史 K 线完全缺失且远程失败：该股票从本次 run 的回放股票范围中剔除，记录 warning 事件和数据准备明细；如果全部股票都被剔除，任务失败。
2. 历史 K 线存在本地数据但区间不完整：只补缺口；补缺口失败时，如果本地数据覆盖每个 checkpoint 所需的最小 lookback 窗口，则允许继续并记录 `partial_local_used`；否则剔除该股票。
3. 指标序列缺失：如果 K 线覆盖充分，则本地计算并写入指标缓存；计算失败时剔除该股票并记录原因。
4. 公司行为数据缺失或远程失败：不直接失败整个任务；记录 `corporate_actions_unavailable` warning，并在任务结果中标注公司行为口径可能不完整。
5. 被剔除股票不得生成信号、成交或持仓；UI 必须展示剔除数量和明细。

## UI 要求

### 股票池管理

1. 工作台提供统一股票池视图。
2. 表格上方提供批量按钮：
   - 加入量化
   - 移出量化
   - 登记持仓
   - 取消关注
   - 刷新行情技术
   - 刷新 AI 分析
3. 行内展示标签，不在右侧堆一行一个操作按钮。

### `/live-sim`

1. 使用“实时量化股票”命名。
2. 展示刷新时间：
   - 行情技术更新时间
   - 实时量化上次运行时间
   - 下一次运行时间
3. 不展示“量化候选池”字样。

### `/his-replay`

1. 使用“回放股票范围”命名。
2. 展示任务启动时冻结的股票数量。
3. 展示历史数据准备状态：
   - local hit
   - partial filled
   - remote refreshed
   - remote failed
4. 任务运行中不展示实时刷新状态。

### `/portfolio`

1. 使用“持仓诊断”定位。
2. 区分：
   - 登记持仓
   - 实时模拟持仓
   - 关注观察
   - 量化股票
3. 行情技术刷新和 AI 分析刷新是两个独立操作。

## 验收标准

1. 所有页面打开只读缓存，不发起远程批量刷新。
2. 实时量化调度周期为 10 分钟，行情技术 TTL 为 2 分钟。
3. 历史回放 checkpoint 执行中不会出现实时行情、基础信息、AI 分析远程请求日志。
4. 同一股票同一数据域失败后进入冷却，不再每轮重复 TDX timeout。
5. `920xxx` 这类股票在远程失败后，日志能看到冷却命中，而不是反复 fallback。
6. 股票池成员变化不会触发行情远程刷新。
7. AI 分析刷新不会隐式触发行情技术远程刷新。
8. live-sim、his-replay、portfolio 仍保持账户、仓位、成交、信号隔离。

## 实施顺序

1. 建立统一股票池聚合服务和 API 口径。
2. 建立 `StockDataRefreshService` 的 domain contract。
3. 收敛行情技术刷新到统一服务。
4. 改造实时量化调度为 10 分钟周期，并通过统一服务刷新行情技术。
5. 改造历史回放准备阶段为 local-first 历史数据获取，checkpoint 只读准备结果。
6. 拆分 portfolio 的行情技术刷新和 AI 分析刷新。
7. 删除旧 watchlist refresh 入口，将快照写回收敛到统一股票池刷新服务。
8. 接入失败冷却、并发去重和刷新状态 UI。
