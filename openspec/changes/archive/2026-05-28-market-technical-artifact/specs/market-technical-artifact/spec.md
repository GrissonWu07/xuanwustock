## ADDED Requirements

### Requirement: 统一行情技术 Artifact 身份
系统 SHALL 为参与量化评估的股票记录统一的行情技术 artifact，且 artifact SHALL 能通过 domain、run、stock、market、checkpoint、timeframe、data version 唯一定位。

系统 SHALL 暴露稳定的 `artifact_ref` 来引用 artifact。`artifact_ref` SHALL 能被解析为 artifact domain、run_id、run_type、stock_code、market、checkpoint_at、timeframe 和 data_version。`checkpoint_at` SHALL 表示该行情技术事实对应的市场时间；`computed_at` SHALL 表示系统完成 artifact 计算或写入的时间；`data_version` SHALL 表示 artifact schema/数据版本；`indicator_version` SHALL 表示技术指标算法版本。

#### Scenario: live artifact 可定位
- **GIVEN** 实时量化刷新在某个 checkpoint 为股票生成行情技术数据
- **WHEN** 用户或系统按该股票、市场、checkpoint、timeframe 和 live domain 查询 artifact
- **THEN** 系统 SHALL 返回该 checkpoint 的 artifact identity、数据状态和行情技术字段

#### Scenario: artifact_ref 可解析

- **GIVEN** 候选入池或信号诊断返回一个 `artifact_ref`
- **WHEN** 用户或系统用该 `artifact_ref` 查询 artifact
- **THEN** 系统 SHALL 解析出 artifact domain、run scope、stock、market、checkpoint、timeframe 和 data version
- **AND** 系统 SHALL 返回同一个 artifact 的行情技术事实

#### Scenario: artifact_ref 无效

- **GIVEN** 用户或系统提交无法解析的 `artifact_ref`
- **WHEN** 系统查询 artifact
- **THEN** 系统 SHALL 返回 `invalid_artifact_ref`
- **AND** 系统 SHALL NOT 用股票代码或最新行情猜测替代 artifact

#### Scenario: replay/drill artifact 与 live 隔离
- **GIVEN** 历史回放或实时量化演练在某个 run 的 checkpoint 为股票生成行情技术数据
- **WHEN** 系统按 run_id、run_type、domain、股票、市场、checkpoint 和 timeframe 查询 artifact
- **THEN** 系统 SHALL 返回该 run-scoped artifact
- **AND** 系统 SHALL NOT 返回同一股票的 live artifact 作为替代

### Requirement: Artifact 字段覆盖
系统 SHALL 在行情技术 artifact 中记录后续候选评分、信号生成、outcome 评分和生命周期诊断所需的行情、均线、动量、结构、交易可行性和数据质量字段。

#### Scenario: artifact 包含最低字段集合
- **GIVEN** 系统成功生成某股票某 checkpoint 的 artifact
- **WHEN** 查询该 artifact
- **THEN** 响应 SHALL 至少包含 open、high、low、close、latest_price、prev_close、volume、amount、turnover_rate、volume_ratio
- **AND** 响应 SHALL 至少包含 ma5、ma10、ma20、ma60、ma20_slope
- **AND** 响应 SHALL 至少包含 rsi、macd、macd_signal、macd_histogram
- **AND** 响应 SHALL 至少包含 trend、price_vs_ma20、price_vs_ma60、ma_stack、above_ma20_checkpoints、retest_confirmed
- **AND** 响应 SHALL 至少包含 is_suspended、is_limit_up、is_limit_down、liquidity_ready
- **AND** 响应 SHALL 至少包含 provider、timeframe、indicator_version、source_status、missing_fields、computed_at

#### Scenario: 缺失字段可诊断
- **GIVEN** 某 artifact 的部分字段无法从数据源获得
- **WHEN** 查询该 artifact 或相关候选/信号诊断
- **THEN** 系统 SHALL 标记 source_status
- **AND** 系统 SHALL 返回 missing_fields
- **AND** 系统 SHALL NOT 将缺失字段伪造成有效值

### Requirement: Artifact 状态和缺失原因
系统 SHALL 使用稳定的 source_status 和 reason_code 表达 artifact 数据质量、缺失和 run scope 错误。

source_status SHALL 至少支持：

- `ready`
- `partial`
- `missing`
- `source_failed`
- `stale`
- `invalid`

reason_code SHALL 至少支持：

- `ok`
- `missing_artifact`
- `missing_artifact_reference`
- `incomplete_artifact`
- `source_failed`
- `run_scope_required`
- `invalid_artifact_ref`
- `stale_artifact`
- `field_missing`
- `source_status_not_ready`

#### Scenario: 缺失 artifact_ref

- **GIVEN** 旧候选或信号记录没有 artifact_ref
- **WHEN** 用户查看诊断或系统尝试读取 artifact
- **THEN** 系统 SHALL 返回 `missing_artifact_reference`
- **AND** 系统 SHALL NOT 使用当前行情静默回填

#### Scenario: run scope 缺失

