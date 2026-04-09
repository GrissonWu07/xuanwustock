# Quant Kernel Design

**Date:** 2026-04-09

**Goal**

Unify quantitative strategy execution inside the main project by extracting a reusable `quant_kernel` from `stockpolicy`, then using that kernel for both `quant_sim` automatic simulation and future live trading. The main project remains the only frontend and the only place that owns data-source configuration, model configuration, and account/result presentation.

**Product Outcome**

- `quant_sim` supports automatic execution in simulation mode.
- `quant_sim` supports replay over a user-selected datetime range.
- Replay can run from a start datetime through an explicit end datetime or, when end is left empty, from the start datetime through the current time.
- The same strategy core is reusable for future live trading.
- `stockpolicy` YAML config, standalone data fetchers, and standalone model clients are no longer runtime dependencies for the main workflow.
- Every per-stock analysis view shows the strategy basics that produced the decision.

## Scope

This design covers:

- extracting a reusable strategy core from `stockpolicy`
- replacing the embedded simplified `quant_sim` strategy logic with that core
- adding automatic simulated execution for realtime scheduled runs
- adding a replay engine for historical-range and past-to-future simulation
- adding dynamic strategy selection based on market regime, stock quality, and selected timeframe mode
- surfacing strategy basics in each stock analysis record shown in Streamlit
- keeping Streamlit, SQLite, data providers, and model providers inside the main project

This design does not cover:

- real broker/live order placement
- preserving the standalone `stockpolicy` CLI UX
- migrating the entire `stockpolicy` tree into the main product
- adding all possible intraday granularities on day one

## Constraints

- The main Streamlit app remains the only UI entry point.
- Main-project data sources are the only market-data providers at runtime.
- Main-project model configuration is the only LLM/model configuration at runtime.
- Simulation and replay must use the same strategy kernel.
- Strategy code must be isolated from Streamlit and SQLite UI concerns.
- The extracted kernel must remain suitable as the foundation for a later live execution adapter.
- Initial timeframe support is limited to `30m` and `1d`.

## Current State

The main project currently has:

- a usable simulation shell in `quant_sim`
- candidate pool, signals, trades, positions, scheduler, and UI
- replay and continuous-simulation orchestration
- partial `quant_kernel` extraction

`stockpolicy` currently has:

- a richer decision engine
- slot-based and lot-based position logic
- pyramiding rules
- T+1/FIFO/pending-exit behavior
- time-range backtest flow
- multi-agent ideas around market regime, policy, and fundamental context

The remaining gap is that the main project still needs a fully explicit dynamic strategy model that:

- derives a market regime
- derives stock quality
- maps those into a current risk style
- then applies the selected timeframe execution mode

## Architecture

### 1. `quant_kernel` as reusable strategy core

`quant_kernel` is the reusable core for:

- realtime simulated auto execution
- historical replay
- future live trading execution adapters

It must not import Streamlit and must not depend on `stockpolicy` YAML files.

Key files:

- `quant_kernel/models.py`
- `quant_kernel/config.py`
- `quant_kernel/interfaces.py`
- `quant_kernel/decision_engine.py`
- `quant_kernel/portfolio_engine.py`
- `quant_kernel/replay_engine.py`
- `quant_kernel/runtime.py`

### 2. Main project owns providers

`quant_kernel` receives provider implementations from the main project:

- `MarketDataProvider`
  - backed by `smart_monitor_tdx_data.py`, `smart_monitor_data.py`, and main-project stock-data helpers
- `ModelProvider`
  - backed by the main project’s configured model/LLM path
- `ExecutionProvider`
  - simulation provider for now
  - live execution provider later

This keeps runtime ownership inside the main project while still reusing the core strategy logic.

### 3. `quant_sim` becomes orchestration + persistence + UI

`quant_sim` remains responsible for:

- candidate pool
- SQLite persistence
- realtime scheduler shell
- Streamlit page rendering
- reporting and metrics display

`quant_sim` stops being the place where strategy semantics live.

## Dynamic Strategy Model

The strategy kernel must not be a fixed threshold table keyed only by timeframe. It must derive a current strategy profile per stock evaluation using:

1. market regime
2. stock fundamental quality
3. selected timeframe mode
4. resulting risk style

### 1. Market Regime

Every evaluation must classify the market into one of:

- `牛市`
- `震荡`
- `弱市`

This classification should be dynamic and time-sensitive. It must be computed from data available at the evaluation timestamp and must not be a static source prior.

First implementation should derive regime from main-project market data that is already available or can be added with low coupling, such as:

- index trend / moving-average structure
- MACD and momentum state
- 成交活跃度 / volume expansion
- short-term volatility state

The regime provider must be pluggable so later live trading can reuse the same logic.

### 2. Fundamental Quality

Every stock evaluation must classify the stock into one of:

- `强基本面`
- `中性`
- `弱基本面`

This classification should use whichever normalized metadata the main project already has or can persist from selector outputs, such as:

- profit growth
- ROE
- PE / PB reasonableness
- sector leadership or market-cap tier
- source-specific quality hints

If some fields are missing, the kernel may fall back to partial scoring, but it must still emit one of the three quality labels.

### 3. Risk Style

The kernel must derive the active risk style from market regime and fundamental quality:

- `激进`
- `稳重`
- `保守`

Recommended mapping:

- 牛市 + 强基本面 -> 激进
- 牛市 + 中性 -> 稳重
- 牛市 + 弱基本面 -> 保守
- 震荡 + 强基本面 -> 稳重
- 震荡 + 中性 -> 保守
- 震荡 + 弱基本面 -> 保守
- 弱市 + 强基本面 -> 稳重偏保守, materialized as 保守 or a lower-allocation 稳重 profile
- 弱市 + 中性/弱基本面 -> 保守

The mapping must be deterministic in code and encoded in `quant_kernel`, not hidden in the UI.

### 4. Timeframe Execution Mode

The first release formally supports:

- `30m`
- `1d`
- `1d+30m 共振`

Definitions:

- `1d`
  - daily direction and swing-style decisioning
- `30m`
  - intraday / short swing execution timing
- `1d+30m 共振`
  - daily direction filter plus 30-minute execution confirmation

The kernel must allow the selected timeframe mode to change thresholds and execution behavior. It is not enough for only the source bars to change while thresholds stay identical.

### 5. Effective Strategy Profile

Each evaluation produces an effective strategy profile:

- market regime label and score
- fundamental quality label and score
- risk style label
- timeframe mode
- effective buy threshold
- effective sell threshold
- effective default position size
- whether pyramiding is allowed
- confirmation requirements

This profile becomes part of the decision payload and must be persistable and renderable.

## Strategy-Core Extraction Rules

The following `stockpolicy` capabilities are in scope for extraction:

- decision data structures
- dual-track decision semantics
- slot and lot models
- T+1 lock semantics
- FIFO selling
- pyramiding
- pending exit / risk exit concepts
- history/temporal memory primitives where they help replay and live consistency
- market-regime and context reasoning ideas

The following `stockpolicy` pieces are explicitly out of scope for direct reuse:

- YAML config loading
- standalone CLI entrypoints
- standalone logging and output layout
- stockpolicy-owned data fetchers and model clients

## Runtime Modes

### Realtime Simulation

Used by the current `quant_sim` scheduler.

Flow:

1. Scheduler wakes up on interval.
2. Active candidates and current positions are analyzed through `quant_kernel`.
3. Dynamic strategy profile is derived for each stock.
4. If auto-execution is enabled:
   - `BUY/SELL` decisions are executed immediately against the simulation account.
5. Signals, strategy profile, trades, and equity snapshots are persisted.

### Historical Replay

Used for explicit datetime-range simulation.

Flow:

1. User specifies:
   - start datetime
   - optional end datetime
   - market
   - timeframe mode
2. If end datetime is omitted, replay runs from start datetime through current time.
3. Replay engine generates evaluation checkpoints.
4. For each checkpoint:
   - fetch historical view available at that checkpoint
   - evaluate candidates and positions through `quant_kernel`
   - derive per-stock strategy profile
   - automatically execute according to simulation execution rules
   - record trades, signals, strategy profile, and equity snapshots
5. Final metrics and timeline are shown in Streamlit.

### Past-to-Future Continuous Simulation

This mode is a composition:

1. run historical replay from `start_datetime` to explicit end time or current time
2. keep the resulting simulation account open
3. if the chosen mode is continuous-to-live, hand off to realtime scheduler for continued forward simulation

This preserves continuity between historical replay and ongoing simulation.

## Execution Semantics

### Automatic Execution

Automatic execution applies only to the simulation account.

Rules:

- `BUY`
  - only execute if cash is sufficient
  - obey A-share lot sizing
  - respect max single-name allocation
  - respect slot allocation and pyramiding stage if enabled
- `SELL`
  - only execute when there is sellable quantity
  - obey T+1 and FIFO
  - T+1 unlock uses the next trading day, not the next natural day
  - never emit executable `SELL` when no position exists
- `HOLD`
  - record only; no execution

### Price Selection

First implementation:

