# Quant Universe Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement lifecycle-driven realtime quant universe management: candidate events, automatic trial entry, health-based exit/cooling, explicit UI controls, and explainable state transitions.

**Architecture:** Add a focused lifecycle layer around the existing `stock_universe` and live-sim flow. `QuantUniverseManager` owns quant lifecycle state and events, while existing signal generation, portfolio sizing, refresh, and replay behavior remain intact. UI consumes lifecycle aggregates through dedicated APIs instead of re-deriving state from raw signal tables.

**Tech Stack:** Python FastAPI-style gateway functions, SQLite-backed `QuantSimDB`, existing quant kernel/runtime services, React + TypeScript UI, Vitest frontend tests, pytest backend tests.

---

## Source Spec

- `docs/superpowers/specs/2026-05-08-quant-universe-lifecycle-design.md`

Implementation must follow the spec as the source of truth. The deployment assumption is delete-and-rebuild databases; do not add old-schema compatibility or migration inference.

## File Structure

### Backend

- Create `app/quant_sim/quant_universe_lifecycle.py`
  - Dataclasses, enums, scoring helpers, state transition validation, lifecycle manager.
- Modify `app/quant_sim/db.py`
  - Add schema for lifecycle fields/tables.
  - Add CRUD for candidate events, quant state snapshots, quant events, settings, overview.
- Modify `app/quant_sim/signal_center_service.py`
  - Enforce `exit_only` BUY/ADD downgrade to HOLD at signal finalization.
- Modify `app/quant_sim/scheduler.py`
  - Update health/state after each live-sim run.
  - Run bounded opportunistic cooling review from local cache only.
- Create or extend a lightweight lifecycle notification helper.
  - Build daily summary payloads and instant retired notifications using existing `notification_service`.
- Modify `app/quant_sim/engine.py`
  - Ensure live-sim candidate scan reads only `quant_enabled=1 AND quant_status IN ('trial','active','exit_only')`.
- Modify `app/gateway/live_sim.py`
  - Return lifecycle fields in live-sim snapshot.
  - Add `quant_status` filtering.
- Create `app/gateway/quant_universe.py`
  - API endpoints for state, overview, settings, and actions.
- Modify `app/gateway/workbench.py`
  - Stop embedding lifecycle overview in workbench snapshot; UI loads it from dedicated endpoint.
- Modify discover/research gateway modules
  - Add lifecycle eligibility fields to result rows.
  - Support promote/ignore actions through the new lifecycle APIs.

### Frontend

- Modify `ui/src/features/quant/live-sim-page.tsx`
  - Add lifecycle controls, status chips, lifecycle table columns, row actions.
- Modify `ui/src/features/discover/discover-page.tsx`
  - Add eligible badges, filters, batch promote dialog, row actions.
- Modify `ui/src/features/research/research-page.tsx`
  - Reuse lifecycle entry UI for stock-linked research rows.
- Modify `ui/src/features/workbench/workbench-page.tsx`
  - Add `QuantOverviewCards` loaded from `/api/v1/quant/universe/overview`.
- Create focused UI components near their feature owners:
  - `EligibleBadge`
  - `BatchPromoteDialog`
  - `QuantOverviewCards`
  - `LifecycleMasterSwitch`
  - `AutoEntryModeSelect`
  - `AutoExitSwitch`
  - `LifecycleSummaryBadgeGroup`
  - `StatusFilterChips`
  - `HealthScoreBar`
  - `AutoManageToggle`
  - `RestoreToTrialButton`

### Tests

- Create `tests/test_quant_universe_lifecycle_db.py`
- Create `tests/test_quant_universe_lifecycle_manager.py`
- Create `tests/test_quant_universe_gateway.py`
- Extend `tests/test_quant_sim_scheduler.py`
- Extend `tests/test_quant_sim_engine.py`
- Extend `tests/test_gateway_signal_table.py` or add a targeted signal finalization test.
- Extend UI tests:
  - `ui/src/tests/live-sim-page.test.tsx`
  - `ui/src/tests/discover-page.test.tsx`
  - `ui/src/tests/research-page.test.tsx`
  - `ui/src/tests/workbench-page.test.tsx`

