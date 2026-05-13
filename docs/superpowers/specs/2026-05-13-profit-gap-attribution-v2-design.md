# 收益差异归因 V2 设计

## 背景

上一轮实时量化收益闭环已经完成基础归因：

- 历史回放 `run #58`：2026-01-01 10:00:00 到 2026-05-11 15:00:00，40W，积极策略，AI hybrid，收益率 `8.9330%`。
- 实时量化演练 `run #56`：同区间、同资金、同策略，收益率 `7.5723%`。
- 已生成 `43` 条股票级归因。

当前归因分布：

| 标签 | 数量 | 说明 |
|---|---:|---|
| `entry_too_late` | 4 | 演练晚于历史买入。 |
| `size_too_small` | 2 | 演练买入时机正确，但仓位偏小。 |
| `bad_extra_buy` | 7 | 演练额外买入且最终亏损。 |
| `sell_blocked_or_late` | 2 | SELL 有阻断或延迟诊断。 |
| `drill_better` | 14 | 实时演练优于历史回放。 |
| `unclassified` | 18 | 归因粒度不足，无法指导下一轮修改。 |

Top 缺口：

1. `300736 百邦科技`：`entry_too_late`，差额 `11629.382`。
2. `301666 大普微-UW`：`size_too_small`，差额 `5009.41`。
3. `600768 宁波富邦`：`bad_extra_buy`，差额 `2996.978`。
4. `300283 温州宏丰`：`size_too_small`，差额 `2801.8259`。
5. `002319 乐通股份`：`bad_extra_buy`，差额 `1789.1432`。
6. `300106 西部牧业`：`unclassified`，差额 `1735.2`。

V1 的问题不是方向错，而是粒度还不够：它能指出“买晚 / 买小 / 误买”，但不能稳定回答“为什么买晚、哪个 gate 卡住、哪个 cap 卡住、误买是否可避免、unclassified 到底是哪类差异”。

## 目标

1. 将收益差异从一级标签推进到可执行的二级原因。
2. 将所有非零大额 `unclassified` 收敛到明确类别。
3. 对 Top 缺口股票输出下一步可直接落到策略代码的建议。
4. 保留 `drill_better` 的正向贡献，避免为了追平历史回放而破坏实时演练的优势。
5. 不在本 spec 中直接调整交易策略参数；本 spec 只定义诊断、数据和验收，为下一轮实现提供依据。

## 非目标

1. 不新增第三套回测或演练系统。
2. 不用历史回放结果反向喂给实时量化决策。
3. 不把候选来源当作 alpha 加分。
4. 不把所有 `bad_extra_buy` 一刀切禁止；需要区分可避免误买和合理探索亏损。
5. 不要求实时演练收益完全等于历史回放；要求能解释差异并给出可执行改进方向。

## 归因 V2 总体设计

V2 归因从当前的一层标签扩展为三层结构：

```text
primary_label
  -> sub_reason
      -> recommended_action
```

示例：

```json
{
  "stock_code": "300736",
  "primary_label": "entry_too_late",
  "sub_reason": "candidate_discovered_late",
  "recommended_action": "check historical candidate event generation and cooling review eligibility before 2026-01-06"
}
```

每条归因必须包含：

1. `primary_label`：保留 V1 标签。
2. `sub_reason`：二级原因，必须来自枚举。
3. `severity`：`high | medium | low | none`。
4. `actionable`：是否能转化为策略或执行层修改。
5. `recommended_action`：一句明确建议。
6. `evidence_json`：支持判断的时间线和 cap/gate 证据。

## 新增二级原因

### 1. `entry_too_late`

`entry_too_late` 必须细分为：

