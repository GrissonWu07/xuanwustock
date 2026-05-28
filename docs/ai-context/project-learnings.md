# Project Learnings

> 默认语言：除非用户明确要求英文，本文档的标题、章节内容和说明均使用中文；代码标识符、API 路径、配置键和命令保持原文。

Use this file to keep concise reusable lessons from completed changes.

## Patterns

- 量化系统中需要跨实时、历史回放、演练复用的行情技术事实，应先落为带 `artifact_ref` 的事实层，再让候选、信号、页面和诊断读取同一个 reader。这样能避免 runtime snapshot、candidate payload、signal market snapshot 和 provider cache 之间出现口径漂移。

## Pitfalls

- 不要把 provider/local cache、runtime snapshot 或 candidate payload 当作 checkpoint 决策事实。它们可以作为 artifact producer 的输入或展示缓存，但 run-scoped replay/drill 必须拒绝 fallback 到 live latest，避免未来函数。
- 信号生成阶段可以在内存里使用完整行情技术 facts，但持久化到 signal detail 的 `market_snapshot` 应只保留 `artifact_ref`、`source_status`、`reason_code`、`missing_fields` 等轻量诊断，避免复制出第二份事实源。

## Verification Notes

- 验证统一事实层时必须构造“旧来源值与 artifact 值冲突”的测试数据；只有断言 artifact 值胜出，才能证明测试没有被 runtime/provider fallback 掩盖。
- run-scoped no-live-fallback 测试应同时存在 live artifact 和缺失的 run artifact，确认 replay/drill 返回 run-scoped missing reason，而不是静默读取 live。
- 文件大小门禁要把“机械抽取的既有代码”和“本次新增行为代码”分开记录覆盖率证据；抽取模块仍需 broad regression，但不应稀释 artifact-focused coverage。

## Project Preferences

- OpenSpec completion 文档和 wiki 默认使用中文；代码标识符、API 路径、reason code 和命令保持原文。
