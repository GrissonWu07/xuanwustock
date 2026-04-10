# Quant Sim Realtime UI Design

**Date:** 2026-04-10

**Goal**

Reshape the realtime `🧪 量化模拟` page into a direct-operating workspace where account, scheduling, timeframe, and strategy configuration are always visible, candidate actions happen in the candidate pool itself, and automatic simulated execution can be explicitly toggled between hands-off and manual-confirmation modes.

**Product Outcome**

- Realtime `🧪 量化模拟` no longer hides core configuration inside an expander.
- The page directly exposes:
  - initial cash / account controls
  - interval scheduling controls
  - start date
  - market
  - timeframe mode
  - strategy mode
  - trading-hours-only flag
  - automatic execution toggle
- Candidate management moves into the candidate-pool area instead of using a separate manual-add form block.
- The account controls support both:
  - `更新资金池`
  - `重置模拟账户`
- Each candidate row supports:
  - `立即分析`
  - `删除`
- The old per-candidate expander button `立即分析该标的` is removed.
- The realtime page uses a left-config / right-results layout, with the candidate pool as the main full-width table and a lower detail area that switches between execution and account views instead of rendering multiple long tables at once.
- Candidate analysis detail should open in a dialog rather than occupying a permanent inline section below the candidate table.
- The visual design remains modern and clean: restrained color, smaller row-level action buttons, and no placeholder section labels such as “主工作区” or “工作区”.
- When `自动执行模拟交易` is enabled, `立即分析` and scheduled scans immediately simulate BUY/SELL execution without waiting for manual confirmation.
- When `自动执行模拟交易` is disabled, BUY/SELL still land in the pending-action flow for user confirmation.

## Scope

This design covers:

- restructuring the realtime quant-simulation page layout
- exposing scheduler and strategy configuration directly on the page
- adding realtime strategy-mode selection
- persisting realtime strategy-mode selection in scheduler config
- moving manual candidate add/delete/analyze actions into the candidate-pool area
- clarifying the behavior difference between auto-executed simulation and manual-confirmation mode

This design does not cover:

- changing historical replay UI structure
- changing replay execution semantics
- placing real broker orders
- replacing the underlying simulation account model

## Current Problem

Today the realtime page in `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py` still reflects an earlier prototype shape:

- core scheduler/account controls are hidden in `⚙️ 定时分析设置与资金池`
- realtime strategy mode is not configurable even though the kernel supports `自动 / 激进 / 中性 / 稳健`
- manual stock add lives in a separate form block disconnected from the candidate pool
- `立即分析` exists in multiple places and the candidate-level action is buried inside an expander
- the automatic execution capability already exists in the backend, but the page still feels centered on manual confirmation

This makes the realtime workflow harder to understand than it needs to be.

## Recommended Approach

Use a single direct-operations page for realtime simulation:

- keep the existing tabs for candidates / signals / pending / positions / trades / equity
- move all control surfaces above the tabs and render them directly
- store realtime strategy mode in scheduler config so manual scan and scheduled scan share one runtime configuration
- treat candidate-pool rows as the place where per-stock actions live

This is the lowest-risk approach because it reuses the current services and account logic while making the product flow much clearer.

## Realtime Page Layout

### 1. Header and account summary

Keep the current page title and top account metrics:

- 初始资金池
- 可用现金
- 持仓市值
- 总权益
- 总盈亏

The caption should explicitly describe both execution modes:

- auto-execute mode: directly simulate execution
- manual mode: generate signals and wait for user confirmation

### 2. Scheduler and strategy configuration

The current expander-based block must be removed. Configuration is always visible.

Recommended visible fields:

- 启用定时模拟
- 开始日期
- 间隔(分钟)
- 仅交易时段运行
- 分析粒度
  - `30m`
  - `1d`
  - `1d+30m`
- 策略模式
  - `自动`
  - `激进`
  - `中性`
  - `稳健`
- 市场
  - `CN`
  - `HK`
  - `US`
- 自动执行模拟交易
- 初始资金池(元)

Visible actions:

- `💾 保存配置`
- `▶️ 保存并启动定时分析`
- `⏹️ 停止定时分析`
- `💰 更新资金池`
- `🔄 重置模拟账户`

### 3. Candidate pool as the main work surface

The candidate pool becomes the primary table on the page and should occupy the main right-side width.

Requirements:

- show search / filter / page-size affordances or a similarly compact table-control strip
- keep row actions visually light; `立即分析` and `删除` should be small action buttons rather than large primary CTAs
- keep `添加股票` near the candidate-pool heading
- avoid nested card expanders for per-row actions

The candidate pool should be the only obviously large table in the first screenful. This keeps the page stable even when the candidate list grows.

