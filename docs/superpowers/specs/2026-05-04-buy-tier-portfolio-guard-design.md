# BUY 分层与组合级防守设计

## 背景

任务 #3 里个股执行反馈已经生效，但仍出现整体亏损。根因不是技术 BUY 全错，而是技术 BUY 只是入场候选，却被当成接近足额开仓信号执行。很多信号属于技术分刚转正、短线反弹、MA20 或中期结构不稳的场景；A 股 T+1 又会放大买入后快速转弱的亏损。

本设计新增统一的 `portfolio_execution_guard`，同时解决 BUY 分层和组合级防守。规则必须同时适用于历史回放和实时模拟，但两者数据隔离：历史回放读 replay 运行库，实时模拟读 primary/live `xuanwu_stock.db`。

## 目标

1. 把 BUY 明确分为 `weak_buy`、`normal_buy`、`strong_buy`，不同层级对应不同仓位倍率或阻断。
2. 在组合连续亏损、连续止损、回撤扩大时，按配置比例对所有新开仓自动降级、缩仓或暂停。
3. 限制同一 checkpoint / 同一交易日的 BUY 数量，避免一批边缘信号同时开仓。
4. 冷启动股票没有盈利历史且趋势确认不足时，只允许轻仓试错。
5. 明确考虑 A 股 T+1 风险，对 30m 级别短线反弹信号提高确认要求。
6. 规则和参数进入策略配置，积极、稳定、保守可以有不同默认值，后续 UI 可编辑。

## 非目标

1. 不重写技术评分和双轨融合模型。
2. 不缓存加工结果。
3. 不把历史回放写入实时模拟状态表。
4. 不一刀切禁止高 RSI 或止损后再买；允许强趋势例外，但必须降仓。

## 执行位置

`SignalCenterService.create_signal()` 中新增门控顺序：

1. `_apply_position_constraints`
2. `_apply_position_add_gate`
3. `_apply_reentry_constraints`
4. `_apply_stock_execution_feedback`
5. `_apply_portfolio_execution_guard`
6. `_apply_transaction_cost_constraints`

`_apply_portfolio_execution_guard` 只记录 gate 和必要的 HOLD 转换，不直接预乘 `position_size_pct`。仓位倍率统一由 `capital_slots.gate_size_multiplier()` 读取，避免重复缩放。

## 统一判定模型

`portfolio_execution_guard` 只处理原始决策为 BUY 的信号。非 BUY 直接 `passed`，不生成 BUY 分层。

每个 BUY 先计算一组派生指标，再计算强度分，再按风险门控降级或阻断。计算顺序固定如下：

1. 读取当前信号的 fusion/tech/context 分数、BUY 阈值、confidence、volume_ratio、MA5/MA10/MA20/MA20 slope、RSI、最近 checkpoint 快照、个股执行摘要、组合执行摘要。
2. 计算趋势确认指标：`ma_stack`、`ma20_rising`、`above_ma20_checkpoints`、`retest_confirmed`。
3. 计算风险识别指标：`is_late_rebound`、`t1_new_buy_risk`、`stock_failure_state`、`portfolio_guard_state`。
4. 计算 `buy_strength_score`，映射初始 `buy_tier`。
5. 依次应用 T+1 风险、冷启动、个股执行反馈、止盈后再入场、组合防守、BUY 数量上限。
6. 输出最终 `status`、`buy_tier`、`size_multiplier`、`reasons`，资金槽只读取最终 gate 倍率。

### 派生指标定义

`buy_edge`：

1. 优先使用 `fusion_score - fusion_buy_threshold`。
2. 如果缺少 fusion 分数，使用 `tech_score - tech_buy_threshold`。
3. 如果两者都缺失，`buy_edge = 0`，并在 reasons 写入 `missing_buy_edge`。

`edge_strength = clamp(buy_edge / full_edge, 0, 1)`。`full_edge` 来自配置，表示“足够强 BUY”相对 BUY 阈值的最小超额。

`ma20_rising = ma20_slope > min_ma20_slope`。

`ma_stack = price > ma20 且 ma5 > ma10 > ma20`。

`above_ma20_checkpoints`：

1. 从当前 checkpoint 向前连续统计。
2. 每个 checkpoint 必须 `close > ma20`。
3. 遇到缺失 close/ma20 或 `close <= ma20` 即停止。

`retest_confirmed`：

1. 最近 `retest_lookback_checkpoints` 内曾经从 MA20 下方突破到 MA20 上方。
2. 突破后至少一个 checkpoint 的 `low >= ma20 * (1 - retest_tolerance_pct / 100)`。
3. 当前 `price > ma20` 且 `price > ma10`。

