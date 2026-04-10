# Quant Sim Realtime UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the realtime `🧪 量化模拟` page so configuration is always visible, realtime strategy mode is configurable and persisted, candidate actions live in the candidate pool, account controls support both updating and resetting the simulated ledger, and candidate-level analysis opens in a modal dialog instead of a permanent inline detail section.

**Architecture:** Keep the current `quant_sim` services and tabs, but flatten the top-level realtime UI into a left-config / right-results layout. Use the candidate pool as the only prominent large table, move candidate add/delete/analyze operations into that table area, replace the old inline candidate-detail block with a focused analysis dialog, and reuse a single lower detail region that switches between execution and account views. Extend scheduler config with `strategy_mode`, reuse the existing `auto_execute` backend path, and add a reset path that clears positions/trades/signals while rebuilding the simulation cash ledger.

**Tech Stack:** Python, Streamlit, SQLite, pytest, existing `quant_sim` services, scheduler, portfolio service

---

### Task 1: Persist realtime `strategy_mode` in scheduler config

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\db.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_db.py`

- [ ] **Step 1: Write the failing test**

```python
def test_scheduler_config_persists_strategy_mode(tmp_path):
    db = QuantSimDB(tmp_path / "quant_sim.db")
    config = db.get_scheduler_config()
    assert config["strategy_mode"] == "auto"

    db.update_scheduler_config(strategy_mode="defensive")
    config = db.get_scheduler_config()
    assert config["strategy_mode"] == "defensive"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_db.py::test_scheduler_config_persists_strategy_mode`
Expected: FAIL because `sim_scheduler_config` does not yet store or return `strategy_mode`.

- [ ] **Step 3: Write minimal implementation**

```python
CREATE TABLE IF NOT EXISTS sim_scheduler_config (
    ...,
    strategy_mode TEXT DEFAULT 'auto',
    ...
)

self._ensure_column(cursor, "sim_scheduler_config", "strategy_mode", "TEXT DEFAULT 'auto'")

def update_scheduler_config(..., strategy_mode: str | None = None):
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_db.py::test_scheduler_config_persists_strategy_mode`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add quant_sim/db.py tests/test_quant_sim_db.py
git commit -m "feat: persist realtime strategy mode in scheduler config"
```

