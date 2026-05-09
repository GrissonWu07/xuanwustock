# 实时量化历史演练设计

Date: 2026-05-09
Status: Draft for review
Owner: Codex

## 1. 背景

系统已经具备三类相关能力：

1. **实时量化**：基于统一股票池中已启用实时量化的股票，按交易时间周期性扫描、生成信号、模拟成交、维护账户和持仓。
2. **历史回放**：基于启动时固定的股票范围，在历史 checkpoint 上回测策略交易表现。
3. **股票池生命周期**：发现/研究结果可形成候选事件，量化股票可在 `trial / active / exit_only / cooling / retired / manual_paused` 等状态之间流转。

当前问题是：实时量化只能等真实交易时间运行，验证周期太慢；普通历史回放又不模拟股票的自动入池、出池和生命周期流转，无法回答“如果实时量化系统从某天上线运行，会发生什么”。

本 spec 定义 **实时量化历史演练**：复用历史 checkpoint 和 replay 长任务框架，但执行实时量化的完整生产逻辑，包括动态股票池、自动入池、自动出池、交易模拟和生命周期状态变化。

## 2. 产品定义

实时量化历史演练回答：

> 如果当前实时量化系统从指定历史日期开始上线运行，它会如何发现股票、纳入量化、扫描、交易、降级、冷却、出池，最终账户和股票池会变成什么状态？

它与普通历史回放的差异：

| 维度 | 普通历史回放 | 实时量化历史演练 |
|---|---|---|
| 目标 | 验证固定股票名单下的策略收益 | 验证实时量化系统的上线运行过程 |
| 股票范围 | 启动时固定，不随任务变化 | 随候选事件和生命周期动态变化 |
| 入池 | 不处理 | 处理候选事件、eligible、auto trial |
| 出池 | 不处理 | 处理 `exit_only / cooling / retired` |
| 扫描对象 | 固定候选 + 持仓 | `trial / active / exit_only`，并低频复评 `cooling` |
| 输出重点 | 收益、成交、信号、资金池 | 额外输出入池、出池、健康度、生命周期事件 |

对客户的解释口径：

> 历史回放是固定名单的策略收益测试；实时量化历史演练是动态股票池的上线彩排。前者看策略过去赚不赚钱，后者看系统从发现股票到退出股票的完整运行是否合理。

## 3. 目标

1. 允许从任意历史日期启动实时量化演练，例如 `2026-01-01`。
2. 每个 checkpoint 按实时量化生产顺序执行，而不是等待真实交易时间。
3. 完整模拟股票自动入池、自动出池、生命周期状态、BUY 分层、组合防守、个股执行反馈、资金槽、T+1、涨跌停不可成交和除权除息。
4. 不污染实时量化 live 状态表，不改变当前 live 账户、持仓、成交、信号和股票池。
5. 复用 replay 长任务、进度、数据准备、信号、交易和结果展示结构。
6. 输出足够解释信息，能够追溯每只股票为什么入池、为什么暂停、为什么只出场、为什么退出。

## 4. 非目标

1. 不新增第三套独立回测系统。
2. 不绕开现有策略 kernel、资金槽、交易撮合、生命周期管理器。
3. 不把普通历史回放改成动态股票池模式。
4. 不允许使用未来数据生成历史候选事件。
5. 不要求 AI 分析结果在没有历史时间戳的情况下参与历史入池。
6. 不改变正式实时量化“只在交易时间运行”的生产约束。

## 5. 任务类型

在 replay 任务体系中新增任务类型：

```text
run_type = live_quant_drill
```

现有普通历史回放使用：

```text
run_type = historical_backtest
```

两者共用 replay 库和任务进度框架，但执行模式不同：

1. `historical_backtest`：固定股票范围，不执行股票池生命周期。
2. `live_quant_drill`：动态股票池，执行候选事件、入池、出池和生命周期状态机。

## 6. 启动配置

实时量化历史演练入口放在实时量化页，同时在历史回放页任务列表中可查看任务结果。

启动参数：

1. `start_date`
   - 默认：`2026-01-01`
   - 市场时区日期

2. `end_date`
   - 默认：当前日期
   - 不允许早于 `start_date`

3. `market`
   - 默认读取当前实时量化配置
   - 支持 `CN / HK / US`

4. `timeframe`
   - 默认读取当前实时量化配置
   - 必须走现有 checkpoint 生成器

5. `initial_cash`
   - 默认读取当前实时量化配置

6. `strategy_profile_id`
   - 默认读取当前实时量化配置

7. `ai_dynamic_strategy / ai_dynamic_strength / ai_dynamic_lookback`
   - 默认读取当前实时量化配置
   - 只允许使用 checkpoint 当时可见的输入

8. `auto_entry_enabled`
   - 默认读取系统级量化自动化开关
   - 控制候选事件是否允许自动进入 `trial`