`volume_confirmed`：

1. `volume_ratio >= strong_volume_ratio`：强量能确认。
2. `normal_volume_ratio <= volume_ratio < strong_volume_ratio`：普通量能确认。
3. 缺失 volume_ratio 时记为未确认，不阻断，但不能帮助升级 strong_buy。

`t1_new_buy_risk`：

1. 市场为 A 股，当前信号周期为 30m 或更短。
2. 当前 checkpoint 是该股在本运行域内最近 `t1_confirm_checkpoints` 个 checkpoint 的首次 BUY。
3. `above_ma20_checkpoints < confirm_checkpoints` 或 `ma20_rising = false`。
4. 同时满足以上条件时为 true，并写入 reason `t1_new_buy_unconfirmed`。

`stock_failure_state`：

1. 直接读取 `stock_execution_feedback_gate.status`。
2. `blocked` 计入硬阻断。
3. `downgraded` 计入风险惩罚，并参与最终倍率最小值。

`portfolio_guard_state`：

1. 由组合亏损熔断、市场环境门控、BUY 上限共同组成。
2. 任一子规则 `blocked` 时，最终 `portfolio_execution_guard.status = blocked`。
3. 只有降级或降仓时，最终 `portfolio_execution_guard.status = downgraded`。

### BUY 强度分

`buy_strength_score` 是 0 到 1 的执行质量分，不替代原始 BUY，只决定 BUY 强弱：

```text
raw_buy_strength_score =
  weight_edge * edge_strength
+ weight_trend_structure * trend_structure_score
+ weight_confirmation * confirmation_score
+ weight_volume * volume_score
+ weight_track_alignment * track_alignment_score
- risk_penalty

buy_strength_score = clamp(raw_buy_strength_score, 0, 1)
```

权重必须来自当前策略模型的 `portfolio_execution_guard_policy`，不能写死在代码里。归一化要求：

1. `weight_edge + weight_trend_structure + weight_confirmation + weight_volume + weight_track_alignment = 1.0`。
2. 读取配置后如果总和不是 1.0，normalize 到 1.0，并在 policy normalization 中保留归一化后的值。
3. aggressive、stable/neutral、conservative 必须使用不同权重，体现不同策略表现目标。
4. UI 保存策略配置时不得用通用默认值覆盖 profile 专属权重。

各组件定义：

1. `trend_structure_score = 1.0`：`ma_stack` 且 `ma20_rising`。
2. `trend_structure_score = 0.75`：`ma20_rising` 且 `above_ma20_checkpoints >= confirm_checkpoints`。
3. `trend_structure_score = 0.65`：`retest_confirmed`。
4. `trend_structure_score = 0.25`：只有 `price > ma20`。
5. `trend_structure_score = 0.0`：价格不在 MA20 上方，或 MA20 数据缺失。
6. `confirmation_score = clamp(above_ma20_checkpoints / confirm_checkpoints, 0, 1)`；`retest_confirmed` 时至少为 `0.75`。
7. `volume_score = 1.0`：强量能确认；`0.6`：普通量能确认；`0.3`：量能缺失或未确认。
8. `track_alignment_score = clamp(1 - abs(tech_score - context_score) / 2, 0, 1)`；缺失时取 `0.5`。
9. `risk_penalty` 由反弹尾段、T+1、个股失败、组合失败叠加，最大不超过 `max_risk_penalty`。

`risk_penalty` 取值：

1. `is_late_rebound = true`：加 `late_rebound_penalty`。
2. `t1_new_buy_risk = true`：加 `t1_risk_penalty`。
3. `stock_execution_feedback_gate.status = downgraded`：加 `stock_failure_penalty`。
4. `portfolio_guard_state.cooldown_active = true`：加 `portfolio_cooldown_penalty`。
5. `portfolio_guard_state.drawdown_guard_triggered = true`：加 `portfolio_drawdown_penalty`。
6. 最终 `risk_penalty = min(sum(penalties), max_risk_penalty)`。

BUY 分层先由 `buy_strength_score` 映射，再由硬性门槛校正：

1. `buy_strength_score < weak_buy_max_score`：`weak_buy`。
2. `weak_buy_max_score <= buy_strength_score < strong_buy_min_score`：候选 `normal_buy`。
3. `buy_strength_score >= strong_buy_min_score`：候选 `strong_buy`。
4. 如果缺少 `normal_buy` 必需趋势确认，候选 `normal_buy` 降为 `weak_buy`。
5. 如果缺少 `strong_buy` 全部硬性条件，候选 `strong_buy` 降为 `normal_buy` 或 `weak_buy`。