- **GIVEN** replay 或 drill 需要读取 run-scoped artifact
- **AND** 请求缺少 run_id 或 run_type
- **WHEN** 系统读取 artifact
- **THEN** 系统 SHALL 返回 `run_scope_required`
- **AND** 系统 SHALL NOT 改读 live artifact

#### Scenario: 数据质量不满足决策

- **GIVEN** artifact 存在但 source_status 不是 `ready`
- **WHEN** 候选入池、信号生成、回放或演练需要该 artifact 作为决策事实
- **THEN** 系统 SHALL 返回对应 reason_code
- **AND** 系统 SHALL 暴露 missing_fields 或 source_status 诊断
- **AND** 系统 SHALL NOT 将 partial、stale 或 invalid artifact 当作 ready artifact

### Requirement: Artifact 查询诊断入口
系统 SHALL 提供可验证的 artifact 查询诊断入口，支持通过 artifact_ref 或完整 identity key 查询行情技术 artifact。

#### Scenario: 按 artifact_ref 查询

- **GIVEN** 用户或系统持有候选诊断或信号详情中的 `artifact_ref`
- **WHEN** 调用 `GET /api/v1/quant/market-technical-artifacts/{artifact_ref}`
- **THEN** 系统 SHALL 返回该 artifact 的 identity、行情技术字段、source_status、missing_fields 和 reason_code

#### Scenario: 按完整 key 查询 live artifact

- **GIVEN** live domain 已为股票生成 artifact
- **WHEN** 调用 `GET /api/v1/quant/market-technical-artifacts` 并提供 domain、stock_code、market、checkpoint_at、timeframe、data_version
- **THEN** 系统 SHALL 返回匹配的 live artifact
- **AND** 系统 SHALL NOT 要求 run_id 或 run_type

#### Scenario: 按完整 key 查询 run-scoped artifact

- **GIVEN** replay 或 drill run 已为股票生成 artifact
- **WHEN** 调用 `GET /api/v1/quant/market-technical-artifacts` 并提供 domain、run_id、run_type、stock_code、market、checkpoint_at、timeframe、data_version
- **THEN** 系统 SHALL 返回匹配的 run-scoped artifact
- **AND** 缺少 run_id 或 run_type 时 SHALL 返回 `run_scope_required`

### Requirement: 实时量化写入 live artifact
系统 SHALL 在实时量化刷新周期中为被刷新股票写入或更新 live domain 的行情技术 artifact，并将该 artifact 作为实时量化决策事实来源。

#### Scenario: 实时刷新生成 artifact
- **GIVEN** 实时量化刷新周期刷新某只股票
- **WHEN** 行情和技术指标准备完成
- **THEN** 系统 SHALL 写入 live domain artifact
- **AND** 后续候选入池或信号生成 SHALL 能引用该 artifact

#### Scenario: 实时决策不得绕过 artifact
- **GIVEN** live domain artifact 缺失或不可用
- **WHEN** 实时量化候选入池或信号生成需要该股票的行情技术数据
- **THEN** 系统 SHALL 返回明确缺失原因
- **AND** 系统 SHALL NOT 静默临时拉取行情并绕过 artifact 作为决策事实

### Requirement: 所有量化流程通过 Artifact 事实层
系统 SHALL 确保实时刷新、实时量化、实时量化演练和历史回放均以 market technical artifact 作为行情技术事实来源。

#### Scenario: 实时刷新只负责生成 live artifact

- **GIVEN** 统一实时刷新任务获取到股票行情和技术指标
- **WHEN** 刷新任务完成数据准备
- **THEN** 系统 SHALL 写入 live domain artifact
- **AND** runtime snapshot MAY 从 live artifact 派生用于展示
- **AND** runtime snapshot SHALL NOT 替代 live artifact 成为后续量化决策事实源

#### Scenario: 实时量化消费 live artifact

- **GIVEN** 实时量化扫描、候选生命周期评估或信号生成需要某股票行情技术数据
- **WHEN** 系统执行实时量化决策
- **THEN** 系统 SHALL 通过 artifact_ref 或完整 identity key 读取 live domain artifact
- **AND** 系统 SHALL NOT 直接读取 runtime snapshot、candidate payload、provider cache 或临时远程行情作为决策事实源

#### Scenario: 当前业务页面消费 live artifact

- **GIVEN** 工作台、发现股票、研究或实时量化页面需要展示当前股票行情、技术指标、候选诊断或信号诊断
- **WHEN** 页面 API 返回 live 口径数据
- **THEN** 系统 SHALL 通过 live domain artifact 或 artifact 派生投影提供行情技术事实
- **AND** 页面 API SHALL 返回 artifact_ref 或可追踪到 live artifact 的诊断引用
- **AND** 页面 API SHALL NOT 将 runtime snapshot、candidate payload 或 provider cache 当作权威行情技术事实源

#### Scenario: 实时量化演练消费 drill artifact

