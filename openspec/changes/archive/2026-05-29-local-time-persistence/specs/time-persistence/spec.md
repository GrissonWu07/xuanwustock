## ADDED Requirements

### Requirement: 项目自有持久化时间使用部署本地时间

The system SHALL persist project-owned business timestamps using the deployment-local time format `YYYY-MM-DD HH:mm:ss`.

#### Scenario: 实时量化写入本地时间

- **GIVEN** 实时量化任务创建或更新信号、成交、账户快照、调度状态
- **WHEN** 系统写入项目自有数据库
- **THEN** `created_at`、`updated_at`、`executed_at`、`snapshot_at`、`last_run_at`、`next_run_at` 等时间字段 SHALL 使用 `YYYY-MM-DD HH:mm:ss` 格式
- **AND** 响应和数据库记录中 SHALL NOT 出现同一语义的 `*Utc` 字段

#### Scenario: 历史回放写入本地时间

- **GIVEN** 用户启动历史回放任务
- **WHEN** 回放生成 checkpoint、信号、交易、任务进度、账户快照和清算结果
- **THEN** 所有项目自有时间字段 SHALL 使用同一部署本地时间格式

#### Scenario: 实时量化演练写入本地时间

- **GIVEN** 用户启动实时量化演练
- **WHEN** 演练生成候选事件、生命周期状态、生命周期事件、summary、信号和交易
- **THEN** 所有项目自有时间字段 SHALL 使用同一部署本地时间格式

### Requirement: checkpoint_at 是唯一检查点时间字段

The system SHALL use `checkpoint_at` as the only checkpoint timestamp for project-owned replay, drill, signal, lifecycle, summary, and artifact references.

#### Scenario: 查询和排序不依赖 UTC checkpoint

- **GIVEN** 用户查看历史回放或实时量化演练结果
- **WHEN** 系统查询信号、候选事件、生命周期状态、生命周期事件、summary 或 artifact
- **THEN** 查询、排序、去重和 join SHALL use `checkpoint_at`
- **AND** 系统 SHALL NOT read, write, create, or return `checkpoint_at_utc`

#### Scenario: 同一 checkpoint 可直接关联

- **GIVEN** 同一股票在同一 checkpoint 生成 artifact、信号、生命周期状态和交易
- **WHEN** 用户查看信号详情或任务归因
- **THEN** 这些记录 SHALL 使用相同 `checkpoint_at` 文本并可直接关联

### Requirement: API 和 UI 只暴露本地时间口径

The system SHALL return and display local-time fields only for changed API and UI surfaces.

#### Scenario: 实时量化快照没有 UTC 字段

- **GIVEN** 前端请求实时量化快照
- **WHEN** 后端返回页面 payload
- **THEN** payload SHALL include local-time display fields
- **AND** payload SHALL NOT include `updatedAtUtc`, `checkpointAtUtc`, or equivalent UTC display fields

#### Scenario: 历史回放页面没有 UTC 字段

- **GIVEN** 前端请求历史回放任务详情
- **WHEN** 后端返回 checkpoint、生命周期、信号和交易相关 payload
- **THEN** payload SHALL expose local `checkpointAt` / `updatedAt` semantics only
- **AND** UI SHALL NOT require converting UTC to local time for these fields

### Requirement: 本地缓存不受数据库重建影响

The system SHALL preserve local provider cache files while normalizing time only at the project-owned persistence boundary.

#### Scenario: 删除重建业务数据库保留 Parquet 缓存

- **GIVEN** 运维或本地验证删除并重建项目业务数据库
- **WHEN** 系统重新初始化实时量化、回放和 artifact 表
- **THEN** `data/local_sources` 下的 Parquet/K 线/provider cache files SHALL remain untouched

#### Scenario: 从缓存写入 artifact 时规范化时间

- **GIVEN** 系统从本地 Parquet/provider cache 读取行情或技术指标
- **WHEN** 系统写入 project-owned market technical artifact、信号、交易或 API payload
- **THEN** persisted project-owned timestamps SHALL be normalized to deployment-local `YYYY-MM-DD HH:mm:ss`
- **AND** the source cache file SHALL NOT be rewritten solely because of this time normalization

### Requirement: 不提供 UTC 兼容路径

The system SHALL rebuild with the local-time schema and SHALL NOT provide UTC compatibility fallback for removed project-owned fields.

#### Scenario: 新数据库不创建 UTC 字段

- **GIVEN** 系统在本地或部署环境初始化新的业务数据库
- **WHEN** DB schema is created
- **THEN** new replay/drill/signal/lifecycle/summary schema SHALL NOT create `checkpoint_at_utc`

#### Scenario: 旧 UTC 字段缺失不触发 fallback

- **GIVEN** 新版本服务查询回放或演练数据
- **WHEN** 查询信号、生命周期、候选事件或 summary
- **THEN** query logic SHALL NOT use `COALESCE(checkpoint_at_utc, checkpoint_at)` or equivalent fallback

### Requirement: 时间行为可从系统入口验证

The system SHALL provide verifiable behavior through real service/job/API/UI entry points for local-time persistence.

#### Scenario: 短演练验证本地时间

- **GIVEN** 本地业务数据库已重建且本地缓存保留
- **WHEN** 用户运行短实时量化演练
- **THEN** run-scoped artifact、candidate event、quant state、summary、signal 和 trade records SHALL share local `checkpoint_at`

#### Scenario: 短回放验证本地时间

- **GIVEN** 本地业务数据库已重建且本地缓存保留
- **WHEN** 用户运行短历史回放
- **THEN** checkpoint、artifact、signal、trade 和 task payload SHALL use local-time fields only