## BUY 分层

### weak_buy

定义：原始 BUY 成立，但执行质量不足，只允许轻仓试错或观察。

触发条件包括任意一个，命中后必须写入 reasons：

1. `buy_strength_score < weak_buy_max_score`。
2. `buy_edge < weak_edge_abs`。
3. MA20 不上行，且不满足 `retest_confirmed`。
4. `above_ma20_checkpoints < confirm_checkpoints`。
5. `ma_stack = false`，且没有其他趋势确认。
6. `is_late_rebound = true`。
7. A 股 30m 信号当前 checkpoint 刚转 BUY，且缺少多 checkpoint 确认。

处理：

1. 默认允许，基础倍率为 `weak_multiplier`。
2. 如果冷启动，倍率再受 `cold_start_weak_multiplier` 限制。
3. 如果组合亏损预算暂停或熔断，转 HOLD，`size_multiplier = 0.0`。

### normal_buy

定义：原始 BUY 成立，趋势已有确认，但强度或环境不足以正常满仓位执行。

必须满足：

1. `buy_strength_score >= weak_buy_max_score`。
2. 至少满足以下趋势确认之一：
   - `ma20_rising = true` 且 `above_ma20_checkpoints >= confirm_checkpoints`。
   - `ma_stack = true`。
   - `retest_confirmed = true`。
3. 不处于组合亏损预算暂停。

降级条件：

1. `is_late_rebound = true` 且不满足 strong_buy 硬性条件时，降为 `weak_buy`。
2. A 股 30m 刚转 BUY 且缺少多 checkpoint 确认时，降为 `weak_buy`。
3. 组合冷却时降为 `weak_buy`，或按 `cooldown_size_multiplier` 降仓。

处理：

1. 基础倍率为 `normal_multiplier`。
2. 冷启动时倍率再受 `cold_start_normal_multiplier` 限制。

### strong_buy

定义：原始 BUY 成立，趋势结构、确认持续性、量能或融合共振、失败环境都通过。

要求：

1. `buy_strength_score >= strong_buy_min_score`。
2. `ma_stack = true`。
3. `price > ma20`。
4. `ma20_rising = true`。
5. 满足 `volume_confirmed`，或 `buy_edge >= strong_edge_abs`。
6. `is_late_rebound = false`，除非 `ma_stack`、`ma20_rising`、`buy_edge >= strong_edge_abs` 同时成立。
7. 没有组合亏损预算暂停或熔断。
8. 个股没有连续止损阻断；如果个股反馈允许强趋势例外，仍必须使用个股反馈给出的降仓倍率。

处理：

1. 基础倍率为 `strong_multiplier`。
2. 组合冷却期内最多 `cooldown_size_multiplier`。
3. 止盈后短期再入场和个股执行反馈的更严格倍率仍然生效。

## BUY 判定需求

### 反弹尾段识别

系统必须识别疑似反弹尾段，而不是只看 MACD/RSI 转强。满足任一条件时，`portfolio_execution_guard` 必须设置 `is_late_rebound = true`，并写入 `late_rebound_reasons`：

1. `ma20_slope <= 0`，但价格刚重新站上 MA20。
2. `above_ma20_checkpoints < confirm_checkpoints`。
3. MA5 > MA10 > MA20 不成立。
4. 价格从短期低点反弹幅度较大，但 MA20 仍未上行。

疑似反弹尾段的 BUY 最多只能归类为 `weak_buy`，除非同时满足 strong_buy 的全部趋势结构要求。

### 技术指标滞后过滤

MACD、RSI、量比、main_force 只能作为 BUY 候选证据，不能单独把信号提升为 `normal_buy` 或 `strong_buy`。提升层级必须额外满足以下趋势确认之一：

1. MA20 上行且价格连续站稳 MA20 达到 `confirm_checkpoints`。
2. MA5 > MA10 > MA20。
3. 价格突破后回踩 MA20 不破，再重新转强。

如果只有技术指标转强，但趋势确认不足，信号必须保持 `weak_buy`。

### BUY 边缘阈值处理

fusion/tech 只比 BUY 阈值高一点时，不再等同普通 BUY。系统必须计算 BUY edge。`buy_edge` 是绝对分差，不是百分比：

1. `buy_edge < weak_edge_abs`：强制 `weak_buy`。
2. `weak_edge_abs <= buy_edge < normal_edge_abs`：只有满足趋势确认后才能 `normal_buy`，否则仍为 `weak_buy`。
3. `buy_edge >= normal_edge_abs`：可以进入 `normal_buy` 判定，但仍不能绕过失败环境和 T+1 风险门控。

### T+1 风险处理

