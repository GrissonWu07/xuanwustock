# 实时量化股票池生命周期与自动纳入/退出设计

Date: 2026-05-08
Status: Draft for review
Owner: Codex

## 1. 背景

当前系统已经完成了统一股票池、实时模拟与历史回放的主边界梳理：

1. 股票主集合统一到 `stock_universe`
2. 实时模拟默认扫描 `quant_enabled=1`
3. 历史回放启动时记录 `quant_enabled=1` 的任务股票范围快照
4. 发现股票、研究情报和 AI 分析仍以结果页或结果缓存为主，进入实时量化通常还需要多次人工操作

这带来两个明显问题：

1. **入池路径过长**
   - 发现股票/研究情报/AI 即使已经判断出高质量标的，仍要经过“加入股票池 -> 再加入量化”的人工中转
   - 自动发现能力没有真正接入实时量化

2. **出池机制缺失**
   - 一只股票只要被纳入实时量化，就可能长期占据扫描资源
   - 即使该股票已经连续多次表现为下行、弱趋势、无有效买点，也不会被自动降级或移出

本 spec 的目标，是把“纳入实时量化”和“退出实时量化”做成可解释、可配置、可回溯的生命周期系统，同时与现有股票池、实时模拟、历史回放和刷新架构保持一致。

2026-05-11 修订：生命周期不再采用“预测性硬出池”作为核心机制。历史演练结果显示，过早把股票打入 `cooling/retired` 会让 aggressive 策略后段无标的可扫，收益显著落后固定池历史回放。因此本 spec 的核心语义调整为：

1. 生命周期主要输出 **风险感知 gate**，控制扫描优先级、BUY 门槛、仓位上限和解释原因。
2. `cooling` 不是“不看了”，而是进入补充扫描/恢复扫描队列。
3. `health_score` 不再直接触发出池；状态降级必须由行情确认的 `downtrend_hit` 或用户手工操作驱动。
4. aggressive / stable / conservative 必须有最小扫描覆盖，避免策略把量化股票池收缩到 0~1 只。

策略相关约束：

1. 所有生命周期参数、阈值、权重都必须挂靠到现有策略 profile
2. aggressive / stable / conservative 三套 profile 必须有不同默认值
3. UI 必须允许按 profile 独立配置这些参数，而不是只给一套全局值
4. 生命周期系统不得引入脱离策略 profile 的“第四套独立风险模板”

## 2. 目标

1. 让发现股票、研究情报、AI 分析和手工录入可以更顺畅地进入实时量化管理流程
2. 为实时量化股票建立明确的生命周期状态机，而不是只有 `quant_enabled=1/0`
3. 允许系统根据候选质量、趋势健康度、执行反馈和组合风险，自动决定股票是进入量化、正式扫描、只出场管理、冷却，还是退出
4. 保留完整留痕，确保任何一只股票“为什么进入、为什么退出、为什么恢复”都可解释
5. 不改变 live-sim 与 his-replay 的数据隔离
6. 不让自动管理打破现有 local-first 刷新约束，也不强依赖 AI 分析

## 3. 非目标

1. 不重写实时模拟的交易执行、资金槽、止盈止损、组合防守、个股执行反馈算法
2. 不改写历史回放“启动时记录任务股票范围快照”的语义
3. 不要求发现股票、研究情报、AI 分析的具体评分算法在本 spec 中全面重做
4. 不把持仓诊断、实时模拟、历史回放合并成一个页面
5. 不允许为了自动纳入而反向触发 AI 远程分析

## 4. 术语

### 4.1 统一股票池

系统股票主表为 `stock_universe`。所有标的成员关系都定义在这张表及其附属事件表上。

### 4.2 量化管理域

`quant_enabled=1` 表示该股票处于量化管理域，即允许被实时模拟和历史回放作为候选范围使用。

### 4.3 实时扫描状态

实时扫描状态由 `quant_status` 定义。`quant_enabled=1` 并不等于“当前一定参与主扫描”。

### 4.4 候选事件

候选事件是“某个来源认为这只股票值得进入量化关注”的结构化记录。候选事件不等于立即纳入实时量化。

### 4.5 生命周期事件

生命周期事件是股票在量化管理域中发生状态变更的留痕，例如“量化纳入”“进入冷却”“退出自动量化”。

## 5. 总体设计

系统引入一个独立的 **量化股票生命周期管理器**（下文简称 `QuantUniverseManager`），负责：

1. 接收来自 discover / research / AI / manual 的候选事件
2. 计算候选股票的纳入评分
3. 决定是否自动纳入 `trial`
4. 在实时模拟运行过程中维护 `health_score`
5. 输出股票的 `active / exit_only / cooling / retired` 生命周期状态和对应 `lifecycle_gate`
6. 记录所有状态变更和原因

系统保持以下分层：

1. **候选来源层**
   - discover / research / AI / manual
   - 只负责发出候选事件

2. **生命周期管理层**
   - `QuantUniverseManager`
   - 唯一允许改写 `quant_status / quant_enabled` 的逻辑层

3. **实时模拟执行层**
   - 主消费 `trial / active / exit_only`
   - 当主扫描覆盖不足时，可补充消费一批 `cooling` 股票
   - 不负责决定股票是否属于量化池，但必须消费 `lifecycle_gate` 做 BUY 门槛和仓位裁剪

4. **历史回放层**
   - 默认记录当前 `quant_enabled=1` 的任务股票范围快照
   - Phase 1 不模拟生命周期动态变化

5. **股票池与刷新协调层**
   - `StockUniverseService` 继续负责股票主对象写入、标签更新、刷新任务入队和本地缓存状态摘要
   - `QuantUniverseManager` 不直接调用远程 provider，只通过 `StockUniverseService` 读取股票状态、写生命周期状态、创建低优先级 refresh job

## 6. 状态机

### 6.1 状态定义

新增 `quant_status`，允许以下值：

1. `inactive`
   - 不属于量化管理域
   - `quant_enabled=0`

2. `trial`
   - 量化状态
   - `quant_enabled=1`
   - 参与实时模拟主扫描
   - 允许 BUY，但默认轻仓

3. `active`
   - 正式扫描状态
   - `quant_enabled=1`
   - 参与实时模拟主扫描
   - 允许正常 BUY / SELL / HOLD

4. `exit_only`
   - 只出场管理状态
   - `quant_enabled=1`
   - 参与实时模拟主扫描
   - 禁止新 BUY / 新加仓
   - 仅允许 SELL / HOLD / 风险管理

5. `cooling`
   - 冷却状态
   - `quant_enabled=1`
   - 不参与默认主扫描
   - 当主扫描覆盖不足时，可作为补充扫描候选
   - 补充扫描必须附带更严格的 `lifecycle_gate`

6. `retired`
   - 退出自动量化状态
   - `quant_enabled=0`
   - 不参与实时模拟主扫描
   - 只在候选事件强触发时考虑重新纳入

7. `manual_paused`
   - 用户手工暂停
   - `quant_enabled=0`
   - 不参与自动恢复
   - 只允许用户主动恢复

### 6.2 状态语义约束

1. `trial / active / exit_only` 属于“默认主扫描范围”
2. `cooling` 属于“补充扫描范围”：默认不抢占主扫描容量，但在最小扫描覆盖不足时参与同一 checkpoint 扫描
3. `retired` 不参与常规扫描，只响应新的高质量候选事件或用户手工恢复
4. 有 live-sim 持仓的股票，禁止直接从 `trial / active` 跳到 `cooling / retired`
5. 有 live-sim 持仓且进入下行防守时，必须先进入 `exit_only`
6. `health_score` 只影响 gate、排序和解释，不得单独触发 `trial/active -> cooling`，也不得触发 `cooling -> retired`

### 6.3 合法流转

允许的主要状态流转如下：

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
11. `retired -> trial`
12. `any managed state -> manual_paused`
13. `manual_paused -> trial | active | cooling`（仅用户手工触发）

禁止：

1. `active -> retired` 直接一步跳转
2. `trial -> retired` 直接一步跳转
3. `cooling -> retired` 自动跳转；`cooling` 是 soft gate，不得因为持续下行被系统批量退休
4. `cooling -> active` 直接跳转，必须先回 `trial`
5. `manual_paused` 被系统自动恢复

补充恢复约束：

1. `exit_only -> trial` 仅允许在“持仓已清空 + checkpoint 行情重新满足最低趋势确认 + health_score 恢复到 cooling_threshold 以上”时发生
2. `exit_only -> active` 仅允许在“持仓已清空 + health_score >= active_upgrade_threshold + 满足 active_upgrade_confirm_checkpoints 趋势确认”时发生
3. 若 `exit_only` 持仓已清空但恢复条件不足，则允许继续降级到 `cooling`

## 7. 数据模型

### 7.1 `stock_universe` 核心字段

为避免主表字段膨胀，`stock_universe` 只保留量化生命周期的核心成员关系字段：