9. `auto_exit_enabled`
   - 默认读取系统级量化自动化开关
   - 控制生命周期自动降级、冷却和退出

10. `execute_trades`
    - 默认开启
    - 开启后模拟成交、费用、T+1、资金槽和账户

11. `liquidate_at_end`
    - 默认开启
    - 结束时清算剩余持仓，用于输出清算后总盈亏

12. `seed_current_quant_universe`
    - 默认开启
    - 任务启动时记录当前实时量化股票池作为演练初始股票状态

13. `generate_historical_candidate_events`
    - 默认开启
    - 按候选生成频率使用历史可见数据生成候选事件

14. `candidate_generation_frequency`
    - 默认：`daily_first_checkpoint`
    - 允许值：
      - `daily_first_checkpoint`：每个交易日第一个 checkpoint 生成一次候选事件
      - `every_n_checkpoints`：每 N 个 checkpoint 生成一次候选事件
    - 不允许默认每个 30m checkpoint 全量运行所有发现策略

15. `candidate_generation_checkpoint_interval`
    - 仅当 `candidate_generation_frequency=every_n_checkpoints` 时生效
    - 默认：`8`
    - 最小值：`2`

配置约束：

1. `seed_current_quant_universe` 和 `generate_historical_candidate_events` 可以同时开启。
2. 若二者都关闭，任务应返回 `400`，因为没有任何股票来源。
3. 演练期间不读取 live 当前状态变化，只读取任务启动时保存的快照和演练内部状态。
4. 启动时必须锁定当前策略 profile 快照和版本信息，运行期间不响应用户对 profile 的后续修改。
5. 若当前 profile 没有显式版本号，metadata 中必须保存完整 profile JSON 作为本次演练的不可变配置。

## 7. 初始股票池快照

任务启动时必须记录当前实时量化相关状态，形成 run-local 初始快照：

1. `stock_universe` 中所有与量化相关的股票。
2. 每只股票的：
   - `stock_code`
   - `stock_name`
   - `market`
   - `industry`
   - `concepts`
   - `quant_enabled`
   - `quant_status`
   - `quant_auto_managed`
   - `quant_manual_override`
   - `quant_entry_source`
   - `quant_entry_at`
3. 对应 `stock_universe_quant_state`：
   - `candidate_score`
   - `health_score`
   - `downtrend_streak`
   - `weakening_warning_streak`
   - `blocked_streak`
   - `no_buy_days`
   - `cooling_until`
   - `retired_at`
   - `reentry_watch_until`
4. 当前系统级生命周期设置：
   - `quant_universe_lifecycle_enabled`
   - `auto_entry_mode`
   - `auto_exit_enabled`
5. 当前策略 profile 中的生命周期 policy。

该快照只作为本次任务输入，不反向更新 live 主库。

## 8. 历史候选事件

实时量化历史演练必须支持历史时间线上的候选事件，候选事件用于验证自动入池。

### 8.1 候选来源历史可用性门控

1. 历史发现策略，但必须通过历史可用性检查。
2. 历史研究输出，但必须有明确历史时间戳。
3. 手工种子股票，来自任务启动时的当前实时量化股票快照。

候选来源历史可用性矩阵只用于判断“该来源在某个历史 checkpoint 是否允许生成候选事件”，不用于给股票价值、交易信号或 `candidate_score` 加分。

| 来源 | 默认是否启用 | 历史可用性要求 | 不满足时行为 |
|---|---:|---|---|
| 低价擒牛 | 是 | 有 checkpoint 之前的历史行情、价格、成交量和策略所需过滤字段 | 写入 `disabled_candidate_sources`，跳过 |
| 小市值 | 条件启用 | 有 as-of 市值数据；若只能拿到当前市值则不可用 | 写入 `disabled_candidate_sources`，跳过 |
| 低估值 | 条件启用 | 有 as-of PE/PB/财务口径；不能用当前估值回填历史 | 写入 `disabled_candidate_sources`，跳过 |
| 净利增长 | 条件启用 | 有财报发布日期或可确认的 as-of 财务数据 | 写入 `disabled_candidate_sources`，跳过 |
| 主力资金 | 条件启用 | provider 支持历史资金流 as-of 查询或已有本地历史资金流缓存 | 写入 `disabled_candidate_sources`，跳过 |
| 当前发现页结果 | 否 | 当前结果没有历史 occurred_at，不可用于历史 checkpoint | 禁止使用 |
| 当前 AI 分析 | 否 | 当前 AI 结论包含未来知识，不可倒灌 | 禁止使用 |
| 历史研究输出 | 条件启用 | 研究记录有 `occurred_at` 且 `occurred_at <= checkpoint_at` | 不满足则跳过该条 |
| 手工种子股票 | 是 | 来自任务启动时的初始快照 | 作为初始状态，不重复生成候选事件 |

说明：