A 股 30m BUY 如果是当天或当前 checkpoint 刚转强，且缺少多 checkpoint 确认，不能归类为 `normal_buy` 或 `strong_buy`。此类信号必须：

1. 默认归类为 `weak_buy`。
2. 冷启动时继续套用 `cold_start_weak_multiplier`。
3. 在交易明细或信号详情中写入 T+1 风险原因。

### 入场确认强度

普通 BUY 和强 BUY 必须代表“趋势确认后入场”，不是“指标满足可买”。实现时必须保证：

1. `normal_buy` 至少满足 MA20 上行、连续站稳 MA20、MA 多头排列、回踩确认之一。
2. `strong_buy` 必须同时满足 MA5 > MA10 > MA20、price > MA20、MA20 上行，以及量能或融合分确认。
3. 缺少趋势确认时，BUY 只能作为轻仓试错或观察信号。

### 市场与个股失败环境

个股失败环境和组合失败环境必须作为 BUY 分层的输入，而不是事后解释：

1. 个股近期连续止损或累计亏损时，继续由 `stock_execution_feedback_gate` 降仓或阻断该股。
2. 组合最近 N checkpoint 或 N 天内止损过多时，所有 BUY 自动降级。
3. 达到组合熔断阈值时，非 `strong_buy` 转 HOLD。
4. 个股亏损反馈、止盈后再入场、组合防守的最终仓位倍率取所有 gate 的最严格值，并保留 `0.0`。

## Gate 合并规则

所有 gate 必须按固定优先级合并，避免某个规则覆盖另一个规则的语义：

1. `stock_execution_feedback_gate.status = blocked`：该股 BUY 直接转 HOLD，除非已有持仓加仓逻辑明确允许。
2. `portfolio_execution_guard.portfolio_guard.loss_budget_triggered = true`：所有新开仓 BUY 转 HOLD，持仓加仓继续走 `position_add_gate`。
3. `portfolio_execution_guard.portfolio_guard.buy_limit_triggered = true`：超出上限的新开仓 BUY 转 HOLD。
4. T+1、反弹尾段、冷启动、组合回撤只做降级或降仓，不单独覆盖止损/亏损硬阻断。
5. 多个降仓 gate 同时存在时，最终 `size_multiplier = min(reentry_gate, stock_execution_feedback_gate, portfolio_execution_guard)`。
6. `size_multiplier = 0.0` 必须保留，不能用 `or 1.0` 兜底。
7. `buy_tier` 表示最终执行层级；`initial_buy_tier` 如果需要调试可额外记录，但 UI 默认展示最终 `buy_tier`。

## 组合级防守

### 组合亏损熔断

统计最近 `lookback_checkpoints` 和 `lookback_days` 的 SELL 交易。窗口同时按 checkpoint 和自然日过滤，任一窗口触发即生效。SELL 分类规则：

1. `stop_loss_trade`：SELL 的 `decision_type`、`reason`、`execution_detail` 命中 hard stop / stop loss / 止损，或单笔已实现盈亏率 <= `stop_loss_pnl_pct_threshold`。
2. `loss_trade`：SELL 已实现盈亏 < 0。
3. `recent_realized_pnl`：窗口内所有 SELL 的已实现盈亏求和。
4. `recent_stop_loss_count`：窗口内 `stop_loss_trade` 数量。
5. `consecutive_stop_loss_count`：按成交时间倒序连续 `stop_loss_trade` 数量，遇到非止损 SELL 即停止。
6. `stop_loss_density = recent_stop_loss_count / max(recent_sell_count, 1)`。
7. `window_drawdown_pct = (recent_equity_peak - current_equity) / recent_equity_peak * 100`，`recent_equity_peak` 来自窗口内账户快照最高总权益。

动作规则：

1. `recent_stop_loss_count >= stop_loss_circuit_threshold` 且 `stop_loss_density >= stop_loss_density_threshold`：进入组合冷却。
2. `recent_realized_pnl_pct <= loss_budget_pct` 或 `recent_realized_pnl <= derived_loss_budget_amount`：暂停新开仓，非持仓加仓 BUY 转 HOLD。
3. `consecutive_stop_loss_count >= consecutive_stop_loss_threshold`：暂停新开仓，非持仓加仓 BUY 转 HOLD。
4. `window_drawdown_pct >= drawdown_guard_pct`：所有 BUY 降一级；weak_buy 转 HOLD。

冷却期持续 `cooldown_checkpoints` 或 `cooldown_days`。冷却期内只允许 strong_buy，且倍率不超过配置的 `cooldown_size_multiplier`。

组合防守使用比例化配置，而不是只用固定金额：

