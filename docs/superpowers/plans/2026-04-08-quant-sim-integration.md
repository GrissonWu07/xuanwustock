# Quant Simulation Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify stock selection and semi-automatic quantitative simulation into the main Streamlit app, with `stockpolicy` embedded as a backend strategy engine and all signals, manual confirmations, and simulated positions owned by the main project.

**Architecture:** Keep the existing Streamlit shell in the main project as the only frontend. Introduce a new `quant_sim` backend package and database schema for candidate pool, strategy signals, pending manual actions, and simulated positions. Reuse `stockpolicy` strategy and position/risk logic through an adapter layer while removing its standalone Flask/YAML/auto-confirm assumptions.

**Tech Stack:** Python, Streamlit, SQLite, pytest, pytdx, tushare, stockpolicy core strategy modules

---

### Task 1: Embed-Ready `stockpolicy` Foundation

**Files:**
- Create: `C:\Projects\githubs\aiagents-stock\tests\test_stockpolicy_embedding.py`
- Modify: `C:\Projects\githubs\aiagents-stock\stockpolicy\livetrading.py`
- Modify: `C:\Projects\githubs\aiagents-stock\stockpolicy\dashboard_flask.py`
- Modify: `C:\Projects\githubs\aiagents-stock\stockpolicy\src\core\live_persistence_manager.py`
- Modify: `C:\Projects\githubs\aiagents-stock\stockpolicy\src\scanner\config_manager.py`
- Modify: `C:\Projects\githubs\aiagents-stock\stockpolicy\tests\test_local_cache_integration.py`

- [ ] **Step 1: Write failing embedding and portability tests**

```python
def test_stockpolicy_modules_import_without_dashboard_side_effects():
    from stockpolicy.src.core.live_persistence_manager import LivePersistenceManager
    assert LivePersistenceManager is not None


def test_pending_signal_is_not_auto_confirmed():
    from stockpolicy.src.core.live_persistence_manager import LivePersistenceManager
    mgr = LivePersistenceManager(base_dir=".")
    state = {"pending_signals": [], "positions": {}, "capital": 100000}
    mgr.add_pending_signal(state, {"signal_id": "sig-1", "action": "BUY", "symbol": "600000"})
    assert mgr.auto_confirm_expired_signals(state) == []
    assert len(state["pending_signals"]) == 1
```

- [ ] **Step 2: Run targeted tests to verify current failures**

Run: `python -m pytest -q C:\Projects\githubs\aiagents-stock\tests\test_stockpolicy_embedding.py C:\Projects\githubs\aiagents-stock\stockpolicy\tests\test_local_cache_integration.py -p no:cacheprovider`

Expected: FAIL because `stockpolicy` still assumes standalone runtime behavior.

- [ ] **Step 3: Remove standalone-only assumptions with minimal code**

```python
# live_persistence_manager.py
def auto_confirm_expired_signals(self, state: dict) -> List[str]:
    """Semi-auto mode keeps signals pending until a human confirms them."""
    return []
```

```python
# livetrading.py
EPILOG = "半自动模式由主项目 Streamlit 页面承载，不在 CLI 中自动确认信号。"
```

```python
# config_manager.py
def export_universe(self, codes: list[str], metadata: dict | None = None) -> dict:
    return {"codes": codes, "metadata": metadata or {}}
```

- [ ] **Step 4: Review twice before moving on**

Run review 1: `git diff -- C:\Projects\githubs\aiagents-stock\stockpolicy`

Run review 2: `python -m pytest -q C:\Projects\githubs\aiagents-stock\tests\test_stockpolicy_embedding.py C:\Projects\githubs\aiagents-stock\stockpolicy\tests\test_local_cache_integration.py -p no:cacheprovider`

Expected: PASS targeted tests, no dashboard or auto-confirm regressions.

- [ ] **Step 5: Commit**

```bash
git add stockpolicy tests/test_stockpolicy_embedding.py
git commit -m "refactor: prepare stockpolicy for embedded semi-auto mode"
```

### Task 2: Quant Simulation Database and Services

**Files:**
- Create: `C:\Projects\githubs\aiagents-stock\quant_sim\__init__.py`
- Create: `C:\Projects\githubs\aiagents-stock\quant_sim\db.py`
- Create: `C:\Projects\githubs\aiagents-stock\quant_sim\candidate_pool_service.py`
- Create: `C:\Projects\githubs\aiagents-stock\quant_sim\signal_center_service.py`
- Create: `C:\Projects\githubs\aiagents-stock\quant_sim\portfolio_service.py`
- Create: `C:\Projects\githubs\aiagents-stock\quant_sim\models.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_db.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_services.py`