1. `quant_status TEXT`
2. `quant_auto_managed INTEGER DEFAULT 1`
3. `quant_manual_override TEXT DEFAULT ''`
4. `quant_entry_source TEXT`
5. `quant_entry_at TEXT`

说明：

1. `quant_enabled` 为现有字段，继续作为“是否属于量化管理域”的总开关
2. `candidate_score`、`health_score`、连续 streak、冷却到期时间、复活观察期等派生值不写主表
3. 主表只存“成员关系”和“最低限度的人工控制”，所有高频变化状态写入专用状态表

### 7.2 生命周期状态表

新增表：`stock_universe_quant_state`

字段：

1. `stock_code PRIMARY KEY`
2. `candidate_score`
3. `candidate_confidence`
4. `health_score`
5. `downtrend_streak`
6. `weakening_warning_streak`
7. `blocked_streak`
8. `no_buy_days`
9. `cooling_until`
10. `retired_at`
11. `retire_reason`
12. `reentry_watch_until`
13. `last_status_changed_at`
14. `last_health_evaluated_at`
15. `snapshot_json`

说明：

1. `stock_universe_quant_state` 是生命周期派生状态快照，不是股票主对象
2. 该表允许被 `QuantUniverseManager` 周期性重写
3. 若状态表缺失，可由最近信号、事件和股票主表重建
4. `snapshot_json` 用于保存最近一次 `health_score` 评估的输入快照，至少包含：
   - 滑动窗口均值
   - warning/downtrend 计数
   - 候选事件支持摘要
   - 执行 penalty 摘要
   - 当次状态判定结果
5. `snapshot_json` 只用于调试、回溯和 explain，不作为主业务判断唯一来源

### 7.3 候选事件表

新增表：`stock_universe_candidate_events`

字段：

1. `id`
2. `stock_code`
3. `source_type`  
   允许值：`discover / research / ai / manual`
4. `source_key`
5. `source_score`
6. `confidence`
7. `trend`
8. `event_weight`
9. `reason_text`
10. `occurred_at`
11. `expires_at`
12. `payload_json`
13. `status`
14. `consumed_by_quant_manager_at`

约束：

1. 候选事件只描述“值得关注”，不直接改实时模拟状态
2. 候选事件允许多来源并存
3. 同一来源、同一股票、同一时间窗口内可做去重

### 7.4 生命周期事件表

新增表：`stock_universe_quant_events`

字段：

1. `id`
2. `stock_code`
3. `event_type`
4. `from_status`
5. `to_status`
6. `trigger_source`
7. `reason_code`
8. `reason_text`
9. `health_score_before`
10. `health_score_after`
11. `candidate_score`
12. `evidence_json`
13. `created_at`

`event_type` 示例：

1. `candidate_promoted_to_trial`
2. `trial_upgraded_to_active`
3. `active_downgraded_to_exit_only`
4. `trial_downgraded_to_cooling`
5. `manual_force_exit_to_retired`
6. `retired_reactivated_to_trial`
7. `manual_pause`
8. `manual_resume`

## 8. 自动纳入设计

### 8.1 候选分来源

候选分由以下来源聚合：

1. discover 结果
2. research 结果
3. AI 分析结果
4. manual 手工标记

要求：

1. AI 结果只能加分，不能成为自动纳入的前置依赖
2. 若 AI 缺失，不阻塞候选纳入
3. discover / research / manual 是主准入来源

### 8.2 候选分计算

定义 `candidate_score ∈ [0, 1]`

建议构成：

1. `source_score_component`
   - 来源原始评分归一化
2. `confidence_component`
   - 来源置信度归一化
3. `trend_component`
   - 趋势确认加分
4. `multi_source_bonus`
   - 多来源共振加分
5. `liquidity_penalty`
   - 流动性不足扣分
6. `cooldown_penalty`
   - 冷却/复活观察期扣分
7. `manual_priority_bonus`
   - 用户手工纳入加分

默认计算原则：

`candidate_score = clamp(weighted_sum + bonuses - penalties, 0, 1)`

`weighted_sum` 的主权重必须按 profile 配置，不允许写死成一套全局值。

默认 profile 权重建议：

#### aggressive

1. `source_score_weight = 0.40`
2. `confidence_weight = 0.20`
3. `trend_weight = 0.15`
4. `multi_source_weight = 0.25`
5. `liquidity_penalty_multiplier = 0.80`
6. `cooldown_penalty_multiplier = 0.80`
7. `manual_priority_bonus_multiplier = 1.10`

#### stable

1. `source_score_weight = 0.35`
2. `confidence_weight = 0.20`
3. `trend_weight = 0.25`
4. `multi_source_weight = 0.20`
5. `liquidity_penalty_multiplier = 1.00`
6. `cooldown_penalty_multiplier = 1.00`
7. `manual_priority_bonus_multiplier = 1.00`

#### conservative

1. `source_score_weight = 0.30`
2. `confidence_weight = 0.20`
3. `trend_weight = 0.35`
4. `multi_source_weight = 0.15`
5. `liquidity_penalty_multiplier = 1.20`
6. `cooldown_penalty_multiplier = 1.20`
7. `manual_priority_bonus_multiplier = 0.90`

约束：

1. `source_score_weight + confidence_weight + trend_weight + multi_source_weight = 1.0`
2. aggressive 更重“来源强度 + 多来源共振”
3. conservative 更重“趋势结构 + 冷却惩罚”
4. stable 作为中性模板，取中间值

### 8.3 自动纳入模式

配置项：`auto_entry_mode`

允许值：

1. `manual_only`
   - 只写候选事件
   - 不自动进入 `trial`

2. `confirm_first`
   - 达到条件后标记为 `eligible`
   - 由用户一键确认进入 `trial`

3. `auto_trial`
   - 达到条件后自动进入 `trial`

默认值：`auto_trial`

### 8.4 纳入阈值

建议配置：

1. `trial_threshold`
2. `strong_candidate_threshold`
3. `high_reentry_threshold`

说明：

1. `trial_threshold` 决定能否进入 `trial`
2. `strong_candidate_threshold` 只表示“候选质量已达到强候选区间”，可用于 UI 标记、排序和更积极的 trial 观察；**不能直接让股票跳过 `trial` 进入 `active`**
3. `high_reentry_threshold` 只用于 `retired -> trial` 的高门槛复活

默认 profile：

#### aggressive

1. `trial_threshold = 0.50`
2. `strong_candidate_threshold = 0.70`
3. `high_reentry_threshold = 0.85`

#### stable

1. `trial_threshold = 0.55`
2. `strong_candidate_threshold = 0.75`
3. `high_reentry_threshold = 0.88`

#### conservative

1. `trial_threshold = 0.65`
2. `strong_candidate_threshold = 0.82`
3. `high_reentry_threshold = 0.92`

### 8.5 自动纳入前置门槛

即使 `candidate_score` 达标，也必须同时满足：

1. 非停牌
2. 非涨停/跌停导致不可成交状态
3. 基础信息不是严重缺失
4. 最近不在 `stock_universe_quant_state.cooling_until` 内
5. 未被 `manual_ban`
6. 未超过当日自动纳入容量上限
7. 未超过同策略单批容量上限

### 8.6 自动纳入容量控制

配置项：

1. `max_auto_entries_per_batch`
2. `max_auto_entries_per_day`
3. `max_auto_entries_per_strategy_batch`
4. `max_same_industry_auto_entries_per_day`

规则：

1. 当天超过 `max_auto_entries_per_day` 后，剩余 eligible 股票只保留候选事件，不进入 `trial`
2. 同一 discover 策略一次运行最多推进 `max_auto_entries_per_strategy_batch`
3. 行业/概念集中度过高时，按 `candidate_score` 排序截断

行业/概念集中度算法：

1. 候选股票先按 `candidate_score DESC, confidence DESC, occurred_at DESC` 排序
2. 逐只尝试纳入时，统计当日已自动纳入股票的 `industry` 与核心 `concept_tag`
3. 若某一行业已达到 `max_same_industry_auto_entries_per_day`，则后续同一行业候选跳过
4. 若某一概念已达到 `max_same_concept_auto_entries_per_day`，则后续同一概念候选跳过
5. 若股票同时属于多个概念，以主概念或候选事件中显式给出的 `primary_theme` 为准
6. 若行业或概念信息缺失，则不享受自动纳入优先权，只能进入 `confirm_first` 或等待基础信息补全

## 9. `trial` 与 `active`

### 9.1 `trial`

含义：

1. 股票已被系统认为值得量化关注
2. 允许参与主扫描
3. 允许 BUY
4. 默认轻仓

约束：

1. 默认套用冷启动限仓
2. 默认不直接给满仓
3. `trial` 是观察态，不是淘汰态；未满足最短观察期前不得因为少量弱信号退回 `cooling`
4. 若 health_score 过低，且连续下行确认和最短观察期都满足，才允许退回 `cooling`

`trial` 仓位规则必须明确：