1. `loss_budget_pct`：最近窗口已实现亏损 / 初始资金或当前权益，低于该比例则暂停新开仓。
2. `drawdown_guard_pct`：当前权益相对近期峰值回撤超过该比例，所有 BUY 降一级。
3. `stop_loss_density_threshold`：最近窗口 SELL 中止损占比超过该比例，所有 BUY 降一级。
4. `cooldown_size_multiplier`：冷却期内允许的 strong_buy 最大倍率。

`derived_loss_budget_amount` 不是独立配置项，必须由 `loss_budget_pct` 换算：

```text
derived_loss_budget_amount = -abs(reference_equity * loss_budget_pct / 100)
```

`reference_equity` 优先使用当前运行初始资金；如果缺失，使用窗口内第一条账户快照的总权益；如果仍缺失，则不启用金额兜底，只使用 `loss_budget_pct`。

### 单 checkpoint / 单日 BUY 上限

自动执行前对 pending BUY 排序。排序规则必须稳定，避免同一批信号每次运行顺序不同：

1. 先按 `buy_tier` 排序：`strong_buy > normal_buy > weak_buy`。
2. 再按 `buy_strength_score` 降序。
3. 再按现有 `calculate_buy_priority()` 降序。
4. 再按 `confidence` 降序。
5. 最后按 `stock_code` 升序作为稳定 tie-breaker。

限制规则：

1. 每个 checkpoint 最多执行 `max_new_buys_per_checkpoint` 个新开仓 BUY。
2. 每个交易日最多执行 `max_new_buys_per_day` 个新开仓 BUY。
3. 已持仓股票加仓不计入“新开仓 BUY”数量，但仍受仓位、资金槽和加仓门控约束。
4. 超出上限的 BUY 转 HOLD，`status = blocked`，`size_multiplier = 0.0`，reason 写明 “组合防守：超过本 checkpoint/本日 BUY 上限”。

### 冷启动轻仓

冷启动只针对“该股当前无持仓的新开仓 BUY”。满足以下全部条件时，视为 cold start：

1. 当前账户该股无可用持仓和冻结持仓。
2. 该运行域内该股没有已实现盈利 SELL，或盈利 SELL 样本数 < `cold_start_profit_sample_threshold`。
3. 该股没有通过 strong_buy 的硬性条件。

动作规则：

1. weak_buy 最多 `cold_start_weak_multiplier`。
2. normal_buy 最多 `cold_start_normal_multiplier`。
3. strong_buy 不受 cold start 倍率限制，但仍受组合冷却、个股反馈、止盈后再入场限制。

冷启动轻仓不是永久限制。首次轻仓建仓后，后续信号转强时必须允许逐步恢复：

1. 如果持仓已有浮盈，且后续信号达到 `normal_buy`，允许通过 `position_add_gate` 加仓，但仍受组合冷却和 BUY 上限约束。
2. 如果后续信号达到 `strong_buy`，且组合不在熔断或亏损预算暂停状态，允许恢复正常仓位倍率。
3. 如果后续仍是 `weak_buy`，只允许维持或轻仓试错，不主动加仓。
4. 如果冷启动后马上止损，后续再买交给 `stock_execution_feedback_gate` 降仓或阻断。

冷启动解决“第一笔不要太重”，不阻止“信号确认后逐步加仓”。

### 市场环境门控

使用当前候选池、持仓快照、近期账户快照估算市场环境。所有指标只使用当前运行域的数据，历史回放不能读取 live 状态。

派生指标：

1. `candidate_below_ma20_ratio = 候选池中 price < MA20 的股票数 / 有效候选数`。
2. `position_below_ma20_ratio = 持仓中 price < MA20 的股票数 / 有效持仓数`。
3. `market_stop_loss_density = recent_stop_loss_count / max(recent_sell_count, 1)`。
4. `portfolio_drawdown_pct = (recent_equity_peak - current_equity) / recent_equity_peak * 100`。

动作规则：

1. `candidate_below_ma20_ratio >= candidate_below_ma20_guard_ratio`：所有新开仓 BUY 降一级。
2. `position_below_ma20_ratio >= position_below_ma20_guard_ratio`：所有新开仓 BUY 降一级。
3. `portfolio_drawdown_pct >= drawdown_guard_pct`：weak_buy 转 HOLD，normal_buy 降为 weak_buy，strong_buy 降仓到 `cooldown_size_multiplier`。
4. `market_stop_loss_density >= stop_loss_density_threshold` 且 `recent_stop_loss_count >= stop_loss_circuit_threshold`：进入组合冷却。

市场/个股失败环境的逻辑风险与边界：

