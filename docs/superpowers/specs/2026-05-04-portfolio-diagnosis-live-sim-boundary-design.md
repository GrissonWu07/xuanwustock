# 持仓诊断与实时模拟边界设计

Date: 2026-05-04
Status: Superseded

Current source of truth: `docs/superpowers/specs/2026-05-05-stock-universe-refresh-architecture-design.md`

## 背景

当前 `/portfolio` 和 `/live-sim` 都展示持仓、股票链接和信号信息，用户容易感觉两个页面重复。实际业务职责不同：

1. `/portfolio` 定位为组合诊断和个股分析页面，回答“当前持仓是否合理、风险在哪里、应该怎么处理”。
2. `/live-sim` 定位为模拟交易执行台，回答“策略如何运行、信号如何产生、资金槽如何占用、成交和账户结果如何变化”。

本设计保留两个页面，但重新定义信息边界、数据口径和展示层级，避免重复和口径混乱。

## 目标

1. `/portfolio` 明确升级为“持仓诊断”页面，覆盖持仓列表、组合诊断、组合最终建议、个股详情、分析师观点、个股最终建议。
2. `/live-sim` 保持“实时模拟账户执行台”定位，只展示执行状态、策略配置、候选池、资金槽、信号、成交和费用统计。
3. 明确数据口径：`/portfolio` 展示层合并 portfolio 持仓、live-sim 持仓、候选池和关注池为统一股票诊断列表；底层账户、成本、收益和执行状态仍按来源隔离。
4. 修复技术指标映射，保证价格均线和成交量均线不混淆。
5. 让组合级最终建议可追溯，必须展示建议动作、目标仓位、主要原因和优先处理对象。
6. 让个股最终建议优先展示，并和分析师观点形成一个完整分析 block。

## 非目标

1. 不合并 `/portfolio` 和 `/live-sim`。
2. 不重写实时模拟、历史回放、信号生成或资金槽算法。
3. 不在 `/portfolio` 展示完整信号执行链路、lot 释放细节或资金槽调度过程。
4. 不把 `/live-sim` 扩展成深度个股分析页面。
5. 不引入新的远程数据源。

## 页面职责边界

### `/portfolio`

定位：组合诊断、持仓分析、个股复核。

必须展示：

1. 组合诊断摘要。
2. 组合最终建议。
3. 持仓列表。
4. 当前持仓、已清仓分析、候选观察的状态区分。
5. 个股详情入口。
6. 个股最终建议。
7. 分析师观点。
8. 关键技术指标和 K 线。
9. 相关待执行信号的简要引用。

不得展示：

1. 资金槽全量 board。
2. lot 释放/锁定执行细节。
3. 实时模拟成交流水。
4. 实时模拟费用统计。
5. 策略调度启动/停止控制。

### `/live-sim`

定位：实时模拟账户执行台。

必须展示：

1. 运行状态和市场时区。
2. 策略配置。
3. 量化候选池。
4. 信号记录。
5. 资金池和资金槽。
6. 成交记录。
7. 费用与执行统计。
8. 模拟账户持仓快照。

不得展示：

1. 多分析师完整观点。
2. 个股最终建议正文。
3. 深度 K 线和指标诊断。
4. 组合诊断全文。

实时模拟中的股票代码和名称继续链接到 `/portfolio/position/:symbol`。

## 数据口径

### 统一股票诊断列表

`/portfolio` 只展示一个统一股票诊断列表。该列表按 `symbol` 去重，合并以下来源：

1. portfolio 持仓分析库。
2. live-sim 实时模拟账户。
3. 量化候选池。
4. 关注池 / watchlist。
5. 已缓存的个股分析结果。

合并规则：

1. 同一股票只显示一行。
2. 行内必须展示来源标签：`portfolio`、`live_sim`、`candidate_pool`、`watchlist`、`analysis_cache`。
3. 如果同一股票同时存在 portfolio 和 live-sim 持仓，不能互相覆盖成本、数量和收益。
4. portfolio 持仓字段和 live-sim 持仓字段必须分开保存到 row payload。
5. 默认排序优先级：任一来源有持仓 > 高风险 > 浮亏金额大 > 接近止损 > 候选观察。

