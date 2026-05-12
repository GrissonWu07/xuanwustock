# Kernel 共振质量与执行仓位重设计

## 1. 背景

当前 BUY 信号的仓位链路存在语义冲突：

1. kernel 双轨决策命中 `resonance_standard` 后，直接给出 `position_ratio = 0.5`。
2. 后续 `portfolio_execution_guard` 又把同一信号判定为 `weak_buy`，并给出 `size_multiplier = 0.25`。
3. 执行层实际按 `50% * 0.25 = 12.5%` 总权益计算买入预算。

对 40 万账户来说，12.5% 约为 5 万。这已经不是“弱买试错”，而是实质仓位。问题不只在执行层倍率，也在 kernel 层：`resonance_standard` 把“刚踩线达标”和“强共振确认”都映射成同一个 50% 原始仓位，导致信号质量信息在源头丢失。

本 spec 统一修复两层问题：

1. kernel 的共振仓位从固定档位改为质量衰减后的连续仓位。
2. 执行层从“倍率缩放”改为“账户风险预算 + buy tier 上限 + 生命周期上限”的最终裁剪。

## 2. 目标

1. `position_ratio` 不再只由固定共振档位决定，必须反映信号质量。
2. `resonance_standard` 仍可表示“技术轨和环境轨都达标”，但不能无条件等于 50% 仓位。
3. `weak_buy` 的实际成交金额必须按账户总权益和风险预算控制，不能只依赖资金槽 slot。
4. live-sim、历史回放、实时量化演练必须使用同一套仓位语义，但数据表继续隔离。
5. UI 和信号详情必须同时展示“kernel 原始建议”和“最终执行仓位”，避免用户看到弱买却买入大额仓位。

## 3. 非目标

1. 不重写技术指标、context score、候选池生命周期的整体算法。
2. 不删除现有 `portfolio_execution_guard`，而是调整它的输出语义和执行层使用方式。
3. 不用候选来源给交易仓位加分。候选来源最多影响入池和初始候选排序，不能让 BUY 信号变强。
4. 不把执行层风险预算写死为单一值，必须按 aggressive / stable / conservative 策略模型配置。

## 4. 当前问题定义

### 4.1 kernel 共振档位过粗

当前配置中：

```python
resonance_standard = DualTrackPositionRule(
    tech_score_min=0.6,
    context_score_min=0.3,
    position_ratio=0.5,
)
```

这会让以下两类信号得到相同原始仓位：

1. 技术分刚过线、环境分刚过线、RSI 过热、MA20 刚拐头。
2. 技术分和环境分明显超阈值、MA 多头、量能确认、趋势延续。

这两类信号不应共享同一个 50% 原始目标仓位。

### 4.2 执行层倍率以错误基数缩放

`weak_buy` 当前使用 `size_multiplier` 缩放 kernel 原始仓位。若 kernel 原始仓位是 50%，弱买倍率 0.25 后仍是 12.5%。这对试错仓位过高。

执行层应该先确定“这笔最多允许亏账户多少钱”，再反推最大买入金额，而不是直接从 50% 原始仓位折扣。

## 5. 新仓位语义

系统必须区分三种仓位：

1. `kernel_base_position_pct`
   - 由共振档位给出的理论上限。
   - 例如 aggressive 的 standard 档位上限固定为 45%，不得回到 50%。

2. `kernel_quality_position_pct`
   - kernel 根据技术质量、趋势确认、热区风险衰减后的原始建议仓位。
   - 这是信号层的“质量调整后建议”。

3. `effective_position_pct`
   - 执行层根据 buy tier、生命周期、账户风险预算、组合防守、资金槽容量裁剪后的最终可成交仓位。
   - 实际下单只能使用这个值。

禁止继续把 `position_size_pct` 作为唯一仓位口径。API 可继续保留该字段，但必须明确它代表 `effective_position_pct`，并把 kernel 原始建议放入 explain 字段。

## 6. Kernel 共振质量模型

### 6.1 共振档位仍保留

kernel 仍先判断共振档位：

1. `resonance_full`
2. `resonance_heavy`
3. `resonance_moderate`
4. `resonance_standard`
5. `divergence_light`
6. `divergence_none`

