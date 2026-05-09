# Live Quant Drill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add realtime-quant historical drill runs that replay historical checkpoints with full quant universe lifecycle behavior, without modifying live-sim state.

**Architecture:** Reuse the existing replay worker, replay database, historical snapshot provider, strategy engine, portfolio execution, and quant lifecycle manager. Add a new `run_type=live_quant_drill`, run-local `QuantSimDB` state, historical candidate-event generation gates, lifecycle persistence tables, and UI entry/results for drill-specific lifecycle output.

**Tech Stack:** Python replay services, SQLite-backed `QuantSimDB` and `QuantSimReplayDB`, existing `QuantSimEngine`, `PortfolioService`, `QuantUniverseManager`, FastAPI-style gateway functions, React + TypeScript UI, pytest, Vitest.

---

## Source Spec

- `docs/superpowers/specs/2026-05-09-live-quant-drill-design.md`

Implementation must follow the spec as the source of truth. Drill runs must not write live-sim positions, trades, account snapshots, live signals, or live stock-universe lifecycle state.

## File Structure

### Backend

- Modify `app/quant_sim/db.py`
  - Add replay DB schema and CRUD for `sim_run_quant_states`, `sim_run_quant_events`, `sim_run_candidate_events`, `sim_run_quant_summary`.
  - Add run-type metadata helpers if missing.
- Modify `app/quant_sim/replay_service.py`
  - Add `enqueue_live_quant_drill()`.
  - Add live-quant-drill context preparation.
  - Add `LiveQuantDrillMode` or focused helper methods near replay execution.
  - Preserve `enqueue_historical_range()` behavior.
- Modify `app/quant_sim/replay_runner.py`
  - Keep the existing worker runner, but ensure active-run mutual exclusion covers all queued/running replay run types through replay DB.
- Modify `app/quant_sim/quant_universe_lifecycle.py`
  - Add drill-safe candidate scoring option that disables source-count `multi_source_bonus`.
  - Ensure candidate source is only audit/evidence, not a direct score factor.
- Modify `app/quant_sim/engine.py`
  - Ensure drill-created engine reads run-local DB candidate/lifecycle state.
  - Add explicit constructor/adapter parameters only if current construction cannot use run-local DB.
- Modify `app/gateway/live_sim.py`
  - Add `start-drill` action.
  - Parse drill payload and call replay service.
- Modify `app/gateway/his_replay.py`
  - Surface run type in task list/details.
  - Add lifecycle drill summary fields and result sections.
- Modify `app/gateway_api.py`
  - Register `/api/v1/quant/live-sim/actions/start-drill`.
  - Register drill lifecycle table endpoints if implemented outside the page snapshot.
- Create `app/quant_sim/live_quant_drill_candidates.py`
  - Historical candidate source availability gates.
  - Candidate generation frequency and dedup helpers.

### Frontend

- Modify `ui/src/features/quant/live-sim-page.tsx`
  - Add `历史演练` button and configuration dialog.
  - Submit `start-drill` action.
- Modify `ui/src/features/quant/his-replay-page.tsx`
  - Show task type `实时量化演练`.
  - Show drill-specific lifecycle summaries and tables when `runType === "live_quant_drill"`.
- Modify `ui/src/lib/page-models.ts`
  - Add drill fields to replay task/snapshot types.
- Modify `ui/src/lib/api-client.ts`
  - Add `start-drill` action mapping.
- Modify `ui/src/locales/zh-CN.json` and `ui/src/locales/en-US.json`
  - Add new UI strings.

### Tests

- Create `tests/test_live_quant_drill_db.py`
- Create `tests/test_live_quant_drill_candidates.py`
- Create `tests/test_live_quant_drill_service.py`
- Create `tests/test_live_quant_drill_gateway.py`
- Extend `tests/test_quant_universe_lifecycle_manager.py`
- Extend `ui/src/tests/live-sim-page.test.tsx`
- Extend `ui/src/tests/his-replay-page.test.tsx`
- Extend `ui/src/tests/i18n-static.test.ts` only if needed by new strings.

---

## Task 1: Replay DB Schema And CRUD

**Files:**
- Modify: `app/quant_sim/db.py`
- Test: `tests/test_live_quant_drill_db.py`

- [x] **Step 1: Write failing schema tests**

Create `tests/test_live_quant_drill_db.py` with:

```python
from app.quant_sim.db import QuantSimReplayDB


def test_live_quant_drill_tables_are_created(tmp_path):
    db = QuantSimReplayDB(str(tmp_path / "replay.db"))
    with db._connect() as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }

    assert "sim_run_quant_states" in tables
    assert "sim_run_quant_events" in tables
    assert "sim_run_candidate_events" in tables
    assert "sim_run_quant_summary" in tables
```

Add CRUD tests:

```python
def test_live_quant_drill_quant_state_crud(tmp_path):
    db = QuantSimReplayDB(str(tmp_path / "replay.db"))
    run_id = db.create_sim_run(
        mode="live_quant_drill",
        timeframe="30m",
        market="CN",
        start_datetime="2026-01-01 09:30:00",
        end_datetime="2026-01-02 15:00:00",
        initial_cash=100000,
        status="running",
        auto_execute=True,
        handoff_to_live=False,
        progress_current=0,
        progress_total=2,
        status_message="running",
        metadata={"run_type": "live_quant_drill"},
    )

    db.upsert_sim_run_quant_states(
        run_id,
        checkpoint_at="2026-01-01 09:30:00",
        checkpoint_at_utc="2026-01-01T01:30:00Z",
        states=[
            {
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "market": "CN",
                "quant_enabled": True,
                "quant_status": "trial",
                "health_score": 88.0,
                "candidate_score": 0.72,
                "latest_reason": "auto_trial",
                "snapshot_json": {"reason_code": "auto_trial"},
            }
        ],
    )

    rows = db.list_sim_run_quant_states(run_id, status="trial")
    assert rows["total"] == 1
    assert rows["items"][0]["stock_code"] == "600519"
    assert rows["items"][0]["snapshot_json"]["reason_code"] == "auto_trial"
```

- [x] **Step 2: Run tests and confirm failure**

Run:

```powershell
pytest tests/test_live_quant_drill_db.py -q
```

Expected: fails because tables and methods do not exist.

- [x] **Step 3: Add replay schema**

In `QuantSimReplayDB` schema initialization, create:

- `sim_run_quant_states`
- `sim_run_quant_events`
- `sim_run_candidate_events`
- `sim_run_quant_summary`

Use the exact fields from the spec. Add indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_sim_run_quant_states_run_status
ON sim_run_quant_states(run_id, quant_status, checkpoint_at_utc);

CREATE INDEX IF NOT EXISTS idx_sim_run_quant_events_run_status
ON sim_run_quant_events(run_id, to_status, checkpoint_at_utc);

