# 实时量化收益差异闭环设计

## 背景

同一时间段、同一账户规模、同一积极策略下，历史回放和实时量化演练存在明显收益差异：

- 历史回放 `run #47`：2026-01-01 10:00:00 到 2026-05-11 15:00:00，初始资金 400000，收益率约 `14.50%`。
- 实时量化演练 `run #55`：同区间、同资金、同策略，收益率约 `6.12%`。

股票级对比显示，收益差不是单一问题：

1. 部分盈利股买入时间正确，但演练仓位显著偏小，例如 `301666 大普微-UW`、`300283 温州宏丰`。
2. 部分盈利股演练买入明显偏晚，例如 `300736 百邦科技`、`300106 西部牧业`。
3. 部分演练额外买入的股票亏损，例如 `600768 宁波富邦`、`002319 乐通股份`。
4. 部分股票出现 recovery probe 反复试错并扩大亏损，例如 `301183 东田微`、`301369 联动科技`。
5. SELL 侧存在 `no_sellable_quantity`、弱 SELL 观察、硬风控 SELL 等不同原因，但当前结果显示它不是主要收益缺口来源，仍需要可诊断。

因此本设计目标不是继续单点调参数，而是建立“收益差异归因 -> 执行修正 -> 再演练验证”的闭环。

## 目标

1. 每次实时量化演练与历史回放对比后，必须能回答：
   - 收益股是买早了、买晚了，还是买对但仓位太小？
   - 亏损股是历史也买了但亏更多，还是实时演练额外误买？
   - SELL 是卖晚了，还是因为 T+1 / 无可卖数量 / 弱 SELL 观察导致没有成交？
2. 对已确认的主要收益差异，提供可执行的策略修正：
   - 强趋势恢复买入不再长期被 recovery probe 仓位压制。
   - 已经出现强/正常趋势确认的股票能更快进入可执行量化扫描。
   - 反复 probe 亏损的股票必须进入更严格的再入场模式。
   - false strong BUY 必须被二次过滤。
   - SELL 侧必须能输出明确阻断原因。
3. 不改变历史回放和实时量化演练的数据隔离原则。
4. 不把候选来源本身作为收益加分依据；候选来源只用于发现和解释，不直接提高交易质量评分。

## 非目标

1. 不新增第三套回测系统。
2. 不用固定历史回放结果倒推未来信号。
3. 不把所有实时演练行为强行对齐固定池历史回放；实时演练仍然保留动态入池、生命周期和真实执行约束。
4. 不通过简单放大所有仓位来追收益。

## 必须覆盖的问题

### 1. 收益归因报表

系统必须为一组可比较的 run 生成股票级收益归因。比较对象必须包含：

- `historical_range` run
- `live_quant_drill` run

比较维度：

1. 股票代码和名称。
2. 历史回放总 PnL：已实现盈亏 + 期末未实现盈亏。
3. 实时演练总 PnL：已实现盈亏 + 期末未实现盈亏。
4. 首次 BUY 时间、价格、金额。
5. 累计 BUY 金额。
6. SELL 次数、SELL 类型、ignored SELL 原因。
7. 演练侧 `buy_tier`、`lifecycle_gate.mode`、`sizing_cap_reason`、`blocked_reason`。

归因标签必须至少包含：

| 标签 | 定义 |
|---|---|
| `size_too_small` | 首次买入时间相近，买入价格相近，但演练累计买入金额显著低于历史回放。 |
| `entry_too_late` | 历史回放更早买入且盈利，演练首次买入晚于历史多个 checkpoint 或买入价格明显更高。 |
| `bad_extra_buy` | 演练买入但历史回放未买入，且该股最终亏损。 |
| `repeat_probe_loss` | 演练中同一股票多次 recovery probe 进场，且累计 probe 交易亏损。 |
| `sell_blocked_or_late` | SELL 信号存在但未成交、延迟成交，或因弱 SELL 观察没有执行。 |
| `drill_better` | 演练收益高于历史回放，用于识别动态生命周期带来的正面贡献。 |