1. `trial` 的最终目标仓位 = `min(正常信号建议仓位 × trial_position_multiplier, trial_max_position_pct)`
2. 若现有 BUY 分层、冷启动限仓、再入场降仓、个股执行反馈或组合防守给出的倍率更严格，则取最小值
3. `trial` 不单独绕过资金槽规则，数量仍由现有 `position_sizing / capital_slots` 逻辑计算

默认值建议：

#### aggressive

1. `trial_position_multiplier = 0.50`
2. `trial_max_position_pct = 12.5`

#### stable

1. `trial_position_multiplier = 0.35`
2. `trial_max_position_pct = 10.0`

#### conservative

1. `trial_position_multiplier = 0.25`
2. `trial_max_position_pct = 7.5`

### 9.2 `active`

含义：

1. 股票已通过量化或强确认
2. 可参与正式扫描
3. 仓位建议由现有 BUY 分层、组合防守、个股执行反馈共同决定

### 9.3 `trial -> active` 升级条件

满足任一强趋势条件，并且 `health_score >= active_upgrade_threshold`：

1. `MA5 > MA10 > MA20`
2. `price > MA20` 持续 `active_upgrade_confirm_checkpoints` 个 checkpoint
3. 突破后回踩 `MA20` 不破
4. 多来源候选事件重新共振，且最近无连续失败

实现要求：

1. `trial -> active` 必须在状态机中显式实现，不能只写在 UI 或文档中。
2. `active_upgrade_confirm_checkpoints` 必须来自最近 checkpoint 的连续趋势确认计数，不得把单个 BUY 信号直接当作完整确认窗口。
3. `trial -> active` 只解除 `trial` 的轻仓限制，不绕过 BUY 分层、组合防守、个股执行反馈和资金槽 sizing。

## 10. `health_score` 设计

### 10.1 目标

`health_score` 用于衡量一只量化股票当前的风险状态和扫描优先级。

范围：`0 ~ 100`

硬约束：

1. `health_score` 不直接决定出池。
2. `health_score` 低时，只能导致：
   - `buy_threshold_delta` 上调
   - `position_size_multiplier` 下调
   - `max_position_pct` 下调
   - 补充扫描排序靠后
   - UI 风险解释增强
3. `trial / active -> cooling` 必须由行情确认的连续 `downtrend_hit` 触发。
4. `retired` 只能由用户强制出池或显式管理操作触发，不能由 `cooling` 自动批量触发。

### 10.2 构成

`health_score` 不再引入一套与 kernel 平行的五维打分体系，而是直接复用已有运行时指标的滑动窗口结果。

核心输入：

1. 最近 `health_score_lookback_checkpoints` 个 checkpoint 的 `tech_score`
2. 最近 `health_score_lookback_checkpoints` 个 checkpoint 的 `context_score`
3. 最近 `health_score_lookback_checkpoints` 个 checkpoint 的 `fusion_score`
4. 最近 `health_score_lookback_checkpoints` 个 checkpoint 的 `buy_strength_score`
5. 最近 `health_score_lookback_checkpoints` 个 checkpoint 的 `portfolio_execution_guard.status`
6. 最近 `health_score_lookback_checkpoints` 个 checkpoint 的 `stock_execution_feedback_gate.status`
7. 最近 `health_score_lookback_checkpoints` 个 checkpoint 的成交与止损结果
8. 候选事件的新鲜度不参与 `health_score`。候选事件只能用于入池推荐、恢复候选排序和初始建仓约束。

建议公式：

1. 先对 `tech_score / context_score / fusion_score / buy_strength_score` 做滑动窗口均值
2. 再统一映射到 `[0, 100]`，得到：
   - `normalized_tech_health`
   - `normalized_context_health`
   - `normalized_fusion_health`
   - `normalized_buy_strength_health`
3. 按当前 profile 的 `kernel_health_weights` 计算 `kernel_health_base`
4. 再叠加：
   - `execution_penalty`
   - `inactivity_penalty`
   - `reentry_watch_penalty`
5. 最终：

`health_score = clamp(kernel_health_base - execution_penalty - inactivity_penalty - reentry_watch_penalty, 0, 100)`

归一化公式必须统一，禁止各实现自行选择 min-max、z-score 或分档映射：

1. `normalized_tech_health = clamp(((avg_tech_score + 1) / 2) * 100, 0, 100)`
2. `normalized_context_health = clamp(((avg_context_score + 1) / 2) * 100, 0, 100)`
3. `normalized_fusion_health = clamp(avg_fusion_score * 100, 0, 100)`
4. `normalized_buy_strength_health = clamp(avg_buy_strength_score * 100, 0, 100)`
5. `kernel_health_base =`
   - `normalized_fusion_health * fusion_health_weight`
   - `+ normalized_buy_strength_health * buy_strength_health_weight`
   - `+ normalized_tech_health * tech_health_weight`
   - `+ normalized_context_health * context_health_weight`
6. `inactivity_penalty_base = min(no_buy_days, trial_no_buy_days_threshold) * 2.0`
7. `inactivity_penalty = inactivity_penalty_base * inactivity_penalty_multiplier`
8. `execution_penalty_base = (recent_stoploss_count * 5.0) + (blocked_streak * 3.0)`
9. `execution_penalty = execution_penalty_base * execution_penalty_multiplier`
10. 候选来源、候选事件数量、`candidate_score` 不得给 `health_score` 加分。它们最多影响入池推荐、初始 `trial` 仓位和恢复候选排序。

说明：

1. 这里假定 `tech_score/context_score ∈ [-1, 1]`
2. 假定 `fusion_score/buy_strength_score ∈ [0, 1]`
3. 若后续 kernel 分值域调整，必须同步修改此处统一公式，不能由调用方各自适配
4. `recent_stoploss_count` 默认取 `health_score_lookback_checkpoints` 窗口内已执行且命中止损或快速转弱失败的交易次数
5. `blocked_streak` 为状态快照中的连续阻断计数

要求：

1. `health_score` 的主输入必须来源于现有 kernel 和执行反馈，不得再平行定义一套独立的“趋势健康、信号健康、执行健康、时间健康”主评分体系
2. 各 profile 的归一化阈值和 penalty 参数可以配置，但必须挂靠现有策略 profile
3. `inactivity_penalty` 对 `trial` 和无持仓股票必须更敏感；当“连续无有效 BUY 天数”达到 `trial_no_buy_days_threshold` 时，应进入满额惩罚区间，而不是继续线性宽松递增
4. 冷启动样本不足时必须启用健康分下限保护，避免 1-3 个 checkpoint 的弱 HOLD 把新入池股票直接打入 `cooling`。
5. `health_score < cooling_threshold` 或 `health_score < retire_threshold` 不得单独作为状态流转条件。

冷启动样本保护：

1. 仅适用于 `trial` 且无持仓股票。
2. 当有效信号数量 `< trial_cold_start_min_checkpoints` 时，最终 `health_score = max(raw_health_score, trial_cold_start_health_floor)`。
3. 保护只影响生命周期状态判断，不修改原始信号分，不给 BUY 加分。
4. 保护证据必须写入 `snapshot_json.health`，至少包含 `cold_start_signal_count / cold_start_min_checkpoints / cold_start_health_floor`。

默认 profile 权重建议：

#### aggressive

1. `fusion_health_weight = 0.35`
2. `buy_strength_health_weight = 0.30`
3. `tech_health_weight = 0.20`
4. `context_health_weight = 0.15`
5. 候选支持不参与健康分加分
6. `execution_penalty_multiplier = 0.90`
7. `inactivity_penalty_multiplier = 0.80`
8. `reentry_watch_penalty_multiplier = 1.00`

#### stable

1. `fusion_health_weight = 0.30`
2. `buy_strength_health_weight = 0.25`
3. `tech_health_weight = 0.25`
4. `context_health_weight = 0.20`
5. 候选支持不参与健康分加分
6. `execution_penalty_multiplier = 1.00`
7. `inactivity_penalty_multiplier = 1.00`
8. `reentry_watch_penalty_multiplier = 1.10`

#### conservative

1. `fusion_health_weight = 0.25`
2. `buy_strength_health_weight = 0.15`
3. `tech_health_weight = 0.30`
4. `context_health_weight = 0.30`
5. 候选支持不参与健康分加分
6. `execution_penalty_multiplier = 1.20`
7. `inactivity_penalty_multiplier = 1.20`
8. `reentry_watch_penalty_multiplier = 1.25`

约束：

1. `fusion_health_weight + buy_strength_health_weight + tech_health_weight + context_health_weight = 1.0`
2. aggressive 对短期趋势转强更敏感，但对 inactivity 和单次执行失败更宽
3. conservative 对 execution 和 reentry 风险更敏感，对新候选支持加分更保守

### 10.3 弱警告与强下行

不能简单按 `HOLD` 扣分，也不能只在强下行时才开始处理。系统必须同时定义：

1. `weakening_warning`
2. `downtrend_hit`

`weakening_warning` 用于提前预警，满足以下任意组合即可：

1. `final_action = HOLD` 且 `tech_score < weak_warning_tech_threshold`
2. `fusion_score` 低于 `buy_threshold` 但尚未接近 `sell_threshold`
3. `price` 跌回 `MA20` 附近且 `buy_strength_score` 明显回落
4. `portfolio_execution_guard` 连续将 BUY 降级为 `weak_buy`