1. `其他已有发现策略` 只有在能证明它使用 checkpoint 当时可见数据时才允许接入。
2. 任何依赖当前实时 provider、当前 AI 输出、当前研究总结的候选来源，默认视为不可历史化。
3. 不可历史化来源必须显式记录，不能静默降级成当前结果。
4. `source_type` 是审计和去重字段，不是评分因子。
5. `candidate_score` 必须来自该候选事件自身的历史 as-of 指标，例如价格结构、成交量、估值、财务增长、资金流等；不能因为来源是“主力资金”“AI”“研究”而额外加权。
6. 多来源同时命中同一股票时，只能作为“候选支持证据”记录在 `evidence_json` 中；是否提升 `candidate_score` 必须由明确的历史指标共振规则决定，不能按来源名称加分。

### 8.2 禁止的数据来源

1. 当前页面中没有历史时间戳的发现结果。
2. 当前 AI 分析结论。
3. 当前研究总结。
4. checkpoint 之后才出现的行情、指标、财务、事件。

### 8.3 候选生成频率

候选事件生成不得默认在每个 checkpoint 全量执行。默认频率：

1. `daily_first_checkpoint`
   - 每个交易日第一个可交易 checkpoint 执行一次候选生成
   - A 股 30m 场景下，通常是 `09:30` 或当天第一个实际 checkpoint

2. `every_n_checkpoints`
   - 每 N 个 checkpoint 执行一次候选生成
   - `N` 来自 `candidate_generation_checkpoint_interval`

频率约束：

1. 默认值必须是 `daily_first_checkpoint`。
2. 不允许以 30m checkpoint 为单位全量运行所有发现策略，除非用户显式选择 `every_n_checkpoints` 且 `N >= 2`。
3. 任务创建时必须估算候选生成次数：
   - `estimated_candidate_generation_runs`
   - `enabled_candidate_sources`
   - `estimated_strategy_invocations`
4. 若预估策略调用次数超过 `1000`，UI 必须提示运行时间风险。
5. 若预估策略调用次数超过 `3000`，启动接口必须要求 `confirmLongRunning=true`。

### 8.4 候选生成规则

在候选生成 checkpoint 执行时：

1. 只使用 `checkpoint_at` 之前可见数据。
2. 生成 `candidate_event`，字段包括：
   - `stock_code`
   - `source_type`
   - `source_key`
   - `candidate_score`
   - `confidence`
   - `reason_text`
   - `evidence_json`
   - `occurred_at`
3. 同一股票、同一来源、同一 checkpoint 的候选事件必须去重。
4. 候选事件先写入 run-local 候选事件表，再交给 run-local `QuantUniverseManager` 处理。
5. 若某类候选策略无法在历史 as-of 口径下运行，必须在任务 metadata 中记录 `disabled_candidate_source`，不能静默使用当前结果。
6. 同一股票、同一来源若已有未被 consumed 的有效候选事件，且距当前 checkpoint 不足 `candidate_event_dedup_days`，必须跳过本次生成。
7. `candidate_event_dedup_days` 默认：
   - aggressive：`3`
   - stable：`5`
   - conservative：`7`
8. 候选事件被成功纳入 `trial`、被用户忽略、过期或进入 retired block 后，视为 consumed 或 closed。
9. drill 表可以通过 `status` 表示 consumed 状态，不要求复制 live `stock_universe_candidate_events.consumed_by_quant_manager_at` 字段。
10. 当候选事件被自动纳入 `trial` 时，`sim_run_candidate_events.status` 必须从 `eligible/active` 更新为 `consumed` 或等价终态，供跨 checkpoint 去重判断使用。

## 9. 自动入池

候选事件进入 run-local `QuantUniverseManager` 后，按现有生命周期规则处理：

1. 基于候选事件自身的历史 as-of 指标计算 `candidate_score`。
2. 检查基础信息是否缺失。
3. 检查停牌、涨跌停、冷却期、retired 复活门槛。
4. 检查容量限制、行业集中度、概念集中度。
5. 根据 `auto_entry_mode` 决定结果：
   - `manual_only`：只记录候选事件，不自动入池。
   - `confirm_first`：记录 eligible，不自动纳入。
   - `auto_trial`：满足阈值自动进入 `trial`。

评分约束：

1. `source_type` 不得直接参与 `candidate_score`。
2. 来源可用性门控只决定候选事件能不能在该 checkpoint 生成。
3. 若需要体现多策略共振，必须把共振拆成可解释的历史指标，例如“价格趋势确认 + 成交量放大 + 估值分位低”，而不是“来源数量越多分越高”。
4. drill 模式不得直接复用 live `calculate_candidate_score()` 中基于来源数量的 `multi_source_bonus`。
5. 若 live 评分函数无法关闭 `multi_source_bonus`，drill 必须提供显式参数或替代函数，使来源数量不直接影响 `candidate_score`。

实时量化历史演练中，`auto_entry_enabled=false` 时：