---

## Task 1: Database Schema And CRUD

**Files:**
- Modify: `app/quant_sim/db.py`
- Test: `tests/test_quant_universe_lifecycle_db.py`

- [ ] **Step 1: Add failing schema tests**

Create tests that instantiate `QuantSimDB` on a temp DB and assert:

```python
def test_quant_universe_schema_created(tmp_path):
    db = QuantSimDB(str(tmp_path / "quant_sim.db"))
    with db._connect() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "stock_universe_quant_state" in tables
    assert "stock_universe_candidate_events" in tables
    assert "stock_universe_quant_events" in tables
```

Add a second test that inserts a stock and writes/reads a quant state snapshot with:

```python
assert state["quant_status"] == "trial"
assert state["health_score"] == 72.5
assert state["snapshot_json"]["kernel_health_base"] == 68.0
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
pytest tests/test_quant_universe_lifecycle_db.py -q
```

Expected: fails because lifecycle tables and methods do not exist.

- [ ] **Step 3: Add schema**

In `QuantSimDB` initialization, add columns to `stock_universe`:

- `quant_status TEXT`
- `quant_auto_managed INTEGER DEFAULT 1`
- `quant_manual_override TEXT DEFAULT ''`
- `quant_entry_source TEXT`
- `quant_entry_at TEXT`

Create tables:

- `stock_universe_quant_state`
- `stock_universe_candidate_events`
- `stock_universe_quant_events`

Use UTC ISO timestamps consistently.

- [ ] **Step 4: Add focused CRUD**

Add methods in `QuantSimDB`:

- `get_quant_universe_state(stock_code: str) -> dict | None`
- `upsert_quant_universe_state(stock_code: str, payload: dict) -> dict`
- `record_quant_universe_event(payload: dict) -> dict`
- `add_candidate_event(payload: dict) -> dict`
- `list_candidate_events(...) -> list[dict]`
- `list_quant_universe_state(statuses: list[str] | None, keyword: str | None, limit: int, offset: int) -> dict`
- `get_quant_universe_overview() -> dict`
- `get_quant_universe_settings() -> dict`
- `update_quant_universe_settings(payload: dict) -> dict`

- [ ] **Step 5: Run database tests**

Run:

```powershell
pytest tests/test_quant_universe_lifecycle_db.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add app/quant_sim/db.py tests/test_quant_universe_lifecycle_db.py
git commit -m "feat: add quant universe lifecycle storage"
```

---

## Task 2: Lifecycle Core And Health Score

**Files:**
- Create: `app/quant_sim/quant_universe_lifecycle.py`
- Test: `tests/test_quant_universe_lifecycle_manager.py`

- [ ] **Step 1: Add failing unit tests for health normalization**

Test required formulas:

```python
def test_health_score_uses_kernel_score_normalization():
    inputs = HealthInputs(
        avg_tech_score=0.0,
        avg_context_score=-1.0,
        avg_fusion_score=0.8,
        avg_buy_strength_score=0.6,
        no_buy_days=3,
        recent_stoploss_count=1,
        blocked_streak=2,
        candidate_support_bonus=4.0,
    )
    policy = QuantUniverseLifecyclePolicy.stable_defaults()
    result = calculate_health_score(inputs, policy)
    assert 0 <= result.health_score <= 100
    assert result.breakdown["normalized_tech_health"] == 50.0
    assert result.breakdown["normalized_context_health"] == 0.0
    assert result.breakdown["execution_penalty_base"] == 11.0
```

- [ ] **Step 2: Add failing state transition tests**

Cover:

- `active -> exit_only` when holding and health is below threshold.
- `active -> cooling` when no holding and downtrend streak reaches threshold.
- `exit_only -> trial` only after position is flat, health recovers, and candidate support exists.
- `exit_only -> active` only after position is flat, health reaches `active_upgrade_threshold`, and trend confirmation passes.
- `restore_to_trial` rejects `active` with `invalid_restore_state`.

