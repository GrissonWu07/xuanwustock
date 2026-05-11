# Soft Lifecycle Scan Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make quant lifecycle a soft scan and sizing gate instead of a hard prediction-based exit system.

**Architecture:** `QuantUniverseManager` remains the owner of lifecycle state. `QuantSimEngine` and replay drill select normal scan candidates plus cooling supplemental candidates when coverage is low, and `SignalCenterService` writes `lifecycle_gate` into the signal profile so execution sizing can cap BUY size and block exit-only buys.

**Tech Stack:** Python, SQLite-backed `QuantSimDB`, pytest.

---

### Task 1: Policy Defaults And State Rules

**Files:**
- Modify: `app/quant_sim/quant_universe_lifecycle.py`
- Modify: `tests/test_quant_universe_lifecycle_manager.py`

- [x] Add tests that aggressive/stable/conservative defaults expose `min_scan_coverage`, longer cooling/retired dwell values, and lifecycle gate defaults.
- [x] Add tests that low `health_score` alone does not move active/trial to cooling or exit_only, and cooling does not retire without confirmed downtrend.
- [x] Implement policy fields, defaults, and `build_lifecycle_gate()`.
- [x] Update `resolve_next_status()` so downtrend confirmation, not health alone, drives exit/cooling/retired.
- [x] Run `pytest tests/test_quant_universe_lifecycle_manager.py -q`.

### Task 2: Execution Sizing Consumes Lifecycle Gate

**Files:**
- Modify: `app/quant_sim/execution_sizing.py`
- Modify: `app/quant_sim/signal_center_service.py`
- Modify: `tests/test_execution_sizing.py`

- [x] Add tests that `cooling_supplemental` applies stricter cap/multiplier and `exit_only` blocks BUY.
- [x] Attach `lifecycle_gate` into `strategy_profile`.
- [x] Include lifecycle gate cap and multiplier in `build_execution_sizing_plan()`.
- [x] Run `pytest tests/test_execution_sizing.py -q`.

### Task 3: Live Scheduler Supplemental Cooling Scan

**Files:**
- Modify: `app/quant_sim/engine.py`
- Modify: `app/quant_sim/scheduler.py`
- Modify: `tests/test_quant_sim_scheduler.py`

- [x] Add tests that aggressive live scans supplement from cooling when normal coverage is below 6 and that supplement rows carry `cooling_supplemental` gate.
- [x] Add candidate selection helpers that rank normal first, then cooling by candidate support, health score, last evaluation age, and stock code.
- [x] Wire scheduler to analyze selected candidates explicitly instead of only the fixed live statuses.
- [x] Run `pytest tests/test_quant_sim_scheduler.py -q`.

### Task 4: Live Quant Drill Supplemental Cooling Scan

**Files:**
- Modify: `app/quant_sim/replay_service.py`
- Modify: `tests/test_live_quant_drill_service.py`

- [x] Add tests that drill fills coverage from cooling in the same checkpoint and persists `lifecycle_gate.mode = cooling_supplemental`.
- [x] Wire drill main scan through the same selection and gate helper.
- [x] Keep cooling review for state recovery separate from supplemental scan.
- [x] Run `pytest tests/test_live_quant_drill_service.py -q`.

### Task 5: Verification And Data Run

**Files:**
- No new files.

- [x] Run the focused pytest set for lifecycle, sizing, scheduler, and drill.
- [x] Run a 2026-01-01 to current aggressive live quant drill and compare against the last historical replay baseline.
- [x] Review `git diff` against the lifecycle and drill specs before final commit.