CREATE INDEX IF NOT EXISTS idx_sim_run_candidate_events_run_stock
ON sim_run_candidate_events(run_id, stock_code, source_type, checkpoint_at_utc);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sim_run_quant_summary_run_checkpoint
ON sim_run_quant_summary(run_id, checkpoint_at_utc);
```

- [x] **Step 4: Add CRUD methods**

Add these methods on `QuantSimReplayDB`:

- `upsert_sim_run_quant_states(run_id, *, checkpoint_at, checkpoint_at_utc, states) -> None`
  - Insert or replace one checkpoint's quant-state rows.
  - JSON-encode `snapshot_json`.
- `list_sim_run_quant_states(run_id, *, checkpoint_at=None, status=None, stock="", page=1, page_size=50) -> dict`
  - Return `{items, total, page, page_size}`.
  - Decode `snapshot_json`.
- `add_sim_run_quant_events(run_id, events) -> None`
  - Bulk insert lifecycle transition events.
  - JSON-encode `reason_json` and `evidence_json`.
- `list_sim_run_quant_events(run_id, *, event_type="", from_status="", to_status="", stock="", page=1, page_size=50) -> dict`
  - Return paged lifecycle event rows.
- `add_sim_run_candidate_events(run_id, events) -> None`
  - Bulk insert historical candidate events.
  - Use `status='new'` unless the caller provides a stricter status.
- `mark_sim_run_candidate_events_consumed(run_id, *, stock_code, source_type=None, checkpoint_at_utc_lte=None) -> int`
  - Update matching rows to `status='consumed'`.
  - Return affected row count.
- `upsert_sim_run_quant_summary(run_id, summary) -> None`
  - Upsert by `(run_id, checkpoint_at_utc)`.
  - JSON-encode `metadata_json`.
- `list_sim_run_quant_summary(run_id) -> list[dict]`
  - Return checkpoint summaries ordered by `checkpoint_at_utc`.

Represent consumed candidate events with `status='consumed'`; do not add `consumed_by_quant_manager_at` to the drill table.

- [x] **Step 5: Run schema tests**

Run:

```powershell
pytest tests/test_live_quant_drill_db.py -q
```

Expected: pass.

- [x] **Step 6: Commit**

```powershell
git add app/quant_sim/db.py tests/test_live_quant_drill_db.py
git commit -m "feat: add live quant drill replay storage"
```

---

## Task 2: Candidate Source Availability And Frequency

**Files:**
- Create: `app/quant_sim/live_quant_drill_candidates.py`
- Test: `tests/test_live_quant_drill_candidates.py`

- [x] **Step 1: Write failing tests for source availability gates**

Create `tests/test_live_quant_drill_candidates.py`:

```python
from datetime import datetime

from app.quant_sim.live_quant_drill_candidates import (
    CandidateGenerationConfig,
    CandidateSourceAvailability,
    should_skip_candidate_event_due_to_dedup,
    should_generate_candidates,
    source_availability_for_checkpoint,
)


def test_current_ai_and_current_discover_are_not_historical_sources():
    availability = source_availability_for_checkpoint(
        source_type="current_ai_analysis",
        checkpoint=datetime(2026, 1, 5, 9, 30),
        available_fields={"generated_at": "2026-05-09T00:00:00Z"},
    )
    assert availability == CandidateSourceAvailability.DISABLED

    availability = source_availability_for_checkpoint(
        source_type="current_discover_result",
        checkpoint=datetime(2026, 1, 5, 9, 30),
        available_fields={},
    )
    assert availability == CandidateSourceAvailability.DISABLED


def test_low_price_can_generate_when_historical_market_fields_exist():
    availability = source_availability_for_checkpoint(
        source_type="low_price",
        checkpoint=datetime(2026, 1, 5, 9, 30),
        available_fields={"ohlcv": True, "price": True, "volume": True},
    )
    assert availability == CandidateSourceAvailability.ENABLED


def test_spec_candidate_source_matrix_is_enforced():
    checkpoint = datetime(2026, 1, 5, 9, 30)
    cases = [
        ("low_price", {"ohlcv": True, "price": True, "volume": True}, CandidateSourceAvailability.ENABLED),
        ("small_cap", {"as_of_fundamental": True}, CandidateSourceAvailability.ENABLED),
        ("low_valuation", {"as_of_fundamental": True}, CandidateSourceAvailability.ENABLED),
        ("profit_growth", {"as_of_financial_report": True}, CandidateSourceAvailability.ENABLED),
        ("main_force", {"historical_capital_flow": True}, CandidateSourceAvailability.ENABLED),
        ("historical_research", {"occurred_at": "2026-01-04T10:00:00Z"}, CandidateSourceAvailability.CONDITIONAL),
        ("manual_seed", {}, CandidateSourceAvailability.ENABLED),
        ("current_ai_analysis", {"generated_at": "2026-05-09T00:00:00Z"}, CandidateSourceAvailability.DISABLED),
        ("current_discover_result", {}, CandidateSourceAvailability.DISABLED),
        ("small_cap", {"as_of_fundamental": False}, CandidateSourceAvailability.DISABLED),
        ("main_force", {"historical_capital_flow": False}, CandidateSourceAvailability.DISABLED),
    ]

    for source_type, fields, expected in cases:
        assert source_availability_for_checkpoint(
            source_type=source_type,
            checkpoint=checkpoint,
            available_fields=fields,
        ) == expected
```

Add frequency tests:

```python
def test_daily_first_checkpoint_only_generates_once_per_trading_day():
    config = CandidateGenerationConfig(frequency="daily_first_checkpoint", checkpoint_interval=8)
    checkpoints = [
        datetime(2026, 1, 5, 9, 30),
        datetime(2026, 1, 5, 10, 0),
        datetime(2026, 1, 6, 9, 30),
    ]

    assert should_generate_candidates(config, checkpoints, 0) is True
    assert should_generate_candidates(config, checkpoints, 1) is False
    assert should_generate_candidates(config, checkpoints, 2) is True


def test_every_n_checkpoints_respects_min_interval():
    config = CandidateGenerationConfig(frequency="every_n_checkpoints", checkpoint_interval=3)
    checkpoints = [datetime(2026, 1, 5, 9, 30 + i) for i in range(6)]

    assert [should_generate_candidates(config, checkpoints, i) for i in range(6)] == [
        True,
        False,
        False,
        True,
        False,
        False,
    ]


def test_candidate_event_dedup_skips_recent_unconsumed_same_source_event():
    config = CandidateGenerationConfig(candidate_event_dedup_days=5)
    should_skip = should_skip_candidate_event_due_to_dedup(
        config=config,
        stock_code="600519",
        source_type="low_price",
        checkpoint=datetime(2026, 1, 6, 9, 30),
        previous_events=[
            {
                "stock_code": "600519",
                "source_type": "low_price",
                "checkpoint_at": "2026-01-03 09:30:00",
                "status": "new",
            }
        ],
    )
    assert should_skip is True