`downtrend_hit` 用于触发状态降级，满足以下更强条件之一：

1. `final_action = SELL`
2. `final_action = HOLD` 且 `tech_score <= 0` 且 `fusion_score` 持续转弱
3. `price < MA20` 且 `MA20_slope <= 0`
4. 连续出现 `weakening_warning` 并达到 `warning_to_downtrend_threshold`
5. 近期执行反馈显示“买入后快速止损”或“连续 blocked 且无恢复”

规则：

1. `weakening_warning` 增加预警计数，不直接把股票移出量化
2. `downtrend_hit` 只参与 `exit_only / cooling` 的状态判断，不得自动推动 `cooling -> retired`

默认 profile 建议：

#### aggressive

1. `weak_warning_tech_threshold = 0.10`
2. `warning_to_downtrend_threshold = 4`

#### stable

1. `weak_warning_tech_threshold = 0.15`
2. `warning_to_downtrend_threshold = 3`

#### conservative

1. `weak_warning_tech_threshold = 0.20`
2. `warning_to_downtrend_threshold = 2`

### 10.4 加分与恢复规则

加分不能只因为“买入触发”，而必须基于后续结果：

1. 成功买入后未快速止损
2. 买入后若干 checkpoint 仍保持趋势结构
3. 最近出现新的高质量候选事件只能作为“是否重新纳入量化”的推荐证据，不能直接抬高健康分
4. 从 `cooling` 低频重评估中恢复出趋势确认
5. `exit_only` 状态下成功完成减仓或清仓后，没有再次出现弱警告

## 11. 自动退出与降级

生命周期降级的设计目标是“风险感知管理”，不是“预测性剔除”。系统不得因为股票暂时弱势就让 aggressive 策略失去可交易标的。降级只能改变扫描/买入/仓位口径；真正退出必须慢、可解释、可恢复。

### 11.1 `exit_only`

触发条件：

1. 当前存在 live-sim 持仓
2. 连续 `downtrend_hit >= exit_only_downtrend_streak`
3. `health_score < exit_only_threshold` 只能提高风险解释和排序优先级，不能单独触发 `exit_only`
4. 若最近 BUY 发生在同一交易日，处于 T+1 生命周期保护期，不允许当天立刻切入 `exit_only`

效果：

1. 禁止新 BUY / 新加仓
2. 继续允许 SELL / HOLD / 风控
3. 保留在主扫描中，直到持仓清空

### 11.2 `cooling`

触发条件：

1. 当前无 live-sim 持仓
2. 连续 `downtrend_hit >= downtrend_cooling_streak`
3. `trial` 股票必须先满足 `trial_min_dwell_checkpoints`，不得在入池当日凭少量 checkpoint 进入 `cooling`
4. 对 aggressive 策略，若进入 `cooling` 会导致默认主扫描覆盖低于 `min_scan_coverage`，则不得立即进入 `cooling`，而应进入带严格 gate 的 `guarded_scan` 派生扫描模式

效果：

1. 不参与默认主扫描排序
2. 可在最小扫描覆盖不足时作为补充扫描候选
3. 补充扫描必须使用 `cooling_supplemental_gate`
4. 设置 `stock_universe_quant_state.cooling_until`，作为最短冷却观察期

### 11.3 `retired`

触发条件：

1. 用户手工强制出池，且当前无 live-sim 持仓
2. 用户手工强制出池时仍有持仓，则先进入 `exit_only`；持仓清空后再进入 `retired`
3. 系统自动流程不得因为 `cooling` 持续下行批量进入 `retired`
4. `cooling` 冷却期后仍持续下行时，继续保持 `cooling`，并通过 `cooling_supplemental_gate` 提高 BUY 门槛、压缩仓位上限和降低扫描优先级

效果：

1. `quant_enabled=0`
2. 不参与默认扫描或补充扫描
3. 仅保留在股票池和事件历史中

## 12. 再入池与复活

### 12.1 `cooling -> trial`

满足：

1. 冷却期已结束
2. 补充扫描或复评 checkpoint 中，趋势结构重新满足 active 级恢复条件
3. `health_score >= active_upgrade_threshold`
4. 连续趋势确认数量 `active_trend_confirm_checkpoints >= active_upgrade_confirm_checkpoints`
5. `health_score >= cooling_threshold` 只作为排序和解释条件，不足以单独恢复
6. 若同时出现新候选事件，可用于排序和 UI 解释，但不是恢复的必要条件
7. 若 cooling 股票被新的历史候选事件或实时发现事件重新命中，只能提高补充扫描优先级；不能仅凭候选来源直接恢复到 `trial`
8. 恢复成功后只能进入 `trial`，不能直接进入 `active`

补充扫描与复评要求：

1. 每个 checkpoint 先构造默认主扫描集合：`trial / active / exit_only`。
2. 若默认主扫描集合数量 `< min_scan_coverage`，从 `cooling` 中补充 `min_scan_coverage - 默认主扫描数量` 只。
3. 补充排序：
   - `has_recent_candidate_support DESC`
   - `recovery_score DESC`
   - `health_score DESC`
   - `last_health_evaluated_at ASC`
   - `stock_code ASC`
4. `has_recent_candidate_support` 只表示最近发现/研究重新命中，不直接加健康分。
5. `recovery_score` 必须来自当前 checkpoint 的行情确认，推荐公式：
   - `trend_recovery_score * 0.45`
   - `buy_strength_score * 0.25`
   - `ma20_reclaim_score * 0.20`
   - `recent_candidate_support_score * 0.10`
6. 补充扫描股票可以产生 BUY 信号，但必须应用更严格的 `cooling_supplemental_gate`。
7. `cooling_supplemental_gate` 下的 BUY 必须同时满足 `buy_tier = strong_buy`、`buy_strength_score >= 0.45 + buy_threshold_delta`、趋势确认成立；`weak_buy` 或“背离试探”即使站上均线也必须转为 HOLD。
8. 只有补充扫描产生强恢复信号，并满足 active 级健康分与连续趋势确认时，状态才恢复为 `trial` 并写入 `cooling_recovered_to_trial` 事件；恢复事件必须包含行情确认理由，而不能只写候选来源。

### 12.2 `retired -> trial`

满足：

1. `retired_reactivation_check_enabled = true`
2. 新 discover / research / manual 事件重新支持
3. `candidate_score >= high_reentry_threshold`
4. 已满足 `retired_min_dwell_days`
5. 不处于 `manual_ban`

效果：

1. 标记为“二次入池”
2. 设置 `stock_universe_quant_state.reentry_watch_until = now + 72h`
3. 72 小时观察期内：
   - 提高降级敏感度
   - 提高扣分速度
   - 默认只能以 `trial` 身份运行

## 13. 防抖与最短停留期

为避免 `trial -> cooling -> trial` 高频抖动，增加防抖：

1. `trial_min_dwell_checkpoints`
2. `cooling_min_dwell_days`
3. `retired_min_dwell_days`

规则：

1. `trial` 在最短停留期内，不允许进入 `cooling` 或 `retired`
2. 进入 `cooling` 时必须设置 `cooling_until = checkpoint_time + cooling_min_dwell_days`
3. `cooling` 在最短停留期内，不允许自动恢复，也不允许自动退休
4. `retired` 在最短停留期内，即使 `candidate_score >= high_reentry_threshold` 也不得重新激活；候选事件返回 `reason_code = retired_dwell_blocked`
5. `retired` 进入时必须记录 `retired_at`，用于后续最短停留期判断

## 14. 手工覆盖

### 14.1 手工覆盖类型

`quant_manual_override` 允许：

1. `manual_pin`
   - 系统不得自动 `retired`

2. `manual_pause`
   - 股票进入 `manual_paused`

3. `manual_ban`
   - 系统不得自动重新纳入

4. `none`
   - 无手工覆盖

### 14.2 优先级

优先级：

`manual_ban > manual_pause > manual_pin > auto rules`

## 15. 实时模拟行为

### 15.1 主扫描范围

`/live-sim` 每个 checkpoint 的扫描分两层：

1. 默认主扫描
2. 覆盖不足时的补充扫描

默认主扫描处理：

1. `quant_enabled=1`
2. `quant_status in ('trial', 'active', 'exit_only')`

其中：

1. `trial / active` 允许 BUY
2. `exit_only` 禁止 BUY，只允许 SELL/HOLD

补充扫描处理：

1. 当默认主扫描数量 `< min_scan_coverage` 时启用
2. 仅从 `quant_status='cooling'` 且不在 `manual_ban/manual_paused` 的股票中选取
3. 选取数量 = `min_scan_coverage - 默认主扫描数量`
4. 补充股票必须带 `lifecycle_gate.mode = cooling_supplemental`
5. 补充股票不得绕过涨跌停、T+1、组合防守、BUY 分层和资金槽规则

执行约束必须落在信号生成层，而不是只靠 UI 或调度器过滤：

