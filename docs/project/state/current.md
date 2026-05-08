# Current State

## Objective

Keep the project state document aligned with the current implementation of the SPA, shared DB runtime, and quant strategy stack. Older spec/plan files remain as design history; this file is the current operational summary.

## Implemented Baseline

- The frontend is a Vite/React SPA served through `app/gateway_api.py` and nginx in production.
- Current visible SPA routes are `/main`, `/discover`, `/research`, `/portfolio`, `/live-sim`, `/his-replay`, `/strategy-config`, and `/settings`.
- `/real-monitor` is retained as a hidden internal route. AI monitor backend APIs and component code remain, but `/ai-monitor` is not mounted in the current SPA route manifest.
- Primary relational data defaults to `data/xuanwu_stock.db`.
- Historical replay relational data defaults to `data/xuanwu_stock_replay.db`.
- `app/db/runtime` provides the process-scoped DB runtime, configurable `sqlite` / `mysql` URLs, named `primary` and `replay` stores, and read/write/worker unit-of-work entrypoints.

## Strategy Runtime

- Realtime simulation and historical replay share the same quant decision kernel.
- Built-in strategy profiles are `aggressive`, `stable`, and `conservative`.
- New default profile is `aggressive`; `stable` remains the balanced baseline, not the initialized default.
- Built-in profiles run with `dual_track.mode=hybrid`. The generic `StrategyScoringConfig.default()` `rule_only` mode is only a compatibility base/fallback, not the active built-in profile mode.
- Strategy profile settings, candidate/position overrides, stock execution feedback policy, portfolio execution guard policy, and AI dynamic strategy parameters are persisted through the strategy-profile APIs and settings snapshot.

## Execution Gates

`SignalCenterService` applies gates in this order:

1. normalize decision payload and canonical v2.3 scores
2. position constraints
3. position add gate
4. reentry constraints
5. stock execution feedback
6. portfolio execution guard
7. transaction-cost constraints
8. signal persistence

Current strategy guard semantics:

- No-position candidates never generate executable SELL; sell-like candidate outcomes become non-tradable HOLD/reject records.
- Loss/stop feedback after a BUY can block or downgrade later BUY signals.
- Strong trend confirmation after loss is strict by default and requires MA stack, consecutive checkpoints above MA20, and MA20 retest confirmation.
- Weak-buy reentry after a loss is additionally checked by the portfolio guard: last buy was weak, a loss happened after that buy, the current signal is still weak, and strict trend confirmation is missing.
- Capital-slot sizing reads final gate multipliers once; gates record evidence and do not pre-scale `position_size_pct`.

## Data And UI Boundaries

- `/live-sim` first snapshot is intentionally light: config, status, account metrics, realtime quant stocks, capital pool, and trade-cost summary.
- Live signals and trades are separate paged endpoints.
- `/his-replay` freezes `stock_universe.quant_enabled=1` at task start and writes only to replay tables.
- UI table timestamps must display system time; persisted timestamps remain UTC.

## Review State

- The active algorithm description is `docs/量化模拟算法设计.md`.
- The active UI/API route descriptions are `docs/前端页面与交互清单.md` and `docs/后端能力与服务接口清单.md`.
- Historical specs under `docs/superpowers/` are design records unless they explicitly include a current implementation note.