### 4. Lower detail area instead of multiple parallel long panels

Below the candidate pool, use one shared detail region that can switch between:

- `执行中心`
- `账户结果`

Do not render multiple long side-by-side tables in this region by default.

This means:

- `执行中心`
  - top: pending actions summary
  - middle: recent signal list
  - bottom/detail: selected signal detail
- `账户结果`
  - positions
  - equity curve
  - trade summary
The lower detail region should use real module titles only. Avoid placeholder UI labels like “主工作区” and “工作区”.

### Strategy-mode semantics

Realtime simulation must use the same strategy-mode model already used by replay:

- `自动`
  - market regime + fundamental quality infer the effective style
- `激进`
  - force aggressive style
- `中性`
  - force neutral / steady style
- `稳健`
  - force defensive style

The selected realtime strategy mode must be persisted and reused by:

- manual `立即分析候选池`
- scheduled scans
- candidate-row `立即分析`

## Auto-execution behavior

The UI must clearly communicate the behavioral split:

### When `自动执行模拟交易 = 开启`

- manual scan immediately simulates executable BUY/SELL outcomes
- scheduled scans immediately simulate executable BUY/SELL outcomes
- candidate-row `立即分析` immediately simulates executable BUY/SELL outcomes
- the signal is still persisted, but executable actions do not wait in the pending-action queue

### When `自动执行模拟交易 = 关闭`

- the same analyses still run
- BUY/SELL become pending actions that require user confirmation
- HOLD remains observational only

This is still simulation only; no real broker execution is introduced.

## Candidate-pool interaction model

The standalone manual-add stock form should be removed from the page body.

Instead, candidate-pool management moves into the candidate tab itself:

- a visible `添加股票` control near the candidate-pool title
- add form fields can appear inline in the candidate section
- stock add still feeds the existing candidate-pool service

Each candidate row should expose:

- `立即分析`
- `删除`

`立即分析` should open a modal dialog with the same strategy explanation depth used by replay, instead of pushing an inline detail section further down the page.

The old expanded-card action `立即分析该标的` must be removed.

The candidate section should stay compact and action-oriented:

- table first
- row-level actions second
- no duplicate analyze buttons in nested UI
- when a user clicks row-level `立即分析`, the page should update a dedicated `候选股详情` area below the candidate pool instead of only showing a transient flash message

## Persistence changes

Realtime scheduler config must persist `strategy_mode`.

The `sim_scheduler_config` record must therefore include:

- `strategy_mode`

The scheduler runtime status must also expose `strategy_mode` so the UI can reflect the currently effective configuration.

## Code boundaries

### `quant_sim/ui.py`

Owns:

- realtime layout
- direct configuration rendering
- candidate-pool add/delete/analyze UI
- copy and status messaging about auto-execute vs manual mode

### `quant_sim/db.py`

Owns:

- scheduler-config storage
- default value / migration for `strategy_mode`

### `quant_sim/scheduler.py`

Owns:

- reading `strategy_mode` from config
- passing it into `QuantSimEngine`
- surfacing it in scheduler status

### `quant_sim/engine.py`

Already supports `strategy_mode`; no responsibility change, but realtime callers must now pass it consistently.

## Testing Strategy

Mandatory coverage:

- realtime page source no longer contains the scheduler/account expander
- realtime page source directly exposes:
  - 分析粒度
  - 策略模式
  - 自动执行模拟交易
  - 开始日期
- scheduler config persists and returns `strategy_mode`
- manual scan passes `strategy_mode` into engine execution
- scheduled scan passes `strategy_mode` into engine execution
- candidate add remains possible from the candidate-pool section
- candidate delete is exposed in the candidate section
- candidate-row analyze action is exposed in the candidate section
- old nested `立即分析该标的` action is no longer present
- realtime candidate analysis renders a dedicated `候选股详情` section with the same strategy-depth narrative used in replay detail
- the realtime page source no longer contains placeholder section labels like “主工作区” or “工作区”
- UI text clearly states that auto-execute simulates execution without real trading

## Review Protocol

This work still follows the existing two-pass review rule:

1. code/spec review
2. runtime verification review

The UI restructure is not complete until both pass without blocking findings.

## Completion Criteria

This feature is complete when:

- realtime `量化模拟` shows scheduler/account/strategy configuration directly on page load
- realtime strategy mode is selectable and persisted
- auto-execution mode is explicitly explained and works without manual confirmation
- manual mode still routes BUY/SELL into the pending queue
- candidate pool owns stock add/delete/analyze actions
- the old nested candidate analyze button is gone
- tests verify config persistence, UI structure, and runtime strategy-mode propagation