1. 当股票 `quant_status = exit_only` 且原始决策动作是 `BUY` 或 `ADD` 时，信号生成层必须强制改写为 `HOLD`
2. 改写后的信号必须保留 explain 字段，明确标注 `decision_type = exit_only_blocked`
3. 若当前代码仍由 `SignalCenterService.create_signal` 负责最终信号落库，则该约束应在该层实现；若后续信号生成入口调整，则必须迁移到等价的统一 signal finalization 层

### 15.2 生命周期 gate

生命周期不直接 veto BUY，除 `exit_only` 外只提供 gate 给执行层消费。

Gate 输出字段：

1. `mode`
2. `buy_threshold_delta`
3. `size_multiplier`
4. `max_position_pct`
5. `requires_strong_confirmation`
6. `reason_code`
7. `reason_text`

默认 gate：

| gate | buy_threshold_delta | size_multiplier | max_position_pct | requires_strong_confirmation |
|---|---:|---:|---:|---:|
| `normal_scan` | `0.00` | `1.00` | profile/default | false |
| `trial_light` | `0.03` | `trial_position_multiplier` | `trial_max_position_pct` | false |
| `guarded_scan` | `0.08` | `0.35` | `4.0` | true |
| `cooling_supplemental` | `0.12` | `0.20` | `3.0` | true |
| `exit_only` | N/A | `0.00` | `0.0` | N/A |

执行层要求：

1. SignalCenterService 或等价 signal finalization 层必须把 `lifecycle_gate` 写入 signal explain。
2. BUY 分层计算必须先应用 `buy_threshold_delta`，再决定 weak/normal/strong。
3. 执行仓位必须取 `min(existing_caps, max_position_pct)`，并应用 `size_multiplier`。
4. `cooling_supplemental` 只有在满足强确认时才允许 BUY；否则只能记录 HOLD/观察。

### 15.3 低频重评估

补充规则：

1. 固定低频重评估仍保留，用于更新 `health_score`、`recovery_score` 和 UI 解释。
2. 低频重评估不得替代最小扫描覆盖；覆盖不足时必须走 15.1 的补充扫描。
3. 实时量化每次 opportunistic review 最多处理 `cooling_review_batch_size` 只，不得固定写死为 5 只。
4. 实时量化演练在每个交易日第一个 checkpoint 必须全量复评已到期 `cooling` 股票，其他 checkpoint 再按 `cooling_review_batch_size` 轮转。
5. opportunistic review 的优先级按：
   - `last_health_evaluated_at` 最早优先
   - 其次 `health_score` 较高者优先
   - 再其次按股票代码稳定排序
6. opportunistic review 只读取已有 local cache，不额外触发远程拉取
7. 即使启用 opportunistic review，仍需保留固定低频重评估兜底

### 15.4 不改变已有执行算法

本 spec 不改变：

1. BUY 分层
2. 组合防守
3. 个股执行反馈
4. 资金槽
5. 止盈/止损

生命周期系统只决定“这只股票是否值得继续参与实时量化管理”，不直接替代信号算法。

## 16. 历史回放行为

### 16.1 Phase 1 规则

历史回放默认行为保持不变：

1. 启动任务时记录当前 `quant_enabled=1` 的股票范围快照
2. 不在回放过程中模拟生命周期动态变化
3. 不因为 live-sim 中的 `cooling / retired` 而重写历史任务语义

### 16.2 后续扩展

Phase 2 可新增高级选项：

1. `freeze_universe`（默认）
2. `simulate_universe_lifecycle`（高级模式）

本 spec Phase 1 不实现第二种模式。

## 17. UI 设计

本节不只定义“显示什么”，还要定义“放在哪里、如何交互、改哪些组件”。前端实现不得自行发挥页面结构。

### 17.1 总体布局原则

1. 不新增顶层页面
2. 生命周期能力优先落在现有页面中：
   - `/discover`
   - `/research`
   - `/main`
   - `/live-sim`
3. `/live-sim` 仍保持现有主结构：
   - 顶部配置面板
   - 中部主 Tab（候选池 / 信号 / 成交 / 持仓）
   - 生命周期能力优先加在“候选池”Tab 内，不新增独立“状态”Tab
4. `/main` 不新增整页二级路由，新增的是工作台中的量化概览区域

### 17.2 `/discover`

#### 布局

1. 在每个发现策略结果表格中新增一列：`量化候选状态`
2. 在表格工具栏右侧新增批量操作区：
   - `加入股票池`
   - `纳入量化`
   - `忽略自动纳入`
3. 在每行操作列新增单行操作：
   - `纳入量化`
   - `忽略自动纳入`
4. 若系统级 `auto_entry_mode = confirm_first`，则工具栏中必须显示：
   - `仅看 eligible` 筛选
   - `一键批量纳入量化`

#### 必须展示的字段

1. 原始发现评分
2. 置信度
3. 趋势方向
4. 是否达到 `trial_threshold`
5. 是否达到 `strong_candidate_threshold`
6. 不可自动入池的阻断原因
7. `eligible / skipped / already_in_quant / cooling_blocked` 状态标签

#### 交互

1. 单行 `纳入量化`
   - 点击后弹确认框
   - 确认后调用 promote-to-trial API
   - 成功后本行保留在原表中，但状态改为 `already_in_quant`
   - 失败时弹 toast，并在本行显示失败原因
2. 批量 `一键批量纳入量化`
   - 仅对当前选中行生效
   - 点击后弹确认框，显示成功数 / 跳过数 / 风险提示
   - 成功后不从发现结果表中移除，只更新状态标签与原因
   - 部分失败必须回显逐行失败原因
3. `忽略自动纳入`
   - 可单行或批量执行
   - 成功后本行状态变为 `skipped`

### 17.3 `/research`

#### 布局

1. 对任何能落到明确股票的研究输出，复用 `/discover` 的量化入口
2. 在研究结果股票列表中新增：
   - `量化候选状态` 列
   - 操作列
3. 工具栏复用批量操作：
   - `纳入量化`
   - `忽略自动纳入`

#### 必须展示的字段

1. 研究结果关联股票
2. 候选事件来源
3. 是否可纳入 `trial`
4. 手工纳入与忽略入口

#### 交互

1. 与 `/discover` 保持一致
2. 若研究结果引用的是同一股票的多条证据，批量纳入时必须合并成同一只股票的单次候选事件，而不是重复创建

### 17.4 `/main`

#### 布局

1. 在现有工作台主内容区中，于关注列表上方新增一组 `量化概览卡片`
2. 卡片固定为 5 张，横向排列；空间不足时折为 3+2：
   - `待纳入量化`
   - `量化`
   - `只出场管理`
   - `冷却中`
   - `已退出待重评估`
3. 卡片下方不再新增长表；详细列表一律跳转 `/live-sim` 对应筛选结果
4. `QuantOverviewCards` 数据必须通过独立接口异步加载，不得继续堆入现有 `/api/v1/workbench` 主快照

#### 卡片内容

每张卡片必须展示：

1. 状态名称
2. 当前计数
3. top 3 股票
4. 一条最近原因摘要

#### 交互

1. `待纳入量化` 卡片不跳转 `/live-sim`
2. 点击 `待纳入量化` 卡片跳转 `/discover`
3. 跳转后自动打开：
   - `仅看 eligible`
   - 或等价的 `eligible` 状态筛选
4. 其余卡片跳转 `/live-sim`
5. 跳转后自动带上状态筛选参数：
   - `量化` -> `trial`
   - `只出场管理` -> `exit_only`
   - `冷却中` -> `cooling`
   - `已退出待重评估` -> `retired`
6. 若存在手工恢复入口，只放在 `/live-sim`，不放在 `/main`

### 17.5 `/live-sim`

#### 布局

1. 保持现有：
   - 顶部配置面板
   - Tab：候选池 / 信号 / 成交 / 持仓
2. 生命周期能力只放在 `候选池` Tab 内
3. 顶部配置面板只展示 `量化池自动管理` 当前运行口径摘要，不在实时模拟页直接编辑系统级开关
4. 系统级开关必须放在 `/settings` 的 `量化策略自动化` 区块中，包含：
   - `生命周期管理` 总开关
   - `自动入池模式` 下拉
   - `自动出池` 开关
   - 详细说明文案
5. `/live-sim` 运行口径摘要文案必须展示：
   - 生命周期管理：开启 / 关闭
   - 自动入池模式：`manual_only / confirm_first / auto_trial`
   - 自动出池：开启 / 关闭
6. 在候选池表格上方新增工具栏，顺序固定为：
   - 左侧：状态筛选 chips
   - 中间：搜索 / 其他已有筛选
   - 右侧：批量操作和全局统计
7. 状态筛选使用 chip/filter pills，不新增 Tab：
   - `trial`
   - `active`
   - `exit_only`
   - `cooling`
   - `retired`
   - `manual_paused`
8. 默认选中：
   - `trial + active + exit_only`
9. `cooling`、`retired` 和 `manual_paused` 通过额外点击显示，不默认占用主视图