- [ ] **Step 3: Run tests and confirm failure**

```powershell
pytest tests/test_quant_universe_lifecycle_manager.py -q
```

Expected: import errors or missing functions.

- [ ] **Step 4: Implement core dataclasses and enums**

Define:

- `QuantStatus`
- `ManualOverride`
- `AutoEntryMode`
- `QuantUniverseLifecyclePolicy`
- `HealthInputs`
- `HealthResult`
- `TransitionResult`

Implement defaults for `aggressive`, `stable`, `conservative`.

- [ ] **Step 5: Implement scoring helpers**

Implement:

- `calculate_health_score(inputs, policy)`
- `detect_weakening_warning(signal, policy)`
- `detect_downtrend_hit(signal, state, policy)`
- `calculate_candidate_score(events, stock_snapshot, policy)`

The health formula must match the spec exactly:

```python
normalized_tech = clamp(((avg_tech + 1) / 2) * 100, 0, 100)
normalized_context = clamp(((avg_context + 1) / 2) * 100, 0, 100)
normalized_fusion = clamp(avg_fusion * 100, 0, 100)
normalized_buy_strength = clamp(avg_buy_strength * 100, 0, 100)
execution_penalty_base = recent_stoploss_count * 5.0 + blocked_streak * 3.0
inactivity_penalty_base = min(no_buy_days, trial_no_buy_days_threshold) * 2.0
candidate_support_bonus_base = min(valid_candidate_event_count * 3.0, 15.0)
reentry_watch_penalty_base = 12.0 if now < reentry_watch_until else 0.0
```

Then apply profile multipliers:

```python
candidate_support_bonus = candidate_support_bonus_base * candidate_support_bonus_multiplier
reentry_watch_penalty = reentry_watch_penalty_base * reentry_watch_penalty_multiplier
```

- [ ] **Step 6: Implement transition validator**

Implement `resolve_next_status(...)` with legal transitions from the spec, including:

- `exit_only -> trial`
- `exit_only -> active`
- `manual_paused` is never auto-restored
- `active -> retired` is forbidden directly

- [ ] **Step 7: Run lifecycle tests**

```powershell
pytest tests/test_quant_universe_lifecycle_manager.py -q
```

Expected: pass.

- [ ] **Step 8: Commit**

```powershell
git add app/quant_sim/quant_universe_lifecycle.py tests/test_quant_universe_lifecycle_manager.py
git commit -m "feat: add quant universe lifecycle core"
```

---

## Task 3: Quant Universe Manager

**Files:**
- Modify: `app/quant_sim/quant_universe_lifecycle.py`
- Test: `tests/test_quant_universe_lifecycle_manager.py`

- [ ] **Step 1: Add manager tests**

Add tests for:

- Candidate event aggregation.
- `confirm_first` returns eligible without changing stock status.
- `auto_trial` promotes to `trial`.
- `auto_exit_enabled=false` still updates `health_score` but does not downgrade.
- `quant_universe_lifecycle_enabled=false` freezes automatic state changes.
- Candidate with `manual_ban` is skipped with reason `manual_ban`.
- Candidate with `basic_info_missing=1` can be marked eligible but cannot auto-promote in `auto_trial`.
- Candidate inside `cooling_until` is skipped with reason `cooling_blocked`.
- Candidate exceeding `max_auto_entries_per_batch` is skipped after higher scored rows are promoted.
- Same-industry and same-concept capacity limits keep only the highest scored rows.
- `retired -> trial` requires `retired_reactivation_check_enabled=true` and `candidate_score >= high_reentry_threshold`.

- [ ] **Step 2: Implement `QuantUniverseManager`**

Constructor inputs:

- `db: QuantSimDB`
- `profile_id: str`
- `policy: QuantUniverseLifecyclePolicy`

Methods:

- `ingest_candidate_event(payload: dict) -> dict`
- `evaluate_candidate(stock_code: str) -> dict`
- `promote_to_trial(stock_codes: list[str], source_type: str, source_key: str | None) -> dict`
- `ignore_auto_entry(stock_codes: list[str], source_type: str | None) -> dict`
- `set_override(stock_code: str, override_type: str) -> dict`
- `restore_to_trial(stock_code: str) -> dict`
- `update_after_signal(stock_code: str, latest_signal: dict, recent_signals: list[dict], position: dict | None) -> dict`
- `overview() -> dict`