但档位不再直接决定最终 `position_ratio`，而是提供 `base_position_ratio` 上限。

### 6.2 质量分

新增 `signal_quality_score`，范围 `0.0 ~ 1.0`。

计算公式：

```text
signal_quality_score = clamp(
  tech_edge_score * weight_tech_edge
  + context_edge_score * weight_context_edge
  + trend_structure_score * weight_trend_structure
  + confirmation_score * weight_confirmation
  + volume_score * weight_volume
  - heat_penalty
  - weak_structure_penalty
  - volatility_penalty,
  0,
  1
)
```

默认权重必须按策略模型区分：

| 权重 | aggressive | stable | conservative |
|---|---:|---:|---:|
| `weight_tech_edge` | 0.22 | 0.20 | 0.18 |
| `weight_context_edge` | 0.18 | 0.20 | 0.22 |
| `weight_trend_structure` | 0.28 | 0.25 | 0.25 |
| `weight_confirmation` | 0.16 | 0.18 | 0.20 |
| `weight_volume` | 0.16 | 0.17 | 0.15 |
| 合计 | 1.00 | 1.00 | 1.00 |

权重必须通过 `kernel_resonance_quality_policy` 配置，不得在代码中写死。aggressive 更重视技术 edge 和成交确认；stable/conservative 更重视 context 和连续确认。

各项定义：

1. `tech_edge_score`
   - `clamp((tech_score - resonance_standard.tech_score_min) / (strong_tech_score - resonance_standard.tech_score_min), 0, 1)`
   - 用于区分“刚过技术阈值”和“明显强技术”。

2. `context_edge_score`
   - `clamp((context_score - resonance_standard.context_score_min) / (strong_context_score - resonance_standard.context_score_min), 0, 1)`
   - 用于区分环境勉强达标和环境明显支持。

3. `trend_structure_score`
   - `1.0`：`price > MA20` 且 `MA5 > MA10 > MA20` 且 `MA20_slope > 0`
   - `0.6`：`price > MA20` 且 `MA20_slope >= 0`
   - `0.3`：仅 `price > MA20`
   - `0.0`：价格低于 MA20 或缺失关键均线。

4. `confirmation_score`
   - 最近 N 个 checkpoint 连续满足趋势确认时上升。
   - `confirmation_score = clamp(confirmed_checkpoints / required_confirm_checkpoints, 0, 1)`

5. `volume_score`
   - `volume_ratio >= strong_volume_ratio` 时为 `1.0`
   - `volume_ratio >= normal_volume_ratio` 时为 `0.6`
   - 否则为 `0.0`

6. `heat_penalty`
   - `RSI < 75`：`0`
   - `75 <= RSI < 85`：线性从 `0.05` 增至 `0.20`
   - `85 <= RSI < 88`：`0.25`
   - `RSI >= 88`：`0.35`
   - 若同时满足强趋势确认，可按 profile 配置将 penalty 乘以 `hot_rsi_trend_relief_multiplier`，但不得低于原 penalty 的 40%。

7. `weak_structure_penalty`
   - `MA20_slope < 0`：`0.20`
   - `MA5 < MA10`：`0.10`
   - `MACD 刚翻红但趋势确认不足`：`0.10`

8. `volatility_penalty`
   - 价格距离 MA20 过远、短期涨幅过大、或疑似反弹尾段时触发。
   - kernel 必须独立计算，不调用执行层函数，不读取组合状态。

默认公式：

```text
volatility_penalty = 0.0

if MA20 > 0 and abs(price - MA20) / MA20 > ma20_deviation_penalty_threshold:
  volatility_penalty += ma20_deviation_penalty

if recent_5d_return > recent_return_penalty_threshold:
  volatility_penalty += recent_return_penalty

volatility_penalty = clamp(volatility_penalty, 0.0, max_volatility_penalty)
```

默认值：