#### 候选池表格必须展示的字段

1. 股票代码 / 名称
2. 当前 `quant_status`
3. `candidate_score`
4. `health_score`
5. `downtrend_streak`
6. `weakening_warning_streak`
7. `cooling_until`
8. `quant_entry_source`
9. 最近一次状态变更原因
10. `quant_auto_managed`
11. `quant_manual_override`

#### 交互

1. 状态筛选 chips
   - 只影响候选池表格
   - 不影响信号 / 成交 / 持仓 Tab
2. 系统级 `生命周期管理 / 自动入池模式 / 自动出池` 只在 `/settings` 修改；`/live-sim` 不提供这些编辑控件
3. `/settings` 修改后只影响后续新产生的候选事件和生命周期推进，不回溯改写已存在股票状态
4. `自动出池` 关闭后仍计算 `health_score` 并展示 weakening/downtrend，但不自动执行 `trial/active/exit_only -> cooling`；`retired` 仅由手工强制出池产生
5. `quant_auto_managed` 开关
   - 放在每行操作列，不做全局总开关
   - 关闭自动管理时弹二次确认
   - 成功后本行变更为 `manual_pin` 或相应手工覆盖状态
   - 关闭后该股票不再受自动入池、自动出池、自动恢复影响
6. 手工恢复按钮
   - 仅对 `cooling` / `manual_paused` / `retired` 展示
   - 按钮统一命名为 `恢复到量化`
   - 不允许 UI 直接恢复到 `active`
   - 点击后弹确认框，确认后只恢复到 `trial`
7. `health_score`
   - 使用颜色条或进度条显示
   - hover 必须显示 breakdown：fusion / buy_strength / tech / context / penalty 概要
8. 最近状态原因
   - 默认单行摘要
   - 点击可展开最近一次生命周期事件 explain
9. 自动开启后的可视反馈必须明显可见：
   - 新进入量化的股票显示 `trial` badge 和“量化”中文标签
   - 自动进入 `cooling` 的股票从默认列表中移出，但在 `cooling` 筛选下可见
   - 自动进入 `retired` 的股票从默认列表中移出，并保留状态原因
   - `already_in_quant / eligible / skipped / cooling_blocked` 等标签在来源页同步更新

### 17.6 通知视图

#### 布局

1. 通知按事件类型分组展示
2. 每组固定显示 top N
3. 溢出部分显示“还有 X 只”

#### 必须展示

1. 事件类型分组
2. 代码 / 名称
3. 状态变化
4. 关键原因
5. 候选分或健康度变化
6. 是否手工覆盖

### 17.7 页面级 UI 元素矩阵

| 页面 | 新增/修改 UI 元素 | 位置 | 交互行为 |
|---|---|---|---|
| `/discover` | `EligibleBadge` 状态列 | 候选表格新增列 | 静态展示状态与阻断原因 |
| `/discover` | `纳入量化` 行按钮 | 每行操作列 | 确认弹窗 -> 单行提交 -> toast -> 行状态更新 |
| `/discover` | `一键批量纳入量化` | 表格工具栏 | 选中多行 -> 确认弹窗 -> 批量提交 -> 部分失败逐行回显 |
| `/research` | 复用 `EligibleBadge` | 研究结果表格新增列 | 与 discover 一致 |
| `/research` | 批量纳入 / 忽略按钮 | 工具栏 | 与 discover 一致 |
| `/main` | `QuantOverviewCards` | 关注列表上方 | `待纳入量化` 跳 `/discover?eligible=1`，其余跳 `/live-sim` 对应筛选 |
| `/settings` | `LifecycleMasterSwitch` | 量化策略自动化区块 | 控制生命周期自动管理总开关 |
| `/settings` | `AutoEntryModeSelect` | 量化策略自动化区块 | 切换 `manual_only / confirm_first / auto_trial` |
| `/settings` | `AutoExitSwitch` | 量化策略自动化区块 | 控制自动出池开启/关闭 |
| `/live-sim` | `LifecycleSummaryBadgeGroup` | 顶部配置面板 | 只读展示当前运行口径摘要，并提示到设置页调整 |
| `/live-sim` | `StatusFilterChips` | 候选池表格上方工具栏左侧 | 过滤候选池列表，默认 `trial+active+exit_only`，支持 `manual_paused` |
| `/live-sim` | `HealthScoreBar` | 候选池表格列 | hover 展示 breakdown |
| `/live-sim` | `AutoManageToggle` | 每行操作列 | 二次确认后切换 auto managed 状态 |
| `/live-sim` | `RestoreToTrialButton` | 每行操作列 | 仅对 `cooling/manual_paused/retired` 展示 |

### 17.8 组件改造清单

新增组件：

1. `EligibleBadge`
2. `BatchPromoteDialog`
3. `QuantOverviewCards`
4. `LifecycleMasterSwitch`
5. `AutoEntryModeSelect`
6. `AutoExitSwitch`
7. `LifecycleSummaryBadgeGroup`
8. `StatusFilterChips`
9. `HealthScoreBar`
10. `AutoManageToggle`
11. `RestoreToTrialButton`

需要改造的现有页面/组件：

1. `DiscoverPage`
2. 发现结果表格组件
3. `ResearchPage`
4. 各研究结果股票表格组件
5. `WorkbenchPage`
6. `LiveSimPage`
7. 候选池表格组件

## 18. 通知

### 18.1 通知策略

默认策略：

1. `daily_summary`
   - 每日汇总状态变更
2. `instant_retire`
   - 进入 `retired` 立即通知

可选即时通知事件：

1. `trial_auto_added`
2. `downgraded_to_exit_only`
3. `recovered_from_cooling`

`daily_summary` 的格式要求：

1. 按变更类型分组：
   - 新纳入 `trial`
   - 升级到 `active`
   - 降级到 `exit_only`
   - 进入 `cooling`
   - 进入 `retired`
   - 从 `cooling` 恢复
2. 每组最多展示 `top_n = 10` 只股票
3. 超出部分以“还有 X 只”汇总
4. 每只股票一行，最少包含：代码、名称、状态变化、关键原因
5. 若当天无变更，则不发送空摘要

### 18.2 通知内容

必须包含：

1. 股票代码 / 名称
2. 状态变更
3. 触发原因
4. 候选分或健康度变化
5. 是否有手工覆盖

## 19. 配置项

新增配置分组：`quant_universe_lifecycle_policy`

### 19.1 基础配置

1. `quant_universe_lifecycle_enabled`
2. `auto_exit_enabled`
3. `auto_entry_mode`
4. `trial_threshold`
5. `strong_candidate_threshold`
6. `high_reentry_threshold`
7. `active_upgrade_threshold`
8. `active_upgrade_confirm_checkpoints`
9. `max_auto_entries_per_batch`
10. `max_auto_entries_per_day`
11. `max_auto_entries_per_strategy_batch`
12. `max_same_industry_auto_entries_per_day`
13. `max_same_concept_auto_entries_per_day`

说明：

1. `quant_universe_lifecycle_enabled` 是系统级总开关，不按 profile 区分
2. `auto_exit_enabled` 是系统级开关，不按 profile 区分
3. `auto_entry_mode` 是系统级运行开关，不按 profile 区分
4. 其余阈值和容量上限按 profile 配置

### 19.2 健康度配置

1. `exit_only_threshold`
2. `cooling_threshold`
3. `retire_threshold`
4. `exit_only_downtrend_streak`
5. `downtrend_cooling_streak`
6. `trial_no_buy_days_threshold`
7. `reentry_watch_hours`
8. `weak_warning_tech_threshold`
9. `warning_to_downtrend_threshold`
10. `health_score_lookback_checkpoints`
11. `candidate_support_lookback_days`

### 19.3 防抖配置

1. `trial_min_dwell_checkpoints`
2. `cooling_min_dwell_days`
3. `retired_min_dwell_days`

### 19.4 扫描配置

1. `cooling_review_interval_minutes`
2. `retired_reactivation_check_enabled`
3. `min_scan_coverage`
4. `cooling_supplemental_gate`

### 19.5 `trial` 仓位配置

1. `trial_position_multiplier`
2. `trial_max_position_pct`

所有配置支持 aggressive / stable / conservative 三套 profile 默认值。

### 19.6 候选分权重配置

1. `source_score_weight`
2. `confidence_weight`
3. `trend_weight`
4. `multi_source_weight`
5. `liquidity_penalty_multiplier`
6. `cooldown_penalty_multiplier`
7. `manual_priority_bonus_multiplier`

### 19.7 `health_score` 权重与 penalty 配置

1. `fusion_health_weight`
2. `buy_strength_health_weight`
3. `tech_health_weight`
4. `context_health_weight`
5. `execution_penalty_multiplier`
6. `inactivity_penalty_multiplier`
7. `reentry_watch_penalty_multiplier`

说明：候选来源和候选事件不得给 `health_score` 加分，因此不再配置 `candidate_support_bonus_multiplier`。候选支持只进入补充扫描排序和恢复 explain。