| sub_reason | 定义 | 下一步方向 |
|---|---|---|
| `candidate_discovered_late` | 历史回放首次 BUY 前，演练还没有对应候选事件。 | 检查历史候选生成频率、候选来源历史可用性、每日发现覆盖。 |
| `candidate_not_promoted` | 候选事件已经出现，但没有进入量化生命周期。 | 检查 auto-entry 阈值、candidate_score、前置过滤。 |
| `lifecycle_gate_delayed` | 股票已在 lifecycle 中，但被 cooling/probe/trial gate 延迟。 | 检查 cooling review、trial_confirmed、probe strict/cooldown。 |
| `execution_budget_delayed` | 同 checkpoint 有 BUY，但被资金槽、batch cap、现金或排序延迟。 | 检查 batch cap 使用实际仓位后的排序和预算耗尽。 |
| `entry_signal_not_strong_enough` | 当时已有扫描，但 BUY tier 未达到可执行门槛。 | 检查 buy tier 公式、confirmation_score、趋势确认窗口。 |
| `data_missing_or_stale` | 当时行情、技术指标或公司行为数据缺失导致不能扫描。 | 检查 local-first 历史数据准备和 cache coverage。 |

`entry_too_late` 的证据必须包含：

```json
{
  "historical_first_buy_at": "2026-01-06T02:00:00Z",
  "drill_first_buy_at": "2026-03-27T02:00:00Z",
  "first_candidate_event_at": "2026-01-05T02:00:00Z",
  "first_quant_state_at": "2026-01-05T02:00:00Z",
  "first_buy_signal_at": "2026-01-06T02:00:00Z",
  "first_ignored_buy_reason": "checkpoint_trial_risk_budget_exhausted",
  "entry_delay_checkpoints": 120
}
```

### 2. `size_too_small`

`size_too_small` 必须细分为：

| sub_reason | 定义 | 下一步方向 |
|---|---|---|
| `recovery_probe_cap` | 被 recovery probe 或 failed probe cap 压仓。 | 检查 strong_recovery_confirmed 是否解除 multiplier。 |
| `trial_aggregate_cap` | 单笔可买，但 trial 总暴露或 checkpoint/daily trial 风险预算限制。 | 检查 batch cap 是否按实际仓位计算、是否过早耗尽。 |
| `account_tier_cap` | 被账户规模分层单股上限截断。 | 检查当前资金规模下 strong/normal cap 是否合理。 |
| `slot_or_cash_cap` | 被资金槽可用现金、现金余额、一手成本限制。 | 检查 slot sizing 和 fractional slot fallback。 |
| `weak_or_normal_tier_cap` | BUY 没进入 strong，按 weak/normal 上限执行。 | 检查强趋势确认是否被 false-strong filter 误降级。 |
| `existing_position_cap` | 已有持仓导致新增预算受单股总仓位限制。 | 检查是否应允许趋势确认后的正常加仓。 |

`size_too_small` 的证据必须包含完整 cap chain：

```json
{
  "requested_position_pct": 0.18,
  "kernel_quality_position_pct": 0.12,
  "buy_tier_cap_pct": 0.15,
  "lifecycle_cap_pct": 0.10,
  "portfolio_cap_pct": 0.08,
  "slot_cap_pct": 0.06,
  "cash_cap_pct": 0.06,
  "effective_position_pct": 0.06,
  "primary_cap_reason": "slot_or_cash_cap"
}
```

### 3. `bad_extra_buy`

`bad_extra_buy` 必须区分“可避免误买”和“合理探索亏损”。

| sub_reason | 定义 | 下一步方向 |
|---|---|---|
| `false_strong_structure_weak` | 被识别为 strong/normal，但趋势结构不足。 | 加强 MA20 上行、MA stack、回踩确认。 |
| `late_rebound_chase` | 下跌后的弱反弹尾段买入，随后快速转弱。 | 加入反弹尾段识别和更严 entry confirmation。 |
| `probe_repeat_after_loss` | 最近 probe 失败后仍再次恢复买入。 | 强化 probe fatigue/cooldown。 |
| `low_price_source_overreach` | 主要由低价候选触发，缺少趋势确认。 | 候选只做推荐，不可绕过交易确认。 |
| `acceptable_exploration_loss` | 当时满足 normal/strong 条件，亏损来自后续行情反转。 | 不直接修策略，只记录风险。 |

`bad_extra_buy` 的证据必须包含：

1. 首次 BUY 的 `buy_tier`。
2. 首次 BUY 的 `buy_strength_score`。
3. `trend_confirmation`。
4. `rsi`、`ma20_distance_pct`、`ma20_slope`。
5. 最近 probe attempts/losses。
6. BUY 后 N 个 checkpoint 内是否进入 `exit_only/cooling`。