1. 候选事件仍保存。
2. `eligible` 仍保存。
3. 不自动改变 `quant_status`。

## 10. 生命周期状态机

实时量化历史演练必须完整执行股票池生命周期状态机。

允许状态：

1. `inactive`
2. `trial`
3. `active`
4. `exit_only`
5. `cooling`
6. `retired`
7. `manual_paused`

状态口径：

| 状态 | run-local `quant_enabled` | 主扫描 | 低频复评 | 自动恢复 | 说明 |
|---|---:|---:|---:|---:|---|
| `inactive` | 0 | 否 | 否 | 可由候选事件进入 `trial` | 不在量化管理域 |
| `trial` | 1 | 是 | 否 | 是 | 新纳入量化，允许轻仓 BUY |
| `active` | 1 | 是 | 否 | 是 | 正常实时量化扫描 |
| `exit_only` | 1 | 是 | 否 | 是 | 只出场管理，禁止 BUY 和加仓 |
| `cooling` | 1 | 否 | 是 | 是 | 冷却状态，不参与主扫描 |
| `retired` | 0 | 否 | 否 | 仅高质量候选事件可重新进入 `trial` | 已退出自动量化 |
| `manual_paused` | 0 | 否 | 否 | 否 | 用户手工暂停，系统不得自动恢复 |

说明：

1. 这里的 `quant_enabled` 是演练 run-local 状态，不回写 live 主库。
2. 普通历史回放不读取这张状态机，也不写这些状态。
3. `manual_paused` 在演练过程中不会由系统自动产生；它只可能从任务启动时的初始股票池快照带入。

主扫描范围：

1. `trial`
2. `active`
3. `exit_only`

低频复评范围：

1. `cooling`

不自动扫描：

1. `retired`
2. `manual_paused`

合法流转：

1. `inactive -> trial`
2. `trial -> active`
3. `trial -> exit_only`
4. `trial -> cooling`
5. `active -> exit_only`
6. `active -> cooling`
7. `exit_only -> cooling`
8. `exit_only -> trial`
9. `exit_only -> active`
10. `cooling -> trial`
11. `cooling -> retired`
12. `retired -> trial`
13. `any managed state -> manual_paused`
14. `manual_paused -> trial | active | cooling`，仅手工种子状态恢复时允许

强约束：

1. 有持仓股票不能直接进入 `cooling / retired`，必须先进入 `exit_only`。
2. `exit_only` 禁止 BUY 和加仓，只允许 SELL/HOLD。
3. `manual_paused` 不得被系统自动恢复。
4. `retired` 只能被高质量候选事件重新激活。
5. `cooling` 不参与主扫描，只参与低频复评。

## 11. Checkpoint 执行顺序

每个 checkpoint 必须按以下顺序执行，不能随意调整：

1. 解析 checkpoint 市场时间和 UTC 时间。
2. 加载 checkpoint 当时可见的行情、K 线、技术指标和公司行为。
3. 应用除权除息、停牌、涨跌停信息。
4. 若当前 checkpoint 命中候选生成频率，则生成历史候选事件；否则跳过候选生成。
5. 执行自动入池逻辑。
6. 获取主扫描股票：
   - `trial`
   - `active`
   - `exit_only`
7. 分析当前持仓股票。
8. 分析当前可扫描候选股票。
9. 执行实时量化信号逻辑：
   - BUY 强弱分层
   - 冷启动轻仓
   - profit reentry 限制
   - 个股执行反馈
   - 组合级防守
   - 涨跌停不可成交
10. 自动执行可成交信号。
11. 更新账户、持仓、lot、slot、T+1 状态。
12. 更新每只股票的 `health_score`。
13. 执行生命周期状态流转。
14. 执行 `cooling` opportunistic review。
15. 写入 checkpoint 快照。
16. 写入本 checkpoint 的信号、交易、候选事件、生命周期事件和股票状态快照。

执行顺序说明：

1. 候选事件必须在主扫描前处理，否则新入池股票无法在同一 checkpoint 参与扫描。
2. 生命周期状态必须在交易执行后更新，因为持仓是否清空会影响 `exit_only -> cooling/trial/active`。
3. `cooling` 复评必须在主扫描后执行，避免冷却股挤占主扫描容量。
4. 步骤 5 中新进入 `trial` 的股票，必须在步骤 6 到 8 的主扫描范围内立即可见。
5. 若当前 checkpoint 不生成候选事件，步骤 5 仍需处理此前未 consumed 的 eligible 事件，例如从 `confirm_first` 切换到 `auto_trial` 的 run-local 设置不在本任务中发生，因此通常不会产生新入池。

## 12. 交易与风控规则

实时量化历史演练必须复用实时量化交易语义：

1. BUY 分层
2. 组合级防守
3. 个股执行反馈
4. profit reentry gate
5. 资金槽 sizing
6. T+1
7. 涨跌停不可买卖
8. 停牌不可交易
9. 除权除息调整 lot、成本、股数和现金分红
10. 手续费和印花税
11. 期末可选清算