### portfolio 持仓口径

字段含义：

1. `portfolio_holding_quantity`：portfolio 持仓分析库中的持仓数量。
2. `portfolio_cost_price`：portfolio 持仓分析库中的成本价。
3. `portfolio_latest_price`：watchlist / 技术快照更新后的最新价格。
4. `portfolio_market_value = portfolio_holding_quantity * portfolio_latest_price`。
5. `portfolio_unrealized_pnl = (portfolio_latest_price - portfolio_cost_price) * portfolio_holding_quantity`。
6. `portfolio_unrealized_pnl_pct = (portfolio_latest_price - portfolio_cost_price) / portfolio_cost_price * 100`，成本缺失或为 0 时显示 `--`。
7. `portfolio_weight_pct = portfolio_market_value / sum(portfolio_market_value of current holdings) * 100`。

### 实时模拟口径

`/live-sim` 继续使用 primary/live `xuanwu_stock.db` 中的账户、持仓、信号、成交、资金槽。

`/portfolio` 合并展示 live-sim 股票时，必须满足：

1. 文案标注“来自实时模拟账户”。
2. live-sim 数量、成本、市值、浮盈亏进入 live-sim 专属字段。
3. live-sim 指标不参与 portfolio 组合收益、portfolio 仓位占比和 portfolio 组合最终建议。
4. 统一列表可以提供“诊断口径”切换：`全部股票`、`portfolio 持仓`、`实时模拟持仓`、`候选观察`。

### 持仓状态分类

统一股票诊断列表必须区分：

1. `portfolio_holding`：portfolio 持仓数量大于 0。
2. `live_sim_holding`：live-sim 当前持仓数量大于 0。
3. `dual_holding`：portfolio 和 live-sim 都有持仓。
4. `closed_analysis`：当前无持仓，但存在历史分析、近期交易或缓存分析。
5. `watch_candidate`：无持仓，但在候选池或关注池中。

默认列表显示全部有诊断价值的股票，但通过筛选快速收敛。页面必须提供状态筛选：

1. 全部。
2. portfolio 持仓。
3. 实时模拟持仓。
4. 双口径持仓。
5. 已清仓分析。
6. 候选观察。

## 技术指标映射

技术指标必须使用稳定 key 匹配，不能用模糊包含造成错配。

### 指标 key 规范

后端返回 `detail.indicators` 时，每个指标必须包含：

```json
{
  "key": "ma5",
  "label": "MA5",
  "value": "8.64",
  "group": "trend",
  "hint": "5-day moving average."
}
```

必需 key：

1. `price`
2. `volume`
3. `volume_ma5`
4. `ma5`
5. `ma10`
6. `ma20`
7. `ma60`
8. `rsi`
9. `macd`
10. `macd_signal`
11. `macd_hist`
12. `boll_upper`
13. `boll_middle`
14. `boll_lower`
15. `kdj_k`
16. `kdj_d`
17. `volume_ratio`

### 前端匹配规则

前端必须优先按 `key` 精确匹配。

兼容旧数据时才允许 label 匹配，且规则必须避免以下错误：

1. `MA5` 只能匹配 label 精确等于 `MA5`、`5日均线`、`5-day moving average`。
2. `volume_ma5` 只能匹配 `Volume MA5`、`5日均量`。
3. `MA5` 不能匹配包含 `Volume MA5`、`成交量 MA5`、`5日均量` 的 label。
4. 所有均线和成交量均线必须进入不同 group。

验收案例：

1. `MA5` 不得显示为 `755622.00` 这类成交量值。
2. 价格位置轴只能使用价格类指标：`boll_lower`、`ma60`、`ma20`、`price`、`ma5`、`boll_upper`。
3. 量能区域才展示 `volume`、`volume_ma5`、`volume_ratio`。

