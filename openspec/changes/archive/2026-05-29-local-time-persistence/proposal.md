# Change: 本地时间持久化

## Workflow Lane

full

## Why

当前系统同时保存和返回本地时间与 UTC 时间，例如 `checkpoint_at` / `checkpoint_at_utc`、`updatedAt` / `updatedAtUtc`。实时量化、历史回放、实时量化演练、artifact、信号、交易和 UI 复盘因此需要反复做时间换算，导致 join 断开、排序/filter 口径不一致、成功交易诊断难以解释。

用户已确认本变更按当前部署本地时间处理，并彻底移除 `updatedAtUtc/checkpointAtUtc` 这类字段。旧数据库不迁移，直接删除重建。

## What Changes

- 项目自有数据库中的业务时间统一保存为部署本地时间字符串 `YYYY-MM-DD HH:mm:ss`。
- `checkpoint_at` 成为唯一 checkpoint 时间字段；不再创建、写入、读取或返回 `checkpoint_at_utc`。
- 实时量化、历史回放、实时量化演练、生命周期、交易、market technical artifact 和 API/UI 使用同一套本地时间语义。
- API/UI 不再暴露 `updatedAtUtc`、`checkpointAtUtc` 或同类 UTC 字段。
- 本地 Parquet/provider cache 保持原文件和原格式，不参与 DB 重建；只在读入业务持久化边界时规范化成本地时间。

## Scope

- 后端时间工具、DB schema/repository、回放/演练、交易/调度、market technical artifact、gateway API、UI page model/locales/tests。
- 本地开发 SQLite 和部署阶段数据库重建说明。
- 测试与验证覆盖 replay、drill、artifact、signals、trades、lifecycle、API payload、UI model、cache 保留。

## Out of Scope

- 不迁移旧数据库。
- 不保留 UTC/local 双字段兼容路径。
- 不设计未来多市场独立时区持久化方案。
- 不调整量化策略、买卖阈值、入池阈值或仓位逻辑。
- 不清理、不重写本地 Parquet/K 线/provider cache。

## Impact

- 数据库 schema 和查询索引需要移除 UTC checkpoint 字段。
- API 响应字段删除会影响前端模型和测试。
- 运行中的历史回放/演练数据需要通过删库重建清理。
- 本地行情缓存仍保留，可继续支持 local-first 数据准备。

## Rules Applied

- `AGENTS.md` / `openspec/AGENTS.md`：OpenSpec full workflow，默认中文，过程证据和 durable artifacts 分离。
- `docs/rules/project-implementation-standards.md`：复用共享逻辑，避免无关重构，保持可验证入口。
- `docs/rules/python-code-standards.md`：Python 改动保持小函数、类型清晰、避免超大文件继续膨胀。
- `docs/rules/configuration-standards.md`：数据库变更明确重建策略，不做隐式兼容。
- `docs/rules/testing-standards.md`：验证必须覆盖项目自有行为，不测试 provider/Parquet 依赖本身。
- `docs/rules/logging-standards.md`：重建/时间规范化相关日志必须带 trace_id 且不输出敏感信息。
- `docs/rules/encoding-standards.md`：中文文案、API payload、测试数据必须 UTF-8 且无 mojibake。

## Risks

- `db.py` 已超过 1000 行，任务应优先使用 focused modules 或薄接线，避免继续堆积主体逻辑。
- `checkpoint_at_utc` 使用点较多，漏改会继续造成 join/sort 断裂。
- API 字段删除可能导致前端页面模型或测试失败。
- 错误地把 DB 重建扩展到 `data/local_sources` 会破坏本地缓存性能，需要明确禁止。

## Open Questions

无阻塞问题。用户已确认本地时间、移除 UTC 字段、删除重建数据库、保留本地缓存。
