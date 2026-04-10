# Quant Replay Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated `🕰️ 历史回放` menu and page, remove replay-only UI from realtime `量化模拟`, and expand replay history into a complete report with per-signal execution records, applied strategy profiles, and per-stock holding outcomes.

**Architecture:** Keep one replay backend (`QuantSimReplayService`, `QuantSimReplayRunner`, replay tables in `QuantSimDB`) and split the frontend into two top-level renderers: realtime `display_quant_sim()` and replay-only `display_quant_replay()`. Reuse shared helpers for replay status, replay configuration, and replay report building, while extending replay persistence so the report can show signal execution details and stock-level outcomes.

Replay execution itself must run in a **standalone worker process**. The implementation should persist `sim_runs.worker_pid`, use OS pid liveness checks during stale-run reconciliation, and finalize any worker that exits without a terminal replay status as `failed`.

The replay page should visually align with the realtime quant-simulation page, but the final arrangement should prioritize replay review: left column for configuration + running overview + current/all replay-task lists, right main column for replay-task selection, selected-task metadata, and the selected run's report details.

**Tech Stack:** Python, Streamlit, SQLite, pytest, existing `quant_sim` services, replay runner/service, main app navigation

---

### Task 1: Add dedicated app navigation for `🕰️ 历史回放`

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\app.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_replay_ui.py`

- [ ] **Step 1: Write the failing test**

```python
def test_app_navigation_exposes_quant_replay_page():
    app_source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")
    assert "🕰️ 历史回放" in app_source
    assert "show_quant_replay" in app_source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_app_navigation_exposes_quant_replay_page`
Expected: FAIL because the replay menu entry and dedicated state do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
if st.button("🕰️ 历史回放", width='stretch', key="nav_quant_replay", ...):
    st.session_state.show_quant_replay = True
    ...

if 'show_quant_replay' in st.session_state and st.session_state.show_quant_replay:
    from quant_sim.ui import display_quant_replay
    display_quant_replay()
    return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_app_navigation_exposes_quant_replay_page`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app.py tests/test_quant_sim_replay_ui.py
git commit -m "feat: add dedicated quant replay navigation"
```

### Task 2: Split `quant_sim` into realtime page and replay page

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_replay_ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_ui_feedback.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_quant_sim_page_no_longer_contains_replay_section():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    quant_sim_block = ui_source.split("def display_quant_sim()", 1)[1].split("def display_quant_replay()", 1)[0]
    assert "历史区间回放" not in quant_sim_block


def test_quant_replay_page_exposes_direct_configuration_without_expander():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    replay_block = ui_source.split("def display_quant_replay()", 1)[1]
    assert "开始日期" in replay_block
    assert "开始时间" in replay_block
    assert "回放模式" in replay_block
    assert "with st.expander(\"🕰️ 历史区间回放\"" not in replay_block
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py tests/test_quant_sim_ui_feedback.py`
Expected: FAIL because replay UI still lives inside `display_quant_sim()` and is gated by an expander.

- [ ] **Step 3: Write minimal implementation**

```python
def display_quant_sim() -> None:
    ...
    # realtime-only sections


def display_quant_replay() -> None:
    ...
    render_replay_status_panel(...)
    render_replay_configuration_form(...)
    render_replay_results(...)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py tests/test_quant_sim_ui_feedback.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add quant_sim/ui.py tests/test_quant_sim_replay_ui.py tests/test_quant_sim_ui_feedback.py
git commit -m "refactor: split realtime simulation and replay pages"
```

### Task 3: Persist replay signal execution detail for report rendering

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\db.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\replay_service.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_replay_engine.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_db.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_replay_results_persist_signal_execution_fields(tmp_path):
    ...
    signals = db.get_sim_run_signals(run_id)
    assert signals[0]["executed"] in {0, 1}
    assert "executed_quantity" in signals[0]
    assert "execution_note" in signals[0]
    trades = db.get_sim_run_trades(run_id)
    assert trades[0]["signal_id"] == signals[0]["id"]


