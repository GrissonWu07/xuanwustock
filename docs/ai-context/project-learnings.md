# Project Learnings

> 默认语言：除非用户明确要求英文，本文档的标题、章节内容和说明均使用中文；代码标识符、API 路径、配置键和命令保持原文。

Use this file to keep concise reusable lessons from completed changes.

## Patterns

- 量化系统中需要跨实时、历史回放、演练复用的行情技术事实，应先落为带 `artifact_ref` 的事实层，再让候选、信号、页面和诊断读取同一个 reader。这样能避免 runtime snapshot、candidate payload、signal market snapshot 和 provider cache 之间出现口径漂移。
- 业务时间持久化应在项目自有 DB/API/artifact 边界统一格式化；provider/local cache 可以保留来源原始格式，避免为了业务时间语义重写 Parquet 缓存。
- 发现来源分、量化技术入池分、信号融合分和交易执行诊断需要分层命名。来源分可以作为审计信息保留，但自动入池、生命周期和 UI 入池标签必须读取 prepared evidence / artifact-backed candidate score。
- 信号 outcome 这类事后质量评分应作为成熟反馈单独持久化和消费：`candidate_score` 仍表示事前技术入池质量，`outcome_feedback_score` 表示同股历史信号成熟后的反馈，二者不能互相覆盖。

## Pitfalls

- 不要把 provider/local cache、runtime snapshot 或 candidate payload 当作 checkpoint 决策事实。它们可以作为 artifact producer 的输入或展示缓存，但 run-scoped replay/drill 必须拒绝 fallback 到 live latest，避免未来函数。
- 信号生成阶段可以在内存里使用完整行情技术 facts，但持久化到 signal detail 的 `market_snapshot` 应只保留 `artifact_ref`、`source_status`、`reason_code`、`missing_fields` 等轻量诊断，避免复制出第二份事实源。
- 不要同时保留 `checkpoint_at` 和 `checkpoint_at_utc` 这类同语义双字段；短期看似兼容，长期会让 artifact、signal、trade、UI filter 的 join/sort 口径再次分裂。
- 不要让 source score、source confidence、来源数量或展示文案进入 outcome scoring。发现来源只能解释“为什么被发现”，不能解释“信号发出后是否被行情验证”。

## Verification Notes

- 验证统一事实层时必须构造“旧来源值与 artifact 值冲突”的测试数据；只有断言 artifact 值胜出，才能证明测试没有被 runtime/provider fallback 掩盖。
- run-scoped no-live-fallback 测试应同时存在 live artifact 和缺失的 run artifact，确认 replay/drill 返回 run-scoped missing reason，而不是静默读取 live。
- 文件大小门禁要把“机械抽取的既有代码”和“本次新增行为代码”分开记录覆盖率证据；抽取模块仍需 broad regression，但不应稀释 artifact-focused coverage。
- 时间口径类变更需要同时做 raw DB/API key 断言和 active-code `rg` 审计；只看页面渲染或 job 成功会掩盖隐藏的 UTC fallback。
- 刷新后重评要从本地候选事件表读取所有数据阻塞事件，而不是只看某个来源或最新一条事件；否则会重新引入“发现来源影响量化状态”的窄口径问题。
- outcome feedback 测试必须证明 `matured_at <= as_of_checkpoint`，并且要构造 live artifact 与 run artifact 冲突/缺失的场景，避免未来函数和跨 run 污染被 happy path 掩盖。

## Project Preferences

- OpenSpec completion 文档和 wiki 默认使用中文；代码标识符、API 路径、reason code 和命令保持原文。