- realtime simulation: current snapshot price
- daily replay: daily bar close
- 30-minute replay: 30-minute interval close

This keeps replay deterministic and easy to reason about.

## Data Model Changes

Current `quant_sim` tables are not enough for replay runs and strategy-profile display. The persistence layer must support:

- `sim_runs`
  - mode, start/end, status, config snapshot
- `sim_run_checkpoints`
  - each replay evaluation timestamp
- `sim_run_metrics`
  - summary metrics per run
- `strategy_signals`
  - persist strategy profile payload for each decision

Replay/account history ordering rules:

- snapshot reads used for metrics must be normalized into chronological order before metric calculation
- continuous handoff must also preserve chronological order when copying snapshots into runtime state

This prevents realtime simulation data from mixing with replay data and avoids reversed performance metrics.

## Config Model

Replace YAML runtime config with dataclasses in `quant_kernel/config.py`.

The config model must cover:

- slot allocation
- pyramiding thresholds
- risk exits
- replay timeframe mode
- automatic execution behavior
- market calendar / trading-hour behavior
- regime thresholds
- fundamental-quality thresholds
- risk-style parameter presets

Main-project UI values map into these dataclasses before kernel execution.

## UI Requirements

### Replay Controls

The replay UI must support:

- start date
- start time
- optional end date
- optional end time
- timeframe mode selector
- market selector
- explicit option meaning “end not provided, replay through now”

The UI must no longer force replay to `00:00 -> 15:00`.

### Per-Stock Strategy Basics

Every signal or stock-analysis presentation in `quant_sim` must show the strategy basics that produced the current decision. At minimum, display:

- `市场状态`
- `基本面质量`
- `当前风格`
- `时间框架`
- `建议仓位`
- effective threshold summary or decision basis summary

This must be visible both in:

- strategy-signal views
- pending/auto-execution views

The goal is that a user can understand why a stock is being treated aggressively, conservatively, or neutrally without opening source code.

## Integration Plan

### Phase 1: Extract reusable `quant_kernel`

- add package
- vendor reusable logic from `stockpolicy`
- replace remaining simplified `quant_sim` strategy behavior with `quant_kernel`
- keep current simulation behavior green

### Phase 2: Dynamic strategy profile

- add regime classification
- add fundamental-quality classification
- add risk-style mapping
- add timeframe-mode-dependent thresholds
- persist and display strategy profile

### Phase 3: Realtime automatic execution

- add `auto_execute` switch to scheduler/runtime
- route `BUY/SELL` to simulation execution provider
- update UI to expose automatic-execution state and strategy basics

### Phase 4: Replay engine

- implement historical-range replay with datetime start/end
- support omitted end datetime meaning “through now”
- add run persistence and results views

### Phase 5: Continuous from past to future

- hand off replay end state into realtime scheduler

## Testing Strategy

Mandatory coverage:

- strategy decisions remain deterministic under fixed inputs
- dynamic regime classification changes with time-sensitive market inputs
- fundamental-quality classification works with complete and partial metadata
- risk-style mapping follows the approved matrix
- timeframe mode changes thresholds and/or execution semantics, not just bar source
- no-position `SELL` is downgraded and not executed
- auto-executed `BUY` updates cash and lots correctly
- auto-executed `SELL` respects T+1 next-trading-day unlock and FIFO
- replay over a range generates runs, checkpoints, trades, and metrics
- omitted replay end datetime resolves to current time
- snapshot ordering for metrics and handoff is chronological
- replay and realtime data do not contaminate one another
- UI exposes strategy basics and replay controls clearly

## Review Protocol

Each implementation phase must complete two reviews before proceeding:

1. **Code/spec review**
   - compare implementation against this spec
   - identify mismatches, hidden coupling, missing requirements
2. **Runtime verification review**
   - run targeted tests
   - run full regression tests when phase scope is broad
   - verify import/build/runtime behavior where applicable

No phase advances while either review still has blocking findings.

## Completion Criteria

This effort is complete when:

- `quant_sim` can auto-execute simulated trades
- `quant_sim` can replay over a selected datetime range
- replay end datetime may be omitted to mean “through now”
- the replay engine and realtime simulation both use the extracted `quant_kernel`
- strategy decisions are driven by:
  - market regime
  - fundamental quality
  - derived risk style
  - selected timeframe mode
- every stock analysis in `quant_sim` shows the strategy basics behind the decision
- `stockpolicy` YAML, model client, and data-fetcher runtime dependencies are removed from the main project flow
- tests and UI behavior verify that strategy core, simulation execution, replay, and displayed strategy metadata all align with this spec
