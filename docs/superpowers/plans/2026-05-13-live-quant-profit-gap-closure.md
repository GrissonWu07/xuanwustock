# Live Quant Profit Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the measurable profit gap between fixed historical replay and live quant drill by adding stock-level attribution, stronger confirmed recovery sizing, faster confirmed entry, probe fatigue, false-strong filtering, SELL diagnostics, and active downgrade protection.

**Architecture:** Keep historical replay and live quant drill isolated. Add a replay-domain attribution service that compares two completed runs, then feed the same diagnostics into API/UI. Strategy behavior changes stay in existing lifecycle gate, signal finalization, execution sizing, and portfolio execution layers.

**Tech Stack:** Python, SQLite replay/live DBs, FastAPI gateway services, pytest, React/TypeScript frontend.

---

## File Map

- `app/quant_sim/profit_gap_attribution.py`: new pure service for run-vs-run stock attribution.
- `app/quant_sim/db.py`: replay DB schema/CRUD for profit gap attribution and additional signal diagnostics.
- `app/quant_sim/replay_service.py`: create/update attribution after drill/replay completion and expose result summaries.
- `app/gateway/his_replay.py`: API endpoint for attribution comparison.
- `app/quant_sim/quant_universe_lifecycle.py`: profile defaults and active downgrade protection semantics.
- `app/quant_sim/signal_center_service.py`: confirmed recovery/trial gate semantics and false-strong downgrade.
- `app/quant_sim/execution_sizing.py`: strong recovery cap, trial-confirmed dual cap semantics, and cap reason persistence.
- `app/quant_sim/portfolio_service.py`: execution diagnostics for BUY/SELL ignored or blocked cases.
- `ui/src/features/his-replay/*`: result page attribution section.
- `ui/src/i18n/*`: new UI labels.
- `tests/test_profit_gap_attribution.py`: pure attribution tests.
- `tests/test_quant_sim_services.py`: signal/gate tests.
- `tests/test_quant_sim_auto_execution.py`: execution diagnostics tests.
- `tests/test_quant_universe_lifecycle_manager.py`: active downgrade protection tests.

---

### Task 1: Profit Gap Attribution Service And Schema

**Files:**
- Create: `app/quant_sim/profit_gap_attribution.py`
- Modify: `app/quant_sim/db.py`
- Test: `tests/test_profit_gap_attribution.py`

- [ ] **Step 1: Write failing tests for attribution labels**

Create `tests/test_profit_gap_attribution.py` with deterministic rows:

```python
from app.quant_sim.profit_gap_attribution import build_profit_gap_attributions


def test_labels_size_too_small_when_entry_matches_but_amount_is_low():
    rows = build_profit_gap_attributions(
        historical=[
            {
                "stock_code": "301666",
                "stock_name": "大普微-UW",
                "total_pnl": 41119.0,
                "first_buy_at": "2026-04-28T02:00:00Z",
                "first_buy_price": 243.14,
                "buy_amount": 95156.0,
            }
        ],
        drill=[
            {
                "stock_code": "301666",
                "stock_name": "大普微-UW",
                "total_pnl": 18023.59,
                "first_buy_at": "2026-04-28T02:00:00Z",
                "first_buy_price": 243.14,
                "buy_amount": 24321.29,
                "buy_tiers": ["strong_buy"],
                "lifecycle_gate_modes": ["recovery_probe_confirmed"],
            }
        ],
    )
    assert rows[0]["attribution_labels"] == ["size_too_small"]
    assert rows[0]["primary_reason"] == "entry matched but drill sizing was materially lower"


def test_labels_entry_too_late_and_bad_extra_buy():
    rows = build_profit_gap_attributions(
        historical=[
            {
                "stock_code": "300736",
                "stock_name": "百邦科技",
                "total_pnl": 10992.0,
                "first_buy_at": "2026-01-06T02:00:00Z",
                "first_buy_price": 16.06,
                "buy_amount": 96566.0,
            }
        ],
        drill=[
            {
                "stock_code": "300736",
                "stock_name": "百邦科技",
                "total_pnl": -1814.38,
                "first_buy_at": "2026-03-27T02:00:00Z",
                "first_buy_price": 22.92,
                "buy_amount": 22926.88,
            },
            {
                "stock_code": "600768",
                "stock_name": "宁波富邦",
                "total_pnl": -2996.98,
                "first_buy_at": "2026-02-24T02:00:00Z",
                "first_buy_price": 19.0,
                "buy_amount": 38011.4,
            },
        ],
    )
    by_code = {row["stock_code"]: row for row in rows}
    assert "entry_too_late" in by_code["300736"]["attribution_labels"]
    assert by_code["600768"]["attribution_labels"] == ["bad_extra_buy"]
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
pytest tests/test_profit_gap_attribution.py -q
```

