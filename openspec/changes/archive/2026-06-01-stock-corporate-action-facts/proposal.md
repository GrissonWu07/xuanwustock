# Change: 公司行为事实层与 local-first 会计应用

## Workflow Lane

Full lane。该变更涉及数据库、公司行为事实持久化、live/replay/drill 调度、会计幂等和真实演练验证，必须完整经过 brainstorm、spec/design、tasks、implementation、completion。

## Why

当前公司行为只在回放应用时临时查询 provider，并依赖进程内缓存。`sim_corporate_action_applications` 记录的是会计应用结果，不是股票事实来源。多次历史回放、实时量化演练和 live-sim 会反复拉取同一区间公司行为，且 live 与 replay 的持仓成本、股数、现金分红、盈亏口径可能不一致。

系统已经引入 `market_technical_artifact` 作为行情技术 checkpoint 事实层，但除权除息、送转、现金分红属于股票级公司行为事实，不能塞入每个行情技术 artifact。需要新增独立的股票公司行为事实层，并让 replay、drill、live 在同一会计规则下应用 due actions。

## What Changes

- 新增股票级公司行为事实持久化能力，覆盖 A 股现金分红、送转/转增、混合分红送转。
- 新增公司行为覆盖/缺失/失败诊断，支持 local-first 读取和 negative cache。
- 改造公司行为 provider：先读本地事实和覆盖记录，缺失时才远程获取并落库。
- replay、实时量化演练、live-sim/实时量化在交易 checkpoint 决策和估值前使用同一个 due corporate action application service。
- 明确事实层共享、应用账本按作用域隔离，避免 replay/drill 污染 live。
- `market_technical_artifact` 仅保留轻量公司行为状态或引用，不保存完整公司行为 payload。

## Scope

- 数据模型：公司行为事实、覆盖诊断、作用域化应用账本。
- 后端服务：local-first provider/service、due action application service。
- 调度/回放：historical replay、live quant drill、live quant scheduler 接入。
- 测试：fake provider、SQLite 行为、幂等、local-first、live/replay/drill 作用域隔离、真实演练验证。

## Out of Scope

- 不实现完整港股/美股公司行为语义。
- 不新增 UI 页面或用户操作入口。
- 不迁移旧数据库；本地/部署可重建数据库。
- 不把完整公司行为事件写入 `market_technical_artifact`。
- 不验证第三方 provider 本身正确性。

## Impact

- Backend: `corporate_actions`、replay/drill service、live scheduler、portfolio accounting。
- Data: 新增公司行为事实与覆盖记录；调整应用账本作用域。
- Performance: 重跑历史回放/实时量化演练时应减少重复远程公司行为请求。
- Accounting: live/replay/drill 统一除权除息、送转、现金分红应用时点和幂等口径。

## Rules Applied

- 数据库变更需要支持 SQLite 和 MySQL 语义。
- 第三方 provider 测试必须验证项目自己的映射、持久化、错误处理，不能把 provider 可用性当测试目标。
- 行为必须可通过 job/API/system entry point 验证。
- 代码应复用统一 service，避免 replay/drill/live 三套重复逻辑。
- 文档与中文说明使用 UTF-8，避免 mojibake。

## Risks

- 应用账本若缺少作用域，会导致 replay/drill/live 幂等互相影响。
- live-sim 如果通过只读 GET 隐式应用公司行为，会重新引入读操作写库风险；本 change 只在交易 checkpoint/调度执行时写库。
- provider 空结果和失败如果不区分，会让系统长期误认为无公司行为或反复远程拉取。
- 公司行为 action identity 如果过窄，未来混合事件或多事件同日会被错误去重。

## Open Questions

- 无待用户确认的开放问题。用户已确认 live-sim / 实时量化必须在每次交易 checkpoint / 估值前自动应用 due corporate actions。