| 参数 | aggressive | stable | conservative |
|---|---:|---:|---:|
| `ma20_deviation_penalty_threshold` | 0.10 | 0.08 | 0.06 |
| `ma20_deviation_penalty` | 0.10 | 0.12 | 0.15 |
| `recent_return_penalty_threshold` | 0.07 | 0.05 | 0.04 |
| `recent_return_penalty` | 0.06 | 0.08 | 0.10 |
| `max_volatility_penalty` | 0.22 | 0.25 | 0.28 |

`recent_5d_return` 使用当前 checkpoint 可见的历史行情计算，不得使用未来数据。若 5 日数据不足，则该项 penalty 为 0，并在 explainability 中记录 `recent_return_missing=true`。

### 6.3 position ratio 连续映射

kernel 输出：

```text
kernel_quality_position_ratio =
  base_position_ratio_min
  + (base_position_ratio_max - base_position_ratio_min) * signal_quality_score
```

每个档位提供 min/max，而不是单点值。

默认建议：

| 档位 | aggressive min/max | stable min/max | conservative min/max |
|---|---:|---:|---:|
| resonance_full | 0.45 / 0.60 | 0.36 / 0.50 | 0.28 / 0.40 |
| resonance_heavy | 0.38 / 0.55 | 0.30 / 0.44 | 0.22 / 0.35 |
| resonance_moderate | 0.28 / 0.50 | 0.22 / 0.38 | 0.16 / 0.30 |
| resonance_standard | 0.12 / 0.45 | 0.08 / 0.32 | 0.05 / 0.24 |
| divergence_light | 0.03 / 0.18 | 0.02 / 0.12 | 0.00 / 0.08 |
| divergence_none | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |

因此，`resonance_standard` 不再固定等于 0.5。踩线达标可能只给 0.12，质量较好的 aggressive standard 才接近 0.45。

`resonance_full` 的 max 不得超过上表上限。即使是 aggressive，kernel 也不得输出 90% 这类接近全仓的建议；账户规模和实际仓位必须继续由执行层 cap 控制。

### 6.4 Kernel 输出契约

`Decision.strategy_profile.explainability` 必须包含：

```json
{
  "resonance": {
    "rule_hit": "resonance_standard",
    "base_position_ratio_min": 0.12,
    "base_position_ratio_max": 0.45,
    "signal_quality_score": 0.38,
    "quality_adjusted_position_ratio": 0.2826,
    "quality_components": {
      "tech_edge_score": 0.12,
      "context_edge_score": 0.20,
      "trend_structure_score": 0.60,
      "confirmation_score": 0.33,
      "volume_score": 0.60
    },
    "quality_penalties": {
      "heat_penalty": 0.18,
      "weak_structure_penalty": 0.10,
      "volatility_penalty": 0.00
    }
  }
}
```

`Decision.position_ratio` 应设置为 `quality_adjusted_position_ratio`，而不是固定档位仓位。

若最终 BUY 不是由 resonance rule 直接产生，而是由双轨加权、AI overlay 或其他非共振链路升级产生，执行层也不得回退到裸 `position_size_pct=50%`。这类信号必须在 `SignalCenterService` 中用已有的 `portfolio_execution_guard.buy_strength_score` 对原始仓位做质量衰减，并写入：

```json
{
  "kernel_positioning": {
    "rule_hit": "non_resonance_guard_quality",
    "quality_position_pct": 11.84,
    "signal_quality_score": 0.236748,
    "quality_components": {
      "buy_strength_score": 0.236748,
      "raw_position_pct": 50.0
    }
  }
}
```

该回退只适用于带完整策略上下文的量化信号；手工或测试用的简化 BUY payload 若没有 `selected_strategy_profile` 或 `explainability`，保留原有兼容路径。

## 7. 执行仓位模型

### 7.1 最终仓位公式

执行层必须使用以下裁剪模型：

```text
effective_position_pct = min(
  kernel_quality_position_pct,
  buy_tier_cap_pct,
  lifecycle_cap_pct,
  risk_budget_position_pct,
  account_equity_tier_cap_pct,
  portfolio_guard_cap_pct,
  available_cash_pct,
  slot_capacity_pct
)
```

其中：

```text
risk_budget_position_pct = (single_trade_risk_budget_pct / expected_stop_loss_pct) * 100
```