归因输出必须支持：

1. API 查询。
2. 演练结果页展示。
3. 后续自动化验收脚本读取。

### 2. 盈利股买太小：strong recovery sizing 放大

问题样例：

- `301666 大普微-UW`：历史和演练在同一时间、同一价格买入，但演练买入金额明显小于历史，导致收益少约 23000。
- `300283 温州宏丰`：买入时间一致，但演练仓位约为历史的 45%。

规则调整：

1. 当 BUY 满足以下条件时，不能长期按 recovery probe 小仓位执行：
   - `buy_tier = strong_buy`
   - `lifecycle_gate.mode` 是 `recovery_probe` 或 `recovery_probe_confirmed`
   - 趋势确认达标
   - 最近 probe 没有失败记录
   - 当前股票没有处于 `probe_cooldown`
2. 该类信号应进入 `strong_recovery_confirmed` sizing：
   - 允许单笔预算达到 profile 的 `strong_recovery_confirmed_cap_pct`，具体上限仍受账户规模、组合风险、资金槽和单股上限约束。
   - 命中 `strong_recovery_confirmed` 后，必须显式覆盖 recovery gate 的仓位倍率：`lifecycle_gate.size_multiplier = 1.0`。
   - `strong_recovery_confirmed_cap_pct` 是该模式的 lifecycle gate 上限，不得再被 `recovery_probe_size_multiplier`、`trial_position_multiplier` 或 `cooling_supplemental_size_multiplier` 二次相乘。
   - 若最终仓位低于 `strong_recovery_confirmed_cap_pct`，只能来自组合风险、账户规模、资金槽、现金、一手成本或单股上限，并必须记录实际 cap reason。
   - 下一 checkpoint 若仍为 `normal_buy` 或 `strong_buy` 且趋势确认继续达标，应解除 recovery probe cap，按 `trial_confirmed` 或 `active` sizing 处理。
3. `normal_buy + recovery_probe` 不直接放大到 strong 档：
   - 默认维持 profile 的 `normal_recovery_cap_pct` 总权益上限。
   - 连续确认后才允许进入 `trial_confirmed` sizing。
4. `weak_buy + recovery_probe` 继续轻仓或观察，不允许因为候选来源或低价属性放大。

`strong_recovery_confirmed` 与现有 gate 的关系：

1. 它是 `lifecycle_gate.mode`，不是新的 `quant_status`。
2. DB 中股票的 `quant_status` 必须是 `trial`；若原状态是 `inactive` 或 `cooling`，进入该 sizing 前必须先写入 `quant_status = trial`，再附加 `lifecycle_gate.mode = strong_recovery_confirmed`。
3. 它只改变 BUY 执行 sizing，不绕过组合风险预算、T+1、涨跌停、现金和一手限制。
4. 它必须在 signal explain 和 execution sizing plan 中持久化，便于收益归因判断“买对但仓位太小”。

验收：

1. 对类似 `301666` 的同价同时间 strong BUY，演练买入金额不得低于历史回放买入金额的 `60%-70%`，除非组合预算或现金不足，并且必须记录明确 cap 原因。
2. `execution_sizing_plan` 必须写出最终命中的 cap，包括 `strong_recovery_confirmed_cap`、`portfolio_cap`、`slot_cap`、`cash_cap`。

### 3. 盈利股买太晚：更快纳入和恢复

问题样例：

- `300736 百邦科技`：历史 2026-01-06 买入，演练 2026-03-27 才买入，错过主升段。
- `300106 西部牧业`：历史 2026-03-30 买入，演练 2026-05-06 才买入。

规则调整：