- [ ] **Step 1: Write failing tests for candidate pool, signals, and simulated positions**

```python
def test_add_candidate_records_source_and_status(tmp_path):
    from quant_sim.db import QuantSimDB
    db = QuantSimDB(tmp_path / "quant_sim.db")
    candidate_id = db.add_candidate({"stock_code": "600000", "source": "main_force"})
    row = db.get_candidates()[0]
    assert candidate_id > 0
    assert row["stock_code"] == "600000"
    assert row["source"] == "main_force"


def test_confirm_buy_creates_simulated_position(tmp_path):
    from quant_sim.db import QuantSimDB
    db = QuantSimDB(tmp_path / "quant_sim.db")
    signal_id = db.add_signal({"stock_code": "600000", "action": "BUY", "status": "pending"})
    db.confirm_signal(signal_id, executed_action="buy", price=10.5, quantity=100)
    positions = db.get_positions()
    assert positions[0]["stock_code"] == "600000"
    assert positions[0]["quantity"] == 100
```

- [ ] **Step 2: Run tests to verify the new API does not exist yet**

Run: `python -m pytest -q C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_db.py C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_services.py -p no:cacheprovider`

Expected: FAIL with import or attribute errors.

- [ ] **Step 3: Implement the smallest working DB and service layer**

```python
class QuantSimDB:
    def add_candidate(self, candidate: dict) -> int: ...
    def get_candidates(self, status: str | None = None) -> list[dict]: ...
    def add_signal(self, signal: dict) -> int: ...
    def confirm_signal(self, signal_id: int, executed_action: str, price: float, quantity: int) -> None: ...
    def get_positions(self) -> list[dict]: ...
```

- [ ] **Step 4: Review twice before moving on**

Run review 1: `git diff -- C:\Projects\githubs\aiagents-stock\quant_sim C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_db.py C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_services.py`

Run review 2: `python -m pytest -q C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_db.py C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_services.py -p no:cacheprovider`

Expected: PASS candidate pool and manual execution tests.

- [ ] **Step 5: Commit**

```bash
git add quant_sim tests/test_quant_sim_db.py tests/test_quant_sim_services.py
git commit -m "feat: add quant simulation data model and services"
```

### Task 3: Strategy Adapter and Signal Generation

**Files:**
- Create: `C:\Projects\githubs\aiagents-stock\quant_sim\stockpolicy_adapter.py`
- Create: `C:\Projects\githubs\aiagents-stock\quant_sim\engine.py`
- Modify: `C:\Projects\githubs\aiagents-stock\smart_monitor_tdx_data.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_engine.py`

- [ ] **Step 1: Write failing tests for candidate analysis and BUY/SELL/HOLD generation**

```python
def test_engine_generates_pending_buy_signal_for_candidate(mocker, tmp_path):
    from quant_sim.engine import QuantSimEngine
    engine = QuantSimEngine(db_file=tmp_path / "quant_sim.db")
    mocker.patch.object(engine.adapter, "analyze_candidate", return_value={
        "action": "BUY",
        "confidence": 82,
        "reasoning": "trend confirmed",
        "position_size_pct": 20,
    })
    signal = engine.analyze_candidate({"stock_code": "600000", "stock_name": "浦发银行"})
    assert signal["action"] == "BUY"
    assert signal["status"] == "pending"
```

- [ ] **Step 2: Run tests to verify the engine is not implemented yet**

Run: `python -m pytest -q C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_engine.py -p no:cacheprovider`

Expected: FAIL with missing adapter or engine API.

- [ ] **Step 3: Implement adapter-based strategy generation**

```python
class StockPolicyAdapter:
    def analyze_candidate(self, candidate: dict, market_snapshot: dict | None = None) -> dict: ...


class QuantSimEngine:
    def analyze_candidate(self, candidate: dict) -> dict:
        decision = self.adapter.analyze_candidate(candidate)
        return self.signal_center.create_signal(candidate, decision)
```

- [ ] **Step 4: Review twice before moving on**

Run review 1: `git diff -- C:\Projects\githubs\aiagents-stock\quant_sim\stockpolicy_adapter.py C:\Projects\githubs\aiagents-stock\quant_sim\engine.py`

Run review 2: `python -m pytest -q C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_engine.py -p no:cacheprovider`

Expected: PASS signal generation tests.

- [ ] **Step 5: Commit**

```bash
git add quant_sim/stockpolicy_adapter.py quant_sim/engine.py tests/test_quant_sim_engine.py
git commit -m "feat: connect stockpolicy decisions to quant simulation signals"
```