## `/portfolio` 列表设计

### 顶部结构

页面标题从“持仓列表”调整为“持仓诊断”。

顶部展示三块：

1. 组合最终建议。
2. 组合诊断指标。
3. 口径筛选、状态筛选和操作。

### 组合最终建议

组合最终建议必须包含：

1. `portfolio_state`：`aggressive`、`balanced`、`defensive`、`risk_reduction` 之一。
2. `action`：`increase`、`hold`、`reduce`、`pause_new_buys` 之一。
3. `target_exposure_pct`：建议目标仓位。
4. `summary`：一句话解释。
5. `top_reasons`：最多 3 条。
6. `priority_actions`：优先处理股票列表。

示例：

```json
{
  "portfolio_state": "risk_reduction",
  "action": "pause_new_buys",
  "target_exposure_pct": 35,
  "summary": "组合处于风险收缩状态：4 只持仓中 3 只亏损，2 只接近止损，建议暂停新开仓。",
  "top_reasons": [
    "亏损持仓占比 75%",
    "2 只股票距离止损线小于 3%",
    "组合浮亏 -1.64%"
  ],
  "priority_actions": [
    {
      "symbol": "300390",
      "name": "天华新能",
      "action": "reduce_or_sell",
      "reason": "浮亏较大且弱于 MA20"
    }
  ]
}
```

### 组合诊断指标

必须展示：

1. 当前持仓数。
2. 持仓总市值。
3. 持仓浮盈亏金额。
4. 持仓浮盈亏率。
5. 现金口径：portfolio 口径没有现金账户时显示 `--`；如果产品选择引用 live-sim 现金，必须显示 `来自实时模拟账户` 标签，且该值不参与 portfolio 组合诊断计算。
6. 盈利持仓数。
7. 亏损持仓数。
8. 接近止损持仓数。
9. 超买高风险持仓数。
10. 最大单股仓位占比。
11. 前三大持仓集中度。
12. 行业集中度。

### 持仓列表列

默认列：

1. 代码。
2. 名称。
3. 来源。
4. 状态。
5. 行业/板块。
6. portfolio 持仓。
7. live-sim 持仓。
8. 现价。
9. portfolio 市值。
10. live-sim 市值。
11. portfolio 浮盈亏。
12. live-sim 浮盈亏。
13. 距止损。
14. 距止盈。
15. 最新信号。
16. 建议动作。
17. 风险标签。
18. 分析更新时间。

排序默认规则：

1. 任一来源有持仓优先。
2. 高风险持仓优先。
3. 浮亏金额大的优先。
4. 接近止损的优先。

### 风险标签

每个持仓可展示多个标签：

1. `near_stop_loss`：当前价距离止损小于等于 3%。
2. `large_unrealized_loss`：浮亏率小于等于 -8%。
3. `overbought_profit_protect`：RSI 大于等于 80 且持仓盈利。
4. `below_ma20`：当前价低于 MA20。
5. `weak_trend`：MA5 < MA10 < MA20 或价格低于 MA20 且 MA20 下行。
6. `stale_analysis`：分析更新时间超过 2 个交易日。
7. `missing_data`：缺少关键价格、成本或技术指标。

### 建议动作

单股建议动作必须使用以下枚举：

1. `buy`
2. `add`
3. `hold`
4. `reduce`
5. `sell`
6. `avoid`
7. `watch`

显示文案：

1. 有持仓且建议 `sell`：卖出。
2. 有持仓且建议 `reduce`：减仓。
3. 有持仓且建议 `hold`：持有。
4. 无持仓且建议 `buy`：建仓。
5. 无持仓且建议 `watch`：观察。
6. 无持仓且建议 `avoid`：回避。

## `/portfolio/position/:symbol` 个股详情设计

### 页面结构

顺序固定：

1. 顶部决策摘要。
2. 持仓与风控信息。
3. 关键技术指标。
4. K 线走势。
5. 分析结论 block。
6. 相关待执行信号。