交易时间口径：

1. 交易时间判断基于 checkpoint 的市场时区。
2. 不使用当前系统时间判断是否可运行。
3. 当前系统时间只用于任务创建时间和日志时间。

## 13. 数据隔离

实时量化历史演练不得写入 live 表：

1. live positions
2. live trades
3. live account
4. live account snapshots
5. live signals
6. live stock universe lifecycle state

演练使用 run-local 状态：

1. 任务启动时从 live 主库读取初始快照。
2. 在 replay worker 内构建隔离的临时运行状态。
3. 所有 checkpoint 对股票池、账户、持仓、交易、信号的修改只发生在临时运行状态中。
4. checkpoint 完成后把结果写入 replay 库。
5. 任务完成后不得把演练状态同步回 live 主库。

## 14. Replay 库数据模型

现有 replay 表继续使用：

1. `sim_runs`
2. `sim_run_checkpoints`
3. `sim_run_signals`
4. `sim_run_trades`
5. `sim_run_positions`
6. `sim_run_account_snapshots`

新增或扩展以下 run-scoped 表。

### 14.1 `sim_run_quant_states`

用途：保存每个 checkpoint 后的股票池状态快照。

字段：

1. `id`
2. `run_id`
3. `checkpoint_at`
4. `checkpoint_at_utc`
5. `stock_code`
6. `stock_name`
7. `market`
8. `quant_enabled`
9. `quant_status`
10. `health_score`
11. `candidate_score`
12. `downtrend_streak`
13. `weakening_warning_streak`
14. `blocked_streak`
15. `no_buy_days`
16. `cooling_until`
17. `retired_at`
18. `latest_reason`
19. `snapshot_json`
20. `created_at`

唯一约束：

```text
(run_id, checkpoint_at_utc, stock_code)
```

### 14.2 `sim_run_quant_events`

用途：保存入池、出池、降级、恢复等生命周期事件。

字段：

1. `id`
2. `run_id`
3. `checkpoint_at`
4. `checkpoint_at_utc`
5. `stock_code`
6. `stock_name`
7. `from_status`
8. `to_status`
9. `event_type`
10. `reason_code`
11. `reason_text`
12. `evidence_json`
13. `created_at`

### 14.3 `sim_run_candidate_events`

用途：保存历史演练中生成的候选事件。

字段：

1. `id`
2. `run_id`
3. `checkpoint_at`
4. `checkpoint_at_utc`
5. `stock_code`
6. `stock_name`
7. `source_type`
8. `source_key`
9. `candidate_score`
10. `confidence`
11. `status`
12. `reason_text`
13. `evidence_json`
14. `created_at`

### 14.4 `sim_run_quant_summary`

用途：保存每个 checkpoint 的生命周期状态预聚合，供 UI 折线图和概览卡片直接读取，避免每次页面交互都从 `sim_run_quant_states` 做聚合。

字段：

1. `id`
2. `run_id`
3. `checkpoint_at`
4. `checkpoint_at_utc`
5. `inactive_count`
6. `trial_count`
7. `active_count`
8. `exit_only_count`
9. `cooling_count`
10. `retired_count`
11. `manual_paused_count`
12. `candidate_event_count`
13. `auto_promoted_count`
14. `auto_exited_count`
15. `created_at`

唯一约束：

```text
(run_id, checkpoint_at_utc)
```

UI 生命周期总览必须优先读取 `sim_run_quant_summary`。`sim_run_quant_states` 用于明细和 drill-down，不作为折线图的默认聚合来源。

### 14.5 `sim_runs.metadata_json`

实时量化历史演练必须在 run metadata 中保存：

1. `run_type = live_quant_drill`
2. `seed_current_quant_universe`
3. `generate_historical_candidate_events`
4. `auto_entry_enabled`
5. `auto_exit_enabled`
6. `execute_trades`
7. `liquidate_at_end`
8. `initial_quant_universe_snapshot`
9. `lifecycle_settings_snapshot`
10. `strategy_profile_snapshot`
11. `disabled_candidate_sources`
12. `data_warnings`
13. `candidate_generation_frequency`
14. `candidate_generation_checkpoint_interval`
15. `candidate_event_dedup_days`
16. `estimated_candidate_generation_runs`
17. `enabled_candidate_sources`
18. `estimated_strategy_invocations`
19. `strategy_profile_version`

## 15. 数据准备和 local-first 规则

实时量化历史演练必须遵守统一刷新与缓存架构：

1. 历史 K 线按区间覆盖判断。
2. 技术指标按 `source + timeframe + formula_version + range` 判断覆盖。
3. checkpoint 阶段只能 lookup，不得反复远程拉取。
4. 数据准备阶段可以按股票批量准备历史行情和指标。
5. 若区间过大，批量准备必须分批执行，避免单次请求过大。
6. 缺失某只股票关键行情时，该股票在相关 checkpoint 跳过，并记录 warning。
7. 公司行为缺失时必须记录 `data_warning`。
8. 若公司行为缺失会影响收益口径，任务结果必须显示“数据风险”。