- **GIVEN** 实时量化演练运行到某个 checkpoint
- **WHEN** 演练执行股票发现、生命周期评估、信号生成或交易模拟
- **THEN** 系统 SHALL 通过 drill run-scoped artifact 获取该 checkpoint 的行情技术事实
- **AND** 演练 SHALL NOT 读取 live domain artifact 或 runtime snapshot 作为该 checkpoint 的替代事实源

#### Scenario: 历史回放消费 replay artifact

- **GIVEN** 历史回放运行到某个 checkpoint
- **WHEN** 回放执行信号生成、交易模拟或结果诊断
- **THEN** 系统 SHALL 通过 replay run-scoped artifact 获取该 checkpoint 的行情技术事实
- **AND** 回放 SHALL NOT 读取 live domain artifact、runtime snapshot 或当前 provider cache 作为该 checkpoint 的替代事实源

### Requirement: 历史回放和实时量化演练写入 run-scoped artifact
系统 SHALL 在历史回放和实时量化演练的 checkpoint 中写入 run-scoped 行情技术 artifact，并禁止使用 live latest 数据替代 run 数据。

#### Scenario: 历史回放 checkpoint 使用 run artifact
- **GIVEN** 历史回放运行到某个 checkpoint
- **WHEN** 系统为某股票准备行情技术数据
- **THEN** 系统 SHALL 写入 replay domain 的 run-scoped artifact
- **AND** 后续回放信号生成 SHALL 引用该 run-scoped artifact

#### Scenario: 实时量化演练 checkpoint 使用 run artifact
- **GIVEN** 实时量化演练运行到某个 checkpoint
- **WHEN** 系统为某股票准备行情技术数据
- **THEN** 系统 SHALL 写入 drill domain 的 run-scoped artifact
- **AND** 后续演练信号生成 SHALL 引用该 run-scoped artifact

#### Scenario: run 数据不得 fallback 到 live latest
- **GIVEN** replay 或 drill run 的某 checkpoint artifact 缺失
- **WHEN** 该 run 需要该 checkpoint 的行情技术数据
- **THEN** 系统 SHALL 返回 run-scoped missing artifact reason
- **AND** 系统 SHALL NOT 使用当前 live artifact、实时 TTL 缓存或最新行情替代

### Requirement: 候选与信号引用 Artifact
系统 SHALL 在候选入池和信号生成的诊断数据中记录 artifact_ref，并以 artifact_ref 指向的行情技术事实作为可复查依据。

#### Scenario: 候选入池记录 artifact 引用
- **GIVEN** 系统评估某股票是否进入量化
- **WHEN** 生成候选入池诊断
- **THEN** 诊断 SHALL 包含 artifact_ref
- **AND** 完整行情技术字段 SHALL 能通过 artifact_ref 查询

#### Scenario: 信号生成记录 artifact 引用
- **GIVEN** 系统生成 BUY、SELL 或 HOLD 信号
- **WHEN** 用户查看信号详情或系统读取信号诊断
- **THEN** 诊断 SHALL 包含 artifact_ref
- **AND** 完整行情技术字段 SHALL 能通过 artifact_ref 查询

### Requirement: 旧来源角色收敛
系统 SHALL 将现有分散行情技术来源收敛为 artifact producer、consumer、adapter 或派生 cache，且 SHALL NOT 继续把分散 payload 当作权威事实源。

#### Scenario: runtime snapshot 只能派生
- **GIVEN** 系统仍需提供最新 runtime snapshot 给 UI 或兼容展示
- **WHEN** runtime snapshot 被更新
- **THEN** 它 SHALL 从 live artifact 派生或同步
- **AND** 它 SHALL NOT 作为量化决策事实源反向输入

#### Scenario: candidate payload 只保留引用和轻量诊断

- **GIVEN** discovery candidate 或 candidate event 已经关联 market technical artifact
- **WHEN** 系统持久化候选诊断
- **THEN** 诊断 SHALL 保存 artifact_ref、technical readiness 和 reason code
- **AND** 诊断 SHALL NOT 把完整行情技术字段作为权威事实源

#### Scenario: provider cache 不是 checkpoint fact artifact
- **GIVEN** 本地 provider cache 中存在某股票的历史行情数据
- **WHEN** 系统执行量化决策、候选入池或信号生成
- **THEN** provider cache MAY 用于构建 artifact
- **AND** provider cache SHALL NOT 直接作为 checkpoint 决策 artifact

### Requirement: 来源评分不得进入 Artifact 事实层
系统 SHALL NOT 将发现来源评分、来源置信度或多来源 bonus 写入行情技术 artifact 作为行情技术事实，也 SHALL NOT 由这些字段影响 artifact 的行情技术字段。

#### Scenario: 不同来源同一技术数据生成相同 artifact 事实
- **GIVEN** 同一股票同一 checkpoint 的行情技术数据相同
- **AND** 该股票来自不同发现来源
- **WHEN** 系统生成行情技术 artifact
- **THEN** artifact 的行情技术字段 SHALL 与发现来源无关
- **AND** artifact SHALL NOT 包含用于量化评分的 source_score、source_confidence 或 multi_source_bonus