### Task 2: Thread realtime `strategy_mode` through scheduler execution

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\scheduler.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_scheduler.py`

- [ ] **Step 1: Write the failing test**

```python
def test_run_once_passes_strategy_mode_to_engine(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    scheduler = QuantSimScheduler(db_file=db_file)
    scheduler.db.update_scheduler_config(strategy_mode="neutral")

    scheduler.engine.analyze_active_candidates = Mock(return_value=[])
    scheduler.engine.analyze_positions = Mock(return_value=[])
    scheduler.portfolio.list_positions = Mock(return_value=[])
    scheduler.run_once("manual_scan")

    scheduler.engine.analyze_active_candidates.assert_called_once_with(
        analysis_timeframe="30m",
        strategy_mode="neutral",
    )
    scheduler.engine.analyze_positions.assert_called_once_with(
        analysis_timeframe="30m",
        strategy_mode="neutral",
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_scheduler.py::test_run_once_passes_strategy_mode_to_engine`
Expected: FAIL because scheduler does not yet read or pass `strategy_mode`.

- [ ] **Step 3: Write minimal implementation**

```python
config = self.db.get_scheduler_config()
analysis_timeframe = str(config["analysis_timeframe"])
strategy_mode = str(config["strategy_mode"])
candidate_signals = self.engine.analyze_active_candidates(
    analysis_timeframe=analysis_timeframe,
    strategy_mode=strategy_mode,
)
position_signals = self.engine.analyze_positions(
    analysis_timeframe=analysis_timeframe,
    strategy_mode=strategy_mode,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_scheduler.py::test_run_once_passes_strategy_mode_to_engine`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add quant_sim/scheduler.py tests/test_quant_sim_scheduler.py
git commit -m "feat: pass realtime strategy mode through scheduler"
```

### Task 3: Flatten realtime configuration UI and expose strategy controls directly

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_ui_feedback.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_quant_sim_ui_no_longer_hides_realtime_controls_in_expander():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    realtime_block = ui_source.split("def display_quant_sim()", 1)[1].split("def display_quant_replay()", 1)[0]
    assert 'with st.expander("⚙️ 定时分析设置与资金池"' not in realtime_block


def test_quant_sim_ui_exposes_strategy_mode_and_auto_execute_copy():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    realtime_block = ui_source.split("def display_quant_sim()", 1)[1].split("def display_quant_replay()", 1)[0]
    assert "策略模式" in realtime_block
    assert "自动执行模拟交易" in realtime_block
    assert "不需要等待用户确认" in realtime_block
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_ui_feedback.py::test_quant_sim_ui_no_longer_hides_realtime_controls_in_expander tests/test_quant_sim_ui_feedback.py::test_quant_sim_ui_exposes_strategy_mode_and_auto_execute_copy`
Expected: FAIL because the realtime page still uses the expander and does not expose realtime strategy mode.

- [ ] **Step 3: Write minimal implementation**

```python
st.markdown("### ⚙️ 定时分析设置与资金池")
...
strategy_mode = st.selectbox(
    "策略模式",
    options=STRATEGY_MODE_OPTIONS,
    format_func=_format_strategy_mode,
    ...
)
st.caption("开启自动执行模拟交易后，不需要等待用户确认，系统会直接按策略写入模拟买卖结果。")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_ui_feedback.py::test_quant_sim_ui_no_longer_hides_realtime_controls_in_expander tests/test_quant_sim_ui_feedback.py::test_quant_sim_ui_exposes_strategy_mode_and_auto_execute_copy`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add quant_sim/ui.py tests/test_quant_sim_ui_feedback.py
git commit -m "feat: expose realtime quant config without expander"
```

### Task 4: Move candidate add/delete/analyze actions into the candidate pool

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_ui_feedback.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_quant_sim_candidate_section_exposes_add_and_delete_actions():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    realtime_block = ui_source.split("def display_quant_sim()", 1)[1].split("def display_quant_replay()", 1)[0]
    assert "➕ 添加股票" in realtime_block
    assert "删除" in realtime_block


def test_quant_sim_candidate_section_no_longer_contains_nested_analyze_button():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    realtime_block = ui_source.split("def display_quant_sim()", 1)[1].split("def display_quant_replay()", 1)[0]
    assert "立即分析该标的" not in realtime_block
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_ui_feedback.py::test_quant_sim_candidate_section_exposes_add_and_delete_actions tests/test_quant_sim_ui_feedback.py::test_quant_sim_candidate_section_no_longer_contains_nested_analyze_button`
Expected: FAIL because candidate add is still in a separate form block and nested analyze is still present.

- [ ] **Step 3: Write minimal implementation**

```python
with tab_candidates:
    st.markdown("#### 候选池")
    if st.button("➕ 添加股票", ...):
        ...
    ...
    candidate_rows = [...]
    st.dataframe(...)
    for candidate in candidates:
        col1, col2 = st.columns(2)
        with col1:
            st.button("立即分析", key=f"candidate_analyze_{candidate['id']}")
        with col2:
            st.button("删除", key=f"candidate_delete_{candidate['id']}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_ui_feedback.py::test_quant_sim_candidate_section_exposes_add_and_delete_actions tests/test_quant_sim_ui_feedback.py::test_quant_sim_candidate_section_no_longer_contains_nested_analyze_button`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add quant_sim/ui.py tests/test_quant_sim_ui_feedback.py
git commit -m "feat: move candidate actions into quant sim candidate pool"
```

### Task 5: Make candidate-row `立即分析` honor auto-execute vs manual mode

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_ui_feedback.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_realtime_manual_scan_and_candidate_actions_share_scheduler_config_copy():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    assert "开启自动执行模拟交易后，不需要等待用户确认" in ui_source
    assert "否则 BUY / SELL 会进入“待执行信号”" in ui_source
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_ui_feedback.py::test_realtime_manual_scan_and_candidate_actions_share_scheduler_config_copy`
Expected: FAIL until the realtime UI copy and candidate analysis path are aligned with auto-execute/manual semantics.

- [ ] **Step 3: Write minimal implementation**

```python
current_strategy_mode = str(scheduler_status["strategy_mode"])
...
signal = engine.analyze_candidate(
    candidate,
    analysis_timeframe=str(scheduler_status["analysis_timeframe"]),
    strategy_mode=current_strategy_mode,
)
if scheduler_status["auto_execute"]:
    portfolio_service.auto_execute_signal(signal)
    queue_quant_sim_flash("success", "✅ 已按策略自动执行模拟交易")
else:
    queue_quant_sim_flash("success", "✅ 已生成信号，BUY/SELL 已进入待执行列表")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_ui_feedback.py::test_realtime_manual_scan_and_candidate_actions_share_scheduler_config_copy`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add quant_sim/ui.py tests/test_quant_sim_ui_feedback.py
git commit -m "feat: align candidate analysis with auto execution mode"
```

### Task 6: Reshape the realtime result area into one large candidate table plus a lower switched detail area

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_ui_feedback.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_quant_sim_ui_uses_candidate_pool_as_primary_large_table():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    realtime_block = ui_source.split("def display_quant_sim()", 1)[1].split("def display_quant_replay()", 1)[0]
    assert "候选池（主工作区）" not in realtime_block
    assert "主工作区" not in realtime_block
    assert "工作区" not in realtime_block
    assert "候选股详情" in realtime_block
    assert "执行中心" in realtime_block
    assert "账户结果" in realtime_block
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_ui_feedback.py::test_quant_sim_ui_uses_candidate_pool_as_primary_large_table`
Expected: FAIL until the lower detail area is shaped as the final B3 layout and placeholder labels are absent.

- [ ] **Step 3: Write minimal implementation**

```python
# candidate pool remains the main table
# lower area exposes only real section labels:
st.markdown("#### 执行中心")
st.markdown("#### 账户结果")
st.markdown("#### 候选股详情")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_ui_feedback.py::test_quant_sim_ui_uses_candidate_pool_as_primary_large_table`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add quant_sim/ui.py tests/test_quant_sim_ui_feedback.py
git commit -m "refactor: adopt cleaner realtime quant result layout"
```

### Task 7: Full verification and review

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\docs\superpowers\specs\2026-04-10-quant-sim-realtime-ui-design.md`
- Modify: `C:\Projects\githubs\aiagents-stock\docs\superpowers\plans\2026-04-10-quant-sim-realtime-ui.md`

- [ ] **Step 1: Review pass 1 - code/spec comparison**

Check:
- realtime config is always visible
- realtime strategy mode exists and persists
- candidate add/delete/analyze live in the candidate section
- old nested analyze button is removed
- auto-execute semantics are explicit and match runtime behavior

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
git add quant_sim/ui.py quant_sim/db.py quant_sim/scheduler.py tests docs/superpowers/specs/2026-04-10-quant-sim-realtime-ui-design.md docs/superpowers/plans/2026-04-10-quant-sim-realtime-ui.md
git commit -m "feat: streamline realtime quant simulation workspace"
```
