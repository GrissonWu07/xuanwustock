## ADDED Requirements

### Requirement: 发现候选必须暴露 prepared evidence

系统 SHALL 在股票发现任务完成后，为每个发现候选提供可观察的 prepared evidence。prepared evidence SHALL 至少表达发现批次、候选股票、发现来源、行情/技术快照准备状态、量化技术入池分、技术置信度、门禁结论、刷新状态和证据时间。

#### Scenario: 发现任务完成后候选带有完整证据

- **GIVEN** 用户启动一次股票发现任务
- **WHEN** 发现任务状态变为 completed
- **THEN** 发现任务结果 SHALL 返回候选数量和技术快照准备摘要
- **AND** 发现候选列表 SHALL 对每个候选显示或提供 prepared evidence 引用
- **AND** 每个 ready 候选 SHALL 有量化技术入池分、技术置信度、门禁结论和证据时间。

#### Scenario: 未准备 raw fallback 不得伪装为可量化候选

- **GIVEN** 系统只能读取未准备的原始 selector 结果
- **WHEN** 用户查看发现候选列表或生命周期入池结果
- **THEN** 该候选 SHALL 标记为 stale/unprepared
- **AND** 该候选 SHALL 不得展示为已满足自动入池条件
- **AND** 该候选 SHALL 显示缺失技术快照或等待准备的原因。

#### Scenario: 技术快照缺失时阻止自动入池

- **GIVEN** 某个发现候选缺少必要行情或技术指标
- **WHEN** 生命周期门禁评估该候选
- **THEN** 该候选 SHALL 被阻止自动进入 trial/active 量化状态
- **AND** 阻止原因 SHALL 指向 missing/stale technical snapshot
- **AND** 发现页或量化候选详情 SHALL 能看到该阻止原因。

### Requirement: 刷新成功必须重新评估被数据问题阻止的候选

系统 SHALL 在统一股票刷新为候选补齐 fresh technical snapshot 后，对之前因 missing/stale technical snapshot 进入 blocked 或 recommended_only 的候选重新执行生命周期评估。

#### Scenario: 刷新补齐数据后候选重新评估

- **GIVEN** 某个候选因为 missing/stale technical snapshot 被阻止自动入池
- **AND** 该候选仍属于当前发现候选集合或量化候选关注范围
- **WHEN** 统一股票刷新成功写入 fresh technical snapshot
- **THEN** 系统 SHALL 重新评估该候选的生命周期门禁和量化技术入池分
- **AND** 候选详情 SHALL 显示最近一次重评时间和重评结果
- **AND** 如果候选满足当前 profile 的入池条件，系统 SHALL 发出对应的入池状态变化或候选事件。

#### Scenario: 刷新仍失败时保留阻止状态

- **GIVEN** 某个候选因为缺少技术快照被阻止
- **WHEN** 后续刷新仍失败或数据仍不完整
- **THEN** 系统 SHALL 保留该候选的阻止或推荐-only 状态
- **AND** 候选详情 SHALL 显示最新刷新失败或仍缺失的原因
- **AND** 系统 SHALL 不得使用发现来源分替代量化技术入池分。

### Requirement: 信号和交易必须暴露 decision provenance

系统 SHALL 为实时量化、历史回放和量化演练产生的 BUY、SELL、HOLD、ignored 信号，以及由信号产生的交易，提供可观察的 decision provenance。

#### Scenario: 信号详情展示决策来源

- **GIVEN** 系统产生一个量化信号
- **WHEN** 用户查看该信号详情
- **THEN** 信号详情 SHALL 显示决策时间或 checkpoint 时间
- **AND** SHALL 显示使用的行情/技术快照状态和 as-of 语义
- **AND** SHALL 显示策略 profile 标识和版本语义
- **AND** SHALL 显示研究上下文是 used 还是 omitted，以及 omitted_reason
- **AND** SHALL 显示信号拆解、门禁结果和最终 action。

#### Scenario: 交易详情能反查仓位和执行依据