Expected: FAIL because `app.quant_sim.profit_gap_attribution` does not exist.

- [ ] **Step 3: Implement pure attribution builder**

Create `app/quant_sim/profit_gap_attribution.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_profit_gap_attributions(
    *,
    historical: list[dict[str, Any]],
    drill: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    hist_by_code = {str(row.get("stock_code")): row for row in historical}
    drill_by_code = {str(row.get("stock_code")): row for row in drill}
    output: list[dict[str, Any]] = []
    for code in sorted(set(hist_by_code) | set(drill_by_code)):
        hist = hist_by_code.get(code) or {}
        cur = drill_by_code.get(code) or {}
        labels = _labels(hist, cur)
        hist_pnl = _float(hist.get("total_pnl"))
        drill_pnl = _float(cur.get("total_pnl"))
        output.append(
            {
                "stock_code": code,
                "stock_name": cur.get("stock_name") or hist.get("stock_name") or code,
                "historical_total_pnl": hist_pnl,
                "drill_total_pnl": drill_pnl,
                "pnl_gap": round(hist_pnl - drill_pnl, 4),
                "historical_first_buy_at": hist.get("first_buy_at"),
                "drill_first_buy_at": cur.get("first_buy_at"),
                "historical_first_buy_price": hist.get("first_buy_price"),
                "drill_first_buy_price": cur.get("first_buy_price"),
                "historical_buy_amount": _float(hist.get("buy_amount")),
                "drill_buy_amount": _float(cur.get("buy_amount")),
                "attribution_labels": labels,
                "primary_reason": _primary_reason(labels),
                "evidence_json": {
                    "buy_tiers": cur.get("buy_tiers") or [],
                    "lifecycle_gate_modes": cur.get("lifecycle_gate_modes") or [],
                    "blocked_reasons": cur.get("blocked_reasons") or [],
                    "cap_reasons": cur.get("cap_reasons") or [],
                },
            }
        )
    output.sort(key=lambda row: row["pnl_gap"], reverse=True)
    return output


def _labels(hist: dict[str, Any], drill: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    hist_has_buy = bool(hist.get("first_buy_at"))
    drill_has_buy = bool(drill.get("first_buy_at"))
    hist_pnl = _float(hist.get("total_pnl"))
    drill_pnl = _float(drill.get("total_pnl"))
    if hist_has_buy and drill_has_buy:
        if _entry_matches(hist, drill) and _float(drill.get("buy_amount")) < _float(hist.get("buy_amount")) * 0.6:
            labels.append("size_too_small")
        if _entry_late(hist, drill) and hist_pnl > 0:
            labels.append("entry_too_late")
        if drill_pnl < hist_pnl and "repeat_probe_loss" in (drill.get("diagnostic_labels") or []):
            labels.append("repeat_probe_loss")
    if drill_has_buy and not hist_has_buy and drill_pnl < 0:
        labels.append("bad_extra_buy")
    if "sell_blocked_or_late" in (drill.get("diagnostic_labels") or []):
        labels.append("sell_blocked_or_late")
    if drill_pnl > hist_pnl:
        labels.append("drill_better")
    return labels or ["unclassified"]


def _entry_matches(hist: dict[str, Any], drill: dict[str, Any]) -> bool:
    hist_at = _parse_dt(hist.get("first_buy_at"))
    drill_at = _parse_dt(drill.get("first_buy_at"))
    if hist_at is None or drill_at is None:
        return False
    price_gap = abs(_float(hist.get("first_buy_price")) - _float(drill.get("first_buy_price")))
    ref_price = max(_float(hist.get("first_buy_price")), 0.01)
    return abs((drill_at - hist_at).total_seconds()) <= 60 * 60 * 24 and price_gap / ref_price <= 0.02


def _entry_late(hist: dict[str, Any], drill: dict[str, Any]) -> bool:
    hist_at = _parse_dt(hist.get("first_buy_at"))
    drill_at = _parse_dt(drill.get("first_buy_at"))
    if hist_at is None or drill_at is None:
        return False
    price_higher = _float(drill.get("first_buy_price")) > _float(hist.get("first_buy_price")) * 1.08
    days_late = (drill_at - hist_at).total_seconds() >= 60 * 60 * 24 * 3
    return days_late or price_higher


def _primary_reason(labels: list[str]) -> str:
    mapping = {
        "size_too_small": "entry matched but drill sizing was materially lower",
        "entry_too_late": "drill entered materially later than historical replay",
        "bad_extra_buy": "drill bought a losing stock that historical replay did not buy",
        "repeat_probe_loss": "recovery probe repeated after prior failure",
        "sell_blocked_or_late": "sell signal was blocked or delayed",
        "drill_better": "drill outperformed historical replay on this stock",
    }
    return mapping.get(labels[0], "no dominant attribution label")


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _float(value: Any) -> float:
    try:
        return round(float(value or 0.0), 4)
    except (TypeError, ValueError):
        return 0.0
```