候选事件历史生成也必须走 local-first：

1. 不能为候选事件生成绕过缓存直接远程拉取。
2. 不能使用实时刷新 2 分钟 TTL 判断历史数据是否过期。
3. 不能使用当前发现结果替代历史 as-of 发现结果。

## 16. 时间口径

1. DB 持久化统一使用 UTC ISO，例如 `2026-05-09T02:30:00Z`。
2. checkpoint 展示使用市场时区。
3. 系统更新时间展示使用用户本地时区或系统时区。
4. A 股和港股使用：
   - `Asia/Shanghai`
   - `Asia/Hong_Kong`
5. 美股使用：
   - `America/New_York`
6. 交易时间判断基于 checkpoint 市场时区。
7. 任务创建、任务完成、worker 日志使用 UTC 保存。

## 17. UI 设计

### 17.1 实时量化页入口

实时量化页增加一个主操作：

```text
历史演练
```

位置：

1. 放在实时量化配置区域的操作按钮组中。
2. 不放在股票表格每行内。
3. 点击后打开演练配置弹窗或抽屉。

弹窗内容：

1. 标题：`实时量化历史演练`
2. 说明：`用历史 checkpoint 模拟实时量化从指定日期开始上线运行的完整过程，包括入池、出池、交易和生命周期。`
3. 配置项：
   - 开始日期
   - 结束日期
   - 市场
   - 周期
   - 初始资金
   - 策略 profile
   - 自动入池
   - 自动出池
   - 模拟交易
   - 期末清算
4. 启动按钮：`开始演练`
5. 取消按钮：`取消`

启动成功后：

1. toast 显示 `实时量化历史演练已启动`
2. 跳转到历史回放页对应任务
3. 任务类型显示为 `实时量化演练`

### 17.2 历史回放页任务列表

任务列表增加任务类型字段：

1. `策略历史回放`
2. `实时量化演练`

实时量化演练任务详情必须显示：

1. 初始量化股票数
2. 历史候选事件数
3. 自动入池数
4. 自动出池数
5. 进入 `exit_only` 数
6. 进入 `cooling` 数
7. 进入 `retired` 数
8. 数据 warning 数

统计来源：

1. 初始量化股票数：读取 `sim_runs.metadata_json.initial_quant_universe_snapshot`。
2. 历史候选事件数：读取 `sim_run_candidate_events` 的 `COUNT(*)`。
3. 自动入池数：优先读取 `sim_run_quant_summary.auto_promoted_count` 的 `SUM`；若 summary 缺失，则从 `sim_run_quant_events` 按 `to_status='trial'` 且 `event_type` 为自动纳入类统计。
4. 自动出池数：优先读取 `sim_run_quant_summary.auto_exited_count` 的 `SUM`；若 summary 缺失，则从 `sim_run_quant_events` 按 `to_status IN ('cooling', 'retired')` 统计。
5. `exit_only / cooling / retired` 数：从 `sim_run_quant_events` 按 `to_status` 统计去重股票数。
6. 数据 warning 数：读取 `sim_runs.metadata_json.data_warnings` 的数量。
7. `sim_runs.metadata_json.estimated_*` 只能用于启动前预估，不得作为完成后实际统计。

### 17.3 结果区新增模块

实时量化演练结果页在普通收益、成交、信号、资金池之外，新增：

1. **生命周期总览**
   - `trial`
   - `active`
   - `exit_only`
   - `cooling`
   - `retired`
   - 每类数量随 checkpoint 的变化
   - 数据来源必须优先使用 `sim_run_quant_summary`
   - UI 可以对该序列做客户端缓存，但不能每次交互都从明细表重新聚合

2. **入池事件**
   - 时间
   - 股票
   - 来源
   - 候选分
   - 状态变化
   - 原因

3. **出池与降级事件**
   - 时间
   - 股票
   - from_status
   - to_status
   - health_score
   - 原因

4. **股票最终状态**
   - 股票
   - 最终状态
   - 实现盈亏
   - 清算后盈亏
   - 状态变化次数
   - 最后原因

5. **数据风险**
   - 缺行情
   - 缺公司行为
   - 候选来源不可历史化
   - provider failure

### 17.4 文案口径

禁止使用“试运行”作为 UI 名称。

推荐文案：

1. `实时量化演练`
2. `策略历史回放`
3. `自动入池`
4. `自动出池`
5. `只出场管理`
6. `冷却`
7. `已退出`

## 18. API 设计

### 18.1 启动实时量化演练

```text
POST /api/v1/quant/live-sim/actions/start-drill
```

请求体：