1. 每日候选生成后，若候选股票已满足趋势确认，不应只进入低优先级观察。
2. 对于候选事件或 cooling review 中出现的股票，如果满足：
   - `buy_tier >= normal_buy`
   - `price > MA20`
   - `MA20` 上行
   - `MA5 > MA10 > MA20`，或连续达到 profile 默认确认窗口的 checkpoint 站上 MA20
   - 非涨停、非停牌、非数据缺失
3. 则允许：
   - `inactive -> trial_confirmed`
   - `cooling -> trial_confirmed`
   - 在同一 checkpoint 或下一 checkpoint 进入可执行扫描。
4. 若出现 `strong_buy` 且趋势确认完整：
   - 可直接进入 `strong_recovery_confirmed` sizing。
   - 不需要等生命周期状态自然多轮升级。
5. 若只有候选推荐但无交易确认：
   - 只能进入普通 `trial`，不能直接放大仓位。

`trial_confirmed` 语义：

1. `trial_confirmed` 不是新的生命周期状态，不写入 `stock_universe.quant_status` 或 `sim_run_quant_states.quant_status`。
2. `trial_confirmed` 是 `lifecycle_gate.mode`，表示该股票仍处于 `trial`，但当前 BUY 已通过趋势确认；单笔 sizing 的 `lifecycle_cap_status` 使用 `active` 档位，聚合风险统计仍使用 `trial` 档位。
3. `trial_confirmed` 的组合统计仍归入 `trial`：
   - 继续占用 trial 总暴露上限。
   - 继续占用 checkpoint / daily trial 风险预算。
   - 继续受 trial 风险诊断和 probe fatigue 管控。
4. `trial_confirmed` 不等于 `active`：
   - 只有连续确认满足 profile 的 `active_upgrade_confirm_checkpoints`，并且 health / execution feedback 未触发阻断，才允许 `trial -> active`。
   - 若确认失败，仍回到普通 `trial` 或进入 `cooling/exit_only`，但必须记录失败原因。
5. `execution_sizing_plan.lifecycle_cap_status` 可以按 `active` 档计算单笔 cap，但必须同时保留 `quant_status = trial` 供组合预算使用，避免绕过 trial 聚合风险。

验收：

1. 早期赢家不应因为 lifecycle/cooling 门控延迟数周才买入。
2. 结果页必须展示 `entry_delay_reason`：
   - `not_in_universe`
   - `cooling_gate`
   - `trend_not_confirmed`
   - `probe_cooldown`
   - `budget_blocked`
   - `data_missing`

### 4. 亏损股不该反复买：probe fatigue 与 probe cooldown

问题样例：

- `301183 东田微`：历史基本持平，演练多次 probe 后亏损扩大。
- `301369 联动科技`：历史也亏，但演练反复进场导致亏更多。

规则调整：

1. 每只股票必须维护 recovery probe 诊断状态：
   - `probe_attempt_count`
   - `recent_probe_loss_count`
   - `last_recovery_probe_attempt_at`
   - `last_recovery_probe_failure_at`
   - `probe_failure_reason`
   - `recovery_probe_cooldown_until`
2. 同一股票在 profile 默认 probe 回看窗口内满足任一条件时进入 `probe_strict_mode`：
   - recovery probe 尝试次数达到阈值但没有正收益。
   - probe 后快速进入 `exit_only` 或 `cooling`。
   - probe 后 SELL 为硬止损。
3. 同一股票在 profile 默认 probe 回看窗口内出现 `2` 次 probe 亏损时进入 `probe_cooldown`。
4. `probe_strict_mode` 下：
   - `normal_buy` 不允许恢复到可放大仓位。
   - 只有 `strong_buy + 趋势确认 + 非过热 + 非偏离 MA20 过远` 才能恢复。
   - 仓位上限降到 `2%-3%`。
5. `probe_cooldown` 下：
   - 普通候选事件不能把股票拉回量化。
   - cooling review 只能记录诊断，不得自动恢复。
   - 只有冷却期结束或更高等级强趋势确认才能重新进入。

验收：

