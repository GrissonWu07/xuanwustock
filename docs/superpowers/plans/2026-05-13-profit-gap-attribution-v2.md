# Profit Gap Attribution V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn live-quant drill vs historical replay profit gaps into actionable stock-level diagnoses with sub-reasons, evidence, filters, and UI visibility.

**Architecture:** Extend the existing V1 attribution builder instead of adding a parallel system. The builder produces enriched rows, the replay DB persists those rows with filterable columns, the gateway returns summary counts, and the history page renders the expanded diagnosis.

**Tech Stack:** Python, SQLite replay DB, FastAPI gateway, React/TypeScript, existing i18n and replay UI components.

---

### Task 1: Attribution Engine V2

**Files:**
- Modify: `app/quant_sim/profit_gap_attribution.py`
- Test: `tests/test_profit_gap_attribution.py`

- [ ] Add tests proving V2 rows include `primary_label`, `sub_reason`, `severity`, `actionable`, `recommended_action`, trade paths, cap chain, and sell diagnostics.
- [ ] Extend `build_run_stock_summaries()` to collect historical/drill trade paths, candidate events, lifecycle events, lifecycle states, sizing cap chains, and sell diagnostics.
- [ ] Replace V1 label-only classification with V2 sub-reason mapping from `docs/superpowers/specs/2026-05-13-profit-gap-attribution-v2-design.md`.
- [ ] Add fallback classification so rows with `abs(pnl_gap) >= 500` never remain naked `unclassified`; use `same_entry_exit_gap`, `mark_to_market_gap`, `rounding_or_lot_gap`, or `missing_evidence`.
- [ ] Run `pytest tests/test_profit_gap_attribution.py -q`.

### Task 2: Replay DB Persistence And Filtering

**Files:**
- Modify: `app/quant_sim/db.py`
- Test: `tests/test_profit_gap_attribution.py`

- [ ] Add replay table columns for V2 scalar and JSON fields.
- [ ] Update `replace_profit_gap_attributions()` to persist all V2 fields.
- [ ] Extend `list_profit_gap_attributions()` with filters: `label`, `sub_reason`, `severity`, `actionable`, `min_abs_gap`, and `stock`.
- [ ] Decode all JSON evidence fields on read.
- [ ] Run `pytest tests/test_profit_gap_attribution.py tests/test_quant_sim_db.py -q`.

### Task 3: Gateway Contract

**Files:**
- Modify: `app/gateway_api.py`
- Test: `tests/test_live_quant_drill_gateway.py`

- [ ] Add query params matching the DB filters.
- [ ] Return `summary` with counts by label, sub-reason, severity, actionable, and unclassified large-gap count.
- [ ] Preserve lazy generation when no attribution rows exist for the run pair.
- [ ] Run `pytest tests/test_live_quant_drill_gateway.py tests/test_profit_gap_attribution.py -q`.

### Task 4: History Replay UI

**Files:**
- Modify: `ui/src/features/quant/his-replay-page.tsx`
- Modify: `ui/src/lib/api-client.ts`
- Modify: `ui/src/locales/zh-CN.json`
- Modify: `ui/src/locales/en-US.json`

- [ ] Extend the profit-gap API client to pass filter query values.
- [ ] Add table columns for label, sub-reason, severity, actionable, and recommended action.
- [ ] Add compact filters for label, severity, actionable-only, and min absolute gap.
- [ ] Add summary chips above the table so users can see the distribution before reading rows.
- [ ] Run `npm test -- --run` and `npm run build` from `ui`.

### Task 5: Real Run Verification

**Files:**
- No production code expected.

- [ ] Generate #58 historical vs #56 drill attribution with V2.
- [ ] Verify no row with `abs(pnl_gap) >= 500` has only `unclassified`.
- [ ] Verify top gaps for `300736`, `301666`, `300283`, `600768`, `002319`, and `300106` have sub-reason and recommended action.
- [ ] Run focused backend/frontend checks again after any fixes.