- [ ] **Step 4: Add replay DB table and CRUD**

In `app/quant_sim/db.py`, add table `sim_run_profit_gap_attributions` inside replay schema initialization:

```sql
CREATE TABLE IF NOT EXISTS sim_run_profit_gap_attributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    historical_run_id INTEGER NOT NULL,
    drill_run_id INTEGER NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT,
    historical_total_pnl REAL DEFAULT 0,
    drill_total_pnl REAL DEFAULT 0,
    pnl_gap REAL DEFAULT 0,
    historical_first_buy_at TEXT,
    drill_first_buy_at TEXT,
    historical_first_buy_price REAL,
    drill_first_buy_price REAL,
    historical_buy_amount REAL DEFAULT 0,
    drill_buy_amount REAL DEFAULT 0,
    attribution_labels_json TEXT DEFAULT '[]',
    primary_reason TEXT,
    evidence_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
)
```

Add methods:

```python
def replace_profit_gap_attributions(self, historical_run_id: int, drill_run_id: int, rows: list[dict[str, Any]]) -> None:
    ...

def list_profit_gap_attributions(self, historical_run_id: int, drill_run_id: int, limit: int = 200) -> list[dict[str, Any]]:
    ...
```

Use existing JSON encode/decode helpers in `db.py`; do not create a second JSON utility.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
pytest tests/test_profit_gap_attribution.py -q
```

Expected: PASS.

---

### Task 2: Confirmed Recovery And Trial Gate Semantics

**Files:**
- Modify: `app/quant_sim/quant_universe_lifecycle.py`
- Modify: `app/quant_sim/signal_center_service.py`
- Modify: `app/quant_sim/execution_sizing.py`
- Test: `tests/test_quant_sim_services.py`
- Test: `tests/test_quant_sim_auto_execution.py`

- [ ] **Step 1: Add tests for multiplier removal**

In `tests/test_quant_sim_services.py`, add:

```python
def test_strong_recovery_confirmed_removes_probe_multiplier(signal_center_service):
    gate = {
        "mode": "recovery_probe",
        "size_multiplier": 0.45,
        "max_position_pct": 6.0,
        "confirmed_max_position_pct": 10.0,
        "recent_probe_loss_count": 0,
        "buy_threshold_delta": 0.08,
    }
    profile = {
        "portfolio_execution_guard": {
            "buy_tier": "strong_buy",
            "buy_strength_score": 0.82,
            "trend_confirmation": {"ma_stack": True, "ma20_rising": True, "above_ma20_checkpoints": 4},
            "score_components": {"confirmation_score": 0.9},
        }
    }
    relaxed = signal_center_service._maybe_relax_trial_lifecycle_gate(gate, profile)
    assert relaxed["mode"] == "recovery_probe_confirmed"
    assert relaxed["size_multiplier"] == 1.0
    assert relaxed["max_position_pct"] == 10.0
```

- [ ] **Step 2: Add tests for `trial_confirmed` dual semantics**

In `tests/test_quant_sim_auto_execution.py`, add:

```python
from app.quant_sim.execution_sizing import build_execution_sizing_plan


def test_trial_confirmed_uses_active_single_cap_but_keeps_trial_status_for_budget():
    signal = {
        "action": "BUY",
        "price": 20.0,
        "position_size_pct": 50.0,
        "stop_loss_pct": 5.0,
        "strategy_profile": {
            "lifecycle_gate": {
                "mode": "trial_confirmed",
                "size_multiplier": 1.0,
                "max_position_pct": None,
            },
            "kernel_positioning": {"quality_position_pct": 20.0},
        },
    }
    plan = build_execution_sizing_plan(
        signal,
        quant_status="trial",
        total_equity=400000.0,
        available_cash=400000.0,
        slot_available_cash=400000.0,
    )
    assert plan["lifecycle_gate_mode"] == "trial_confirmed"
    assert plan["lifecycle_cap_pct"] == 15.0
    assert plan["effective_position_pct"] <= 15.0
    assert plan["quant_status_for_portfolio_budget"] == "trial"