1. `301183`、`301369` 这类股票不能在短期内靠普通 recovery probe 反复买入。
2. 每次 probe 被允许或拒绝，必须记录 reason：
   - `probe_allowed_strong_confirmation`
   - `probe_blocked_recent_loss`
   - `probe_blocked_attempt_fatigue`
   - `probe_blocked_cooldown`
   - `probe_allowed_small_size_only`

### 5. false strong BUY 二次过滤

问题样例：

- `600768 宁波富邦`：演练买入但历史未买，最终亏损，属于疑似 false strong / recovery confirmed。

规则调整：

1. `strong_buy` 不得只由分数阈值决定，必须通过结构确认。
2. 下列条件至少满足一组：
   - `MA5 > MA10 > MA20` 且 `MA20` 上行。
   - `price > MA20` 连续达到 profile 默认确认窗口的 checkpoint，且 `MA20` 上行。
   - 突破后回踩不破 MA20，再次转强。
3. 下列情况必须降级：
   - RSI 过热且价格距离 MA20 过远。
   - 刚从 cooling 恢复但没有连续确认。
   - 近期 probe 失败。
   - 只是低价、量比或短线反弹导致分数达标。
4. 降级方式：
   - `strong_buy -> normal_buy`
   - 或保留 strong 标签但执行层按 `normal/probe` cap 计算，并记录 `strong_buy_execution_downgraded`。
5. 候选来源不得直接使 BUY 升级为 strong。

验收：

1. false strong 的亏损占比应下降。
2. 被降级的 strong 信号必须能在信号详情中看到原因：
   - `weak_trend_structure`
   - `overheated_distance`
   - `recent_probe_failure`
   - `source_only_strength`

### 6. SELL 诊断与卖晚判断

当前收益缺口主要在 BUY 侧，但 SELL 侧必须能解释，不允许只看到 ignored。

规则调整：

1. 每个 SELL 信号必须记录：
   - `sell_trigger_type`
   - `hard_veto_id`
   - `is_weak_sell_observe`
   - `sellable_quantity`
   - `locked_quantity`
   - `blocked_reason`
   - `first_sell_signal_at`
   - `actual_sell_at`
2. SELL 分类：
   - `hard_stop_loss`
   - `hard_profit_trailing_stop`
   - `profit_tech_sell`
   - `weak_sell_observe`
   - `t1_blocked`
   - `no_sellable_quantity`
3. 若同一股票出现 SELL 信号但连续多个 checkpoint 无法成交，必须在结果页标记为 `sell_blocked_or_late`。
4. 弱 SELL 观察不算卖晚，但必须统计观察期间价格变化。

验收：

1. 能区分“算法没卖”和“T+1/无可卖导致卖不了”。
2. 能区分“弱 SELL 观察”和“硬风控 SELL 未执行”。
3. 结果页能列出造成收益损失最大的 SELL 阻断事件。

### 7. active 降级保护衔接

问题：

1. `strong_recovery_confirmed` 和 `trial_confirmed` 解决的是“买得太小 / 买得太晚”。
2. 如果股票买入后很快升级到 `active`，但 1-2 个短周期弱化 checkpoint 就被打回 `exit_only/cooling`，盈利股仍然留不住。
3. 因此 strong/confirmed 买入后的 active 状态必须有降级保护，但不能屏蔽硬风控。

规则调整：

1. 下列路径进入 active 后，应启动 active 保护窗口：
   - `trial_confirmed` 连续确认后正式 `trial -> active`。
   - `strong_recovery_confirmed` 买入后，后续 checkpoint 仍保持 `normal_buy/strong_buy` 并升级 active。
   - `cooling -> trial_confirmed -> active`。
2. 保护窗口长度使用 profile 的 `active_min_dwell_checkpoints`。
3. 保护窗口内：
   - 普通短周期弱化不得直接触发 `active -> exit_only` 或 `active -> cooling`。
   - 普通 `dual_track_weighted_sell` 必须进入 `weak_sell_observe` 或 `active_guarded`，不得立即清仓。
   - 若趋势弱化但未触发硬风控，应保留 `active` 状态并附加 `lifecycle_gate.mode = active_guarded`。