其中 `single_trade_risk_budget_pct` 和 `expected_stop_loss_pct` 都按百分数数值传入，例如 `0.25` 表示 `0.25%`，`5.0` 表示 `5%`。

例如总权益 40 万，`single_trade_risk_budget_pct = 0.25`，预期止损 `expected_stop_loss_pct = 5.0`，则：

```text
risk_budget_position_pct = (0.25 / 5.0) * 100 = 5%
买入金额上限 = 400000 * 5% = 20000
```

执行层还必须计算绝对现金预算：

```text
final_budget = min(
  total_equity * effective_position_pct / 100,
  account_equity_tier_max_cash,
  available_cash,
  slot_available_cash
)
```

实际下单数量只能从 `final_budget` 反推，不能再从 `signal["position_size_pct"]` 重新推导现金预算。

### 7.2 buy tier 上限

默认建议：

| buy tier | aggressive | stable | conservative |
|---|---:|---:|---:|
| weak_buy cap | 7.0% | 3.5% | 2.0% |
| normal_buy cap | 9.0% | 7.0% | 5.0% |
| strong_buy cap | 15.0% | 12.0% | 9.0% |

`weak_buy` 无论 kernel 原始仓位是多少，都不能超过 `weak_buy_cap_pct`。

### 7.3 生命周期上限

默认建议：

| 状态 | aggressive | stable | conservative |
|---|---:|---:|---:|
| trial weak_buy | 3.0% | 2.0% | 1.0% |
| trial normal_buy | 6.0% | 4.5% | 3.0% |
| trial strong_buy | 10.0% | 8.0% | 6.0% |
| active weak_buy | 7.0% | 3.5% | 2.0% |
| active normal_buy | 9.0% | 7.0% | 5.0% |
| active strong_buy | 15.0% | 12.0% | 9.0% |
| exit_only | 0.0% | 0.0% | 0.0% |

`trial` 是观察态，不能因为 kernel 达到 standard resonance 就获得 active 级别仓位。

### 7.4 单笔风险预算

默认建议：

| buy tier | aggressive | stable | conservative |
|---|---:|---:|---:|
| weak_buy risk | 0.30% | 0.20% | 0.10% |
| normal_buy risk | 0.45% | 0.35% | 0.25% |
| strong_buy risk | 0.65% | 0.50% | 0.40% |

`expected_stop_loss_pct` 默认读取信号 `stop_loss_pct`。如果缺失，则：

1. A 股默认使用 `5%`
2. 港股默认使用 `6%`
3. 美股默认使用 `7%`

后续支持不同市场时必须按市场配置。

### 7.5 checkpoint 和组合暴露限制

新增组合级限制：

| 限制 | aggressive | stable | conservative |
|---|---:|---:|---:|
| 单 checkpoint 新开 trial 总风险 | 0.80% | 0.50% | 0.30% |
| 单日新开 trial 总风险 | 1.50% | 1.00% | 0.60% |
| trial 总持仓市值上限 | 20% | 12% | 8% |
| weak_buy 总持仓市值上限 | 12% | 8% | 5% |

超出后，后续 BUY 必须转 HOLD，并在信号解释中写明 `portfolio_trial_risk_budget_exhausted` 或 `weak_buy_exposure_cap_hit`。

这些限制不是单信号规则，必须在批量自动执行阶段统一处理：

1. `SignalCenterService` 仍负责为每条 BUY 生成单笔 `execution_sizing_plan`。
2. `PortfolioService.auto_execute_pending_signals()` 在执行前读取同一批 pending BUY，按优先级排序。
3. 排序顺序：`SELL` 优先；BUY 内部按 `strong_buy > normal_buy > weak_buy`、`buy_strength_score`、`confidence`、`signal_id` 排序。
4. 对 `trial` BUY 累计本 checkpoint 和当日实际执行风险；超出 `checkpoint_trial_risk_budget_pct` 或 `daily_trial_risk_budget_pct` 的信号转 HOLD/skip。
   - 实际执行风险字段为 `batch_risk_pct`。
   - `batch_risk_pct = effective_position_pct * expected_stop_loss_pct / 100`。
   - 若旧数据缺少 `batch_risk_pct`，可按 `effective_position_pct` 与 `expected_stop_loss_pct` 回算；再缺失时才 fallback 到名义 `risk_budget_pct`。
   - `risk_budget_pct` 仍表示该 buy tier 的单笔风控预算，不得直接作为 batch 聚合累计值。