```

- [ ] **Step 3: Implement execution sizing status split**

In `app/quant_sim/execution_sizing.py`, keep current `lifecycle_cap_status = "active" if mode == "trial_confirmed"`, and add:

```python
portfolio_budget_status = "trial" if status == "trial" else status
```

Return it:

```python
"quant_status_for_portfolio_budget": portfolio_budget_status,
```

For `recovery_probe_confirmed`, treat it like confirmed recovery cap:

```python
if lifecycle_gate_mode == "recovery_probe_confirmed":
    lifecycle_gate_multiplier = 1.0
```

- [ ] **Step 4: Implement signal gate normalization**

In `app/quant_sim/signal_center_service.py`, ensure `_maybe_relax_trial_lifecycle_gate()` emits:

```python
relaxed["mode"] = "recovery_probe_confirmed"
relaxed["size_multiplier"] = 1.0
relaxed["max_position_pct"] = cls._safe_float(
    normalized_gate.get("confirmed_max_position_pct"),
    normalized_gate.get("max_position_pct"),
)
relaxed["reason_code"] = "recovery_probe_strong_confirmed"
```

For `trial_confirmed`, ensure it emits:

```python
relaxed["mode"] = "trial_confirmed"
relaxed["size_multiplier"] = 1.0
relaxed["max_position_pct"] = None
relaxed["reason_code"] = "trial_confirmed_active_like_sizing"
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
pytest tests/test_quant_sim_services.py tests/test_quant_sim_auto_execution.py -q
```

Expected: PASS.

---

### Task 3: Faster Confirmed Entry And False Strong Downgrade

**Files:**
- Modify: `app/quant_sim/portfolio_execution_guard.py`
- Modify: `app/quant_sim/signal_center_service.py`
- Modify: `app/quant_sim/replay_service.py`
- Test: `tests/test_quant_sim_services.py`
- Test: `tests/test_live_quant_drill_service.py`

- [ ] **Step 1: Add tests for false-strong downgrade**

In `tests/test_quant_sim_services.py`, add a pure guard test:

```python
def test_false_strong_is_downgraded_when_overheated_without_structure(signal_center_service):
    payload = {
        "action": "BUY",
        "strategy_profile": {
            "portfolio_execution_guard": {
                "buy_tier": "strong_buy",
                "buy_strength_score": 0.72,
                "trend_confirmation": {
                    "ma_stack": False,
                    "ma20_rising": False,
                    "above_ma20_checkpoints": 1,
                    "ma20_distance_pct": 12.0,
                    "rsi": 88.0,
                },
                "score_components": {"confirmation_score": 0.2},
            }
        },
    }
    result = signal_center_service._apply_false_strong_filter(payload)
    guard = result["strategy_profile"]["portfolio_execution_guard"]
    assert guard["buy_tier"] == "normal_buy"
    assert guard["strong_filter_result"] == "downgraded"
    assert "overheated_distance" in guard["strong_filter_reasons"]
```

- [ ] **Step 2: Implement false-strong filter**

In `app/quant_sim/signal_center_service.py`, add `_apply_false_strong_filter()` before lifecycle relaxation:

```python
def _apply_false_strong_filter(self, payload: dict[str, Any]) -> dict[str, Any]:
    profile = payload.get("strategy_profile") if isinstance(payload.get("strategy_profile"), dict) else {}
    guard = profile.get("portfolio_execution_guard") if isinstance(profile.get("portfolio_execution_guard"), dict) else {}
    if str(guard.get("buy_tier") or "").lower() != "strong_buy":
        return payload
    trend = guard.get("trend_confirmation") if isinstance(guard.get("trend_confirmation"), dict) else {}
    reasons: list[str] = []
    structure_ok = bool(trend.get("ma_stack") or trend.get("retest_confirmed") or (trend.get("ma20_rising") and int(trend.get("above_ma20_checkpoints") or 0) >= 2))
    if not structure_ok:
        reasons.append("weak_trend_structure")
    if float(trend.get("ma20_distance_pct") or 0.0) >= 10.0 and float(trend.get("rsi") or 0.0) >= 86.0:
        reasons.append("overheated_distance")
    if reasons:
        new_payload = dict(payload)
        new_profile = dict(profile)
        new_guard = dict(guard)
        new_guard["buy_tier"] = "normal_buy"
        new_guard["strong_filter_result"] = "downgraded"
        new_guard["strong_filter_reasons"] = reasons
        new_profile["portfolio_execution_guard"] = new_guard
        new_payload["strategy_profile"] = new_profile
        return new_payload
    return payload