1. 这类门控会降低交易频率，可能错过 V 型反转，所以不能只因单次止损就熔断。
2. 组合级防守必须要求“数量 + 比例”同时有意义，例如 stop_loss_count 达标且 stop_loss_density 达标。
3. 个股失败环境只影响该股；组合失败环境影响所有新开仓。
4. strong_buy 可以作为例外，但在冷却期也必须降仓，避免刚亏完马上重仓追。
5. 所有触发原因必须写入 gate，UI 能看到是市场风险、个股失败，还是组合亏损预算导致。

## 配置

新增 `portfolio_execution_guard_policy`，放在策略配置：

`base.context.portfolio_execution_guard_policy`

默认值按策略区分。每个策略模型的数字和权重必须服务于不同表现目标：

1. aggressive：允许更早捕捉趋势，权重更偏 `edge_strength` 和 `volume_score`，确认 checkpoint 更少，BUY 上限更宽，但仍要受组合亏损和 T+1 风险约束。
2. stable / neutral：作为基线，权重在 edge、趋势结构、确认持续性之间均衡，减少边缘信号足额开仓。
3. conservative：偏确认后行动，权重更偏 `trend_structure_score` 和 `confirmation_score`，风险惩罚更高，BUY 阈值、更强量能、更严格市场环境门控都更保守。

实现要求：

1. profile id 包含 `aggressive` 时读取 aggressive 默认值。
2. profile id 包含 `stable` 或 `neutral` 时读取 stable / neutral 默认值。
3. profile id 包含 `conservative` 时读取 conservative 默认值。
4. candidate/position profile 如果没有显式覆盖，继承对应 base profile 的 `portfolio_execution_guard_policy`，不能回落到通用默认。
5. 策略配置 UI 读取和保存时必须保留 profile 专属权重、阈值、惩罚值。

### aggressive

1. `enabled = true`
2. `weak_multiplier = 0.25`
3. `normal_multiplier = 0.5`
4. `strong_multiplier = 1.0`
5. `weight_edge = 0.40`
6. `weight_trend_structure = 0.25`
7. `weight_confirmation = 0.10`
8. `weight_volume = 0.15`
9. `weight_track_alignment = 0.10`
10. `weak_buy_max_score = 0.45`
11. `strong_buy_min_score = 0.78`
12. `full_edge = 0.10`
13. `weak_edge_abs = 0.03`
14. `normal_edge_abs = 0.08`
15. `strong_edge_abs = 0.14`
16. `confirm_checkpoints = 2`
17. `min_ma20_slope = 0.0`
18. `normal_volume_ratio = 1.1`
19. `strong_volume_ratio = 1.5`
20. `retest_lookback_checkpoints = 5`
21. `retest_tolerance_pct = 1.5`
22. `max_risk_penalty = 0.45`
23. `late_rebound_penalty = 0.18`
24. `t1_risk_penalty = 0.12`
25. `stock_failure_penalty = 0.18`
26. `portfolio_cooldown_penalty = 0.20`
27. `portfolio_drawdown_penalty = 0.15`
28. `t1_confirm_checkpoints = 2`
29. `lookback_checkpoints = 8`
30. `lookback_days = 5`
31. `cooldown_checkpoints = 2`
32. `max_new_buys_per_checkpoint = 2`
33. `max_new_buys_per_day = 4`
34. `stop_loss_pnl_pct_threshold = -5.0`
35. `stop_loss_circuit_threshold = 3`
36. `consecutive_stop_loss_threshold = 2`
37. `cooldown_days = 1`
38. `loss_budget_pct = -3.0`
39. `drawdown_guard_pct = 4.0`
40. `stop_loss_density_threshold = 0.50`
41. `cooldown_size_multiplier = 0.5`
42. `cold_start_profit_sample_threshold = 1`
43. `cold_start_weak_multiplier = 0.25`
44. `cold_start_normal_multiplier = 0.5`
45. `candidate_below_ma20_guard_ratio = 0.65`
46. `position_below_ma20_guard_ratio = 0.65`

### stable / neutral

