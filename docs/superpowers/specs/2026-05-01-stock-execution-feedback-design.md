# 个股执行反馈机制设计

## 背景

历史回放和实时模拟已经共享 QuantSimDB、策略配置、候选池和资金槽语义，但运行状态数据必须隔离。现有再入场控制主要覆盖“止盈后短期追高”和“过热 BUY 降仓”，没有完整处理同一只股票反复止损、近期累计亏损后继续 BUY、以及假突破导致的重复买入。

本设计新增“个股执行反馈”机制：同一个规则引擎同时服务实时模拟和历史回放；实时模拟只读取 live 表，历史回放只读取回放临时运行域内的数据，最终持久化到 `sim_run_*` 表时不得污染 live 状态。

## 目标

1. 同一股票最近窗口内连续止损后，暂停新开仓，除非出现强趋势确认。
2. 同一股票近期已实现亏损超过阈值后，后续 BUY 降低仓位上限。
3. 假突破过滤不能只看站上 MA5/MA20，需要 MA20 上行、连续确认、均线多头排列或回踩不破 MA20。
4. 积极、中性、保守策略使用不同默认参数，并可在 UI 策略配置页调整。
5. live-sim 和 his-replay 复用同一套规则计算，但查询数据源隔离。
6. 信号来源如 `main_force` 只保留为候选来源和溯源信息，不因来源获得加分。

## 非目标

1. 不新增跨任务的回放经验学习。每个历史回放任务只使用该任务自身执行历史。
2. 不把历史回放成交写入 `strategy_signals`、`sim_trades`、`sim_positions` 等 live 状态表。
3. 不通过 `source_prior/main_force` 调整 BUY 分数；个股反馈只通过执行反馈分、门控和仓位倍率生效。

## 配置结构

策略配置增加 `stock_execution_feedback_policy`，放在 profile 的 `base.context` 下，允许 candidate 和 position profile 继承。

字段：

```json
{
  "enabled": true,
  "lookback_days": 20,
  "stop_loss_count_threshold": 2,
  "stop_loss_cooldown_days": 12,
  "loss_pnl_pct_threshold": -5.0,
  "loss_amount_threshold": -1000.0,
  "loss_reentry_size_multiplier": 0.35,
  "repeated_stop_size_multiplier": 0.25,
  "require_trend_confirmation": true,
  "trend_confirm_checkpoints": 3,
  "require_ma20_slope": true,
  "allow_ma_stack_confirmation": true,
  "allow_ma20_retest_confirmation": true,
  "strict_reentry_trend_confirmation": true,
  "execution_feedback_score_cap": 0.25
}
```

默认值：

| 参数 | 积极 | 中性 | 保守 |
| --- | ---: | ---: | ---: |
| `lookback_days` | 20 | 30 | 45 |
| `stop_loss_count_threshold` | 2 | 2 | 2 |
| `stop_loss_cooldown_days` | 8 | 12 | 20 |
| `loss_pnl_pct_threshold` | -8.0 | -5.0 | -3.0 |
| `loss_amount_threshold` | -2000 | -1000 | -500 |
| `loss_reentry_size_multiplier` | 0.50 | 0.35 | 0.25 |
| `repeated_stop_size_multiplier` | 0.25 | 0.25 | 0.15 |
| `trend_confirm_checkpoints` | 2 | 3 | 3 |
| `strict_reentry_trend_confirmation` | true | true | true |

## 运行机制

新增公共模块 `app/quant_sim/stock_execution_feedback.py`：

1. 输入：
   - `stock_code`
   - 当前决策时间
   - 当前市场快照
   - 策略 policy
   - 当前股票最近执行摘要
   - 可选的近期 checkpoint 快照摘要
2. 输出：
   - `status`: `passed | downgraded | blocked`
   - `intent`: `stock_execution_feedback`
   - `size_multiplier`
   - `execution_feedback_score`
   - `recent_stop_loss_count`
   - `recent_realized_pnl`
   - `recent_realized_pnl_pct`
   - `trend_confirmed`
   - `reasons`

动作规则：