### 4. `sell_blocked_or_late`

`sell_blocked_or_late` 必须细分为：

| sub_reason | 定义 | 下一步方向 |
|---|---|---|
| `t1_blocked` | SELL 出现但可卖数量为 0 或被 T+1 锁定。 | 不改算法，只标记交易制度影响。 |
| `no_sellable_quantity` | 没有可卖 lot。 | 检查 lot allocation 和 corporate action 调整。 |
| `weak_sell_observe_loss` | 弱 SELL 观察期间价格继续下跌并造成损失。 | 检查 weak SELL 观察窗口和 active_guarded。 |
| `hard_sell_not_executed` | hard stop / profit protection SELL 未执行。 | P0 风控 bug，必须修。 |
| `sell_signal_late` | SELL 信号本身晚于历史回放。 | 检查 profit trailing、tech sell 和 active 降级保护。 |

### 5. `unclassified`

`unclassified` 只能用于以下情况：

1. `abs(pnl_gap) < 100`，差异太小。
2. 两边都没有交易，只有期末 mark-to-market 小差异。
3. 证据缺失，无法判断。

所有 `abs(pnl_gap) >= 500` 的股票不得保持 `unclassified`。必须落入：

| 新标签 | 定义 |
|---|---|
| `same_entry_exit_gap` | 首买接近，但 SELL/期末持仓处理不同。 |
| `mark_to_market_gap` | 主要来自期末未实现盈亏口径差异。 |
| `rounding_or_lot_gap` | 主要来自一手、lot、slot、取整造成的小金额差异。 |
| `missing_evidence` | 数据缺失导致无法判断，但必须明确缺什么。 |

## 数据模型

扩展 `sim_run_profit_gap_attributions`，新增字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `primary_label` | TEXT | 一级标签；等价于 `attribution_labels[0]`。 |
| `sub_reason` | TEXT | 二级原因枚举。 |
| `severity` | TEXT | `high | medium | low | none`。 |
| `actionable` | INTEGER | 1 表示可转化为策略/执行修改。 |
| `recommended_action` | TEXT | 下一步建议。 |
| `historical_trade_path_json` | TEXT | 历史回放该股票的 BUY/SELL 路径摘要。 |
| `drill_trade_path_json` | TEXT | 演练该股票的 BUY/SELL 路径摘要。 |
| `entry_timeline_json` | TEXT | 候选、入池、信号、执行时间线。 |
| `sizing_cap_chain_json` | TEXT | 仓位 cap 链路。 |
| `sell_diagnostics_json` | TEXT | SELL 诊断摘要。 |

兼容要求：

1. 继续保留 `attribution_labels_json` 和 `evidence_json`。
2. API 返回时同时提供旧字段和新字段。
3. 旧 UI 不依赖新字段也能正常展示。

## 归因生成逻辑

### 输入

归因服务必须从 replay DB 读取：

1. `sim_run_trades`
2. `sim_run_positions`
3. `sim_run_signals`
4. `sim_run_quant_states`
5. `sim_run_quant_events`
6. `sim_run_candidate_events`
7. `sim_run_quant_summary`

### 时间线提取

每只股票必须生成：

```json
{
  "first_candidate_event_at": null,
  "first_candidate_score": null,
  "first_quant_state_at": null,
  "first_quant_status": null,
  "first_buy_signal_at": null,
  "first_ignored_buy_reason": null,
  "first_executed_buy_at": null,
  "first_executed_buy_price": null,
  "first_executed_buy_amount": null,
  "first_sell_signal_at": null,
  "first_executed_sell_at": null
}
```

### 决策顺序

归因分类顺序必须固定：