4. 下列硬风控不受保护窗口影响，必须继续允许 SELL 或 exit-only：
   - `hard_stop_loss`
   - `stop_loss`
   - `risk_stop`
   - `quick_stoploss`
   - `hard_profit_trailing_stop`
   - `profit_tech_sell`
   - 涨跌停 / 停牌 / 数据异常造成的不可交易诊断不改变 SELL 触发，只影响成交可行性。
5. 保护窗口结束后，active 降级必须使用 active 专属确认条件：
   - 有持仓：连续达到 `active_exit_only_downtrend_streak` 才允许 `active -> exit_only`。
   - 无持仓：连续达到 `active_cooling_downtrend_streak` 才允许 `active -> cooling`。
   - 健康分未跌破 profile 阈值时，只允许进入 `active_guarded`，不得直接出池。
6. 每次 active 降级被阻止或执行，必须记录 reason：
   - `active_min_dwell_guarded`
   - `active_downtrend_guarded`
   - `active_holding_downtrend_exit_only`
   - `active_flat_downtrend_cooling`
   - `active_hard_risk_exit`

验收：

1. strong/confirmed BUY 后升级 active 的股票，不会因 1-2 个普通弱化 checkpoint 立即掉回 `cooling/exit_only`。
2. 硬止损、硬浮盈回撤和 profit protection 仍然能立即触发 SELL。
3. 结果页能看出 active 是被保护、被 guarded，还是被硬风控退出。

## Profile 默认参数

本 spec 的阈值必须进入策略 profile 配置，并在 UI 的策略配置中可调整。默认值先按下表执行：

| 参数 | aggressive | stable | conservative | 用途 |
|---|---:|---:|---:|---|
| `trend_confirm_checkpoints` | 2 | 3 | 4 | 连续站上 MA20 / 趋势确认窗口。 |
| `strong_recovery_confirmed_cap_pct` | 10.0 | 8.0 | 6.0 | strong recovery confirmed 单笔仓位上限。 |
| `normal_recovery_cap_pct` | 6.0 | 5.0 | 4.0 | normal recovery 单笔仓位上限。 |
| `failed_probe_cap_pct` | 2.5 | 2.0 | 1.5 | probe 失败后的轻仓上限。 |
| `probe_lookback_days` | 30 | 30 | 30 | probe strict / cooldown 回看窗口。 |
| `probe_attempt_fatigue_threshold` | 4 | 3 | 2 | 回看窗口内 probe 尝试过多阈值。 |
| `probe_loss_cooldown_threshold` | 2 | 2 | 2 | 回看窗口内 probe 亏损触发 cooldown 的次数。 |
| `probe_cooldown_days` | 15 | 20 | 30 | probe cooldown 时长。 |
| `false_strong_ma20_distance_pct` | 10.0 | 8.0 | 6.0 | 距离 MA20 过远时 strong 降级阈值。 |
| `false_strong_hot_rsi` | 86.0 | 82.0 | 78.0 | RSI 过热降级阈值。 |
| `active_min_dwell_checkpoints` | 16 | 12 | 8 | active 升级后的最短保护窗口。 |
| `active_exit_only_downtrend_streak` | 6 | 5 | 4 | 有持仓 active 进入 exit_only 的连续下行确认次数。 |
| `active_cooling_downtrend_streak` | 8 | 6 | 4 | 空仓 active 进入 cooling 的连续下行确认次数。 |
| `active_guarded_size_multiplier` | 0.35 | 0.30 | 0.25 | active 短期弱化但未硬退出时的仓位倍率。 |
| `active_guarded_max_position_pct` | 4.0 | 3.0 | 2.0 | active_guarded 单笔仓位上限。 |