1. 非 BUY 不处理。
2. 已有持仓的加仓继续走原有加仓门控，不使用新开仓冷却阻断。
3. policy disabled 时直接 `passed`。
4. 最近窗口内止损次数达到阈值：
   - 无强趋势确认：BUY 改 HOLD，仓位 0。
   - 有强趋势确认：BUY 保留，但仓位倍率不超过 `repeated_stop_size_multiplier`。
5. 最近累计亏损达到金额或百分比阈值：
   - BUY 保留，但仓位倍率不超过 `loss_reentry_size_multiplier`。
6. 假突破过滤：
   - 如果处于亏损/止损反馈状态，并且只满足 `price > MA20`，不算强趋势确认。
   - 当前默认 `strict_reentry_trend_confirmation=true`。亏损/止损反馈后的强趋势确认必须同时满足：
     - `price > MA20`，且 `MA5 > MA10 > MA20`
     - 最近连续 `trend_confirm_checkpoints` 个 checkpoint 都站上 MA20
     - 最近突破后回踩低点不破 MA20，并重新站上 MA20
     - 如果 `require_ma20_slope=true`，上述 MA 多头和连续 checkpoint 都要求 MA20 slope > 0
   - 只有显式配置 `strict_reentry_trend_confirmation=false` 时，才退回兼容模式：MA 多头、连续 checkpoint、MA20 回踩确认满足任一类即可通过。

## 数据隔离

实时模拟 provider：

1. 查询 `strategy_signals` 和 `sim_trades`。
2. 不读取 `sim_run_signals`、`sim_run_trades`。
3. 使用当前 live DB 里的已执行记录。

历史回放 provider：

1. 回放执行期间运行在 temp DB 内，查询 temp DB 的 `strategy_signals` 和 `sim_trades`。
2. temp DB 只包含当前回放任务产生的数据，因此天然按任务隔离。
3. 回放结果持久化到主 DB 时写入 `sim_run_signals`、`sim_run_trades`，不写 live 表。

如果未来直接在主 DB 上做 replay 增量执行，必须改为按 `run_id` 查询 `sim_run_*`，不能复用 live provider。

## UI

策略配置页新增或扩展“个股执行反馈”区域，字段映射到 `stock_execution_feedback_policy`：

1. 启用执行反馈
2. 回看天数
3. 止损次数阈值
4. 止损冷却天数
5. 亏损百分比阈值
6. 亏损金额阈值
7. 亏损再买仓位倍率
8. 连续止损例外仓位倍率
9. 趋势确认 checkpoint 数
10. MA20 上行要求
11. 均线多头排列确认
12. 回踩不破 MA20 确认
13. 亏损后复买严格趋势确认

## 测试要求

1. 公共规则单测：连续 2 次止损且无趋势确认时 BUY 变 HOLD。
2. 公共规则单测：连续止损但强趋势确认时 BUY 降仓，不阻断。
3. 公共规则单测：近期累计亏损超过阈值时 BUY 降仓。
4. live provider 单测：只读取 `strategy_signals/sim_trades`。
5. replay 隔离单测：回放 temp DB 的亏损反馈不读取主 DB live 成交。
6. capital slot 单测：反馈 gate 的 `size_multiplier` 会缩小 slot units。
7. 配置单测：积极、中性、保守默认 policy 不同且可解析。
8. UI 单测或静态校验：策略配置页展示 policy 字段说明。

## 对齐检查

第一轮实现后检查：

1. 是否所有参数均来自策略 profile。
2. 是否 live/replay 都调用同一公共规则函数。
3. 是否没有任何历史回放数据写入 live 表。
4. 是否没有恢复 `source_prior/main_force` 加分。

第二轮测试后检查：

1. 规则触发说明是否写入 signal 的 `strategy_profile.stock_execution_feedback_gate`。
2. 仓位缩放是否最终进入 capital slot sizing。
3. UI 参数文案是否说明“来源不加分，个股反馈影响仓位和门控”。
4. 旧的止盈后再入场控制是否仍然有效，并可与新 gate 取更严格的仓位倍率。