```json
{
  "startDate": "2026-01-01",
  "endDate": "2026-05-09",
  "market": "CN",
  "timeframe": "30m",
  "initialCash": 50000,
  "strategyProfileId": "aggressive",
  "autoEntryEnabled": true,
  "autoExitEnabled": true,
  "executeTrades": true,
  "liquidateAtEnd": true,
  "seedCurrentQuantUniverse": true,
  "generateHistoricalCandidateEvents": true,
  "candidateGenerationFrequency": "daily_first_checkpoint",
  "candidateGenerationCheckpointInterval": 8,
  "confirmLongRunning": false
}
```

响应：

```json
{
  "runId": 123,
  "runType": "live_quant_drill",
  "status": "queued",
  "redirect": "/his-replay?runId=123"
}
```

### 18.2 查询演练生命周期状态

```text
GET /api/v1/quant/replay/{run_id}/quant-states
```

参数：

1. `checkpointAt`
2. `status`
3. `stock`
4. `page`
5. `pageSize`

### 18.3 查询演练生命周期事件

```text
GET /api/v1/quant/replay/{run_id}/quant-events
```

参数：

1. `eventType`
2. `fromStatus`
3. `toStatus`
4. `stock`
5. `page`
6. `pageSize`

### 18.4 查询演练候选事件

```text
GET /api/v1/quant/replay/{run_id}/candidate-events
```

参数：

1. `sourceType`
2. `status`
3. `stock`
4. `page`
5. `pageSize`

## 19. Worker 和执行架构

实时量化历史演练复用 replay worker。

### 19.1 Worker 互斥关系

`live_quant_drill` 与 `historical_backtest` 默认共用同一个 replay worker 池和同一套 active-run 互斥检查。

规则：

1. 任意 `historical_backtest` 正在 `queued/running` 时，不允许启动新的 `live_quant_drill`。
2. 任意 `live_quant_drill` 正在 `queued/running` 时，不允许启动新的 `historical_backtest`。
3. 启动接口必须复用或扩展现有 `_ensure_no_active_replay()`，检查范围覆盖所有 replay run type。
4. 不设计并行执行，避免多个长任务同时竞争本地行情缓存、TDX/Akshare provider、SQLite 写锁和 CPU。
5. 后续若需要并行执行，必须另写 worker 并发和资源隔离 spec，本 spec 不包含。

新增执行模式：

```text
LiveQuantDrillMode
```

职责：

1. 构建 run-local 初始股票池状态。
2. 初始化 run-local 账户、持仓、资金槽。
3. 在每个 checkpoint 生成候选事件。
4. 调用 run-local `QuantUniverseManager`。
5. 调用实时量化同一套 `QuantSimEngine` 信号逻辑。
6. 调用同一套 portfolio execution。
7. 保存 replay 结果和生命周期结果。

禁止：

1. 直接调用 live scheduler 的 `run_once()`。
2. 修改 live `stock_universe_quant_state`。
3. 修改 live account/trade/signal 表。

原因：

1. live scheduler 依赖当前交易时间。
2. drill 必须注入 checkpoint decision_time。
3. drill 必须保持 run-local 状态隔离。

### 19.2 Run-local 服务注入

实时量化历史演练不能让 `QuantSimEngine`、`CandidatePoolService`、`PortfolioService` 或 `QuantUniverseManager` 读取 live 主库的当前状态。执行器必须显式构造 run-local 服务图。

推荐实现：

1. 在 replay worker 临时目录中创建 run-local `QuantSimDB`。
2. 将任务启动时的股票池快照、生命周期状态、策略配置、账户配置写入 run-local DB。
3. 使用该 run-local DB 构造：
   - `QuantSimEngine(db_file=temp_db_file, ...)`
   - `PortfolioService(db_file=temp_db_file, ...)`
   - `CandidatePoolService(db_file=temp_db_file, ...)`
   - `QuantUniverseManager(db=temp_db, profile_id=locked_profile_id, policy=locked_policy)`
4. 如果当前服务构造函数只默认读取 live DB，必须先增加显式 DB 注入参数，不能在 drill 中复用全局 context。
5. `QuantSimEngine.list_live_scan_candidates()` 在 drill 模式下读取 run-local `stock_universe / stock_universe_quant_state`，而不是 live 主库。
6. 每个 checkpoint 新写入 run-local `trial` 的股票，下一次候选查询必须立即可见；同一 checkpoint 内步骤 5 后的主扫描也必须可见。
7. replay 库只保存结果，不作为 engine 的运行状态库。

禁止实现：

1. 在 live 主库上临时改 `quant_status` 再回滚。
2. 让 drill 期间的 `QuantUniverseManager` 直接持有 live `QuantSimDB`。
3. 让 UI API 读取 live 状态后拼装 drill 结果。

## 20. 错误处理

1. 没有股票来源：
   - 返回 `400`
   - 错误：`No quant universe source selected`