```

- [x] **Step 2: Run tests and confirm failure**

```powershell
pytest tests/test_live_quant_drill_candidates.py -q
```

Expected: fails because module does not exist.

- [x] **Step 3: Implement availability and frequency helpers**

Create `app/quant_sim/live_quant_drill_candidates.py` with:

```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class CandidateSourceAvailability(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    CONDITIONAL = "conditional"


@dataclass(frozen=True)
class CandidateGenerationConfig:
    frequency: str = "daily_first_checkpoint"
    checkpoint_interval: int = 8
    candidate_event_dedup_days: int = 5
    confirm_long_running: bool = False


def source_availability_for_checkpoint(
    *,
    source_type: str,
    checkpoint: datetime,
    available_fields: dict[str, Any],
) -> CandidateSourceAvailability:
    source = str(source_type or "").strip().lower()
    if source in {"current_ai_analysis", "current_discover_result", "current_research_summary"}:
        return CandidateSourceAvailability.DISABLED
    if source == "low_price":
        return CandidateSourceAvailability.ENABLED if all(available_fields.get(key) for key in ("ohlcv", "price", "volume")) else CandidateSourceAvailability.DISABLED
    if source in {"small_cap", "low_valuation"}:
        return CandidateSourceAvailability.ENABLED if bool(available_fields.get("as_of_fundamental")) else CandidateSourceAvailability.DISABLED
    if source == "profit_growth":
        return CandidateSourceAvailability.ENABLED if bool(available_fields.get("as_of_financial_report")) else CandidateSourceAvailability.DISABLED
    if source == "main_force":
        return CandidateSourceAvailability.ENABLED if bool(available_fields.get("historical_capital_flow")) else CandidateSourceAvailability.DISABLED
    if source == "historical_research":
        occurred_at = available_fields.get("occurred_at")
        if not occurred_at:
            return CandidateSourceAvailability.DISABLED
        return CandidateSourceAvailability.CONDITIONAL
    if source == "manual_seed":
        return CandidateSourceAvailability.ENABLED
    return CandidateSourceAvailability.DISABLED


def should_generate_candidates(
    config: CandidateGenerationConfig,
    checkpoints: list[datetime],
    index: int,
) -> bool:
    if index < 0 or index >= len(checkpoints):
        return False
    frequency = str(config.frequency or "daily_first_checkpoint")
    if frequency == "every_n_checkpoints":
        interval = max(2, int(config.checkpoint_interval or 8))
        return index % interval == 0
    current = checkpoints[index]
    if index == 0:
        return True
    previous = checkpoints[index - 1]
    return current.date() != previous.date()


def should_skip_candidate_event_due_to_dedup(
    *,
    config: CandidateGenerationConfig,
    stock_code: str,
    source_type: str,
    checkpoint: datetime,
    previous_events: list[dict[str, Any]],
) -> bool:
    window_days = max(0, int(config.candidate_event_dedup_days or 0))
    if window_days <= 0:
        return False
    for event in previous_events:
        if event.get("stock_code") != stock_code:
            continue
        if event.get("source_type") != source_type:
            continue
        if str(event.get("status") or "new") == "consumed":
            continue
        occurred_at = datetime.fromisoformat(str(event["checkpoint_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
        if 0 <= (checkpoint - occurred_at).days < window_days:
            return True
    return False
```

- [x] **Step 4: Add runtime estimate helper**

Add:

```python
def estimate_candidate_generation(
    *,
    checkpoints: list[datetime],
    config: CandidateGenerationConfig,
    enabled_sources: list[str],
) -> dict[str, int | list[str]]:
    generation_runs = sum(1 for index in range(len(checkpoints)) if should_generate_candidates(config, checkpoints, index))
    sources = [source for source in enabled_sources if source]
    return {
        "estimated_candidate_generation_runs": generation_runs,
        "enabled_candidate_sources": sources,
        "estimated_strategy_invocations": generation_runs * len(sources),
    }
```

- [x] **Step 5: Run candidate tests**

```powershell
pytest tests/test_live_quant_drill_candidates.py -q
```

Expected: pass.

- [x] **Step 6: Commit**

```powershell
git add app/quant_sim/live_quant_drill_candidates.py tests/test_live_quant_drill_candidates.py
git commit -m "feat: add live drill candidate generation gates"
```

---

## Task 3: Drill-Safe Candidate Scoring

**Files:**
- Modify: `app/quant_sim/quant_universe_lifecycle.py`
- Test: `tests/test_quant_universe_lifecycle_manager.py`

- [x] **Step 1: Add failing test that drill ignores source-count bonus**

Append to lifecycle manager tests:

```python
from app.quant_sim.quant_universe_lifecycle import QuantUniverseLifecyclePolicy, calculate_candidate_score


def test_live_quant_drill_candidate_score_does_not_use_source_count_bonus():
    policy = QuantUniverseLifecyclePolicy.stable_defaults()
    single_result = calculate_candidate_score(
        [{"source_type": "low_price", "source_score": 0.8, "confidence": 0.7, "trend": "up"}],
        {"is_liquid": True},
        policy,
        drill_mode=True,
    )
    multi_result = calculate_candidate_score(
        [
            {"source_type": "low_price", "source_score": 0.8, "confidence": 0.7, "trend": "up"},
            {"source_type": "main_force", "source_score": 0.8, "confidence": 0.7, "trend": "up"},
        ],
        {"is_liquid": True},
        policy,
        drill_mode=True,
    )

    assert single_result["candidate_score"] == multi_result["candidate_score"]
    assert multi_result["breakdown"]["multi_source_bonus"] == 0.0
```

- [x] **Step 2: Run targeted test and confirm failure**

```powershell
pytest tests/test_quant_universe_lifecycle_manager.py::test_live_quant_drill_candidate_score_does_not_use_source_count_bonus -q
```

Expected: fails because scoring lacks `drill_mode` or still applies source-count bonus.

- [x] **Step 3: Add drill-mode scoring behavior**

Update `calculate_candidate_score()` or the equivalent scoring helper by threading a `drill_mode: bool = False` parameter through the existing call path and replacing only the source-count branch:

```python
if drill_mode or source_count < 2:
    multi_source_bonus = 0.0
else:
    multi_source_bonus = 1.0
```

Rules:

- `source_type` remains in `evidence_json` and event payloads.
- Source count cannot directly increase `candidate_score` when `drill_mode=True`.
- Historical indicator confluence may still score if represented as explicit metrics, not source count.

- [x] **Step 4: Run lifecycle tests**

```powershell
pytest tests/test_quant_universe_lifecycle_manager.py -q
```

Expected: pass.

- [x] **Step 5: Commit**

```powershell
git add app/quant_sim/quant_universe_lifecycle.py tests/test_quant_universe_lifecycle_manager.py
git commit -m "fix: disable source-count candidate bonus in drill mode"
```

---

## Task 4: Live Quant Drill Context And Run Creation

**Files:**
- Modify: `app/quant_sim/replay_service.py`
- Test: `tests/test_live_quant_drill_service.py`

- [x] **Step 1: Write failing service tests for drill run creation**

Create `tests/test_live_quant_drill_service.py`:

```python
from datetime import datetime

import pytest

from app.quant_sim.db import QuantSimDB, QuantSimReplayDB
from app.quant_sim.replay_service import QuantSimReplayService


def test_enqueue_live_quant_drill_creates_run_with_metadata(tmp_path):
    live_db_file = tmp_path / "live.db"
    replay_db_file = tmp_path / "replay.db"
    live_db = QuantSimDB(str(live_db_file))
    live_db.add_watch("600519", "贵州茅台", quant_enabled=True)
    live_db.upsert_quant_universe_state("600519", {"quant_status": "active", "health_score": 91.0})

    service = QuantSimReplayService(db_file=str(live_db_file), replay_db_file=str(replay_db_file))
    run_id = service.enqueue_live_quant_drill(
        start_datetime=datetime(2026, 1, 1, 9, 30),
        end_datetime=datetime(2026, 1, 2, 15, 0),
        timeframe="30m",
        market="CN",
        initial_cash=100000,
        seed_current_quant_universe=True,
        generate_historical_candidate_events=True,
        auto_entry_enabled=True,
        auto_exit_enabled=True,
        execute_trades=True,
        liquidate_at_end=True,
    )

    replay_db = QuantSimReplayDB(str(replay_db_file))
    run = replay_db.get_sim_run(run_id)
    assert run["mode"] == "live_quant_drill"
    assert run["metadata"]["run_type"] == "live_quant_drill"
    assert run["metadata"]["seed_current_quant_universe"] is True
    assert run["metadata"]["generate_historical_candidate_events"] is True
    assert run["metadata"]["initial_quant_universe_snapshot"][0]["stock_code"] == "600519"
    assert "strategy_profile_snapshot" in run["metadata"]
```

Add validation test:

```python
def test_live_quant_drill_requires_at_least_one_stock_source(tmp_path):
    service = QuantSimReplayService(db_file=str(tmp_path / "live.db"), replay_db_file=str(tmp_path / "replay.db"))

    with pytest.raises(ValueError, match="No quant universe source selected"):
        service.enqueue_live_quant_drill(
            start_datetime=datetime(2026, 1, 1, 9, 30),
            end_datetime=datetime(2026, 1, 2, 15, 0),
            timeframe="30m",
            market="CN",
            seed_current_quant_universe=False,
            generate_historical_candidate_events=False,
        )


def test_live_quant_drill_requires_confirmation_for_large_candidate_generation(tmp_path, monkeypatch):
    live_db_file = tmp_path / "live.db"
    replay_db_file = tmp_path / "replay.db"
    live_db = QuantSimDB(str(live_db_file))
    live_db.add_watch("600519", "贵州茅台", quant_enabled=True)
    service = QuantSimReplayService(db_file=str(live_db_file), replay_db_file=str(replay_db_file))

    monkeypatch.setattr(
        "app.quant_sim.replay_service.estimate_candidate_generation",
        lambda **kwargs: {
            "estimated_candidate_generation_runs": 1001,
            "enabled_candidate_sources": ["low_price", "main_force", "profit_growth"],
            "estimated_strategy_invocations": 3003,
        },
    )

    with pytest.raises(ValueError, match="Long running drill requires confirmation"):
        service.enqueue_live_quant_drill(
            start_datetime=datetime(2026, 1, 1, 9, 30),
            end_datetime=datetime(2026, 5, 1, 15, 0),
            timeframe="30m",
            market="CN",
            confirm_long_running=False,
        )

    run_id = service.enqueue_live_quant_drill(
        start_datetime=datetime(2026, 1, 1, 9, 30),
        end_datetime=datetime(2026, 5, 1, 15, 0),
        timeframe="30m",
        market="CN",
        confirm_long_running=True,
    )
    assert run_id > 0


def test_live_quant_drill_is_blocked_by_running_historical_backtest(tmp_path):
    live_db_file = tmp_path / "live.db"
    replay_db_file = tmp_path / "replay.db"
    replay_db = QuantSimReplayDB(str(replay_db_file))
    replay_db.create_sim_run(
        mode="historical_backtest",
        timeframe="30m",
        market="CN",
        start_datetime="2026-01-01 09:30:00",
        end_datetime="2026-01-02 15:00:00",
        initial_cash=100000,
        status="running",
        auto_execute=True,
        handoff_to_live=False,
        progress_current=1,
        progress_total=2,
        status_message="running",
        metadata={"run_type": "historical_backtest"},
    )

    live_db = QuantSimDB(str(live_db_file))
    live_db.add_watch("600519", "贵州茅台", quant_enabled=True)
    service = QuantSimReplayService(db_file=str(live_db_file), replay_db_file=str(replay_db_file))

    with pytest.raises(RuntimeError, match="active replay"):
        service.enqueue_live_quant_drill(
            start_datetime=datetime(2026, 1, 1, 9, 30),
            end_datetime=datetime(2026, 1, 2, 15, 0),
            timeframe="30m",
            market="CN",
        )
```

- [x] **Step 2: Run tests and confirm failure**

```powershell
pytest tests/test_live_quant_drill_service.py -q
```

Expected: fails because `enqueue_live_quant_drill()` does not exist.

- [x] **Step 3: Add public service method**

In `QuantSimReplayService`, add:

```python
def enqueue_live_quant_drill(
    self,
    *,
    start_datetime: datetime | str,
    end_datetime: datetime | str | None,
    timeframe: str,
    market: str,
    strategy_profile_id: str | None = None,
    initial_cash: float | None = None,
    ai_dynamic_strategy: str = DEFAULT_AI_DYNAMIC_STRATEGY,
    ai_dynamic_strength: float = DEFAULT_AI_DYNAMIC_STRENGTH,
    ai_dynamic_lookback: int = DEFAULT_AI_DYNAMIC_LOOKBACK,
    auto_entry_enabled: bool = True,
    auto_exit_enabled: bool = True,
    execute_trades: bool = True,
    liquidate_at_end: bool = True,
    seed_current_quant_universe: bool = True,
    generate_historical_candidate_events: bool = True,
    candidate_generation_frequency: str = "daily_first_checkpoint",
    candidate_generation_checkpoint_interval: int = 8,
    confirm_long_running: bool = False,
) -> int:
```

It must:

- Call `_ensure_no_active_replay()` and ensure it treats queued/running `historical_backtest` and `live_quant_drill` as mutually exclusive.
- Validate at least one source is enabled.
- Resolve checkpoints.
- Build initial quant universe snapshot from live DB.
- Lock strategy profile binding and full snapshot.
- Estimate candidate generation runs.
- Reject `estimated_strategy_invocations > 3000` unless `confirm_long_running=True`.
- Create `sim_runs` row with `mode="live_quant_drill"` and metadata `run_type="live_quant_drill"`.
- Start replay worker with a new worker target, not historical `_execute_prepared_replay()` directly.

- [x] **Step 4: Add context builder**

Add helper:

```python
def _prepare_live_quant_drill_context(
    self,
    *,
    start_datetime: datetime | str,
    end_datetime: datetime | str | None,
    timeframe: str,
    market: str,
    strategy_profile_id: str | None,
    initial_cash: float | None,
    ai_dynamic_strategy: str,
    ai_dynamic_strength: float,
    ai_dynamic_lookback: int,
    auto_entry_enabled: bool,
    auto_exit_enabled: bool,
    execute_trades: bool,
    liquidate_at_end: bool,
    seed_current_quant_universe: bool,
    generate_historical_candidate_events: bool,
    candidate_generation_frequency: str,
    candidate_generation_checkpoint_interval: int,
) -> dict:
    return context
```

Context must contain:

- `start_dt`
- `end_dt`
- `timeframe`
- `market`
- `checkpoints`
- `account_summary`
- `scheduler_config`
- `strategy_profile_binding`
- `initial_quant_universe_snapshot`
- `lifecycle_settings_snapshot`
- `candidate_generation`
- `auto_entry_enabled`
- `auto_exit_enabled`
- `execute_trades`
- `liquidate_at_end`

- [x] **Step 5: Run service tests**

```powershell
pytest tests/test_live_quant_drill_service.py -q
```

Expected: run creation tests pass. Worker execution can still fail in follow-up execution tests if the worker target is not implemented; this task should use a test-safe runner injection or synchronous mode only for metadata tests.

- [x] **Step 6: Commit**

```powershell
git add app/quant_sim/replay_service.py tests/test_live_quant_drill_service.py
git commit -m "feat: create live quant drill replay runs"
```

---

## Task 5: Run-Local Database Initialization

**Files:**
- Modify: `app/quant_sim/replay_service.py`
- Test: `tests/test_live_quant_drill_service.py`

- [x] **Step 1: Add failing test for run-local DB initialization**

Add:

```python
def test_live_quant_drill_initializes_run_local_quant_state(tmp_path):
    live_db_file = tmp_path / "live.db"
    live_db = QuantSimDB(str(live_db_file))
    live_db.add_watch("600519", "贵州茅台", quant_enabled=True)
    live_db.upsert_quant_universe_state("600519", {"quant_status": "active", "health_score": 91.0})

    service = QuantSimReplayService(db_file=str(live_db_file), replay_db_file=str(tmp_path / "replay.db"))
    context = service._prepare_live_quant_drill_context(
        start_datetime=datetime(2026, 1, 1, 9, 30),
        end_datetime=datetime(2026, 1, 2, 15, 0),
        timeframe="30m",
        market="CN",
        seed_current_quant_universe=True,
        generate_historical_candidate_events=False,
    )
    temp_db = service._create_live_quant_drill_temp_db(context, tmp_path / "temp.db")

    state = temp_db.get_quant_universe_state("600519")
    candidate = temp_db.get_candidate("600519")
    assert state["quant_status"] == "active"
    assert state["health_score"] == 91.0
    assert candidate["stock_code"] == "600519"
```

- [x] **Step 2: Run targeted test and confirm failure**

```powershell
pytest tests/test_live_quant_drill_service.py::test_live_quant_drill_initializes_run_local_quant_state -q
```

Expected: fails because temp DB initializer does not exist.

- [x] **Step 3: Implement temp DB initializer**

Add:

```python
def _create_live_quant_drill_temp_db(self, context: dict, temp_db_file: str | Path) -> QuantSimDB:
    temp_db = QuantSimDB(temp_db_file)
    temp_db.reset_account(initial_cash=float(context["account_summary"]["initial_cash"]))
    temp_db.update_scheduler_config(
        enabled=False,
        interval_minutes=int(context["scheduler_config"].get("interval_minutes", 10)),
        strategy_profile_id=context["strategy_profile_binding"]["profile_id"],
    )
    for row in context["initial_quant_universe_snapshot"]:
        temp_db.add_watch(
            row["stock_code"],
            row.get("stock_name") or row["stock_code"],
            quant_enabled=bool(row.get("quant_enabled", True)),
        )
        temp_db.upsert_quant_universe_state(
            row["stock_code"],
            quant_status=row["quant_status"],
            health_score=float(row.get("health_score", 100.0)),
            candidate_score=row.get("candidate_score"),
            latest_reason=row.get("latest_reason") or "seed_current_quant_universe",
        )
    return temp_db
```

Rules:

- Do not use live DB for subsequent engine reads.
- Preserve `trial / active / exit_only / cooling / retired / manual_paused` in run-local state.
- Only `trial / active / exit_only` should be in main scan.

- [x] **Step 4: Run service tests**

```powershell
pytest tests/test_live_quant_drill_service.py -q
```

Expected: pass for context and initialization tests.

- [x] **Step 5: Commit**

```powershell
git add app/quant_sim/replay_service.py tests/test_live_quant_drill_service.py
git commit -m "feat: initialize run-local live drill state"
```

---

## Task 6: LiveQuantDrillMode Checkpoint Execution

**Files:**
- Modify: `app/quant_sim/replay_service.py`
- Modify: `app/quant_sim/engine.py` if needed for run-local candidate reads
- Test: `tests/test_live_quant_drill_service.py`

- [x] **Step 1: Add failing integration-style test for no live writes**

Add:

```python
def test_live_quant_drill_execution_does_not_write_live_account(tmp_path):
    live_db_file = tmp_path / "live.db"
    replay_db_file = tmp_path / "replay.db"
    live_db = QuantSimDB(str(live_db_file))
    live_db.reset_account(initial_cash=50000)
    live_db.add_watch("600519", "贵州茅台", quant_enabled=True)
    live_db.upsert_quant_universe_state("600519", {"quant_status": "active", "health_score": 85.0})
    before = live_db.get_account_summary()

    service = QuantSimReplayService(db_file=str(live_db_file), replay_db_file=str(replay_db_file))
    result = service.run_live_quant_drill(
        start_datetime=datetime(2026, 1, 1, 9, 30),
        end_datetime=datetime(2026, 1, 1, 10, 0),
        timeframe="30m",
        market="CN",
        initial_cash=50000,
        seed_current_quant_universe=True,
        generate_historical_candidate_events=False,
        execute_trades=True,
    )

    after = live_db.get_account_summary()
    assert result["run_id"] > 0
    assert after["available_cash"] == before["available_cash"]
    assert after["total_equity"] == before["total_equity"]
```

Add:

```python
def test_live_quant_drill_runs_cooling_opportunistic_review_after_main_scan(tmp_path, monkeypatch):
    service = QuantSimReplayService(db_file=str(tmp_path / "live.db"), replay_db_file=str(tmp_path / "replay.db"))
    call_order: list[str] = []

    def fake_main_scan(*args, **kwargs):
        call_order.append("main_scan")
        return {"signals": []}

    def fake_cooling_review(*args, **kwargs):
        call_order.append("cooling_review")
        return {"reviewed": 2, "restored": 1}

    monkeypatch.setattr(service, "_run_live_quant_drill_main_scan", fake_main_scan)
    monkeypatch.setattr(service, "_run_live_quant_drill_cooling_review", fake_cooling_review)

    service._run_live_quant_drill_checkpoint(
        run_id=1,
        checkpoint=datetime(2026, 1, 5, 10, 0),
        checkpoint_index=1,
        context={"checkpoints": [datetime(2026, 1, 5, 10, 0)]},
        temp_db=QuantSimDB(str(tmp_path / "temp.db")),
        engine=object(),
        portfolio=object(),
        manager=object(),
    )

    assert call_order == ["main_scan", "cooling_review"]
```

- [x] **Step 2: Run test and confirm failure**

```powershell
pytest tests/test_live_quant_drill_service.py::test_live_quant_drill_execution_does_not_write_live_account -q
```

Expected: fails because execution mode does not exist.

- [x] **Step 3: Add synchronous execution entry for tests**

Add:

```python
def run_live_quant_drill(
    self,
    *,
    start_datetime: datetime | str,
    end_datetime: datetime | str | None,
    timeframe: str,
    market: str,
    strategy_profile_id: str | None = None,
    initial_cash: float | None = None,
    execute_trades: bool = True,
    liquidate_at_end: bool = True,
    seed_current_quant_universe: bool = True,
    generate_historical_candidate_events: bool = True,
    candidate_generation_frequency: str = "daily_first_checkpoint",
    candidate_generation_checkpoint_interval: int = 8,
) -> dict:
    context = self._prepare_live_quant_drill_context(
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        timeframe=timeframe,
        market=market,
        strategy_profile_id=strategy_profile_id,
        initial_cash=initial_cash,
        ai_dynamic_strategy=DEFAULT_AI_DYNAMIC_STRATEGY,
        ai_dynamic_strength=DEFAULT_AI_DYNAMIC_STRENGTH,
        ai_dynamic_lookback=DEFAULT_AI_DYNAMIC_LOOKBACK,
        auto_entry_enabled=True,
        auto_exit_enabled=True,
        execute_trades=execute_trades,
        liquidate_at_end=liquidate_at_end,
        seed_current_quant_universe=seed_current_quant_universe,
        generate_historical_candidate_events=generate_historical_candidate_events,
        candidate_generation_frequency=candidate_generation_frequency,
        candidate_generation_checkpoint_interval=candidate_generation_checkpoint_interval,
    )
    run_id = self._create_replay_run_from_context(context)
    return self._execute_live_quant_drill(run_id=run_id, context=context)
```

- [x] **Step 4: Implement `_execute_live_quant_drill()` skeleton**

Required order:

1. Create temp DB in worker temp dir.
2. Construct run-local services:
   - `QuantSimEngine(db_file=temp_db_file, stock_analysis_db_file=self.stock_analysis_db_file)`
   - `PortfolioService(db_file=temp_db_file)`
   - `SignalCenterService(db=temp_db or db_file=temp_db_file)`
   - `QuantUniverseManager(db=temp_db, profile_id=locked_profile_id, policy=locked_policy)`
3. Loop checkpoints.
4. For each checkpoint, call drill checkpoint helper.
5. Persist replay signals/trades/snapshots/positions.
6. Finalize run.
7. Delete temp dir in `finally`.

- [x] **Step 5: Add checkpoint helper**

Add:

```python
def _run_live_quant_drill_checkpoint(
    self,
    *,
    run_id: int,
    checkpoint: datetime,
    checkpoint_index: int,
    context: dict,
    temp_db: QuantSimDB,
    engine: QuantSimEngine,
    portfolio: PortfolioService,
    manager: QuantUniverseManager,
) -> dict:
    return checkpoint_result
```

It must:

- Apply due corporate actions.
- Generate candidates only when frequency matches.
- Process auto-entry before scan.
- Scan `trial / active / exit_only`.
- Execute trades only if `execute_trades=True`.
- Update lifecycle after execution.
- Run `cooling` opportunistic review after the main scan and lifecycle update.
- Bound opportunistic review by the lifecycle policy, never allowing cooling stocks to replace the main `trial / active / exit_only` scan.
- Save quant states/events/candidate events/summary.

- [x] **Step 6: Run targeted tests**

```powershell
pytest tests/test_live_quant_drill_service.py -q
```

Expected: all current drill service tests pass.

- [x] **Step 7: Commit**

```powershell
git add app/quant_sim/replay_service.py app/quant_sim/engine.py tests/test_live_quant_drill_service.py
git commit -m "feat: execute live quant drill in run-local state"
```

---

## Task 7: Candidate Events In Drill Checkpoints

**Files:**
- Modify: `app/quant_sim/replay_service.py`
- Modify: `app/quant_sim/live_quant_drill_candidates.py`
- Test: `tests/test_live_quant_drill_service.py`

- [x] **Step 1: Add failing test for same-checkpoint trial visibility**

Add:

```python
def test_live_quant_drill_new_trial_is_scanned_in_same_checkpoint(tmp_path, monkeypatch):
    service = QuantSimReplayService(db_file=str(tmp_path / "live.db"), replay_db_file=str(tmp_path / "replay.db"))
    scanned_codes = []

    def fake_generate(*args, **kwargs):
        return [
            {
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "source_type": "low_price",
                "source_key": "low_price:2026-01-01",
                "candidate_score": 0.95,
                "confidence": 0.90,
                "status": "active",
                "reason_text": "historical low price candidate",
                "evidence_json": {"price_structure": "strong"},
            }
        ]

    monkeypatch.setattr(service, "_generate_live_quant_drill_candidate_events", fake_generate)
    monkeypatch.setattr(service, "_evaluate_drill_candidate", lambda candidate, *args, **kwargs: scanned_codes.append(candidate["stock_code"]))

    service.run_live_quant_drill(
        start_datetime=datetime(2026, 1, 1, 9, 30),
        end_datetime=datetime(2026, 1, 1, 9, 30),
        timeframe="30m",
        market="CN",
        seed_current_quant_universe=False,
        generate_historical_candidate_events=True,
        execute_trades=False,
    )

    assert "600519" in scanned_codes
```

- [x] **Step 2: Run test and confirm failure**

```powershell
pytest tests/test_live_quant_drill_service.py::test_live_quant_drill_new_trial_is_scanned_in_same_checkpoint -q
```

Expected: fails until candidate events are promoted before scan and visible in run-local DB.

- [x] **Step 3: Implement candidate event generation hook**

Add `_generate_live_quant_drill_candidate_events()`:

```python
def _generate_live_quant_drill_candidate_events(
    self,
    *,
    checkpoint: datetime,
    context: dict,
    temp_db: QuantSimDB,
) -> list[dict]:
    return candidate_events
```

Initial implementation can support:

- manual seed already initialized
- `low_price` historical source when local historical data exists
- disabled source tracking for unsupported historical sources

Unsupported sources must append to `context["disabled_candidate_sources"]`.

- [x] **Step 4: Mark consumed events**

When manager promotes a candidate to `trial`:

- Write candidate event to `sim_run_candidate_events`.
- Update run-local candidate event state to consumed.
- Call `mark_sim_run_candidate_events_consumed()` on replay DB for persisted event rows.

- [x] **Step 5: Run service tests**

```powershell
pytest tests/test_live_quant_drill_service.py -q
```

Expected: pass.

- [x] **Step 6: Commit**

```powershell
git add app/quant_sim/replay_service.py app/quant_sim/live_quant_drill_candidates.py tests/test_live_quant_drill_service.py
git commit -m "feat: generate drill candidate events before scanning"
```

---

## Task 8: Lifecycle Persistence And Summary

**Files:**
- Modify: `app/quant_sim/replay_service.py`
- Test: `tests/test_live_quant_drill_service.py`

- [x] **Step 1: Add failing test for quant summary persistence**

Add:

```python
def test_live_quant_drill_persists_quant_summary(tmp_path):
    live_db_file = tmp_path / "live.db"
    replay_db_file = tmp_path / "replay.db"
    live_db = QuantSimDB(str(live_db_file))
    live_db.add_watch("600519", "贵州茅台", quant_enabled=True)
    live_db.upsert_quant_universe_state("600519", {"quant_status": "active", "health_score": 85.0})

    service = QuantSimReplayService(db_file=str(live_db_file), replay_db_file=str(replay_db_file))
    result = service.run_live_quant_drill(
        start_datetime=datetime(2026, 1, 1, 9, 30),
        end_datetime=datetime(2026, 1, 1, 10, 0),
        timeframe="30m",
        market="CN",
        seed_current_quant_universe=True,
        generate_historical_candidate_events=False,
        execute_trades=False,
    )

    replay_db = QuantSimReplayDB(str(replay_db_file))
    summary = replay_db.list_sim_run_quant_summary(result["run_id"])
    states = replay_db.list_sim_run_quant_states(result["run_id"])
    assert len(summary) >= 1
    assert states["total"] >= 1
    assert summary[0]["active_count"] >= 1
```

- [x] **Step 2: Run test and confirm failure**

```powershell
pytest tests/test_live_quant_drill_service.py::test_live_quant_drill_persists_quant_summary -q
```

Expected: fails until persistence is implemented.

- [x] **Step 3: Persist checkpoint quant state**

After lifecycle evaluation each checkpoint, collect all run-local quant states and write:

- `sim_run_quant_states`
- `sim_run_quant_events`
- `sim_run_candidate_events`
- `sim_run_quant_summary`

Summary counts must include:

- `inactive_count`
- `trial_count`
- `active_count`
- `exit_only_count`
- `cooling_count`
- `retired_count`
- `manual_paused_count`
- `candidate_event_count`
- `auto_promoted_count`
- `auto_exited_count`

- [x] **Step 4: Run drill service tests**

```powershell
pytest tests/test_live_quant_drill_service.py -q
```

Expected: pass.

- [x] **Step 5: Commit**

```powershell
git add app/quant_sim/replay_service.py tests/test_live_quant_drill_service.py
git commit -m "feat: persist live drill lifecycle results"
```

---

## Task 9: Gateway APIs

**Files:**
- Modify: `app/gateway/live_sim.py`
- Modify: `app/gateway/his_replay.py`
- Modify: `app/gateway_api.py`
- Test: `tests/test_live_quant_drill_gateway.py`

- [ ] **Step 1: Write failing gateway tests**

Create `tests/test_live_quant_drill_gateway.py`:

```python
from app.gateway.live_sim import _action_live_sim_start_drill


class FakeReplayService:
    def __init__(self):
        self.payload = None

    def enqueue_live_quant_drill(self, **kwargs):
        self.payload = kwargs
        return 42


class FakeContext:
    def __init__(self):
        self.service = FakeReplayService()
        self.db_runtime = None

    def replay_service(self):
        return self.service


def test_start_drill_gateway_calls_replay_service():
    context = FakeContext()
    result = _action_live_sim_start_drill(
        context,
        {
            "startDate": "2026-01-01",
            "endDate": "2026-05-09",
            "market": "CN",
            "timeframe": "30m",
            "initialCash": 50000,
            "autoEntryEnabled": True,
            "autoExitEnabled": True,
            "executeTrades": True,
            "liquidateAtEnd": True,
            "seedCurrentQuantUniverse": True,
            "generateHistoricalCandidateEvents": True,
            "candidateGenerationFrequency": "daily_first_checkpoint",
            "candidateGenerationCheckpointInterval": 8,
            "confirmLongRunning": False,
        },
    )

    assert result["runId"] == 42
    assert result["runType"] == "live_quant_drill"
    assert result["redirect"] == "/his-replay?runId=42"
    assert context.service.payload["start_datetime"] == "2026-01-01"


def test_start_drill_gateway_returns_400_when_long_run_is_not_confirmed():
    class LongRunService(FakeReplayService):
        def enqueue_live_quant_drill(self, **kwargs):
            raise ValueError("Long running drill requires confirmation")

    context = FakeContext()
    context.service = LongRunService()

    result = _action_live_sim_start_drill(
        context,
        {
            "startDate": "2026-01-01",
            "endDate": "2026-05-09",
            "market": "CN",
            "timeframe": "30m",
            "confirmLongRunning": False,
        },
    )

    assert result["statusCode"] == 400
    assert result["error"] == "Long running drill requires confirmation"


def test_drill_lifecycle_query_endpoints_are_registered():
    from app.gateway_api import create_app

    app = create_app(FakeContext())
    routes = {
        route.path
        for route in app.routes
        if hasattr(route, "methods") and "GET" in route.methods
    }
    assert "/api/v1/quant/replay/{run_id}/quant-states" in routes
    assert "/api/v1/quant/replay/{run_id}/quant-events" in routes
    assert "/api/v1/quant/replay/{run_id}/candidate-events" in routes
```

- [ ] **Step 2: Run tests and confirm failure**

```powershell
pytest tests/test_live_quant_drill_gateway.py -q
```

Expected: fails because gateway action is missing.

- [ ] **Step 3: Add live-sim action**

In `app/gateway/live_sim.py`, add:

```python
def _action_live_sim_start_drill(context: UIApiContext, payload: Any) -> dict[str, Any]:
    body = _payload_dict(payload)
    run_id = context.replay_service().enqueue_live_quant_drill(
        start_datetime=body.get("startDate") or body.get("start_datetime"),
        end_datetime=body.get("endDate") or body.get("end_datetime"),
        timeframe=body.get("timeframe", "30m"),
        market=body.get("market", "CN"),
        strategy_profile_id=body.get("strategyProfileId") or body.get("strategy_profile_id"),
        initial_cash=body.get("initialCash") or body.get("initial_cash"),
        auto_entry_enabled=bool(body.get("autoEntryEnabled", body.get("auto_entry_enabled", True))),
        auto_exit_enabled=bool(body.get("autoExitEnabled", body.get("auto_exit_enabled", True))),
        execute_trades=bool(body.get("executeTrades", body.get("execute_trades", True))),
        liquidate_at_end=bool(body.get("liquidateAtEnd", body.get("liquidate_at_end", True))),
        seed_current_quant_universe=bool(body.get("seedCurrentQuantUniverse", body.get("seed_current_quant_universe", True))),
        generate_historical_candidate_events=bool(body.get("generateHistoricalCandidateEvents", body.get("generate_historical_candidate_events", True))),
        candidate_generation_frequency=body.get("candidateGenerationFrequency") or body.get("candidate_generation_frequency", "daily_first_checkpoint"),
        candidate_generation_checkpoint_interval=int(body.get("candidateGenerationCheckpointInterval", body.get("candidate_generation_checkpoint_interval", 8))),
        confirm_long_running=bool(body.get("confirmLongRunning", body.get("confirm_long_running", False))),
    )
    return {
        "runId": run_id,
        "runType": "live_quant_drill",
        "status": "queued",
        "redirect": f"/his-replay?runId={run_id}",
    }
```

- [ ] **Step 4: Register API route**

In `app/gateway_api.py`, add action mapping:

```python
("/api/v1/quant/live-sim/actions/start-drill", "live-sim", "start-drill")
```

And map `("live-sim", "start-drill")` to `_action_live_sim_start_drill`.

- [ ] **Step 5: Add replay result query endpoints**

Expose these as dedicated endpoints, not as optional page-snapshot-only data:

- `/api/v1/quant/replay/{run_id}/quant-states`
- `/api/v1/quant/replay/{run_id}/quant-events`
- `/api/v1/quant/replay/{run_id}/candidate-events`

Each endpoint must:

- Return `404` when `run_id` does not exist.
- Return `400` when `run_type` is not `live_quant_drill`.
- Support the filters defined in spec 18.2 through 18.4.
- Return paged `{items, total, page, pageSize}` payloads.

`_snapshot_his_replay()` may include compact summary data, but detailed lifecycle tables must call these dedicated endpoints.

- [ ] **Step 6: Run gateway tests**

```powershell
pytest tests/test_live_quant_drill_gateway.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```powershell
git add app/gateway/live_sim.py app/gateway/his_replay.py app/gateway_api.py tests/test_live_quant_drill_gateway.py
git commit -m "feat: add live quant drill gateway actions"
```

---

## Task 10: His-Replay Snapshot And Result Tables

**Files:**
- Modify: `app/gateway/his_replay.py`
- Modify: `ui/src/lib/page-models.ts`
- Modify: `ui/src/features/quant/his-replay-page.tsx`
- Test: `ui/src/tests/his-replay-page.test.tsx`

- [ ] **Step 1: Add failing UI fixture expectations**

In `ui/src/tests/his-replay-page.test.tsx`, add a run fixture with:

```ts
{
  id: "drill-1",
  mode: "live_quant_drill",
  runType: "live_quant_drill",
  title: "实时量化演练",
  lifecycleSummary: {
    initialQuantCount: 20,
    candidateEventCount: 15,
    autoPromotedCount: 4,
    autoExitedCount: 3,
    exitOnlyCount: 2,
    coolingCount: 1,
    retiredCount: 1,
    dataWarningCount: 0,
  },
  lifecycleSeries: [
    {
      checkpointAt: "2026-01-05 09:30:00",
      trialCount: 3,
      activeCount: 17,
      exitOnlyCount: 0,
      coolingCount: 0,
      retiredCount: 0,
    },
    {
      checkpointAt: "2026-01-05 10:00:00",
      trialCount: 4,
      activeCount: 16,
      exitOnlyCount: 1,
      coolingCount: 0,
      retiredCount: 0,
    },
  ],
  candidateEventsTable: {
    items: [{ stockCode: "600519", stockName: "贵州茅台", sourceType: "low_price", candidateScore: 0.76, reason: "历史低价候选" }],
    total: 1,
  },
  exitEventsTable: {
    items: [{ stockCode: "600519", fromStatus: "active", toStatus: "exit_only", healthScore: 34, reason: "downtrend_hit" }],
    total: 1,
  },
  finalStatesTable: {
    items: [{ stockCode: "600519", finalStatus: "exit_only", realizedPnl: 120.5, liquidationPnl: 90.2, stateChangeCount: 2, latestReason: "downtrend_hit" }],
    total: 1,
  },
  dataRisksTable: {
    items: [{ stockCode: "000001", domain: "candidate_source", provider: "main_force", reason: "source_not_historical" }],
    total: 1,
  },
}
```

Assert:

```ts
expect(await screen.findByText("实时量化演练")).toBeInTheDocument();
expect(screen.getByText("历史候选事件")).toBeInTheDocument();
expect(screen.getByText("15")).toBeInTheDocument();
expect(screen.getByText("自动入池")).toBeInTheDocument();
expect(screen.getByText("4")).toBeInTheDocument();
expect(screen.getByText("生命周期趋势")).toBeInTheDocument();
expect(screen.getByText("入池事件")).toBeInTheDocument();
expect(screen.getByText("出池与降级事件")).toBeInTheDocument();
expect(screen.getByText("股票最终状态")).toBeInTheDocument();
expect(screen.getByText("数据风险")).toBeInTheDocument();
```

- [ ] **Step 2: Run UI test and confirm failure**

```powershell
npm test -- his-replay-page.test.tsx -- --runInBand
```

Expected: fails because UI does not render drill lifecycle sections.

- [ ] **Step 3: Extend backend snapshot**

In `_build_his_replay_task_items()` and selected run payload:

- Add `runType`.
- Add `typeLabel`.
- Add `lifecycleSummary`.
- For drill runs, calculate summary from:
  - initial count from metadata
  - candidate count from `sim_run_candidate_events`
  - promoted/exited from `sim_run_quant_summary`
  - status counts from `sim_run_quant_events`
  - warning count from metadata

Do not use `estimated_*` as completed actuals.

- [ ] **Step 4: Extend page models**

In `ui/src/lib/page-models.ts`, add:

```ts
type ReplayDrillTable = {
  items: Array<Record<string, unknown>>;
  total: number;
  page?: number;
  pageSize?: number;
};

runType?: string;
lifecycleSummary?: {
  initialQuantCount: number;
  candidateEventCount: number;
  autoPromotedCount: number;
  autoExitedCount: number;
  exitOnlyCount: number;
  coolingCount: number;
  retiredCount: number;
  dataWarningCount: number;
};
lifecycleSeries?: Array<{
  checkpointAt: string;
  trialCount: number;
  activeCount: number;
  exitOnlyCount: number;
  coolingCount: number;
  retiredCount: number;
}>;
candidateEventsTable?: ReplayDrillTable;
exitEventsTable?: ReplayDrillTable;
finalStatesTable?: ReplayDrillTable;
dataRisksTable?: ReplayDrillTable;
```

- [ ] **Step 5: Render lifecycle summary, trend, and detail tables**

In `HisReplayPage`, when selected task `runType === "live_quant_drill"`, render:

Lifecycle summary cards:

- `初始量化股票`
- `历史候选事件`
- `自动入池`
- `自动出池`
- `只出场管理`
- `冷却`
- `已退出`
- `数据风险`

Lifecycle trend chart:

- Title `生命周期趋势`.
- Use `lifecycleSeries` from `sim_run_quant_summary`.
- Plot `trial / active / exit_only / cooling / retired`.
- Do not aggregate from `sim_run_quant_states` on every UI interaction.

Detail tables:

- `入池事件`: from `/api/v1/quant/replay/{run_id}/candidate-events`.
- `出池与降级事件`: from `/api/v1/quant/replay/{run_id}/quant-events`.
- `股票最终状态`: from selected run payload or `/api/v1/quant/replay/{run_id}/quant-states` at the final checkpoint.
- `数据风险`: from run metadata warnings and `disabled_candidate_sources`.

Each table must support empty state text and pagination when the backend returns `total > pageSize`.

- [ ] **Step 6: Run UI test**

```powershell
npm test -- his-replay-page.test.tsx i18n-static.test.ts -- --runInBand
```

Expected: pass.

- [ ] **Step 7: Commit**

```powershell
git add app/gateway/his_replay.py ui/src/lib/page-models.ts ui/src/features/quant/his-replay-page.tsx ui/src/tests/his-replay-page.test.tsx ui/src/locales/zh-CN.json ui/src/locales/en-US.json
git commit -m "feat: show live quant drill replay results"
```

---

## Task 11: Live-Sim Drill Launch UI

**Files:**
- Modify: `ui/src/features/quant/live-sim-page.tsx`
- Modify: `ui/src/lib/api-client.ts`
- Modify: `ui/src/locales/zh-CN.json`
- Modify: `ui/src/locales/en-US.json`
- Test: `ui/src/tests/live-sim-page.test.tsx`

- [ ] **Step 1: Add failing UI test for launch dialog**

In `ui/src/tests/live-sim-page.test.tsx`, add:

```ts
it("starts live quant drill from live sim page", async () => {
  const client = {
    getPageSnapshot: vi.fn().mockResolvedValue(liveSimSnapshot),
    runPageAction: vi.fn().mockResolvedValue({
      runId: 42,
      runType: "live_quant_drill",
      status: "queued",
      redirect: "/his-replay?runId=42",
    }),
  } as unknown as ApiClient;

  renderLiveSimPage(client);

  await userEvent.click(await screen.findByRole("button", { name: "历史演练" }));
  expect(screen.getByText("实时量化历史演练")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "开始演练" }));

  expect(client.runPageAction).toHaveBeenCalledWith(
    "live-sim",
    "start-drill",
    expect.objectContaining({
      startDate: "2026-01-01",
      candidateGenerationFrequency: "daily_first_checkpoint",
      seedCurrentQuantUniverse: true,
      generateHistoricalCandidateEvents: true,
    }),
  );
});
```

- [ ] **Step 2: Run UI test and confirm failure**

```powershell
npm test -- live-sim-page.test.tsx -- --runInBand
```

Expected: fails because action/UI do not exist.

- [ ] **Step 3: Add API action mapping**

In `ui/src/lib/api-client.ts`:

```ts
pageActionEndpoints["live-sim"]["start-drill"] = "/api/v1/quant/live-sim/actions/start-drill";
```

- [ ] **Step 4: Add launch dialog**

In `LiveSimPage`:

- Add button `历史演练` in the page action area.
- Dialog defaults:
  - start date: `2026-01-01`
  - end date: current local date
  - market/timeframe/profile/initial cash from snapshot config
  - autoEntryEnabled: true
  - autoExitEnabled: true
  - executeTrades: true
  - liquidateAtEnd: true
  - seedCurrentQuantUniverse: true
  - generateHistoricalCandidateEvents: true
  - candidateGenerationFrequency: `daily_first_checkpoint`
  - candidateGenerationCheckpointInterval: `8`

Submit via `runPageAction("live-sim", "start-drill", payload)`.

- [ ] **Step 5: Add i18n entries**

Add translations for:

- `历史演练`
- `实时量化历史演练`
- `用历史 checkpoint 模拟实时量化从指定日期开始上线运行的完整过程，包括入池、出池、交易和生命周期。`
- `开始演练`
- `候选生成频率`
- `每日第一个检查点`
- `每 N 个检查点`
- `确认长任务`

- [ ] **Step 6: Run UI tests**

```powershell
npm test -- live-sim-page.test.tsx i18n-static.test.ts -- --runInBand
```

Expected: pass.

- [ ] **Step 7: Commit**

```powershell
git add ui/src/features/quant/live-sim-page.tsx ui/src/lib/api-client.ts ui/src/locales/zh-CN.json ui/src/locales/en-US.json ui/src/tests/live-sim-page.test.tsx
git commit -m "feat: add live quant drill launcher"
```

---

## Task 12: End-To-End Verification And Build

**Files:**
- No new production files expected.
- May modify tests for final alignment if a contract mismatch is found.

- [ ] **Step 1: Run backend drill tests**

```powershell
pytest tests/test_live_quant_drill_db.py tests/test_live_quant_drill_candidates.py tests/test_live_quant_drill_service.py tests/test_live_quant_drill_gateway.py -q
```

Expected: pass.

- [ ] **Step 2: Run related existing backend tests**

```powershell
pytest tests/test_quant_universe_lifecycle_manager.py tests/test_quant_sim_scheduler.py -q
```

Expected: pass. If `tests/test_quant_sim_scheduler.py` does not exist in this checkout, run:

```powershell
pytest tests -q -k "quant_universe or replay or live_quant"
```

- [ ] **Step 3: Run frontend tests**

```powershell
npm test -- live-sim-page.test.tsx his-replay-page.test.tsx i18n-static.test.ts -- --runInBand
```

Expected: pass.

- [ ] **Step 4: Build frontend**

```powershell
npm run build
```

Expected: TypeScript and Vite build pass. Existing chunk-size warnings are acceptable.

- [ ] **Step 5: Manual local smoke**

Start backend and frontend using the project’s usual commands. Then verify:

1. `/live-sim` shows `历史演练`.
2. Clicking it opens the configuration dialog.
3. Starting a short drill returns a queued run.
4. `/his-replay?runId=<id>` shows task type `实时量化演练`.
5. live-sim account summary is unchanged after the drill completes.

- [ ] **Step 6: Commit final adjustments**

If any final test-only or UI-copy changes were made:

```powershell
git add <changed-files>
git commit -m "test: verify live quant drill flow"
```

If no files changed, skip this commit.

---

## Self-Review Checklist

- [ ] The plan has a task for every spec area: run type, DB tables, candidate source gates, candidate frequency, run-local state, lifecycle execution, API, UI, and result display.
- [ ] Drill does not write live-sim state.
- [ ] Candidate source names do not directly affect `candidate_score`.
- [ ] `multi_source_bonus` is disabled or bypassed in drill mode.
- [ ] Candidate generation defaults to daily first checkpoint, not every 30m checkpoint.
- [ ] `sim_run_quant_summary` is persisted and used for lifecycle overview.
- [ ] His-replay drill results include lifecycle trend plus 入池事件、出池与降级事件、股票最终状态、数据风险 tables.
- [ ] `cooling` opportunistic review runs after main scan and is bounded.
- [ ] `quant-states / quant-events / candidate-events` are independent endpoints.
- [ ] `confirmLongRunning=false` blocks drills with `estimated_strategy_invocations > 3000`.
- [ ] Source availability tests cover low_price, small_cap, low_valuation, profit_growth, main_force, historical_research, manual_seed, current discover, and current AI.
- [ ] Historical backtest and live quant drill are mutually exclusive.
- [ ] Profile snapshot is locked at run start.
- [ ] All new Chinese UI text is wrapped in i18n.