### 顶部决策摘要

必须首屏展示：

1. 最新建议动作。
2. 当前持仓数量。
3. 成本价。
4. 现价。
5. 浮盈亏金额。
6. 浮盈亏率。
7. 止盈/止损线。
8. 距止盈/止损。
9. 最新信号。
10. 分析更新时间。

### 分析结论 block

当前“最终建议”和“分析师观点”必须合并到同一个大 block 内。

结构：

1. 最终建议。
2. 触发原因 Top 3。
3. 一致性。
4. 分歧点。
5. 会议共识。
6. 分析师观点 tabs。
7. 完整分析原文 disclosure。

最终建议必须默认展开；完整分析原文也默认展开，但用户可以折叠。

### 最终建议内容

最终建议必须展示：

1. 投资评级。
2. 操作建议。
3. 目标价。
4. 进场区间。
5. 止盈位置。
6. 止损位置。
7. 仓位建议。
8. 持有周期。
9. 置信度。
10. 风险提示摘要。

不得再额外拆出独立“操作建议”和“风险提示”卡片；这些内容归并到最终建议中。

### 分析师观点

分析师观点必须满足：

1. 与最终建议属于同一分析 block。
2. tab 切换只展示当前分析师正文。
3. tab 区域显示观点数量。
4. 如果没有分析师观点，展示空状态，不影响最终建议展示。

### 相关待执行信号

个股详情只展示该股相关信号摘要：

1. 时间。
2. 动作。
3. 状态。
4. 策略。
5. 简要依据。
6. 信号详情链接。

不得在此处展开完整信号执行链路。

## `/live-sim` 去重设计

### 保留内容

1. 定时任务配置。
2. 量化候选池。
3. 信号记录。
4. 资金池总览。
5. 成交记录。
6. 费用与执行统计。
7. 模拟账户持仓快照。

### 持仓快照规则

实时模拟持仓快照只展示执行账户状态：

1. 股票。
2. 数量。
3. 成本。
4. 现价。
5. 市值。
6. 浮盈亏。
7. T+1 可卖/锁定数量。
8. 占用 slot。

深度分析入口通过股票链接跳转到 `/portfolio/position/:symbol`。

### 文案调整

必须标注：

1. `实时模拟账户持仓`。
2. `资金槽为模拟执行口径`。
3. `股票诊断请进入持仓诊断详情页`。

## API 数据契约

### Portfolio snapshot

`GET portfolio` 返回：

```json
{
  "portfolioScope": "portfolio_diagnosis",
  "updatedAt": "2026-05-04T15:42:29Z",
  "diagnosis": {
    "portfolioState": "risk_reduction",
    "action": "pause_new_buys",
    "targetExposurePct": 35,
    "summary": "...",
    "topReasons": [],
    "priorityActions": []
  },
  "metrics": [],
  "holdingGroups": {
    "portfolioHolding": [],
    "liveSimHolding": [],
    "dualHolding": [],
    "closedAnalysis": [],
    "watchCandidate": []
  },
  "holdings": {
    "columns": [],
    "rows": [],
    "pagination": {}
  }
}
```

### Position detail snapshot

当前页面模型的 portfolio detail snapshot 返回 `detail` 时，必须包含：

```json
{
  "symbol": "601918",
  "stockName": "新集能源",
  "positionStatus": "watch_candidate",
  "sources": ["candidate_pool", "analysis_cache"],
  "positionSummary": {
    "portfolio": {
      "quantity": 0,
      "costPrice": 0,
      "marketValue": 0,
      "unrealizedPnl": 0,
      "unrealizedPnlPct": null
    },
    "liveSim": {
      "quantity": 0,
      "costPrice": 0,
      "marketValue": 0,
      "unrealizedPnl": 0,
      "unrealizedPnlPct": null
    },
    "latestPrice": 8.95,
    "takeProfit": null,
    "stopLoss": null,
    "distanceToTakeProfitPct": null,
    "distanceToStopLossPct": null
  },
  "indicators": [],
  "kline": [],
  "stockAnalysis": {
    "finalDecision": {},
    "consensus": {},
    "analystViews": [],
    "rawSummary": ""
  },
  "relatedSignals": []
}
```