5. 对当前持仓市值累计 `trial_total_exposure_cap_pct` 与 `weak_buy_total_exposure_cap_pct`；超出后对应 BUY 转 HOLD/skip。
6. 被截断的信号必须更新状态为 skipped/delayed，并记录 reason code：`portfolio_trial_risk_budget_exhausted`、`daily_trial_risk_budget_exhausted`、`trial_exposure_cap_hit`、`weak_buy_exposure_cap_hit`。
7. 聚合 gate 不能改变 SELL 执行，不能阻止已有持仓的风险退出。
8. 聚合 gate 只拦截新的 BUY 或加仓预算，不会因为 trial/weak 总暴露超限而强制卖出或减仓已有持仓；已有持仓只通过正常 SELL、止损、止盈和生命周期出场逻辑退出。

### 7.6 账户规模分层上限

同样的百分比在 10 万、40 万和 100 万账户上代表完全不同的绝对风险。执行层必须按账户总权益增加单票规模 cap，防止高资金账户被百分比仓位放大。

默认建议：

| 账户总权益 | aggressive cap / max cash | stable cap / max cash | conservative cap / max cash |
|---|---:|---:|---:|
| `< 100,000` | 18% / 18,000 | 14% / 14,000 | 10% / 10,000 |
| `100,000 ~ 299,999.99` | 15% / 35,000 | 12% / 28,000 | 8% / 20,000 |
| `300,000 ~ 799,999.99` | 12.5% / 70,000 | 10% / 55,000 | 7% / 40,000 |
| `>= 800,000` | 8% / 100,000 | 6% / 75,000 | 4% / 50,000 |

规则：

1. `account_equity_tier_cap_pct` 参与 `effective_position_pct = min(...)`。
2. `account_equity_tier_max_cash` 参与 `final_budget = min(...)`。
3. 该 cap 适用于所有 buy tier，包括 `strong_buy` 和 `resonance_full`。
4. 若用户显式配置更低的单票上限，取更低值。
5. 对 100 万账户，aggressive 单票即使 kernel 是 `resonance_full`，默认也不得超过 8% 或 10 万现金中的较低限制。
6. 实现时使用 `<` 判断边界：`equity < 100000`、`equity < 300000`、`equity < 800000`、否则进入最后一档。

## 8. 与现有模块关系

### 8.1 Kernel

修改范围：

1. `DualTrackPositionRule` 从单一 `position_ratio` 直接改为 `position_ratio_min / position_ratio_max`。不保留旧字段读取路径；部署时按当前项目未上线口径重建配置。
2. `DecisionEngine._position_rule()` 返回质量调整后的连续仓位。
3. `Decision.strategy_profile.explainability` 增加 resonance quality payload。

### 8.2 SignalCenterService

职责：

1. 保留 kernel 输出的 `kernel_quality_position_pct`。
2. 执行 `portfolio_execution_guard` 后，不再只写“资金槽执行时按 X 倍缩放”。
3. 必须生成 `execution_sizing_plan`，描述最终执行仓位如何从各个上限裁剪。
4. 必须计算并写入 `execution_sizing_plan.final_budget`，这是下单层唯一可用的现金预算输入。

### 8.3 PortfolioExecutionGuard

职责：

1. 继续判断 `weak_buy / normal_buy / strong_buy`。
2. 输出 `buy_tier_cap_pct` 和 `risk_budget_pct`。
3. 不再输出 `size_multiplier` 作为执行控制核心。执行层必须读取 cap 和 risk budget。
4. 如需展示倍率，只能作为从 `effective_position_pct / kernel_quality_position_pct` 派生出的解释值，不得参与下单计算。

### 8.4 PortfolioService / CapitalSlots

职责：