2. 开始日期晚于结束日期：
   - 返回 `400`

3. 已有 replay 长任务运行中：
   - 返回 `409`
   - 错误：`Another replay task is already running`
   - 适用于 `historical_backtest` 与 `live_quant_drill`

4. 预估策略调用次数过大但未确认：
   - 当 `estimated_strategy_invocations > 3000` 且 `confirmLongRunning=false`
   - 返回 `400`
   - 错误：`Long running drill requires confirmation`

5. 历史数据部分缺失：
   - 任务继续
   - 记录 warning
   - 对缺失股票/缺失 checkpoint 跳过

6. 关键配置缺失：
   - 使用当前实时量化默认配置
   - 若仍无法解析，任务失败

7. 候选来源不能历史化：
   - 不失败
   - 写入 `disabled_candidate_sources`

8. Worker 异常退出：
   - run 状态置为 `failed`
   - 保留已完成 checkpoint 的部分结果

## 21. 验收标准

1. 能从实时量化页启动 `live_quant_drill`。
2. 默认可从 `2026-01-01` 跑到当前日期。
3. 任务不受当前真实交易时间限制。
4. 任务不写 live-sim 账户、持仓、成交、信号和生命周期状态。
5. 当前实时量化股票能作为初始演练池。
6. 历史候选事件能在 checkpoint 中触发自动入池。
7. `trial / active / exit_only / cooling / retired` 状态能在演练中变化。
8. 有持仓股票不会直接进入 `retired`。
9. `exit_only` 股票不会产生 BUY 成交。
10. `cooling` 股票不参与主扫描，但参与低频复评。
11. 结果页能解释每一次入池、出池、冷却、恢复原因。
12. 收益结果、实现盈亏、清算后总盈亏口径清楚区分。
13. 缺失数据会在结果页显示 warning。
14. 普通历史回放行为不受影响。
15. 默认候选生成频率为每日第一个 checkpoint，不会每个 30m checkpoint 全量执行发现策略。
16. 当前 AI 分析和无历史时间戳的当前研究结果不会进入历史候选事件。
17. drill 与普通历史回放互斥，任意一个运行中时另一个不能启动。
18. `sim_run_quant_summary` 每个 checkpoint 写入一行状态聚合。
19. 启动时锁定策略 profile 快照，运行期间 profile 修改不影响任务。

## 22. 测试要求

后端测试：

1. `live_quant_drill` run 创建测试。
2. run-local 状态隔离测试。
3. 当前量化股票初始化测试。
4. 历史候选事件生成测试。
5. 自动入池测试。
6. `exit_only` BUY 阻断测试。
7. 持仓股票禁止直接 retired 测试。
8. cooling 低频复评测试。
9. 期末清算收益口径测试。
10. live 表不被写入测试。
11. 候选生成频率测试。
12. 候选来源历史可用性门控测试。
13. run-local DB 注入测试。
14. drill/backtest 互斥测试。
15. 同 checkpoint 新入 `trial` 后立即参与扫描测试。
16. strategy profile snapshot 锁定测试。

前端测试：

1. 实时量化页显示 `历史演练` 入口。
2. 启动弹窗参数默认读取实时量化配置。
3. 启动成功跳转到历史回放任务。
4. 历史回放任务列表显示 `实时量化演练` 类型。
5. 结果页显示生命周期总览。
6. 结果页显示入池和出池事件。
7. 所有新增中文 UI 文案都走 i18n。
8. 超长任务预估提示测试。
9. 生命周期总览读取 `sim_run_quant_summary` 的接口测试。

集成测试：

1. 用当前量化股票从 `2026-01-01` 到指定结束日完成一次演练。
2. 至少产生一条候选事件。
3. 至少保存一条 `sim_run_quant_states`。
4. 至少保存一条 `sim_run_quant_summary`。
5. 若存在下行股票，能产生 `exit_only / cooling / retired` 事件。
6. 任务完成后 live-sim 当前账户和持仓未变化。
7. 普通历史回放运行中启动 drill 返回 `409`。
8. drill 运行中启动普通历史回放返回 `409`。

## 23. 实施顺序

1. 扩展 replay run type 和 metadata。
2. 增加 replay 库生命周期表。
3. 增加 run-local 股票池状态初始化。
4. 增加 `LiveQuantDrillMode` 执行器。
5. 接入历史候选事件生成。
6. 接入 run-local `QuantUniverseManager`。
7. 接入候选生成频率、跨 checkpoint 去重和历史可用性门控。
8. 保存 quant states/events/candidate events/summary。
9. 增加启动 API。
10. 增加实时量化页入口。
11. 增加历史回放页任务类型和结果展示。
12. 补齐测试。

实施约束：

1. 每一步都必须保持普通历史回放可运行。
2. 每一步都必须保持实时量化正式运行不被非交易时间绕开。
3. 不允许为了演练修改 live scheduler 的交易时间限制。