### Indicator item

每个指标必须包含：

```json
{
  "key": "ma5",
  "label": "MA5",
  "value": "8.64",
  "group": "trend",
  "hint": "5-day moving average."
}
```

## 实施顺序

1. 修复技术指标 key 和前端匹配，先保证数据正确。
2. 构建 `/portfolio` 统一股票诊断列表，按 symbol 合并 portfolio、live-sim、候选池、关注池和分析缓存。
3. 在统一列表中分离 portfolio 口径和 live-sim 口径字段。
4. 新增持仓状态分类和诊断指标。
5. 增强持仓列表字段。
6. 重做组合最终建议和组合诊断卡片。
7. 重排个股详情页面，把最终建议、共识、分歧点、分析师观点和完整原文合并为一个分析 block。
8. 调整 `/live-sim` 文案和持仓快照，避免深度诊断重复。
9. 补充单元测试和前端构建验证。

## 测试要求

### 后端

1. 指标映射测试：`MA5` 不得匹配 `Volume MA5`。
2. 统一列表合并测试：同一 symbol 在 portfolio、live-sim、候选池同时存在时只返回一行，并保留所有来源标签。
3. portfolio 口径测试：`/portfolio` 默认 portfolio metrics 不使用 live-sim account summary。
4. live-sim 口径测试：live-sim 数量、成本、市值、浮盈亏只进入 live-sim 字段，不覆盖 portfolio 字段。
5. 持仓状态分类测试：portfolio 持仓、live-sim 持仓、双口径持仓、已清仓分析、候选观察分别进入正确状态。
6. 组合诊断测试：亏损数、接近止损数、集中度、风险标签计算正确。
7. 相关信号测试：个股详情只返回该股简要 signal summary。

### 前端

1. `/portfolio` 默认展示持仓诊断，不展示资金槽 board。
2. `/portfolio` 表格展示统一股票诊断列表和新增诊断列。
3. `/portfolio/position/:symbol` 首屏能看到最终建议和持仓风控摘要。
4. 分析师观点和最终建议在同一个分析 block 内。
5. `/live-sim` 持仓只作为模拟账户快照，股票链接跳转到个股详情。
6. 前端构建通过。

## 验收标准

1. 用户打开 `/portfolio`，能先看到组合最终建议和组合风险，而不是只看到基础表格。
2. 用户只看到一个股票诊断列表，并能区分 portfolio 持仓、实时模拟持仓、双口径持仓、已清仓分析、候选观察。
3. 用户打开个股详情，首屏能回答“现在要买、持有、减仓、卖出还是观察”。
4. 用户能看到最终建议来自哪些原因和哪些分析师观点。
5. 用户打开 `/live-sim`，能明确这是模拟账户执行台，而不是另一个持仓诊断页。
6. `MA5`、`MA10`、`MA20`、`Volume MA5` 不再错配。
7. `/portfolio` 和 `/live-sim` 的现金、收益、持仓口径不会混用或误标。

## 自检记录

### 第一轮：产品边界

1. `/portfolio` 和 `/live-sim` 的职责已分别定义。
2. 重复展示的持仓信息已改为 `/portfolio` 统一股票诊断列表，行内保留不同来源口径。
3. `/portfolio` 只保留相关信号摘要，不展示完整执行链路。
4. `/live-sim` 不再承载多分析师深度诊断。

### 第二轮：数据正确性

1. 技术指标错配被列为第一实施步骤和验收标准。
2. portfolio 和 live-sim 的账户口径已明确隔离，但展示层按 symbol 合并。
3. 持仓数量为 0 的股票不会被默认当成 portfolio 当前持仓。
4. 组合最终建议要求携带原因和优先处理对象，避免只有一句动作。