### Task 4: Streamlit `量化模拟` Page and Selector Integration

**Files:**
- Create: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\app.py`
- Modify: `C:\Projects\githubs\aiagents-stock\main_force_ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\low_price_bull_ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\profit_growth_ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\value_stock_ui.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_selector_integration.py`

- [ ] **Step 1: Write failing tests for selector-to-candidate-pool integration**

```python
def test_add_selected_stock_to_quant_sim_candidate_pool(tmp_path):
    from quant_sim.candidate_pool_service import CandidatePoolService
    service = CandidatePoolService(db_file=tmp_path / "quant_sim.db")
    candidate_id = service.add_manual_candidate(
        stock_code="600000",
        stock_name="浦发银行",
        source="main_force",
    )
    assert candidate_id > 0
    assert service.list_candidates()[0]["stock_code"] == "600000"
```

- [ ] **Step 2: Run tests to verify integration points are not wired**

Run: `python -m pytest -q C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_selector_integration.py -p no:cacheprovider`

Expected: FAIL with missing service usage in selectors.

- [ ] **Step 3: Implement Streamlit page and selector entry points**

```python
# app.py
if st.button("量化模拟", ...):
    st.session_state.page = "quant_sim"

# selector pages
if st.button("加入量化模拟", ...):
    candidate_pool_service.add_manual_candidate(...)
```

- [ ] **Step 4: Review twice before moving on**

Run review 1: `git diff -- C:\Projects\githubs\aiagents-stock\app.py C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`

Run review 2: `python -m pytest -q C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_selector_integration.py -p no:cacheprovider`

Expected: PASS selector integration tests.

- [ ] **Step 5: Commit**

```bash
git add app.py quant_sim/ui.py main_force_ui.py low_price_bull_ui.py profit_growth_ui.py value_stock_ui.py tests/test_quant_sim_selector_integration.py
git commit -m "feat: add quant simulation Streamlit workflow"
```

### Task 5: Manual Execution, Risk Tracking, and Final Verification

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\portfolio_service.py`
- Create: `C:\Projects\githubs\aiagents-stock\quant_sim\scheduler.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_manual_execution.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_scheduler.py`

- [ ] **Step 1: Write failing tests for manual confirmation and risk follow-up**

```python
def test_delay_signal_keeps_pending_status(tmp_path):
    from quant_sim.db import QuantSimDB
    db = QuantSimDB(tmp_path / "quant_sim.db")
    signal_id = db.add_signal({"stock_code": "600000", "action": "SELL", "status": "pending"})
    db.delay_signal(signal_id, note="waiting for close")
    signal = db.get_pending_signals()[0]
    assert signal["status"] == "pending"
    assert signal["delay_count"] == 1
```

- [ ] **Step 2: Run tests to verify missing manual workflow behavior**

Run: `python -m pytest -q C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_manual_execution.py C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_scheduler.py -p no:cacheprovider`

Expected: FAIL because delay/ignore/scheduler flows are incomplete.

- [ ] **Step 3: Implement manual execution and scheduled refresh**

```python
class QuantSimScheduler:
    def run_once(self) -> dict:
        return {"candidates_scanned": 0, "signals_created": 0, "positions_checked": 0}
```

```python
def confirm_sell(...):
    portfolio_service.execute_manual_sell(...)
```

- [ ] **Step 4: Review twice before moving on**

Run review 1: `git diff -- C:\Projects\githubs\aiagents-stock\quant_sim`

Run review 2:
`python -m pytest -q C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_manual_execution.py C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_scheduler.py -p no:cacheprovider`
`python -m compileall .`
`python -c "import app; print('app-import-ok')"`

Expected: PASS targeted tests, compile succeeds, app imports cleanly.

- [ ] **Step 5: Commit**

```bash
git add quant_sim tests
git commit -m "feat: complete semi-auto quant simulation workflow"
```

## Self-Review

- Spec coverage:
  - Unified Streamlit frontend: covered by Task 4.
  - `stockpolicy` backend embedding: covered by Task 1 and Task 3.
  - Semi-auto signals plus manual confirmation: covered by Task 2 and Task 5.
  - Candidate pool and full workflow visibility: covered by Task 2 and Task 4.
  - Review and verification gates: explicitly embedded in each task.
- Placeholder scan:
  - No `TODO`/`TBD` markers remain.
  - Each task names exact files, concrete commands, and target behavior.
- Type consistency:
  - Database API is consistently referred to as `QuantSimDB`.
  - Strategy adapter is consistently referred to as `StockPolicyAdapter`.
  - UI workflow uses `pending` signal state throughout.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-08-quant-sim-integration.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration

2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