def test_replay_signal_records_capture_truncated_sell_execution(tmp_path):
    ...
    assert signal["executed_quantity"] == 100
    assert "可卖数量" in signal["execution_note"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_replay_engine.py tests/test_quant_sim_db.py`
Expected: FAIL because replay signals do not yet persist execution status/quantity/note and replay trades do not yet point back to the originating replay signal.

- [ ] **Step 3: Write minimal implementation**

```python
CREATE TABLE ... sim_run_signals (
    ...,
    executed INTEGER DEFAULT 0,
    executed_quantity INTEGER DEFAULT 0,
    executed_price REAL DEFAULT 0,
    execution_note TEXT
)

CREATE TABLE ... sim_run_trades (
    ...,
    signal_id INTEGER
)

signal["executed"] = bool(executed)
signal["executed_quantity"] = executed_quantity
signal["executed_price"] = executed_price
signal["execution_note"] = execution_note
trade["signal_id"] = replay_signal_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_replay_engine.py tests/test_quant_sim_db.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add quant_sim/db.py quant_sim/replay_service.py tests/test_quant_replay_engine.py tests/test_quant_sim_db.py
git commit -m "feat: persist replay signal execution details"
```

### Task 4: Build replay report payload with stock-level outcomes

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_ui_feedback.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_build_replay_report_payload_exposes_per_stock_outcomes():
    payload = build_replay_report_payload(...)
    assert payload["stock_outcomes"][0]["stock_code"] == "300390"
    assert payload["stock_outcomes"][0]["buy_count"] == 2
    assert payload["stock_outcomes"][0]["sell_count"] == 1


def test_build_replay_signal_row_exposes_execution_detail():
    row = _build_replay_signal_row({...})
    assert row["是否执行"] == "是"
    assert row["执行数量"] == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_ui_feedback.py`
Expected: FAIL because the report payload and signal rows do not yet expose stock outcomes or execution detail.

- [ ] **Step 3: Write minimal implementation**

```python
def build_replay_stock_outcomes(trades, positions, signals) -> list[dict]:
    ...


def _build_replay_signal_row(signal: dict) -> dict:
    return {
        ...,
        "是否执行": "是" if signal.get("executed") else "否",
        "执行数量": signal.get("executed_quantity") or 0,
        "执行价格": signal.get("executed_price") or "",
        "执行说明": signal.get("execution_note") or "",
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_ui_feedback.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add quant_sim/ui.py tests/test_quant_sim_ui_feedback.py
git commit -m "feat: add replay stock outcomes and signal execution report"
```

### Task 10: Add kernel-level explainability payload for replay, realtime, and future live views

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_kernel\runtime.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_kernel\decision_engine.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_kernel\models.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_kernel_runtime.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_ui_feedback.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_kernel_decision_exposes_vote_breakdown():
    decision = runtime.evaluate_candidate(...)
    assert "tech_votes" in decision.strategy_profile["explainability"]
    assert "context_votes" in decision.strategy_profile["explainability"]
    assert "dual_track" in decision.strategy_profile["explainability"]


def test_replay_signal_detail_summary_mentions_vote_breakdown():
    summary = _build_replay_signal_detail_summary(signal)
    assert "技术投票" in summary
    assert "环境投票" in summary
    assert "双轨裁决" in summary
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_kernel_runtime.py tests/test_quant_sim_ui_feedback.py`
Expected: FAIL because the kernel does not yet persist structured vote breakdown and the UI cannot render it.

- [ ] **Step 3: Write minimal implementation**

```python
strategy_profile["explainability"] = {
    "tech_votes": [...],
    "context_votes": [...],
    "dual_track": {
        "tech_signal": ...,
        "context_signal": ...,
        "resonance_type": ...,
        "rule_hit": ...,
        "position_ratio": ...,
    },
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_kernel_runtime.py tests/test_quant_sim_ui_feedback.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add quant_kernel/runtime.py quant_kernel/decision_engine.py quant_kernel/models.py tests/test_quant_kernel_runtime.py tests/test_quant_sim_ui_feedback.py
git commit -m "feat: add explainable vote breakdown for quant kernel decisions"
```

### Task 5: Render dedicated replay page sections

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_replay_ui.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_quant_replay_page_mentions_report_sections():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    replay_block = ui_source.split("def display_quant_replay()", 1)[1]
    assert "回放总览" in replay_block
    assert "信号执行记录" in replay_block
    assert "每股持仓结果" in replay_block
    assert "成交明细" in replay_block


def test_quant_replay_page_exposes_run_selector():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    replay_block = ui_source.split("def display_quant_replay()", 1)[1]
    assert "选择回放任务" in replay_block
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py`
Expected: FAIL because the replay page renderer and report sections do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def display_quant_replay() -> None:
    st.title("🕰️ 历史回放")
    render_replay_status_panel(...)
    render_replay_configuration(...)
    render_replay_results(...)


def render_replay_results(...):
    st.subheader("回放总览")
    ...
    st.subheader("信号执行记录")
    ...
    st.subheader("每股持仓结果")
    ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add quant_sim/ui.py tests/test_quant_sim_replay_ui.py
git commit -m "feat: add dedicated replay page and report sections"
```

### Task 6: Remove replay UI from realtime quant simulation page

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_replay_ui.py`

- [ ] **Step 1: Write the failing test**

```python
def test_display_quant_sim_excludes_replay_result_tab():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    quant_sim_block = ui_source.split("def display_quant_sim()", 1)[1].split("def display_quant_replay()", 1)[0]
    assert "🕰️ 回放结果" not in quant_sim_block
    assert "当前回放状态" not in quant_sim_block
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_display_quant_sim_excludes_replay_result_tab`
Expected: FAIL because the realtime page still contains replay UI.

- [ ] **Step 3: Write minimal implementation**

```python
tab_candidates, tab_signals, tab_pending, tab_positions, tab_trades, tab_equity = st.tabs(...)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_display_quant_sim_excludes_replay_result_tab`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add quant_sim/ui.py tests/test_quant_sim_replay_ui.py
git commit -m "refactor: remove replay UI from realtime quant simulation page"
```

### Task 7: Full review and verification

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\docs\superpowers\specs\2026-04-10-quant-replay-menu-design.md`
- Test: `C:\Projects\githubs\aiagents-stock\tests\`

- [ ] **Step 1: Review pass 1 - code/spec comparison**

Check:
- dedicated `🕰️ 历史回放` menu exists
- replay page opens directly into config/status
- realtime `量化模拟` no longer contains replay-only content
- replay report includes per-signal execution records
- replay report includes applied strategy info
- replay report includes per-stock holding outcomes

- [ ] **Step 2: Review pass 2 - runtime verification**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests
python -m compileall quant_sim app.py
python -c "import app; print('app-import-ok')"
```

Expected:
- tests pass
- compile succeeds
- app import succeeds

- [ ] **Step 3: Commit final cleanup**

```powershell
git add app.py quant_sim/ui.py quant_sim/db.py quant_sim/replay_service.py tests docs/superpowers/specs/2026-04-10-quant-replay-menu-design.md docs/superpowers/plans/2026-04-10-quant-replay-menu.md
git commit -m "feat: add dedicated quant replay workspace"
```

### Task 8: Add replay strategy mode and richer compact signal detail

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_kernel\runtime.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\stockpolicy_adapter.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\engine.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\replay_service.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_ui_feedback.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_replay_engine.py`

- [ ] **Step 1: Write failing tests**

```python
def test_quant_sim_replay_ui_exposes_strategy_mode_options():
    ...


def test_replay_run_persists_strategy_mode_metadata(tmp_path):
    ...


def test_build_replay_signal_row_keeps_detail_compact_but_rich():
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_ui_feedback.py tests/test_quant_replay_engine.py`

- [ ] **Step 3: Write minimal implementation**

```python
strategy_mode = st.selectbox("策略模式", ["auto", "aggressive", "neutral", "defensive"], ...)
...
runtime.evaluate_candidate(..., strategy_mode=strategy_mode)
...
strategy_profile["strategy_mode"] = {...}
signal_row["详情说明"] = ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_ui_feedback.py tests/test_quant_replay_engine.py`

### Task 9: Delete finished replay runs

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\db.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_db.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_replay_ui.py`

- [ ] **Step 1: Write failing tests**

```python
def test_delete_sim_run_removes_all_replay_artifacts(tmp_path):
    ...


def test_quant_replay_page_exposes_delete_for_finished_runs():
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_db.py tests/test_quant_sim_replay_ui.py`

- [ ] **Step 3: Write minimal implementation**

```python
db.delete_sim_run(run_id)
...
if selected_run.status in {"completed", "failed", "cancelled"}:
    st.button("🗑️ 删除回放任务", ...)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_db.py tests/test_quant_sim_replay_ui.py`