1. 下单预算必须来自 `execution_sizing_plan.final_budget`。
2. `PortfolioService.auto_execute_signal()` 读取 `final_budget` 后，直接以该现金预算计算可买股数。
3. 当前 `_estimate_buy_quantity()` 中 `position_size_pct -> target_position_budget` 的换算必须被移除或改为只服务 explain，不得参与最终下单预算。
4. 资金槽只负责容量分配和资金占用，不能放大执行层 cap。
5. 当 slot floor 一手买入成本超过风险预算时：
   - 如果是 `weak_buy`，直接跳过。
   - 如果是 `normal_buy`，只有满足 profile 的 `allow_one_lot_floor_for_normal_buy` 才允许买一手。
   - 如果是 `strong_buy`，允许一手 floor，但必须记录 `one_lot_floor_override=true`。

明确采用执行链路 C：

```text
SignalCenterService
  -> 生成 execution_sizing_plan.final_budget
PortfolioService.auto_execute_signal()
  -> 读取 final_budget
  -> 调用资金槽检查 slot_available_cash
  -> quantity = floor(min(final_budget, slot_available_cash, available_cash) / lot_cost)
CapitalSlots
  -> 只记录 slot 占用和 explain，不再从 position_pct 放大预算
```

禁止采用以下两种方案：

1. 在 `auto_execute_signal` 入口简单覆盖 `signal["position_size_pct"]` 后继续走旧链路。
2. 先按旧 slot budget 算出买入金额，再事后用 `effective_position_pct` cap 一次。

## 9. Data Contract

信号 payload 新增：

```json
{
  "kernel_positioning": {
    "base_position_pct": 45.0,
    "quality_position_pct": 28.26,
    "rule_hit": "resonance_standard",
    "signal_quality_score": 0.38,
    "quality_penalties": ["rsi_hot", "weak_ma20_slope"]
  },
  "execution_sizing_plan": {
    "buy_tier": "weak_buy",
    "kernel_quality_position_pct": 28.26,
    "buy_tier_cap_pct": 5.0,
    "lifecycle_cap_pct": 3.0,
    "risk_budget_pct": 0.30,
    "expected_stop_loss_pct": 5.0,
    "batch_risk_pct": 0.15,
    "risk_budget_position_pct": 6.0,
    "account_equity_tier_cap_pct": 12.5,
    "account_equity_tier_max_cash": 70000.0,
    "portfolio_guard_cap_pct": 3.0,
    "effective_position_pct": 3.0,
    "final_budget": 12000.0,
    "cap_reasons": ["trial_weak_buy_cap", "buy_tier_cap"]
  }
}
```

`position_size_pct` 对外表示 `effective_position_pct`。如果 UI 需要展示 kernel 建议，必须读取 `kernel_positioning.quality_position_pct`。

## 10. UI 要求

信号详情必须展示：

1. Kernel 建议仓位：例如 `28.3%`
2. 最终执行仓位：例如 `3.0%`
3. 裁剪原因：例如 `trial 弱买上限 / 单笔风险预算`
4. 预计风险金额：例如 `最大风险约 1,200`
5. 若最终不成交，展示“不成交原因”，例如 `弱买一手成本超过风险预算`

禁止只展示 `position_size_pct=50%` 或只展示 `weak_buy`，两者必须能解释到最终成交金额。

## 11. 配置

新增配置必须放在策略 profile 中，且 aggressive / stable / conservative 有不同默认值：

1. `kernel_resonance_quality_policy`
   - 各档位 `position_ratio_min / position_ratio_max`
   - 质量分权重
   - RSI 热区 penalty
   - 趋势结构 penalty
   - 量能阈值

2. `execution_position_cap_policy`
   - `buy_tier_cap_pct`
   - `lifecycle_cap_pct`
   - `single_trade_risk_budget_pct`
   - `checkpoint_trial_risk_budget_pct`
   - `daily_trial_risk_budget_pct`
   - `trial_total_exposure_cap_pct`
   - `weak_buy_total_exposure_cap_pct`
   - `account_equity_tier_caps`
   - `one_lot_floor_override_policy`

UI 策略配置页需要提供可编辑入口，但可以先折叠在“高级仓位控制”分组。