- **GIVEN** 某个 BUY 或 SELL 信号被执行为交易
- **WHEN** 用户查看交易详情
- **THEN** 交易详情 SHALL 能关联到原始信号
- **AND** SHALL 显示信号对应的仓位计划、slot/lot 计划、执行状态、执行数量、执行价格和费用
- **AND** 如果交易缺少 lot 或 slot 信息，详情 SHALL 显示缺失原因而不是空白通过。

#### Scenario: ignored 信号也进入统计和解释

- **GIVEN** 系统产生一个被忽略的 BUY 或 SELL 信号
- **WHEN** 用户查看信号统计、任务报告或信号详情
- **THEN** 该 ignored 信号 SHALL 被纳入 ignored 统计
- **AND** SHALL 显示忽略原因、门禁结果和当时的决策证据。

### Requirement: 分数和状态口径必须明确

系统 SHALL 在 API、任务报告和 UI 中明确区分发现来源审计分、量化技术入池分、技术置信度、信号融合分、信号置信度和研究上下文分。系统 SHALL NOT 将发现来源分或来源置信度展示或映射为量化技术入池分。

#### Scenario: 发现页和量化池不混用 score

- **GIVEN** 一个候选同时具有发现来源审计分和量化技术入池分
- **WHEN** 用户查看发现页、量化候选详情或实时量化候选表
- **THEN** UI/API SHALL 使用明确标签区分两类分数
- **AND** 自动入池判断 SHALL 只显示量化技术入池分和技术置信度作为入池依据
- **AND** 来源审计分 SHALL 仅作为发现来源解释使用。

#### Scenario: source score 不得作为 candidate score fallback

- **GIVEN** 某个候选缺少 prepared technical evidence
- **AND** 该候选有 discovery source score 或 source confidence
- **WHEN** 系统生成发现 API、生命周期状态或量化候选视图
- **THEN** 系统 SHALL NOT 用 source score 或 source confidence 填充量化技术入池分
- **AND** 该候选的量化技术入池分 SHALL 显示为缺失、未准备或 0，并附带原因。

#### Scenario: 生命周期状态计数口径一致

- **GIVEN** 实时量化页面显示候选股票和状态统计
- **WHEN** 用户查看“待量化”“表内”“trial”“active”“cooling”“retired”等数量
- **THEN** 每个数量 SHALL 有一致的状态定义
- **AND** 表格过滤结果 SHALL 与状态统计口径一致
- **AND** 如果某个数量是汇总或筛选结果，UI SHALL 使用能表达该口径的名称。

### Requirement: 回放和演练必须披露 checkpoint 数据覆盖

系统 SHALL 在历史回放和量化演练任务中披露 checkpoint 数据准备覆盖情况，并说明每个任务路径与实时量化输入上下文的差异。

#### Scenario: 回放任务报告数据覆盖证明

- **GIVEN** 用户启动一次历史回放任务
- **WHEN** 历史数据准备阶段完成
- **THEN** 任务事件或任务报告 SHALL 显示股票数量、checkpoint 数量、ready 覆盖、缺失覆盖和失败原因摘要
- **AND** 对于使用最近可用行情条的 checkpoint，报告 SHALL 区分其不是精确 checkpoint 数据
- **AND** 如果必要数据缺失导致某个 checkpoint 无法可靠决策，系统 SHALL 记录跳过或阻止原因。

#### Scenario: 回放/演练信号披露实时上下文差异

- **GIVEN** 实时量化可使用某类研究上下文
- **AND** 历史回放或量化演练为了 as-of 安全禁用了该上下文
- **WHEN** 用户查看回放/演练任务报告或信号详情
- **THEN** 系统 SHALL 显示该上下文被 omitted
- **AND** SHALL 显示 omitted_reason
- **AND** 不得让用户误以为回放/演练与实时量化使用了完全相同的上下文输入。

#### Scenario: UI 时间展示使用系统本地时间

- **GIVEN** 证据、信号、交易或任务事件在持久化层使用系统本地时间
- **WHEN** 用户在发现股票、研究股票、工作池、实时量化、历史量化或量化演练 UI 查看时间
- **THEN** UI SHALL 展示系统当前时区时间
- **AND** UI 表格 SHALL NOT 直接显示 UTC 原始格式或 UTC 后缀字段。