```

Use profile defaults for thresholds when wiring final implementation; test can use aggressive defaults.

- [ ] **Step 3: Add drill test for `cooling -> trial_confirmed` visibility**

In `tests/test_live_quant_drill_service.py`, add:

```python
def test_cooling_confirmed_buy_is_visible_in_same_checkpoint_scan(tmp_path, monkeypatch):
    service = QuantSimReplayService(db_file=str(tmp_path / "live.db"), replay_db_file=str(tmp_path / "replay.db"))
    checkpoint = datetime(2026, 1, 6, 10, 0)
    temp_db = QuantSimDB(str(tmp_path / "temp.db"))
    temp_db.upsert_quant_universe_state(
        {
            "stock_code": "300736",
            "stock_name": "百邦科技",
            "quant_enabled": True,
            "quant_status": "cooling",
            "health_score": 70.0,
            "candidate_score": 0.8,
        }
    )
    context = {
        "run_id": 1,
        "temp_db": temp_db,
        "strategy_profile_binding": {"id": "aggressive"},
        "checkpoint_timezone": "Asia/Shanghai",
    }

    def fake_scan_candidate(candidate, decision_time=None):
        candidate = dict(candidate)
        candidate["action"] = "BUY"
        candidate["strategy_profile"] = {
            "portfolio_execution_guard": {
                "buy_tier": "normal_buy",
                "buy_strength_score": 0.75,
                "trend_confirmation": {"ma_stack": True, "ma20_rising": True, "above_ma20_checkpoints": 3},
            }
        }
        return candidate

    monkeypatch.setattr(service.engine, "analyze_candidate", fake_scan_candidate)
    service._run_live_quant_drill_cooling_review(context, checkpoint)
    state = temp_db.get_quant_universe_state("300736")
    assert state["quant_status"] == "trial"
    candidate = service.engine.list_live_scan_candidates(strategy_profile_binding={"id": "aggressive"}, as_of=checkpoint)
    assert any(item["stock_code"] == "300736" and item["lifecycle_gate"]["mode"] == "trial_confirmed" for item in candidate)
```

- [ ] **Step 4: Implement confirmed entry in drill cooling review**

In `app/quant_sim/replay_service.py`, when cooling review produces executable `normal_buy` or `strong_buy` with trend confirmation:

```python
state_update = {
    "quant_status": "trial",
    "last_status_changed_at": checkpoint_iso,
    "snapshot_json": {
        **(state.get("snapshot_json") if isinstance(state.get("snapshot_json"), dict) else {}),
        "lifecycle_gate_mode": "trial_confirmed",
        "entry_delay_reason": None,
    },
}
```

After the state update, call `engine.list_live_scan_candidates(strategy_profile_binding=context["strategy_profile_binding"], as_of=checkpoint)` in the same checkpoint and assert the stock is present with `lifecycle_gate.mode = trial_confirmed`.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
pytest tests/test_quant_sim_services.py tests/test_live_quant_drill_service.py -q
```

Expected: PASS.

---

### Task 4: Probe Fatigue And Cooldown Enforcement

**Files:**
- Modify: `app/quant_sim/quant_universe_lifecycle.py`
- Modify: `app/quant_sim/db.py`
- Modify: `app/quant_sim/replay_service.py`
- Test: `tests/test_quant_universe_lifecycle_manager.py`

- [ ] **Step 1: Add lifecycle tests**

In `tests/test_quant_universe_lifecycle_manager.py`, add:

```python
def test_probe_attempt_fatigue_enters_strict_mode(policy_aggressive):
    gate = build_lifecycle_gate(
        "trial",
        policy_aggressive,
        recovery_probe_active=True,
        recovery_probe_attempt_count=4,
        recent_probe_loss_count=0,
        recovery_probe_cooldown_active=False,
    )
    assert gate["mode"] == "recovery_probe_fatigue"
    assert gate["requires_strong_confirmation"] is True
    assert gate["max_position_pct"] == policy_aggressive.recovery_probe_failed_max_position_pct


def test_probe_loss_count_blocks_recovery(policy_aggressive):
    gate = build_lifecycle_gate(
        "trial",
        policy_aggressive,
        recovery_probe_active=True,
        recovery_probe_attempt_count=2,
        recent_probe_loss_count=2,
        recovery_probe_cooldown_active=True,
    )
    assert gate["mode"] == "recovery_probe_cooldown"
    assert gate["buy_blocked"] is True
    assert gate["reason_code"] == "recovery_probe_cooldown"
```

- [ ] **Step 2: Ensure policy fields exist**

In `app/quant_sim/quant_universe_lifecycle.py`, policy dataclass must include:

```python
recovery_probe_failure_threshold: int
recovery_probe_failure_lookback_days: int
recovery_probe_attempt_fatigue_threshold: int
recovery_probe_cooldown_days: int
```

Defaults:

```python
# aggressive
recovery_probe_failure_threshold=2
recovery_probe_failure_lookback_days=20
recovery_probe_attempt_fatigue_threshold=4
recovery_probe_cooldown_days=15
```

- [ ] **Step 3: Persist probe diagnostics**

In `app/quant_sim/db.py`, ensure live and drill state tables have:

```sql
recovery_probe_attempt_count INTEGER DEFAULT 0,
last_recovery_probe_attempt_at TEXT,
recent_probe_loss_count INTEGER DEFAULT 0,
last_recovery_probe_failure_at TEXT,
recovery_probe_cooldown_until TEXT,
probe_failure_reason TEXT
```

- [ ] **Step 4: Update probe failure after execution**

In `app/quant_sim/replay_service.py`, after auto execution and lifecycle update, if a probe BUY later exits by hard stop or enters cooling/exit_only within the probe window, update:

```python
state["recent_probe_loss_count"] = int(state.get("recent_probe_loss_count") or 0) + 1
state["last_recovery_probe_failure_at"] = checkpoint_iso
state["probe_failure_reason"] = failure_reason
state["recovery_probe_cooldown_until"] = checkpoint + timedelta(days=policy.recovery_probe_cooldown_days)
```

The `failure_reason` must be one of:

- `probe_failed_hard_stop`
- `probe_failed_fast_exit_only`
- `probe_failed_fast_cooling`
- `probe_failed_negative_realized_pnl`

- [ ] **Step 5: Run focused tests**

Run:

```powershell
pytest tests/test_quant_universe_lifecycle_manager.py -q
```

Expected: PASS.

---

### Task 5: Active Downgrade Protection

**Files:**
- Modify: `app/quant_sim/quant_universe_lifecycle.py`
- Modify: `app/quant_sim/signal_center_service.py`
- Test: `tests/test_quant_universe_lifecycle_manager.py`
- Test: `tests/test_quant_sim_services.py`

- [ ] **Step 1: Add tests for active guard**

In `tests/test_quant_universe_lifecycle_manager.py`, add:

```python
def test_active_min_dwell_blocks_soft_exit(policy_aggressive):
    update = resolve_next_status(
        current_status="active",
        policy=policy_aggressive,
        health_score=70.0,
        downtrend_streak=2,
        has_position=True,
        active_dwell_checkpoints=2,
        latest_signal={"action": "SELL", "decision_type": "dual_track_weighted_sell"},
    )
    assert update["next_status"] == "active"
    assert update["reason_code"] == "active_min_dwell_guarded"


def test_active_hard_stop_still_exits(policy_aggressive):
    update = resolve_next_status(
        current_status="active",
        policy=policy_aggressive,
        health_score=70.0,
        downtrend_streak=1,
        has_position=True,
        active_dwell_checkpoints=1,
        latest_signal={"action": "SELL", "decision_type": "hard_stop_loss", "veto_id": "hard_stop_loss"},
    )
    assert update["next_status"] == "exit_only"
    assert update["reason_code"] == "active_hard_risk_exit"
```

- [ ] **Step 2: Implement active protection rules**

In `app/quant_sim/quant_universe_lifecycle.py`, update active branch:

```python
if current == QuantStatus.ACTIVE:
    if _signal_requires_immediate_exit(latest_signal):
        return _transition(current, QuantStatus.EXIT_ONLY, "active_hard_risk_exit", "active 硬风控退出")
    active_min_dwell_active = int(active_dwell_checkpoints or 0) < int(policy.active_min_dwell_checkpoints or 0)
    if active_min_dwell_active and downtrend_streak > 0:
        return _blocked(current, "active_min_dwell_guarded", "active 最短停留期内仅进入 guarded gate")
    if has_position and downtrend_streak >= policy.active_exit_only_downtrend_streak:
        return _transition(current, QuantStatus.EXIT_ONLY, "active_holding_downtrend_exit_only", "active 持仓持续下行，进入只出场管理")
    if not has_position and downtrend_streak >= policy.active_cooling_downtrend_streak:
        return _transition(current, QuantStatus.COOLING, "active_flat_downtrend_cooling", "active 空仓持续下行，进入冷却")
    if downtrend_streak > 0:
        return _blocked(current, "active_downtrend_guarded", "active 短期弱化，保留 active 并使用 guarded gate")
```

- [ ] **Step 3: Ensure weak SELL observation still applies**

In `app/quant_sim/signal_center_service.py`, add or update tests so hard veto IDs remain executable and ordinary `dual_track_weighted_sell` becomes `weak_sell_observe`. The implementation must call the existing weak SELL observation helper in the signal finalization path and must not create a second weak SELL classifier.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
pytest tests/test_quant_universe_lifecycle_manager.py tests/test_quant_sim_services.py -q
```

Expected: PASS.

---

### Task 6: SELL Diagnostics Persistence

**Files:**
- Modify: `app/quant_sim/db.py`
- Modify: `app/quant_sim/portfolio_service.py`
- Modify: `app/quant_sim/signal_center_service.py`
- Test: `tests/test_quant_sim_auto_execution.py`

- [ ] **Step 1: Add tests for ignored SELL diagnostics**

In `tests/test_quant_sim_auto_execution.py`, add:

```python
def test_ignored_sell_persists_sellable_diagnostics(portfolio_service, replay_db):
    signal = {
        "id": 101,
        "action": "SELL",
        "stock_code": "300001",
        "quantity": 100,
        "decision_type": "dual_track_weighted_sell",
        "strategy_profile": {"explainability": {"vetoes": []}},
    }
    result = portfolio_service.auto_execute_signal(signal, run_id=1)
    assert result["status"] == "ignored"
    saved = replay_db.get_signal(101)
    assert saved["blocked_reason"] in {"weak_sell_observe", "no_sellable_quantity"}
    assert "sellable_quantity" in saved["execution_diagnostics"]
```

- [ ] **Step 2: Add execution diagnostics JSON to signal updates**

In `app/quant_sim/db.py`, ensure signal tables can store diagnostics:

```sql
execution_diagnostics_json TEXT DEFAULT '{}'
```

Use `execution_diagnostics_json` as the canonical storage field and expose it as `execution_diagnostics` in API payloads.

- [ ] **Step 3: Populate SELL diagnostics**

In `app/quant_sim/portfolio_service.py`, when SELL is ignored or blocked, write:

```python
diagnostics = {
    "sell_trigger_type": sell_trigger_type,
    "hard_veto_id": hard_veto_id,
    "is_weak_sell_observe": is_weak_sell,
    "sellable_quantity": sellable_quantity,
    "locked_quantity": locked_quantity,
    "blocked_reason": blocked_reason,
    "first_sell_signal_at": signal.get("created_at") or signal.get("checkpoint_at"),
    "actual_sell_at": None,
}
```

For executed SELL, set `actual_sell_at` to execution time.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
pytest tests/test_quant_sim_auto_execution.py -q
```

Expected: PASS.

---

### Task 7: API And UI Attribution View

**Files:**
- Modify: `app/gateway/his_replay.py`
- Modify: `ui/src/features/his-replay/his-replay-page.tsx`
- Modify: `ui/src/i18n/zh.ts`
- Modify: `ui/src/i18n/en.ts`
- Test: frontend test file matching his-replay feature.

- [ ] **Step 1: Add API endpoint**

In `app/gateway/his_replay.py`, add:

```python
@router.get("/runs/{drill_run_id}/profit-gap")
def get_profit_gap(drill_run_id: int, historical_run_id: int):
    rows = replay_db.list_profit_gap_attributions(historical_run_id, drill_run_id)
    return {"historical_run_id": historical_run_id, "drill_run_id": drill_run_id, "items": rows}
```

Use `context.replay_db()` as the replay DB dependency, matching the other functions in `app/gateway/his_replay.py`.

- [ ] **Step 2: Add UI table**

In `ui/src/features/his-replay/his-replay-page.tsx`, add a section below the existing summary:

```tsx
<section className="replay-profit-gap">
  <header>
    <h2>{t("hisReplay.profitGap.title")}</h2>
  </header>
  <DataTable
    rows={profitGapItems}
    columns={[
      { key: "stock", title: t("common.stock") },
      { key: "historical_total_pnl", title: t("hisReplay.profitGap.historicalPnl") },
      { key: "drill_total_pnl", title: t("hisReplay.profitGap.drillPnl") },
      { key: "pnl_gap", title: t("hisReplay.profitGap.gap") },
      { key: "attribution_labels", title: t("hisReplay.profitGap.labels") },
      { key: "primary_reason", title: t("hisReplay.profitGap.reason") },
    ]}
  />
</section>
```

Use the local table rendering pattern already used by the his-replay page; do not introduce a new table library.

- [ ] **Step 3: Add i18n**

Add Chinese labels:

```ts
hisReplay: {
  profitGap: {
    title: "收益差异归因",
    historicalPnl: "历史盈亏",
    drillPnl: "演练盈亏",
    gap: "差额",
    labels: "归因",
    reason: "主要原因",
  },
}
```

Add English labels:

```ts
hisReplay: {
  profitGap: {
    title: "Profit Gap Attribution",
    historicalPnl: "Historical PnL",
    drillPnl: "Drill PnL",
    gap: "Gap",
    labels: "Labels",
    reason: "Primary reason",
  },
}
```

- [ ] **Step 4: Run frontend tests/build**

Run:

```powershell
cd ui
npm test -- --run
npm run build
```

Expected: tests pass and build completes.

---

### Task 8: End-To-End Verification

**Files:**
- No planned source edits; only fix defects found by the verification commands in Tasks 1-7.

- [ ] **Step 1: Run backend focused suite**

Run:

```powershell
pytest tests/test_profit_gap_attribution.py tests/test_quant_sim_services.py tests/test_quant_sim_auto_execution.py tests/test_quant_universe_lifecycle_manager.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full backend suite**

Run:

```powershell
pytest -q
```

Expected: PASS with the repository's existing skipped tests unchanged.

- [ ] **Step 3: Run 40W aggressive AI hybrid drill**

Run this inline service command:

```powershell
@'
from app.quant_sim.replay_service import QuantSimReplayService

service = QuantSimReplayService()
result = service.run_live_quant_drill(
    start_datetime="2026-01-01 10:00:00",
    end_datetime="2026-05-11 15:00:00",
    timeframe="30m",
    market="CN",
    strategy_profile_id="aggressive",
    initial_cash=400000,
    ai_dynamic_strategy="hybrid",
)
print(result)
'@ | python -
```

- [ ] **Step 4: Run matching historical replay**

Run:

```powershell
@'
from app.quant_sim.replay_service import QuantSimReplayService

service = QuantSimReplayService()
result = service.run_historical_range(
    start_datetime="2026-01-01 10:00:00",
    end_datetime="2026-05-11 15:00:00",
    timeframe="30m",
    market="CN",
    strategy_profile_id="aggressive",
    initial_cash=400000,
    ai_dynamic_strategy="hybrid",
)
print(result)
'@ | python -
```

- [ ] **Step 5: Generate attribution and inspect acceptance cases**

Call the new endpoint or service and verify:

```python
rows = db.list_profit_gap_attributions(historical_run_id, drill_run_id)
by_code = {row["stock_code"]: row for row in rows}
assert "size_too_small" not in by_code["301666"]["attribution_labels"] or by_code["301666"]["evidence_json"].get("cap_reason")
assert by_code["301183"]["evidence_json"].get("probe_attempt_count", 0) >= 1
assert "sell_trigger_type" in any_sell_diagnostic
```

- [ ] **Step 6: Review against spec**

Check every spec section:

- Section 1 attribution report: Task 1 and Task 7.
- Section 2 strong recovery sizing: Task 2.
- Section 3 faster entry/recovery: Task 3.
- Section 4 probe fatigue/cooldown: Task 4.
- Section 5 false strong filtering: Task 3.
- Section 6 SELL diagnostics: Task 6.
- Section 7 active downgrade protection: Task 5.

---

## Plan Self-Review

- Spec coverage: all seven required sections map to tasks above.
- Placeholder scan: no deferred implementation language is used in task requirements.
- Type consistency: `strong_recovery_confirmed`, `trial_confirmed`, `active_guarded`, `probe_*`, and `profit_gap_attributions` names are consistent with the spec.