1. `weak_multiplier = 0.25`
2. `normal_multiplier = 0.5`
3. `strong_multiplier = 1.0`
4. `weight_edge = 0.32`
5. `weight_trend_structure = 0.30`
6. `weight_confirmation = 0.18`
7. `weight_volume = 0.10`
8. `weight_track_alignment = 0.10`
9. `weak_buy_max_score = 0.50`
10. `strong_buy_min_score = 0.82`
11. `full_edge = 0.20`
12. `weak_edge_abs = 0.04`
13. `normal_edge_abs = 0.10`
14. `strong_edge_abs = 0.16`
15. `confirm_checkpoints = 3`
16. `normal_volume_ratio = 1.2`
17. `strong_volume_ratio = 1.6`
18. `max_risk_penalty = 0.50`
19. `late_rebound_penalty = 0.20`
20. `t1_risk_penalty = 0.15`
21. `stock_failure_penalty = 0.20`
22. `portfolio_cooldown_penalty = 0.25`
23. `portfolio_drawdown_penalty = 0.18`
24. `t1_confirm_checkpoints = 3`
25. `lookback_checkpoints = 12`
26. `lookback_days = 8`
27. `cooldown_checkpoints = 4`
28. `max_new_buys_per_checkpoint = 1`
29. `max_new_buys_per_day = 3`
30. `stop_loss_pnl_pct_threshold = -4.0`
31. `stop_loss_circuit_threshold = 2`
32. `consecutive_stop_loss_threshold = 2`
33. `cooldown_days = 2`
34. `loss_budget_pct = -2.0`
35. `drawdown_guard_pct = 3.0`
36. `stop_loss_density_threshold = 0.40`
37. `cooldown_size_multiplier = 0.35`
38. `cold_start_profit_sample_threshold = 1`
39. `cold_start_weak_multiplier = 0.25`
40. `cold_start_normal_multiplier = 0.5`
41. `candidate_below_ma20_guard_ratio = 0.60`
42. `position_below_ma20_guard_ratio = 0.60`

### conservative

1. `weak_multiplier = 0.20`
2. `normal_multiplier = 0.4`
3. `strong_multiplier = 0.8`
4. `weight_edge = 0.25`
5. `weight_trend_structure = 0.35`
6. `weight_confirmation = 0.22`
7. `weight_volume = 0.08`
8. `weight_track_alignment = 0.10`
9. `weak_buy_max_score = 0.55`
10. `strong_buy_min_score = 0.86`
11. `full_edge = 0.22`
12. `weak_edge_abs = 0.05`
13. `normal_edge_abs = 0.12`
14. `strong_edge_abs = 0.18`
15. `confirm_checkpoints = 3`
16. `normal_volume_ratio = 1.3`
17. `strong_volume_ratio = 1.8`
18. `max_risk_penalty = 0.55`
19. `late_rebound_penalty = 0.22`
20. `t1_risk_penalty = 0.18`
21. `stock_failure_penalty = 0.22`
22. `portfolio_cooldown_penalty = 0.30`
23. `portfolio_drawdown_penalty = 0.20`
24. `t1_confirm_checkpoints = 3`
25. `lookback_checkpoints = 16`
26. `lookback_days = 12`
27. `cooldown_checkpoints = 6`
28. `max_new_buys_per_checkpoint = 1`
29. `max_new_buys_per_day = 2`
30. `stop_loss_pnl_pct_threshold = -3.0`
31. `stop_loss_circuit_threshold = 2`
32. `consecutive_stop_loss_threshold = 2`
33. `cooldown_days = 3`
34. `loss_budget_pct = -1.5`
35. `drawdown_guard_pct = 2.0`
36. `stop_loss_density_threshold = 0.35`
37. `cooldown_size_multiplier = 0.25`
38. `cold_start_profit_sample_threshold = 1`
39. `cold_start_weak_multiplier = 0.20`
40. `cold_start_normal_multiplier = 0.4`
41. `candidate_below_ma20_guard_ratio = 0.55`
42. `position_below_ma20_guard_ratio = 0.55`

## Data Contract

新增 gate 存入 `strategy_profile.portfolio_execution_guard`：

```json
{
  "intent": "portfolio_execution_guard",
  "status": "passed|downgraded|blocked",
  "initial_buy_tier": "normal_buy",
  "buy_tier": "weak_buy|normal_buy|strong_buy",
  "buy_tier_label": "弱买|普通买|强买",
  "buy_strength_score": 0.42,
  "size_multiplier": 0.25,
  "is_late_rebound": true,
  "late_rebound_reasons": ["MA20 still falling", "only one checkpoint above MA20"],
  "score_components": {
    "buy_edge": 0.02,
    "edge_strength": 0.111111,
    "trend_structure_score": 0.25,
    "confirmation_score": 0.333333,
    "volume_score": 0.6,
    "track_alignment_score": 0.72,
    "risk_penalty": 0.2,
    "risk_penalties": {
      "late_rebound": 0.18,
      "t1": 0.0,
      "stock_failure": 0.0,
      "portfolio_cooldown": 0.0,
      "portfolio_drawdown": 0.02
    }
  },
  "trend_confirmation": {
    "ma_stack": false,
    "ma20_rising": true,
    "above_ma20_checkpoints": 2,
    "retest_confirmed": false,
    "volume_confirmed": "normal"
  },
  "t1_risk": {
    "active": false,
    "confirm_checkpoints": 2
  },
  "portfolio_guard": {
    "cooldown_active": false,
    "recent_stop_loss_count": 1,
    "consecutive_stop_loss_count": 1,
    "recent_realized_pnl": -1200.0,
    "recent_realized_pnl_pct": -0.8,
    "stop_loss_density": 0.25,
    "portfolio_drawdown_pct": 1.2,
    "loss_budget_triggered": false,
    "drawdown_guard_triggered": false,
    "buy_limit_triggered": false,
    "reasons": ["组合回撤达到防守阈值"]
  },
  "cold_start": {
    "active": true,
    "profit_sample_count": 0,
    "size_multiplier": 0.25
  },
  "ui_badges": ["弱买", "疑似反弹尾段", "组合冷却"],
  "reasons": []
}
```