### 19.8 profile 绑定要求

1. `quant_universe_lifecycle_policy` 必须作为策略 profile 的子配置保存
2. aggressive / stable / conservative 默认值必须随 profile 版本持久化
3. UI 修改任一 profile 时，只影响该 profile，不得覆盖其他 profile
4. 运行时必须按任务或 live-sim 当前绑定的 profile 读取对应生命周期配置
5. 若现有 UI 文案使用“中性”而内部 profile id 使用 `stable`，两者视为同一 profile 槽位，不得再新增第四个中间 profile

### 19.9 关键默认值矩阵

除前文已定义的 `trial_threshold / strong_candidate_threshold / high_reentry_threshold`、`trial_position_multiplier / trial_max_position_pct`、候选分权重和 `health_score` 权重外，核心生命周期阈值默认值建议如下：

系统级默认值：

1. `quant_universe_lifecycle_enabled = true`
2. `auto_exit_enabled = true`
3. `auto_entry_mode = auto_trial`

#### aggressive

1. `active_upgrade_threshold = 60`
2. `active_upgrade_confirm_checkpoints = 2`
3. `exit_only_threshold = 38`
4. `exit_only_downtrend_streak = 3`
5. `cooling_threshold = 30`
6. `retire_threshold = 22`
7. `downtrend_cooling_streak = 3`
8. `trial_no_buy_days_threshold = 12`
9. `reentry_watch_hours = 72`
10. `health_score_lookback_checkpoints = 8`
11. `candidate_support_lookback_days = 5`
12. `trial_min_dwell_checkpoints = 16`
13. `trial_cold_start_min_checkpoints = 8`
14. `trial_cold_start_health_floor = 45`
15. `cooling_min_dwell_days = 3`
16. `retired_min_dwell_days = 14`
17. `cooling_review_interval_minutes = 30`
18. `cooling_review_batch_size = 20`
19. `max_auto_entries_per_batch = 6`
20. `max_auto_entries_per_day = 20`
21. `max_auto_entries_per_strategy_batch = 3`
22. `max_same_industry_auto_entries_per_day = 3`
23. `max_same_concept_auto_entries_per_day = 3`
24. `min_scan_coverage = 6`
25. `guarded_buy_threshold_delta = 0.08`
26. `guarded_size_multiplier = 0.35`
27. `guarded_max_position_pct = 4.0`
28. `cooling_supplemental_buy_threshold_delta = 0.12`
29. `cooling_supplemental_size_multiplier = 0.20`
30. `cooling_supplemental_max_position_pct = 3.0`

#### stable

1. `active_upgrade_threshold = 68`
2. `active_upgrade_confirm_checkpoints = 3`
3. `exit_only_threshold = 45`
4. `exit_only_downtrend_streak = 3`
5. `cooling_threshold = 36`
6. `retire_threshold = 28`
7. `downtrend_cooling_streak = 3`
8. `trial_no_buy_days_threshold = 10`
9. `reentry_watch_hours = 96`
10. `health_score_lookback_checkpoints = 10`
11. `candidate_support_lookback_days = 7`
12. `trial_min_dwell_checkpoints = 24`
13. `trial_cold_start_min_checkpoints = 10`
14. `trial_cold_start_health_floor = 50`
15. `cooling_min_dwell_days = 5`
16. `retired_min_dwell_days = 21`
17. `cooling_review_interval_minutes = 60`
18. `cooling_review_batch_size = 12`
19. `max_auto_entries_per_batch = 4`
20. `max_auto_entries_per_day = 12`
21. `max_auto_entries_per_strategy_batch = 2`
22. `max_same_industry_auto_entries_per_day = 2`
23. `max_same_concept_auto_entries_per_day = 2`
24. `min_scan_coverage = 4`
25. `guarded_buy_threshold_delta = 0.10`
26. `guarded_size_multiplier = 0.30`
27. `guarded_max_position_pct = 3.0`
28. `cooling_supplemental_buy_threshold_delta = 0.15`
29. `cooling_supplemental_size_multiplier = 0.15`
30. `cooling_supplemental_max_position_pct = 2.0`

#### conservative

1. `active_upgrade_threshold = 75`
2. `active_upgrade_confirm_checkpoints = 4`
3. `exit_only_threshold = 52`
4. `exit_only_downtrend_streak = 2`
5. `cooling_threshold = 42`
6. `retire_threshold = 34`
7. `downtrend_cooling_streak = 2`
8. `trial_no_buy_days_threshold = 8`
9. `reentry_watch_hours = 120`
10. `health_score_lookback_checkpoints = 12`
11. `candidate_support_lookback_days = 10`
12. `trial_min_dwell_checkpoints = 40`
13. `trial_cold_start_min_checkpoints = 12`
14. `trial_cold_start_health_floor = 55`
15. `cooling_min_dwell_days = 7`
16. `retired_min_dwell_days = 30`
17. `cooling_review_interval_minutes = 90`
18. `cooling_review_batch_size = 8`
19. `max_auto_entries_per_batch = 2`
20. `max_auto_entries_per_day = 6`
21. `max_auto_entries_per_strategy_batch = 1`
22. `max_same_industry_auto_entries_per_day = 1`
23. `max_same_concept_auto_entries_per_day = 1`
24. `min_scan_coverage = 2`
25. `guarded_buy_threshold_delta = 0.12`
26. `guarded_size_multiplier = 0.25`
27. `guarded_max_position_pct = 2.0`
28. `cooling_supplemental_buy_threshold_delta = 0.18`
29. `cooling_supplemental_size_multiplier = 0.10`
30. `cooling_supplemental_max_position_pct = 1.5`

约束：

1. aggressive 允许更多量化标的与更慢退场，但仍受 `exit_only` 和组合风控约束
2. conservative 更快降级、更少自动纳入、更低行业集中度容忍度
3. stable 作为中性模板，所有默认值必须位于 aggressive 和 conservative 之间

## 20. 刷新与数据边界约束

本 spec 必须遵守当前刷新架构：

1. 候选事件生成不得隐式触发 AI 远程分析
2. 生命周期管理不得绕过 local-first 行情技术刷新
3. `cooling` 低频复评仍走本地行情技术缓存优先
4. 历史回放不复用实时 quote 逻辑
5. live-sim 与 replay 的信号、成交、账户表继续隔离

与 `StockUniverseService` 的协作规则：

1. 候选事件写入后，若股票尚未存在于 `stock_universe`，由 `StockUniverseService` 负责创建最小股票主对象
2. 若股票存在但 `basic_info_missing=1`：
   - `QuantUniverseManager` 只能创建低优先级 `basic_info` refresh job
   - 不得同步触发远程拉取
   - 自动模式下，该股票最多进入 `confirm_first`，不得直接 `auto_trial`
3. `cooling` 和 `retired` 股票仍允许参与：
   - 日级 `basic_info`
   - 日级 `fundamental`
   - 低频 `flow_sentiment`
4. `cooling` 股票若被选入补充扫描，允许读取当前 local-first 行情技术快照；若本地缓存未覆盖，不得为单只 cooling 股票同步阻塞式远程拉取
5. `retired` 股票不参与高频 `quote_realtime` 主扫描，只在新候选事件或用户操作后重新进入评估
6. 若某股票处于 `trial / active / exit_only`，其行情技术刷新仍完全复用现有实时模拟 local-first 调度
7. 若某股票被 `manual_pause` 或 `manual_ban`，系统不得因为刷新结果变化而自动恢复其扫描状态

### 20.1 端到端数据流

生命周期相关数据流必须明确为以下顺序：

1. `discover / research / AI / manual` 产生候选输入
2. 候选输入被标准化为 `stock_universe_candidate_events`
3. `QuantUniverseManager` 聚合候选事件，计算 `candidate_score`
4. 通过前置门槛、容量控制和系统级 `auto_entry_mode` 判断：
   - 仅标记 `eligible`
   - 进入 `trial`
   - 或跳过并记录原因
5. 生命周期状态写入：
   - `stock_universe.quant_status`
   - `stock_universe.quant_enabled`
   - `stock_universe_quant_state`
   - `stock_universe_quant_events`
6. `/live-sim` 默认主扫描读取：
   - `quant_enabled=1`
   - `quant_status in ('trial', 'active', 'exit_only')`
7. 若默认主扫描覆盖低于 `min_scan_coverage`，补充读取：
   - `quant_enabled=1`
   - `quant_status='cooling'`
   - 按最近候选支持、恢复分、健康分和最久未评估排序
8. 每次扫描后更新：
   - `health_score`
   - `warning/downtrend` 计数
   - 生命周期状态
9. `cooling` 股票同时进入低频重评估链路，用于更新恢复解释和排序
10. `retired` 股票仅在高门槛候选事件触发时重新进入评估
11. UI 只消费状态表与事件表提供的聚合结果，不直接从原始信号表拼装生命周期口径

### 20.2 数据口径来源

为避免前后端各自解释，UI 字段来源必须统一：

