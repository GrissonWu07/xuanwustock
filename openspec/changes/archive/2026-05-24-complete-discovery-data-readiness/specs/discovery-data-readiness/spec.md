## ADDED Requirements

### Requirement: 发现候选必须使用完整数据快照 ready 口径

系统 SHALL 在股票发现候选进入量化评分或自动入池判断前，使用统一的数据快照 ready 口径。该口径 SHALL 至少要求核心行情字段、技术指标字段、快照时间、provider、timeframe 和 indicator version 完整，且快照状态为 ready。

#### Scenario: 完整快照允许继续评分

- **GIVEN** 股票发现任务产生一个候选
- **AND** 候选具备完整核心行情和技术指标快照
- **AND** 快照状态为 ready
- **WHEN** 系统评估该候选是否可进入量化生命周期
- **THEN** 系统 SHALL 允许后续技术评分内核计算 `candidate_score`
- **AND** 系统 SHALL 允许后续技术置信度计算 `candidate_confidence`。

#### Scenario: 缺失核心快照阻止评分

- **GIVEN** 股票发现任务产生一个候选
- **AND** 候选缺少任一必要核心行情或技术指标字段
- **WHEN** 系统评估该候选是否可进入量化生命周期
- **THEN** 系统 SHALL NOT 计算有效 `candidate_score`
- **AND** 系统 SHALL NOT 计算有效 `candidate_confidence`
- **AND** 系统 SHALL 返回可观察的 blocking reason 和缺失字段。

#### Scenario: stale 快照阻止评分

- **GIVEN** 股票发现任务产生一个候选
- **AND** 候选快照状态为 stale、failed、incomplete 或 stale_unprepared
- **WHEN** 系统评估该候选是否可进入量化生命周期
- **THEN** 系统 SHALL NOT 使用扣分方式继续评分
- **AND** 系统 SHALL 返回可观察的 stale 或 non-ready blocking reason。

### Requirement: 自动入池不得按发现来源改变门禁语义

系统 SHALL 使用相同的数据 ready 与技术分阈值判断发现候选是否允许自动入池。发现来源、策略来源、source score、source confidence 和来源文本 SHALL NOT 放宽或收紧自动入池门禁。

#### Scenario: 相同快照不同来源得到相同入池门禁

- **GIVEN** 两个候选具有相同的数据快照和技术指标
- **AND** 两个候选来自不同发现策略
- **WHEN** 系统评估自动入池门禁
- **THEN** 两个候选 SHALL 使用相同的数据 ready 规则
- **AND** 两个候选 SHALL 使用相同的技术分和技术置信度阈值。

#### Scenario: source score 不改变缺数据结果

- **GIVEN** 一个候选缺少完整核心行情或技术指标快照
- **AND** 该候选具有很高的 source score 或 source confidence
- **WHEN** 系统评估自动入池
- **THEN** 系统 SHALL 阻止自动入池
- **AND** 系统 SHALL NOT 用 source score 或 source confidence 替代技术评分。

### Requirement: AI Scanner 必须测试稳定且不触发非预期外部 IO

系统 SHALL 保证 AI Scanner 在单元测试路径中使用显式 fake 或 fixture 数据，不得在默认单元测试中触发真实外部历史行情 IO。AI Scanner 对相同输入 SHALL 产生稳定排序。

#### Scenario: 单元测试不访问真实行情网络

- **GIVEN** AI Scanner 测试提供 fake sector 和 fake candidate 数据
- **WHEN** 测试运行 scanner
- **THEN** scanner SHALL NOT 调用真实 AkShare、TDX 或其它外部历史行情服务
- **AND** 测试 SHALL 使用显式 fixture 或 fake history provider 表达技术数据是否可用。

#### Scenario: 相同输入排序稳定

- **GIVEN** AI Scanner 接收相同的候选、主题和技术 fixture
- **WHEN** scanner 多次运行
- **THEN** 输出候选顺序 SHALL 保持一致
- **AND** 排序 SHALL 不依赖真实网络返回时序或外部数据源可用性。
