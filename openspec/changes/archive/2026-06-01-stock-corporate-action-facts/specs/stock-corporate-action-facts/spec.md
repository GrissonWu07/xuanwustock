## ADDED Requirements

### Requirement: 股票级公司行为事实持久化

系统 SHALL 将公司行为作为股票级事实持久化，且该事实 SHALL 可被 live、historical replay 和 live quant drill 共享读取。

公司行为事实 identity SHALL 至少包含 `stock_code`、`market`、`action_type`、`ex_date`、`record_date`、`data_version`，并 SHALL 暴露稳定 `action_ref`。`action_ref` SHALL 由 normalized identity 和 normalized action terms 确定性生成，且 SHALL NOT 使用随机 UUID、数据库自增 id 或 provider 临时行号。第一阶段支持的 `action_type` SHALL 至少包括 `cash_dividend`、`bonus_share`、`share_transfer`、`mixed_dividend_share`。缺失 `record_date` 时系统 SHALL 使用空字符串或等价 normalized value 参与 identity，而不是丢弃有效除权日事实。不支持的公司行为 SHALL 持久化为 `unsupported` 或 `raw_only` 状态，但 SHALL NOT 自动应用到账户会计。

#### Scenario: 现金分红和送转事实可持久化

- **GIVEN** provider 返回某 A 股在除权日发生现金分红和送转
- **WHEN** 系统规范化并保存该公司行为
- **THEN** 系统 SHALL 保存 `action_ref`、`stock_code`、`market`、`action_type`、`ex_date`、`record_date`、`bonus_share_ratio`、`cash_dividend_per_share`、`provider`、`source_status`、`data_version` 和 `raw_json`
- **AND** 后续查询同一股票、市场和日期范围 SHALL 能从本地返回该事实

#### Scenario: unsupported 公司行为不自动应用

- **GIVEN** provider 返回系统第一阶段不支持的公司行为类型
- **WHEN** 系统保存该公司行为
- **THEN** 系统 SHALL 保存原始 payload 和 unsupported 状态
- **AND** due action application SHALL NOT 调整持仓 lot、现金、成本或 slot allocation
- **AND** 诊断 SHALL 返回 `unsupported_action_type`

### Requirement: 公司行为 local-first 获取与覆盖诊断

系统 SHALL 在查询公司行为时优先读取本地事实和覆盖诊断；仅当本地事实或有效覆盖记录不能满足请求区间时，系统 MAY 调用远程 provider。对历史日期范围，已记录的事实和 coverage SHALL 被视为稳定，除非后续显式刷新能力改变该策略。

系统 SHALL 区分至少以下 source status：`local_hit`、`remote_fetched`、`empty_range`、`provider_failed`、`partial_missing`。系统 SHALL 记录 stock、market、date range、provider、status、reason_code、checked_at。

#### Scenario: 已有本地事实时不远程拉取

- **GIVEN** 本地已保存某股票在请求日期范围内的公司行为事实
- **AND** 本地 coverage 已覆盖该请求日期范围
- **WHEN** replay、drill 或 live 请求该股票同一区间公司行为
- **THEN** 系统 SHALL 返回本地事实
- **AND** 系统 SHALL NOT 调用远程 provider
- **AND** 诊断 SHALL 标记 `local_hit`

#### Scenario: 本地事实只覆盖部分区间时只补缺口

- **GIVEN** 本地已有部分公司行为事实
- **AND** 本地 coverage 未覆盖完整请求日期范围
- **WHEN** replay、drill 或 live 请求完整区间公司行为
- **THEN** 系统 SHALL 返回已知本地事实
- **AND** 系统 SHALL 只对未覆盖子区间调用远程 provider
- **AND** 诊断 SHALL 标记 `partial_missing` 或 `remote_fetched`

#### Scenario: 空区间覆盖避免重复远程调用

- **GIVEN** 本地已记录某股票某日期范围 provider 返回空结果
- **WHEN** 系统在有效覆盖窗口内再次请求同一区间
- **THEN** 系统 SHALL 返回空结果
- **AND** 系统 SHALL NOT 调用远程 provider
- **AND** 诊断 SHALL 标记 `empty_range`

#### Scenario: provider 失败可诊断且不伪装为空

- **GIVEN** 远程 provider 查询失败
- **WHEN** 系统处理该查询
- **THEN** 系统 SHALL 记录 `provider_failed` 和失败 reason_code
- **AND** 系统 SHALL NOT 将失败伪装为“无公司行为”
- **AND** provider failure coverage SHALL 包含 retry_after 或 valid_until
- **AND** retry_after 或 valid_until 过期后系统 SHALL 允许再次远程查询该范围
- **AND** 后续任务 SHALL 能在诊断中看到 provider failure

### Requirement: Due 公司行为统一会计应用

系统 SHALL 在 live、historical replay、live quant drill 的每个交易 checkpoint 决策和估值前自动应用 due corporate actions。due action SHALL 表示 `ex_date <= checkpoint_date` 且当前会计作用域尚未应用的 supported 公司行为，不得仅限 `ex_date == checkpoint_date`。

