## ADDED Requirements

### Requirement: AI Scanner 单元测试隔离历史行情 IO

系统 SHALL 允许 AI Scanner 单元测试在不调用真实 AkShare、TDX 或本地市场历史行情客户端的情况下执行。

#### Scenario: 注入 history provider 阻止真实历史客户端访问

- **GIVEN** AI Scanner 单元测试提供了 history provider
- **AND** market history client 如果被调用会失败
- **WHEN** scanner 为候选股票计算技术分
- **THEN** scanner SHALL 使用注入的 history provider
- **AND** SHALL NOT 调用 market history client
- **AND** 测试 SHALL 在没有外部网络或 provider 依赖的情况下完成。

#### Scenario: fake market client 是单元测试中唯一市场 IO 边界

- **GIVEN** AI Scanner 单元测试没有提供 history provider
- **AND** 该测试提供了 fake market client
- **WHEN** scanner 需要历史行情数据
- **THEN** scanner SHALL 只调用 fake market client
- **AND** SHALL NOT 实例化或调用真实 AkShare local client。

### Requirement: AI Scanner 候选排序稳定

系统 SHALL 对相同输入数据返回确定性的 AI Scanner 候选排序。

#### Scenario: 重复扫描返回相同顺序

- **GIVEN** 固定的板块列表
- **AND** 固定的板块成分股行
- **AND** 固定的历史数据行为
- **WHEN** AI Scanner 多次扫描相同输入
- **THEN** 每次扫描 SHALL 返回相同的股票代码顺序列表。

#### Scenario: 最终分数并列时使用显式 tie-breaker

- **GIVEN** 两个或多个 AI Scanner 候选具有相同最终 scanner score
- **WHEN** scanner 对最终候选排序
- **THEN** scanner SHALL 使用显式确定性的 tie-breaker 字段
- **AND** SHALL NOT 只依赖隐式 DataFrame 行顺序作为排序规则。

### Requirement: AI Scanner 稳定性测试面向回归

系统 SHALL 保留能证明原始 bug entry point 不再失败的回归测试。

#### Scenario: 原始热门板块成分股测试保持稳定

- **GIVEN** 热门板块成分股 fixture 中 `688111` 位于 `000001` 之前
- **AND** 技术历史不可用但被注入为确定性空 frame
- **WHEN** 原始 AI Scanner 热门板块候选测试运行
- **THEN** 候选顺序 SHALL 保持为 `688111`，然后是 `000001`
- **AND** 重复执行 SHALL 产生相同顺序。

#### Scenario: no-real-IO 回归被独立断言

- **GIVEN** 测试配置了一个被调用就会抛错的 real-history-client sentinel
- **WHEN** scanner 使用注入的 history provider 运行
- **THEN** sentinel SHALL 保持未被使用
- **AND** 如果真实历史 IO 被意外引入，断言 SHALL 失败。