Admission gates must enforce:

- non-tradable state blocks auto-entry
- `basic_info_missing=1` blocks `auto_trial`
- `manual_ban` blocks entry
- `cooling_until` blocks entry
- per-batch, per-day, per-strategy, industry, and concept capacity limits
- `strong_candidate_threshold` is only a UI/ranking label, not a direct promotion to `active`

- [ ] **Step 3: Enforce API error semantics inside manager**

`restore_to_trial()` must return or raise a structured domain error:

```python
{
    "error_code": "invalid_restore_state",
    "error_message": "股票当前处于 active，无需恢复",
}
```

for `trial/active/exit_only`.

- [ ] **Step 4: Run manager tests**

```powershell
pytest tests/test_quant_universe_lifecycle_manager.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add app/quant_sim/quant_universe_lifecycle.py tests/test_quant_universe_lifecycle_manager.py
git commit -m "feat: add quant universe manager"
```

---

## Task 4: Signal Finalization And `exit_only`

**Files:**
- Modify: `app/quant_sim/signal_center_service.py`
- Test: `tests/test_quant_universe_lifecycle_manager.py` or `tests/test_quant_sim_services.py`

- [ ] **Step 1: Add failing signal test**

Create a signal with:

```python
decision = {"action": "BUY", "decision_type": "weighted_buy", "position_size_pct": 50}
stock_context = {"quant_status": "exit_only"}
```

Expected normalized signal:

```python
assert signal["action"] == "HOLD"
assert signal["position_size_pct"] == 0
assert signal["decision_type"] == "exit_only_blocked"
assert signal["explain"]["lifecycle"]["quant_status"] == "exit_only"
```

- [ ] **Step 2: Implement finalization guard**

In `SignalCenterService.create_signal`, after existing BUY gate logic but before persistence, detect `quant_status == "exit_only"` and original action `BUY` or `ADD`.

Force:

- `action = "HOLD"`
- `position_size_pct = 0`
- `decision_type = "exit_only_blocked"`
- explain lifecycle reason.

- [ ] **Step 3: Run service tests**

```powershell
pytest tests/test_quant_sim_services.py tests/test_stock_execution_feedback.py -q
```

Expected: pass.

- [ ] **Step 4: Commit**

```powershell
git add app/quant_sim/signal_center_service.py tests/test_quant_sim_services.py
git commit -m "feat: block buy signals for exit-only stocks"
```

---

## Task 5: Scheduler And Engine Integration

**Files:**
- Modify: `app/quant_sim/scheduler.py`
- Modify: `app/quant_sim/engine.py`
- Test: `tests/test_quant_sim_scheduler.py`
- Test: `tests/test_quant_sim_engine.py`

- [ ] **Step 1: Add scheduler tests**

Cover:

- Main scan includes `trial/active/exit_only`.
- Main scan excludes `cooling/retired/manual_paused`.
- Opportunistic review processes at most `min(5, cooling_count)`.
- Opportunistic review does not call remote refresh or provider code.
- `cooling` review uses local cache only and does not call `load_stock_runtime_entries` with remote fetch behavior.
- Historical replay candidate freeze remains based on `quant_enabled=1` and does not apply dynamic lifecycle transitions.

- [ ] **Step 2: Wire candidate selection**

Update the live-sim candidate query to use:

```sql
quant_enabled = 1
AND quant_status IN ('trial', 'active', 'exit_only')
```

Keep historical replay unchanged.

- [ ] **Step 3: Update lifecycle after signals**

After each candidate signal is generated, call:

```python
manager.update_after_signal(stock_code, latest_signal, recent_signals, current_position)
```

Record events only when status changes.

- [ ] **Step 4: Implement opportunistic cooling review**

After main scan:

- Get cooling stocks with fresh local cache.
- Sort by `health_score ASC`, `last_health_evaluated_at ASC`.
- Process at most `min(5, cooling_count)`.
- Do not trigger remote quote/K-line/basic-info fetch.

- [ ] **Step 5: Add refresh-boundary assertions**

Lifecycle code must not call remote providers directly. If a candidate has `basic_info_missing=1`, the manager may only mark it as not auto-promotable and rely on the existing stock refresh scheduler to fill data later.

- [ ] **Step 6: Run scheduler and engine tests**

```powershell
pytest tests/test_quant_sim_scheduler.py tests/test_quant_sim_engine.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```powershell
git add app/quant_sim/scheduler.py app/quant_sim/engine.py tests/test_quant_sim_scheduler.py tests/test_quant_sim_engine.py
git commit -m "feat: integrate lifecycle with live sim scanning"
```

---

## Task 6: Quant Universe API

**Files:**
- Create: `app/gateway/quant_universe.py`
- Modify route registration if needed in `app/main.py` or existing gateway registry.
- Test: `tests/test_quant_universe_gateway.py`

- [ ] **Step 1: Add failing gateway tests**

Test endpoints from spec:

- `GET /api/v1/quant/universe/state`
- `GET /api/v1/quant/universe/overview`
- `GET /api/v1/quant/universe/settings`
- `POST /api/v1/quant/universe/settings`
- `POST /api/v1/quant/universe/actions/promote-to-trial`
- `POST /api/v1/quant/universe/actions/ignore-auto-entry`
- `POST /api/v1/quant/universe/actions/set-override`
- `POST /api/v1/quant/universe/actions/restore-to-trial`

Include a test that `restore-to-trial` on `active` returns:

```json
{
  "error_code": "invalid_restore_state",
  "error_message": "股票当前处于 active，无需恢复"
}
```

with HTTP 400.

- [ ] **Step 2: Implement endpoints**

Use `QuantUniverseManager` and `QuantSimDB` only. Do not let endpoints directly calculate lifecycle rules.

- [ ] **Step 3: Implement lightweight overview**

`/api/v1/quant/universe/overview` must return top items only with:

- `stock_code`
- `stock_name`
- `latest_reason`

No quote, price, K-line, or heavy market fields.

- [ ] **Step 4: Run gateway tests**

```powershell
pytest tests/test_quant_universe_gateway.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add app/gateway/quant_universe.py tests/test_quant_universe_gateway.py
git commit -m "feat: add quant universe lifecycle api"
```

---

## Task 7: Live-Sim API Payloads

**Files:**
- Modify: `app/gateway/live_sim.py`
- Test: `tests/test_quant_universe_gateway.py` or `tests/test_ui_backend_api_contract.py`

- [ ] **Step 1: Add failing API contract test**

Request `/api/v1/quant/live-sim?quant_status=trial,active`.

Assert response includes:

```python
candidate = response["candidatePool"]["rows"][0]
assert candidate["lifecycle"]["quant_status"] in {"trial", "active"}
assert "health_score" in candidate["lifecycle"]
assert "candidate_score" in candidate["lifecycle"]
assert "latest_reason" in candidate["lifecycle"]
```

- [ ] **Step 2: Implement `quant_status` filter**

Pass filter from gateway to candidate listing. Do not filter signals/trades/positions tabs.

- [ ] **Step 3: Append lifecycle data to candidate rows**

Attach lifecycle fields from `stock_universe_quant_state` and latest quant event.

- [ ] **Step 4: Run API contract tests**

```powershell
pytest tests/test_ui_backend_api_contract.py tests/test_quant_universe_gateway.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add app/gateway/live_sim.py tests/test_ui_backend_api_contract.py
git commit -m "feat: expose lifecycle fields in live sim"
```

---

## Task 8: Discover And Research Lifecycle Entrypoints

**Files:**
- Modify: `app/gateway/research.py`
- Modify discover gateway module currently serving `/discover`.
- Modify: `app/discover/discover.py` if row shaping happens there.
- Test: `tests/test_ui_backend_api_contract.py`
- Test: `tests/test_research_watchlist_integration.py`

- [ ] **Step 1: Add tests for discover result fields**

Each discover candidate row must include:

- `eligible_status`
- `candidate_score`
- `blocking_reason`
- `already_in_quant`

- [ ] **Step 2: Add tests for research result fields**

Stock-linked research rows must include equivalent lifecycle entry fields.

- [ ] **Step 3: Implement row enrichment**

Use `QuantUniverseManager.evaluate_candidate` or a read-only helper. Do not create candidate events during read-only GET requests.

- [ ] **Step 4: Run tests**

```powershell
pytest tests/test_ui_backend_api_contract.py tests/test_research_watchlist_integration.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add app/gateway/research.py app/discover/discover.py tests/test_ui_backend_api_contract.py tests/test_research_watchlist_integration.py
git commit -m "feat: expose lifecycle eligibility in discovery and research"
```

---

## Task 9: Strategy Config UI And Policy Persistence

**Files:**
- Modify: `app/gateway/strategy_profiles.py`
- Modify: `ui/src/features/settings/strategy-config-page.tsx`
- Test: `tests/quant_kernel/test_config_profile_merge.py`
- Test: `ui/src/tests/strategy-config-page.test.tsx`

- [ ] **Step 1: Add profile config tests**

Assert lifecycle policy is profile-specific:

- aggressive values differ from stable.
- conservative values differ from stable.
- Editing stable does not overwrite aggressive.

- [ ] **Step 2: Add UI test**

Open strategy config page fixture and assert lifecycle section includes:

- `trial_threshold`
- `strong_candidate_threshold`
- `health_score_lookback_checkpoints`
- `trial_position_multiplier`
- `auto_exit_enabled` does not appear in the profile lifecycle policy section.

- [ ] **Step 3: Implement backend profile default merge**

Add `quant_universe_lifecycle_policy` defaults per profile. System-level settings remain outside profile:

- `quant_universe_lifecycle_enabled`
- `auto_exit_enabled`
- `auto_entry_mode`

- [ ] **Step 4: Implement UI section**

Add a dedicated lifecycle policy section with compact numeric controls and profile-aware save behavior.

- [ ] **Step 5: Run tests**

```powershell
pytest tests/quant_kernel/test_config_profile_merge.py -q
npm --prefix ui run test -- strategy-config-page.test.tsx
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add app/gateway/strategy_profiles.py ui/src/features/settings/strategy-config-page.tsx ui/src/tests/strategy-config-page.test.tsx
git commit -m "feat: add lifecycle policy strategy config"
```

---

## Task 10: Live-Sim UI

**Files:**
- Modify: `ui/src/features/quant/live-sim-page.tsx`
- Create component files under `ui/src/features/quant/` as needed.
- Test: `ui/src/tests/live-sim-page.test.tsx`

- [ ] **Step 1: Add failing UI tests**

Tests must assert:

- Top config shows lifecycle switch, auto-entry mode, auto-exit switch.
- Candidate tab shows status chips including `manual_paused`.
- Default selected chips are `trial`, `active`, `exit_only`.
- Candidate rows show health score and lifecycle reason.
- Restore button appears only for `cooling`, `manual_paused`, `retired`.

- [ ] **Step 2: Add lifecycle control components**

Implement:

- `LifecycleMasterSwitch`
- `AutoEntryModeSelect`
- `AutoExitSwitch`
- `LifecycleSummaryBadgeGroup`

Use existing button/select/toggle patterns in the UI.

- [ ] **Step 3: Add candidate table lifecycle components**

Implement:

- `StatusFilterChips`
- `HealthScoreBar`
- `AutoManageToggle`
- `RestoreToTrialButton`

- [ ] **Step 4: Wire API calls**

Use:

- `GET /api/v1/quant/universe/settings`
- `POST /api/v1/quant/universe/settings`
- `POST /api/v1/quant/universe/actions/set-override`
- `POST /api/v1/quant/universe/actions/restore-to-trial`

Show confirmation dialogs for destructive or state-changing actions.

- [ ] **Step 5: Run UI tests**

```powershell
npm --prefix ui run test -- live-sim-page.test.tsx
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add ui/src/features/quant ui/src/tests/live-sim-page.test.tsx
git commit -m "feat: add lifecycle controls to live sim"
```

---

## Task 11: Discover And Research UI

**Files:**
- Modify: `ui/src/features/discover/discover-page.tsx`
- Modify: `ui/src/features/research/research-page.tsx`
- Test: `ui/src/tests/discover-page.test.tsx`
- Test: `ui/src/tests/research-page.test.tsx`

- [ ] **Step 1: Add discover UI tests**

Assert:

- `EligibleBadge` renders `eligible`, `already_in_quant`, `skipped`, `cooling_blocked`.
- Toolbar has `仅看 eligible`.
- Batch promote opens confirmation dialog.
- Partial failures remain visible row-by-row.

- [ ] **Step 2: Add research UI tests**

Assert research stock rows show lifecycle badges and batch promote actions.

- [ ] **Step 3: Implement `EligibleBadge` and `BatchPromoteDialog`**

Keep them small and reusable between discover and research.

- [ ] **Step 4: Wire actions**

Use:

- `POST /api/v1/quant/universe/actions/promote-to-trial`
- `POST /api/v1/quant/universe/actions/ignore-auto-entry`

Rows must stay visible after success and update to `already_in_quant`.

- [ ] **Step 5: Run UI tests**

```powershell
npm --prefix ui run test -- discover-page.test.tsx research-page.test.tsx
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add ui/src/features/discover ui/src/features/research ui/src/tests/discover-page.test.tsx ui/src/tests/research-page.test.tsx
git commit -m "feat: add lifecycle entry controls to discovery and research"
```

---

## Task 12: Workbench Overview UI

**Files:**
- Modify: `ui/src/features/workbench/workbench-page.tsx`
- Create component under `ui/src/features/workbench/`
- Test: `ui/src/tests/workbench-page.test.tsx`

- [ ] **Step 1: Add workbench UI tests**

Assert:

- `QuantOverviewCards` renders five cards.
- `待纳入量化` click navigates to `/discover?eligible=1`.
- `只出场管理` click navigates to `/live-sim` with `exit_only`.
- Cards use `/api/v1/quant/universe/overview`, not `/api/v1/workbench`.

- [ ] **Step 2: Implement `QuantOverviewCards`**

Each card displays:

- status label
- count
- top three items with `stock_code`, `stock_name`, `latest_reason`

- [ ] **Step 3: Wire async loading**

Load overview in parallel with existing workbench snapshot. Do not block the whole workbench page if overview fails; render a compact error state for only the card group.

- [ ] **Step 4: Run UI test**

```powershell
npm --prefix ui run test -- workbench-page.test.tsx
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add ui/src/features/workbench ui/src/tests/workbench-page.test.tsx
git commit -m "feat: add quant universe overview cards"
```

---

## Task 13: Lifecycle Notifications

**Files:**
- Create or modify: `app/quant_sim/quant_universe_notifications.py`
- Modify: `app/quant_sim/scheduler.py`
- Test: `tests/test_notification_service.py` or create `tests/test_quant_universe_notifications.py`

- [ ] **Step 1: Add notification tests**

Cover:

- Daily summary groups events by type:
  - new `trial`
  - upgraded `active`
  - downgraded `exit_only`
  - entered `cooling`
  - entered `retired`
  - recovered from `cooling`
- Each group returns at most top 10 rows and an overflow count.
- Empty event day sends no empty summary.
- `retired` event can create an instant notification payload.
- Notification rows include code, name, status change, key reason, candidate/health delta, and manual override flag.

- [ ] **Step 2: Implement summary builder**

Build pure functions:

- `build_quant_universe_daily_summary(events: list[dict]) -> dict | None`
- `build_quant_universe_retired_notification(event: dict) -> dict`

Do not send from these functions; return payloads for `notification_service`.

- [ ] **Step 3: Wire scheduler notification dispatch**

After lifecycle transitions are applied, collect created events and:

- send instant notification for `retired` if enabled
- store or dispatch daily summary according to existing notification scheduling conventions

- [ ] **Step 4: Run notification tests**

```powershell
pytest tests/test_quant_universe_notifications.py tests/test_notification_service.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add app/quant_sim/quant_universe_notifications.py app/quant_sim/scheduler.py tests/test_quant_universe_notifications.py tests/test_notification_service.py
git commit -m "feat: add quant universe lifecycle notifications"
```

---

## Task 14: Delete-And-Rebuild Deployment Cleanup

**Files:**
- Modify deployment docs/scripts used for database reset.
- Test: `tests/test_runtime_db_paths.py` or a new focused test if scripts are checked in.

- [ ] **Step 1: Identify reset entrypoint**

Locate current DB reset/deploy scripts. Use:

```powershell
rg "quant_sim.db|quant_sim_replay.db|reset_db|reset|deploy" -n scripts app docs .github
```

- [ ] **Step 2: Add documented reset steps**

Ensure deployment notes explicitly delete and recreate:

- `quant_sim.db`
- lifecycle state/event tables
- old candidate pool residue if still present

Do not add compatibility migration.

- [ ] **Step 3: Verify startup creates empty lifecycle schema**

Run a local backend startup or direct `QuantSimDB` initialization and confirm lifecycle tables exist and are empty.

- [ ] **Step 4: Commit**

```powershell
git add docs scripts tests
git commit -m "docs: document quant universe reset deployment"
```

---

## Task 15: Full Verification

**Files:**
- No production edits unless verification finds defects.

- [ ] **Step 1: Run backend targeted tests**

```powershell
pytest tests/test_quant_universe_lifecycle_db.py tests/test_quant_universe_lifecycle_manager.py tests/test_quant_universe_gateway.py tests/test_quant_universe_notifications.py -q
```

Expected: pass.

- [ ] **Step 2: Run quant-sim regression tests**

```powershell
pytest tests/test_quant_sim_scheduler.py tests/test_quant_sim_engine.py tests/test_quant_sim_services.py tests/test_stock_execution_feedback.py -q
```

Expected: pass.

- [ ] **Step 3: Run API contract tests**

```powershell
pytest tests/test_ui_backend_api_contract.py tests/test_ui_backend_api_actions.py -q
```

Expected: pass.

- [ ] **Step 4: Run frontend tests**

```powershell
npm --prefix ui run test -- live-sim-page.test.tsx discover-page.test.tsx research-page.test.tsx workbench-page.test.tsx strategy-config-page.test.tsx
```

Expected: pass.

- [ ] **Step 5: Build frontend**

```powershell
npm --prefix ui run build
```

Expected: pass.

- [ ] **Step 6: Run diff checks**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors. Only intended files changed.

- [ ] **Step 7: Commit verification fixes if any**

If verification required small fixes:

```powershell
git add <fixed-files>
git commit -m "fix: finalize quant universe lifecycle integration"
```

---

## Self-Review Checklist

- [ ] `exit_only` blocks BUY/ADD at signal finalization.
- [ ] `manual_paused` uses `quant_enabled=0` and is visible in UI filters.
- [ ] `pending_eligible` is sourced from eligible candidate events, not `trial`.
- [ ] `QuantOverviewCards` uses `/api/v1/quant/universe/overview`, not `/api/v1/workbench`.
- [ ] Overview `top_items` does not include quote, price, K-line, or heavy fields.
- [ ] `restore-to-trial` returns `400 invalid_restore_state` for `trial/active/exit_only`.
- [ ] Historical replay still freezes `quant_enabled=1` and does not simulate lifecycle.
- [ ] UI does not re-derive lifecycle state from raw signal tables.
- [ ] No old-schema compatibility migration was added.
- [ ] Auto-entry gates cover `manual_ban`, `basic_info_missing`, `cooling_until`, and capacity limits.
- [ ] Industry and concept capacity limits are tested with sorted candidate scores.
- [ ] Lifecycle code does not call remote market/basic-info providers directly.
- [ ] Daily summary and instant retired notification payloads are covered by tests.