默认值允许后续通过演练结果微调，但实现必须支持 profile 级覆盖；不得把这些值硬编码在单个服务里。

## 数据契约

### Profit Gap Attribution

新增以下结构：

```json
{
  "comparison_id": 1,
  "historical_run_id": 47,
  "drill_run_id": 55,
  "stock_code": "301666",
  "stock_name": "大普微-UW",
  "historical_total_pnl": 41119.0,
  "drill_total_pnl": 18023.59,
  "pnl_gap": 23095.41,
  "historical_first_buy_at": "2026-04-28T02:00:00Z",
  "drill_first_buy_at": "2026-04-28T02:00:00Z",
  "historical_first_buy_price": 243.14,
  "drill_first_buy_price": 243.14,
  "historical_buy_amount": 95156.0,
  "drill_buy_amount": 24321.29,
  "attribution_labels": ["size_too_small"],
  "primary_reason": "strong recovery confirmed sizing was capped by recovery_probe",
  "evidence_json": {
    "buy_tier": "strong_buy",
    "lifecycle_gate_mode": "recovery_probe_confirmed",
    "cap_reason": "recovery_probe_max_position_pct"
  }
}
```

### Signal Execution Diagnostics

BUY 信号必须追加：

```json
{
  "buy_tier": "strong_buy",
  "entry_delay_reason": "cooling_gate",
  "lifecycle_gate_mode": "recovery_probe_confirmed",
  "sizing_cap_reason": "strong_recovery_confirmed_cap",
  "probe_attempt_count": 1,
  "recent_probe_loss_count": 0,
  "strong_filter_result": "passed"
}
```

SELL 信号必须追加：

```json
{
  "sell_trigger_type": "hard_stop_loss",
  "hard_veto_id": "hard_stop_loss",
  "sellable_quantity": 0,
  "locked_quantity": 300,
  "blocked_reason": "no_sellable_quantity",
  "first_sell_signal_at": "2026-03-02T02:00:00Z",
  "actual_sell_at": null
}
```

## UI 要求

实时量化演练结果页新增“收益差异归因”区域：

1. 顶部汇总：
   - 历史收益率
   - 演练收益率
   - 收益差额
   - 最大差异股票
2. 股票级表格：
   - 股票
   - 历史 PnL
   - 演练 PnL
   - 差额
   - 首买时间差
   - 买入金额比例
   - 归因标签
   - 主要原因
3. 支持筛选：
   - 买太小
   - 买太晚
   - 额外误买
   - probe 反复亏损
   - SELL 阻断
4. 点击股票可进入股票详情或该 run 的信号明细。

## 验收标准

1. 同区间 40W、积极、AI hybrid 再跑演练后，能自动生成和历史回放的股票级差异归因。
2. `301666`、`300283` 这类同时间强买股票，不再因为 recovery probe 长期小仓位导致主要收益缺口。
3. `300736`、`300106` 这类历史早期赢家，若实时演练未早买，系统必须明确给出原因，且不能因为 cooling/trial 低效恢复延迟数周。
4. `301183`、`301369` 这类 probe 反复亏损股票，必须触发 strict 或 cooldown 诊断。
5. `600768` 这类 false strong 必须能被降级或给出执行层降仓原因。
6. SELL ignored 必须能区分 T+1、无可卖、弱 SELL 观察和硬风控阻断。
7. 演练收益不要求等于历史回放，但应显著缩小收益差；若收益仍低，归因报表必须能指出下一轮主要缺口。

## 自检

1. 本 spec 覆盖收益归因、强恢复仓位、晚入场、probe 反复亏损、false strong、SELL 诊断六类问题。
2. 本 spec 不把候选来源当作交易加分项，符合“来源不影响股票价值”的约束。
3. 本 spec 不改变历史回放和实时量化演练的数据隔离。
4. 本 spec 没有依赖未来数据；所有判断必须基于 checkpoint 当时可见的数据。