due action SHALL 使用同一套会计规则调整 eligible lot、lot cost、slot allocation、position quantity、position cost、latest price/market value、cash dividend 和 application ledger。应用 SHALL 按作用域幂等，replay/drill 应用 SHALL NOT 污染 live 账户。

#### Scenario: 历史回放 checkpoint 前应用 due action

- **GIVEN** replay run 在某 checkpoint 前持有某股票 eligible lot
- **AND** 该股票在该 checkpoint 日期存在 due 公司行为
- **WHEN** replay 执行该 checkpoint
- **THEN** 系统 SHALL 在信号生成、交易执行和账户快照前应用该公司行为
- **AND** replay run 的 lot、现金、成本和 position SHALL 反映该应用
- **AND** live-sim 状态 SHALL NOT 被修改

#### Scenario: 实时量化演练 checkpoint 前应用 due action

- **GIVEN** live quant drill 在某 checkpoint 前持有某股票 eligible lot
- **AND** 该股票在该 checkpoint 日期存在 due 公司行为
- **WHEN** drill 执行该 checkpoint
- **THEN** 系统 SHALL 在生命周期评估、信号生成、交易执行和账户快照前应用该公司行为
- **AND** drill run 的会计结果 SHALL 与同一输入下 replay 使用同一 due action 规则

#### Scenario: live-sim 交易 checkpoint 前应用 due action

- **GIVEN** live-sim / 实时量化在交易时间执行调度 checkpoint
- **AND** live 账户持有某股票 eligible lot
- **AND** 该股票在当前 checkpoint 日期存在 due 公司行为
- **WHEN** 系统执行该 checkpoint
- **THEN** 系统 SHALL 在 outcome scoring、持仓估值、候选扫描、信号生成、自动执行和账户快照前应用 due 公司行为
- **AND** 应用 SHALL 写入 live 作用域应用账本

#### Scenario: 同一作用域内重复执行不重复应用

- **GIVEN** 某作用域已经应用过某 `action_ref`
- **WHEN** 同一作用域再次执行相同 checkpoint 或重试应用
- **THEN** 系统 SHALL NOT 再次调整 lot、现金、成本或 slot allocation
- **AND** 诊断 SHALL 返回 `already_applied`

### Requirement: 事实层与应用账本作用域隔离

系统 SHALL 共享股票级公司行为事实层，但 SHALL 按会计作用域隔离应用账本。

应用作用域 SHALL 至少区分 `live`、`historical_replay`、`live_quant_drill`，并 SHALL 记录非空 `scope_id` 或等价 run/account identifier。live 作用域的默认 `scope_id` SHALL 为 `live`；replay/drill 作用域的 `scope_id` SHALL 为对应 run id 或等价 run-local identifier。应用幂等键 SHALL 包含作用域和 `action_ref`。

#### Scenario: 同一事实可应用到不同 replay run

- **GIVEN** 两个 replay run 使用同一股票公司行为事实
- **WHEN** 两个 run 分别执行到除权日
- **THEN** 每个 run SHALL 在自己的作用域内应用一次
- **AND** 一个 run 的应用账本 SHALL NOT 阻止另一个 run 应用

#### Scenario: replay 应用不污染 live

- **GIVEN** replay run 应用了某 `action_ref`
- **WHEN** live-sim 后续执行到同一 action date
- **THEN** live-sim SHALL 仍可按 live 作用域应用该 action
- **AND** replay 的应用账本 SHALL NOT 被 live 读取为已应用

### Requirement: market_technical_artifact 边界保持轻量引用

系统 SHALL NOT 将完整公司行为 payload 写入每个 `market_technical_artifact`。系统 MAY 在行情技术 artifact 或相关诊断中保存轻量公司行为状态、reason_code 或 `action_ref` 列表引用。

#### Scenario: artifact 只保存轻量公司行为诊断

- **GIVEN** 某 checkpoint 存在 due 公司行为或公司行为数据缺失
- **WHEN** 系统生成 market technical artifact 或关联诊断
- **THEN** artifact MAY 包含 `corporate_action_status`、`corporate_action_reason_code`、`corporate_action_refs`
- **AND** artifact SHALL NOT 保存完整 `raw_json`、完整 provider response 或完整应用账本

### Requirement: 公司行为验证入口和性能反馈

系统 SHALL 能通过 job/system entry point 验证公司行为事实 local-first、due application、幂等和性能效果。

#### Scenario: 实时量化演练验证 local-first 性能

- **GIVEN** 公司行为事实已经落库
- **WHEN** 用户重复运行同一量化股票范围和历史区间的 live quant drill
- **THEN** 系统 SHALL 优先复用本地公司行为事实
- **AND** 演练诊断 SHALL 能显示公司行为 local/remote/empty/provider_failed 统计
- **AND** 运行不应因重复公司行为远程拉取显著变慢

#### Scenario: 测试不验证第三方 provider 正确性

- **GIVEN** 自动化测试覆盖公司行为 provider integration
- **WHEN** 测试运行
- **THEN** 测试 SHALL 使用 fake provider、fixture 或 mock 响应
- **AND** 测试 SHALL 验证项目自己的映射、持久化、错误处理、local-first 和会计应用
- **AND** 测试 SHALL NOT 依赖真实 Akshare/TDX 可用性或返回内容