1. `candidate_score`、`health_score`、`cooling_until`、streak 类字段来自 `stock_universe_quant_state`
2. 最近状态变化与原因来自 `stock_universe_quant_events`
3. 股票主身份信息来自 `stock_universe`
4. 原始信号解释、决策 explain 仍来自 live-sim / replay 各自信号表
5. 不允许 UI 直接用原始信号表重新推导生命周期状态，避免与后台规则漂移

### 20.3 HTTP API 合同

UI 第 17 节引用的交互必须落到明确 API，不允许只写“调用某个接口”而不定义签名。

| 端点 | 方法 | 用途 | 请求 | 返回 |
|---|---|---|---|---|
| `/api/v1/quant/universe/state` | `GET` | 获取生命周期聚合状态列表 | `?status=trial,active&keyword=...&page=...` | `{ items: [{ stock_code, stock_name, quant_status, candidate_score, health_score, downtrend_streak, weakening_warning_streak, cooling_until, quant_entry_source, quant_auto_managed, quant_manual_override, latest_reason }], total }` |
| `/api/v1/quant/universe/actions/promote-to-trial` | `POST` | 单行或批量纳入 `trial` | `{ stock_codes: string[], source_type: string, source_key?: string }` | `{ success: [{ stock_code, new_status }], skipped: [{ stock_code, reason_code, reason_text }], failed: [{ stock_code, reason_text }] }` |
| `/api/v1/quant/universe/actions/ignore-auto-entry` | `POST` | 单行或批量忽略自动纳入 | `{ stock_codes: string[], source_type?: string }` | `{ success: string[], failed: [{ stock_code, reason_text }] }` |
| `/api/v1/quant/universe/actions/set-override` | `POST` | 设置单股手工覆盖 | `{ stock_code: string, override_type: 'manual_pin' \| 'manual_pause' \| 'manual_ban' \| 'none' }` | `{ stock_code, quant_status, quant_auto_managed, quant_manual_override }` |
| `/api/v1/quant/universe/actions/restore-to-trial` | `POST` | 手工将 `cooling/manual_paused/retired` 恢复到 `trial` | `{ stock_code: string }` | 成功：`{ stock_code, old_status, new_status: 'trial' }`；非法调用：`400 { error_code: 'invalid_restore_state', error_message: '股票当前处于 active，无需恢复' }` |
| `/api/v1/quant/universe/settings` | `GET` | 获取系统级生命周期设置 | 无 | `{ quant_universe_lifecycle_enabled, auto_exit_enabled, auto_entry_mode }` |
| `/api/v1/quant/universe/settings` | `POST` | 更新系统级生命周期设置 | `{ quant_universe_lifecycle_enabled?, auto_exit_enabled?, auto_entry_mode? }` | `{ quant_universe_lifecycle_enabled, auto_exit_enabled, auto_entry_mode }` |
| `/api/v1/quant/universe/overview` | `GET` | 获取工作台量化概览卡片数据 | 无 | `{ cards: { pending_eligible, trial, exit_only, cooling, retired } }`，每个卡片只含 `count`, `top_items`, `latest_reason`；`top_items` 仅返回 `{ stock_code, stock_name, latest_reason }` |
| `/api/v1/quant/live-sim` | `GET` | 获取 live-sim 页面候选池、信号、成交、持仓快照 | 现有参数 + `quant_status` 过滤 | 现有结构追加 `lifecycle` 字段和 `quant_status_filters` |
| `/api/v1/discover/...` | `GET` | 发现结果查询 | 现有参数 | 每行结果追加 `eligible_status`, `candidate_score`, `blocking_reason`, `already_in_quant` |
| `/api/v1/research/...` | `GET` | 研究结果查询 | 现有参数 | 每行结果追加与 discover 对齐的生命周期入口字段 |

约束：

1. `promote-to-trial` 必须支持部分成功、部分跳过、部分失败
2. `set-override` 与 `restore-to-trial` 必须返回更新后的最新状态，避免前端二次猜测
3. `restore-to-trial` 对 `trial/active/exit_only` 调用时必须返回 `400 invalid_restore_state`，不得静默成功
4. `QuantOverviewCards` 必须通过 `/api/v1/quant/universe/overview` 独立加载，不得塞进 `/api/v1/workbench`
5. `overview.cards[*].top_items` 只允许返回 `{ stock_code, stock_name, latest_reason }`，不得附带 price、kline、quote 或其他重字段
6. `/api/v1/quant/live-sim` 中生命周期字段必须来自 `stock_universe_quant_state` 和 `stock_universe_quant_events` 聚合结果
7. `/api/v1/quant/universe/overview` 的 `待纳入量化` 卡片数据来源是 `eligible` 候选，不是 `trial` 列表

## 21. 回滚与部署

### 21.1 Phase 1 rollout

建议阶段：

1. 只新增表和状态字段，不改变现有 `quant_enabled` 扫描逻辑
2. 启用候选事件与生命周期事件留痕
3. 启用 `trial / active / cooling / retired / exit_only`
4. 最后启用自动纳入和自动退出

### 21.2 部署策略

本需求不做旧数据迁移，也不做兼容 bootstrap。部署策略明确为：

1. 删除旧的实时量化数据库并重建
2. 删除旧的生命周期状态表、事件表、旧量化池残留数据
3. 使用新 schema 初始化空库
4. 由用户或新的候选事件重新建立股票池与量化管理状态
5. 手工暂停功能默认关闭，需用户显式操作

部署执行必须使用重置脚本，而不是临时 SQL：

```powershell
python scripts/reset_stock_universe_deployment.py --yes --recreate
```

脚本职责：

1. 删除当前运行时主库 `xuanwu_stock.db`、回放库 `xuanwu_stock_replay.db`
2. 删除旧库 `quant_sim.db`、`quant_sim_replay.db`、`watchlist.db`、`portfolio_stocks.db`
3. 同步删除上述库的 `.backup*`、`.bak-*`、`-wal`、`-shm`、`-journal`
4. 重新创建空的运行时主库和回放库
5. 新主库必须包含空的 `stock_universe`、`stock_universe_quant_state`、`stock_universe_candidate_events`、`stock_universe_quant_events`、`quant_universe_settings`
6. 新回放库必须包含空的 `sim_run_*` 回放结果表
7. 不从旧量化池、旧关注池、旧持仓池恢复任何成员关系

要求：

1. 新版本代码中不得保留“如果缺字段就兼容旧状态”的过渡逻辑
2. 新版本代码中不得保留“从旧量化池推断新状态”的迁移逻辑
3. 环境切换后，所有生命周期状态都以新库中的真实记录为准
4. 文档、部署脚本和运维步骤必须显式写明“删库重建”前提

## 22. 测试要求

必须覆盖：

1. discover 候选事件进入 `trial`
2. `trial -> active`
3. `active -> exit_only`
4. `active -> cooling`
5. 用户强制出池进入 `retired`
6. `retired -> trial` 高门槛复活
7. 有持仓股票不会直接跳过 `exit_only`
8. `manual_pause / manual_ban / manual_pin` 覆盖行为
9. 历史回放仍只记录 `quant_enabled=1` 的任务股票范围快照
10. `cooling` 股票在默认主扫描覆盖不足时进入补充扫描，并应用 `cooling_supplemental_gate`
11. `health_score` 低但没有连续 `downtrend_hit` 时，不得触发 `trial/active -> cooling`；任何自动流程都不得触发 `cooling -> retired`
12. `min_scan_coverage` 生效：aggressive 演练中默认主扫描 + 补充扫描 + exit_only 覆盖不得长期低于 6

## 23. 推荐落地顺序

优先级必须先解决“硬出池导致无标的可扫”，再解决“坏股票长期占用正常仓位风险”。

推荐顺序：

1. 数据结构：`quant_status` + `stock_universe_quant_state` + 事件表
2. `health_score`、`weakening_warning`、`downtrend_hit`
3. `lifecycle_gate` 与执行层 BUY 门槛/仓位裁剪
4. `min_scan_coverage` 与 `cooling` 补充扫描
5. `exit_only / cooling` 慢速降级机制，`retired` 仅保留为手工强制出池状态
6. 工作台与 `/live-sim` 的状态展示
7. 候选事件写入与候选分计算
8. `trial` 自动纳入
9. 通知
10. `cooling` 低频重评估与 `retired` 高门槛复活

## 24. 最终约束

本 spec 的核心约束：

1. **自动入池只能先进入 `trial`，不能直接无门槛进入正式量化。**
2. **进入下行时，若当前有持仓，必须先进入 `exit_only`，不能直接停止处理。**
3. **生命周期不直接替代信号算法；除 `exit_only` 外，它只能通过 gate 调整 BUY 门槛、仓位上限和扫描优先级。**
4. **`health_score` 低不能单独触发出池；状态降级必须有连续 `downtrend_hit` 或用户手工操作。**
5. **aggressive 策略必须保持最小扫描覆盖，避免自动管理把可交易股票收缩到 0~1 只。**
6. **所有自动纳入、降级、退出、恢复都必须写事件留痕，并允许用户手工覆盖。**