1. 若 `drill_total_pnl > historical_total_pnl`，标记 `drill_better`，但仍可附加辅助标签。
2. 若演练买入而历史未买且亏损，标记 `bad_extra_buy` 并细分 sub_reason。
3. 若历史买入而演练未买或明显晚买，标记 `entry_too_late`。
4. 若首买时间和价格接近但金额低，标记 `size_too_small`。
5. 若首买接近但退出路径不同，标记 `same_entry_exit_gap`。
6. 若 SELL 有阻断且造成明显损失，标记 `sell_blocked_or_late`。
7. 若差异小于阈值，标记 `rounding_or_lot_gap` 或 `mark_to_market_gap`。
8. 最后仍无法判断，标记 `missing_evidence`，不得使用裸 `unclassified`。

## API 要求

现有接口：

```text
GET /api/v1/quant/his-replay/runs/{drill_run_id}/profit-gap?historicalRunId=58
```

需要新增筛选参数：

| 参数 | 说明 |
|---|---|
| `label` | 过滤一级标签。 |
| `subReason` | 过滤二级原因。 |
| `severity` | 过滤严重级别。 |
| `actionable` | `true/false`。 |
| `minAbsGap` | 最小绝对差额。 |
| `stock` | 代码/名称搜索。 |

返回结构：

```json
{
  "historical_run_id": 58,
  "drill_run_id": 56,
  "summary": {
    "total": 43,
    "actionable_count": 12,
    "high_count": 5,
    "unclassified_large_gap_count": 0,
    "label_counts": {"entry_too_late": 4},
    "sub_reason_counts": {"candidate_discovered_late": 2}
  },
  "items": []
}
```

## UI 要求

历史回放页的“收益差异归因”区域需要扩展：

1. 顶部显示：
   - 历史收益率
   - 演练收益率
   - 收益差额
   - 可行动问题数量
   - 大额未分类数量
2. 表格新增列：
   - 一级标签
   - 二级原因
   - 严重级别
   - 是否可行动
   - 建议动作
3. 支持筛选：
   - 买太晚
   - 买太小
   - 误买
   - SELL 阻断
   - 正向贡献
   - 可行动
   - 大额差异
4. 点击行展开：
   - 时间线
   - cap chain
   - SELL 诊断
   - drill/historical 交易路径对比

UI 文案必须国际化。

## 验收标准

使用 `run #58` 对比 `run #56`：

1. `abs(pnl_gap) >= 500` 的股票，`sub_reason` 覆盖率必须为 `100%`。
2. `unclassified` 不得出现在 `abs(pnl_gap) >= 500` 的股票上。
3. Top 10 差异股票必须都有 `recommended_action`。
4. `300736` 必须被细分到 `entry_too_late` 的某个具体 sub_reason。
5. `301666` 和 `300283` 必须输出完整 `sizing_cap_chain_json`。
6. `600768`、`002319` 必须区分 `false_strong_structure_weak`、`late_rebound_chase`、`probe_repeat_after_loss`、`acceptable_exploration_loss` 中的一类。
7. `300106` 不得继续是裸 `unclassified`。
8. API 支持按 label/subReason/actionable/minAbsGap 筛选。
9. 前端构建和现有测试通过。

## 后续策略修改入口

V2 归因完成后，下一轮策略修改只允许基于以下证据触发：

1. 若 `entry_too_late.candidate_discovered_late` 占主导，优先改候选生成频率或历史候选覆盖。
2. 若 `entry_too_late.lifecycle_gate_delayed` 占主导，优先改 cooling review / trial_confirmed。
3. 若 `size_too_small.recovery_probe_cap` 占主导，优先改 confirmed recovery sizing。
4. 若 `size_too_small.trial_aggregate_cap` 占主导，优先改 batch cap 排序和预算释放。
5. 若 `bad_extra_buy.false_strong_structure_weak` 占主导，优先改 strong filter。
6. 若 `bad_extra_buy.acceptable_exploration_loss` 占主导，不应收紧策略，只记录风险。
7. 若 `sell_blocked_or_late.hard_sell_not_executed` 出现，必须优先修风控 SELL。

## 自检

1. 本 spec 只定义诊断和分析，不直接改交易策略。
2. 所有新增字段都有明确用途。
3. `unclassified` 的使用边界明确，不会继续吞掉大额差异。
4. 归因不使用未来数据作为实时决策输入；它只比较已完成 run 的结果。
5. 候选来源仍然只用于解释，不作为交易质量加分。