`capital_slots.gate_size_multiplier()` 需要同时读取：

1. `reentry_gate`
2. `stock_execution_feedback_gate`
3. `portfolio_execution_guard`

最终倍率取最小值，保留 `0.0`。

## 实时模拟与历史回放

实时模拟：

1. 从 live `sim_trades`、`strategy_signals`、`sim_account_snapshots` 统计组合状态。
2. 不读 replay DB。

历史回放：

1. 从回放临时库统计组合状态。
2. 持久化结果写入 replay DB。
3. checkpoint 时间必须来自 market snapshot / checkpoint，不使用任务运行时。

## UI

信号列表与信号详情必须展示 BUY 分层结果：

1. 信号列表新增或复用字段展示 `buy_tier_label`，例如弱买、普通买、强买。
2. 信号详情展示 `is_late_rebound`，并列出 `late_rebound_reasons`。
3. 如果被组合防守降级或阻断，展示 `portfolio_guard.reasons`。
4. 交易明细中的资金槽解释继续展示最终倍率。

设置页展示到策略配置中，与个股执行反馈配置同级：

1. BUY 分层
2. 组合熔断
3. BUY 上限
4. 冷启动轻仓
5. 市场环境门控
6. 亏损预算

## 测试

1. 强度分：给定 fusion edge、MA、checkpoint、volume、risk，`buy_strength_score` 按公式得到确定值。
2. `weak_buy`：技术刚过线且 MA20 不上行，`buy_tier = weak_buy`，倍率为 `weak_multiplier`。
3. `normal_buy`：MA20 上行且连续站稳，`buy_tier = normal_buy`，倍率为 `normal_multiplier`。
4. `strong_buy`：MA 多头排列、MA20 上行、量能确认、无冷却，`buy_tier = strong_buy`，倍率为 `strong_multiplier`。
5. 反弹尾段：`is_late_rebound = true` 时写入 `late_rebound_reasons`，且不能升级到 normal/strong，除非满足 strong_buy 全部硬性条件。
6. T+1 风险：A 股 30m 单 checkpoint 刚转强只能 weak_buy，并写入 `t1_new_buy_unconfirmed`。
7. 组合冷却：连续止损 + 止损密度达标后普通 BUY blocked，strong BUY downgraded 到 `cooldown_size_multiplier`。
8. checkpoint BUY 上限：按 `buy_tier`、`buy_strength_score`、`calculate_buy_priority()`、`confidence`、`stock_code` 排序，只保留最高优先级 BUY，其他转 HOLD。
9. 冷启动：无盈利历史且非 strong BUY 降仓。
10. 冷启动后信号转为 strong_buy 时，允许通过加仓门控恢复正常加仓。
11. 组合防守比例：`loss_budget_pct`、`drawdown_guard_pct`、`stop_loss_density_threshold` 能触发降级或暂停。
12. 多 gate 合并：`reentry_gate`、`stock_execution_feedback_gate`、`portfolio_execution_guard` 同时存在时取最小倍率，并保留 `0.0`。
13. 信号 UI payload 包含 `buy_strength_score`、`buy_tier_label`、`is_late_rebound`、`late_rebound_reasons`、`score_components`。
14. 历史回放与实时模拟使用相同规则但数据隔离。

## 验收

用任务 #3 相同配置重跑：

1. 3/25 不应一次执行 4 笔接近正常仓位 BUY。
2. `300857`、`300684` 这类止损后再买继续保留个股反馈降仓。
3. 初始第一波边缘 BUY 数量下降。
4. 交易数下降，最大回撤下降。
5. 每个被降仓或阻断的 BUY 都能在信号详情中说明原因。