## 12. 回放与演练验收

必须至少对以下任务做回归：

1. 最近一次实时量化演练同参数重跑。
2. 同时间范围的历史回放重跑。
3. 对比旧版本与新版本：
   - BUY 数量
   - weak_buy BUY 数量
   - weak_buy 平均成交金额
   - realized_pnl
   - final_equity
   - max_drawdown
   - trial / cooling / retired 状态变更次数

核心验收标准：

1. `weak_buy` 平均成交金额必须明显低于旧版本。
2. 40 万账户下 `trial weak_buy` 单笔买入原则上不应超过 1.2 万到 2 万，除非强制一手 floor 且有明确解释。
3. `resonance_standard` 的 `position_ratio` 不应再固定为 50%。
4. 100 万账户下，即使是 `resonance_full + strong_buy`，默认单票买入金额也不得超过账户规模分层上限。
5. 信号详情中必须能解释：为什么 kernel 给出该仓位，为什么执行层又裁剪到最终仓位。
6. 若收益下降但回撤和已实现亏损显著改善，视为策略风险修复有效；后续再调高 aggressive 参数。

## 13. 测试要求

### 13.1 Kernel 单元测试

1. 刚踩线 standard resonance 不得输出 50% 仓位。
2. 强共振信号输出高于 standard 踩线信号。
3. RSI > 88 会显著降低 `signal_quality_score`。
4. MA 多头 + 量能确认会提高 `signal_quality_score`。
5. aggressive / stable / conservative 输出存在预期差异。

### 13.2 执行层单元测试

1. `weak_buy` 即使 kernel 给 50%，最终也被 `weak_buy_cap_pct` 限制。
2. `trial weak_buy` 被生命周期上限进一步限制。
3. 单笔风险预算能把 40 万账户、5% 止损的 weak buy 限制到合理预算。
4. 一手成本超过 risk budget 时，weak buy 跳过不成交。
5. normal/strong buy 的一手 floor override 行为符合配置。
6. 10 万、20 万、40 万、100 万账户分别命中对应 `account_equity_tier_cap_pct` 和 `account_equity_tier_max_cash`。

### 13.3 集成测试

1. live-sim、历史回放、实时量化演练都写入相同结构的 `kernel_positioning` 和 `execution_sizing_plan`。
2. replay DB 与 live DB 数据隔离不变。
3. UI payload 国际化字段不出现硬编码中文之外的未翻译 key。

## 14. 实施顺序

1. 增加 kernel resonance quality policy 和 tests。
2. 修改 `DecisionEngine` 输出质量调整后的 `position_ratio`。
3. 增加执行仓位 cap/risk budget policy 和 tests。
4. 修改 `SignalCenterService` 生成 `execution_sizing_plan`。
5. 修改 `PortfolioService / capital_slots` 使用最终执行预算。
6. 更新 UI 信号详情和列表展示。
7. 重跑实时量化演练和历史回放，对比报告。

## 15. 风险与注意事项

1. 仓位下调后，短期收益可能下降；这是预期风险修复，不应只用 final equity 判断。
2. aggressive 仍应允许强信号加大仓位，但 weak/trial 不能再获得大额实质仓位。
3. 若一手成本很高，弱买可能大量跳过，这是合理行为；高价股必须由 normal/strong 条件承接。
4. 不得让候选来源、AI 推荐、低价策略来源直接提高交易仓位。

## 16. 参数校准项

以下不是架构未决问题，而是需要通过演练和历史回放校准的参数：

1. aggressive 的 `trial weak_buy` 单笔风险预算默认采用 `0.30%` 是否过高。
2. aggressive 的 `resonance_standard` 上限固定为 `45%`，后续只能通过数据验证决定是否下调，不再回到 `50%`。
3. “背离观望”不在 kernel 层直接转 HOLD，先通过 `heat_penalty + weak_structure_penalty + volatility_penalty` 降低质量分；若演练仍出现解释为观望但实际成交过大的情况，再在执行层将该类信号转 HOLD。
4. 账户规模分层 cap 的现金上限需要用 10 万、20 万、40 万、100 万四档演练验证。
