---
source: openspec/changes/stock-corporate-action-facts
title: 公司行为事实层与本地优先会计应用
last_synced: 2026-06-01
last_reviewed: 2026-06-01
status: implemented
change_id: stock-corporate-action-facts
---

# 公司行为事实层与本地优先会计应用

## 能力摘要

系统现在把股票公司行为作为独立事实层持久化，不再把除权、送转、现金分红这类持仓会计事实塞进行情技术 artifact 或各个运行态 payload。历史回放、实时量化演练和实时量化调度在进入交易 checkpoint 的估值、信号、交易执行之前，统一查询并应用已到期公司行为。

这解决两个核心问题：

- 公司行为数据走 local-first，已覆盖的历史区间不会在每次回放或演练时重复远程拉取。
- replay、drill、live 使用同一套会计应用服务，但应用账本按 scope 隔离，不会互相污染。

## 用户可见行为

- 历史回放 checkpoint 前会先应用该 run scope 下尚未应用的 due 公司行为。
- 实时量化演练 checkpoint 前会先应用该演练 run scope 下尚未应用的 due 公司行为。
- 实时量化定时任务在交易时间内执行时，会先应用 live scope 下的 due 公司行为，再继续持仓估值、信号生成、自动交易和快照。
- live-sim 页面 GET/快照读取仍保持只读，不会因为打开页面而写入公司行为账本。
- 如果真实演练区间没有 due 公司行为，系统会保留 `empty_range` / `no_due_action_in_real_range` 诊断；会计路径由 fixture 和 DB 回归测试覆盖。

## 数据流

```text
checkpoint
  -> CorporateActionApplicationService.apply_due_actions
  -> CorporateActionFactService.get_actions(local-first)
  -> CorporateActionFactStore(corporate_action_facts / corporate_action_coverage)
  -> QuantSimDB.apply_corporate_action_command(scoped ledger)
  -> checkpoint valuation / signal / execution / snapshot
```

## 数据表

### corporate_action_facts

股票级公司行为事实表。核心字段包括：

- `action_ref`: deterministic identity。
- `stock_code`, `market`, `action_type`。
- `ex_date`, `record_date`。
- `bonus_share_ratio`, `cash_dividend_per_share`。
- `provider`, `source_status`, `reason_code`, `data_version`。

### corporate_action_coverage

公司行为数据覆盖表，用来判断一个股票某个日期区间是否已经本地覆盖，避免重复远程拉取。核心字段包括：

- `stock_code`, `market`, `start_date`, `end_date`, `provider`。
- `source_status`: 如 `remote_fetched`, `empty_range`, `provider_failed`。
- `retry_after`, `valid_until`。

### sim_corporate_action_applications

公司行为会计应用账本。核心隔离字段包括：

- `scope_type`: `live`, `historical_replay`, `live_quant_drill`。
- `scope_id`: live 固定为 `live`，回放/演练为 run id。
- `action_ref`: 同一 scope 内幂等；不同 scope 可独立应用同一事实。

## 本地优先规则

- 如果 facts 和终态 coverage 已覆盖查询区间，直接返回本地事实，不调用 provider。
- 如果 coverage 只覆盖部分区间，只拉取未覆盖子区间。
- 如果 provider 失败，写入 `provider_failed` 和 retry 元数据；在 retry 期内不重复远程调用。
- 如果 provider 返回空且区间稳定，写入 `empty_range`，后续同范围直接命中本地覆盖。

## 会计应用规则

- due action 定义为 `ex_date <= checkpoint_date` 且当前 scope 尚未应用。
- supported action 才会进入会计应用；unsupported/raw-only 事实只持久化和诊断。
- 应用顺序固定为 `ex_date ASC, action_ref ASC`。
- 具体 lot、slot、现金、成本调整复用原 `QuantSimDB.apply_corporate_action` 会计逻辑，避免重写账务算法。

## Scope 隔离

同一 `action_ref` 可以在不同 scope 各自应用一次：

- live: `scope_type=live`, `scope_id=live`
- historical replay: `scope_type=historical_replay`, `scope_id=<run_id>`
- live quant drill: `scope_type=live_quant_drill`, `scope_id=<run_id>`

这样历史回放和实时量化演练不会把公司行为应用写进 live 账户状态。

## 验证摘要

自动化验证：

- corporate action fact/store/service/accounting/scheduler 测试通过。
- provider 使用 fake provider，不验证第三方 Akshare 正确性。
- changed focused modules 覆盖率满足目标；大型 legacy 文件按路径级测试和 review 记录例外。

真实演练验证：

- 用当前量化股票池跑两次 bounded live quant drill。
- 每次 2 个 checkpoint，状态 completed。
- live `sim_trades` 保持 0，证明演练未污染 live 交易表。
- 真实区间无 due 公司行为，记录 `no_due_action_in_real_range`。

## 注意事项

- 公司行为事实不属于 `market_technical_artifact`。行情技术 artifact 可以引用公司行为状态或轻量诊断，但不能复制完整事实和应用账本。
- 长窗口演练可能因为行情技术 artifact 缺失而慢，这属于行情 artifact 准备性能问题，不是公司行为 local-first 逻辑问题。
