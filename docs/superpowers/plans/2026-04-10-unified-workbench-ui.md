# Unified Workbench UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the app into a consistent modern workbench UI across sidebar navigation, stock analysis home, realtime quant simulation, and historical replay.

**Architecture:** First establish shared visual tokens and layout helpers in `app.py` and `quant_sim/ui.py`, then refactor the sidebar and page shell, then reshape `股票分析`, `量化模拟`, and `历史回放` onto the same page skeleton. Preserve existing routing and backend behavior; only change presentation and interaction structure where the spec explicitly calls for it.

**Tech Stack:** Python, Streamlit, existing app routing in `app.py`, existing quant UI in `quant_sim/ui.py`, pytest source assertions and import checks

---

### Task 1: Add source-level tests for the unified workbench contract

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_replay_ui.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_app_uses_unified_workbench_page_header_copy():
    app_source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")

    assert "render_workbench_page_header" in app_source
    assert "stock analysis home" not in app_source


def test_quant_sim_and_replay_use_shared_layout_helpers():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")

    assert "render_quant_sim_layout_styles()" in ui_source
    assert "render_workspace_section_header(" in ui_source
    assert "render_workspace_metric_band(" in ui_source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_app_uses_unified_workbench_page_header_copy tests/test_quant_sim_replay_ui.py::test_quant_sim_and_replay_use_shared_layout_helpers`
Expected: FAIL because these helpers do not yet exist in the unified form.

- [ ] **Step 3: Write minimal implementation**

```python
def render_workbench_page_header(...):
    ...


def render_workspace_section_header(...):
    ...


def render_workspace_metric_band(...):
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_app_uses_unified_workbench_page_header_copy tests/test_quant_sim_replay_ui.py::test_quant_sim_and_replay_use_shared_layout_helpers`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_quant_sim_replay_ui.py app.py quant_sim/ui.py
git commit -m "test: define unified workbench UI contract"
```

### Task 2: Establish shared visual tokens and a consistent page shell

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\app.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_replay_ui.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_app_replaces_heavy_gradient_shell_with_light_workbench_shell():
    app_source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")

    assert "#F5F8FD" in app_source
    assert "#FBFCFF" in app_source
    assert ".workbench-shell" in app_source
    assert ".top-nav" not in app_source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_app_replaces_heavy_gradient_shell_with_light_workbench_shell`
Expected: FAIL because the old top-nav and heavy shell styles still exist.

- [ ] **Step 3: Write minimal implementation**

```python
st.markdown(
    """
    <style>
    .workbench-shell { ... }
    .workbench-page-header { ... }
    .workbench-metric-card { ... }
    </style>
    """,
    unsafe_allow_html=True,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_app_replaces_heavy_gradient_shell_with_light_workbench_shell`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app.py tests/test_quant_sim_replay_ui.py
git commit -m "style: add unified workbench shell tokens"
```

### Task 3: Rebuild the stock-analysis home page on the new workbench skeleton

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\app.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_replay_ui.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_home_page_uses_analysis_workspace_and_result_workbench_copy():
    app_source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")

    assert "分析工作区" in app_source
    assert "统一结果工作台" in app_source
    assert "选择分析师团队" not in app_source
    assert "分析师团队" in app_source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_home_page_uses_analysis_workspace_and_result_workbench_copy`
Expected: FAIL because the old home layout and labels still dominate.

- [ ] **Step 3: Write minimal implementation**

```python
left_col, right_col = st.columns([1.05, 1.35], gap="large")
with left_col:
    render_workspace_section_header("分析工作区", ...)
with right_col:
    render_workspace_section_header("统一结果工作台", ...)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_home_page_uses_analysis_workspace_and_result_workbench_copy`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app.py tests/test_quant_sim_replay_ui.py
git commit -m "refactor: rebuild stock analysis page as workbench"
```

### Task 4: Unify realtime quant simulation onto the shared workbench layout

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_ui_feedback.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_replay_ui.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_quant_sim_uses_left_config_right_workspace_structure():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")

    assert "左侧配置栏" not in ui_source
    assert 'st.columns([0.95, 2.1], gap="large")' in ui_source
    assert "执行中心" in ui_source
    assert "账户结果" in ui_source


def test_quant_sim_candidate_pool_keeps_dialog_detail_not_inline_section():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")

    assert '@st.dialog("候选股分析详情"' in ui_source
    assert "候选股详情" not in ui_source.split("def display_quant_sim()", 1)[1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_ui_feedback.py tests/test_quant_sim_replay_ui.py::test_quant_sim_uses_left_config_right_workspace_structure tests/test_quant_sim_replay_ui.py::test_quant_sim_candidate_pool_keeps_dialog_detail_not_inline_section`
Expected: FAIL until the new layout is wired.

- [ ] **Step 3: Write minimal implementation**

```python
config_col, workspace_col = st.columns([0.95, 2.1], gap="large")
with config_col:
    render_quant_sim_config_rail(...)
with workspace_col:
    render_workspace_metric_band(...)
    render_quant_sim_candidate_pool(...)
    render_quant_sim_workspace_tabs(...)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_ui_feedback.py tests/test_quant_sim_replay_ui.py::test_quant_sim_uses_left_config_right_workspace_structure tests/test_quant_sim_replay_ui.py::test_quant_sim_candidate_pool_keeps_dialog_detail_not_inline_section`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add quant_sim/ui.py tests/test_quant_sim_ui_feedback.py tests/test_quant_sim_replay_ui.py
git commit -m "refactor: align realtime quant sim to workbench layout"
```

### Task 5: Unify historical replay onto the shared workbench layout

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_replay_ui.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_quant_replay_uses_left_task_rail_and_right_result_panel():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    replay_block = ui_source.split("def display_quant_replay()", 1)[1]

    assert 'st.columns([0.95, 2.1], gap="large")' in replay_block
    assert "当前回放任务" in replay_block
    assert "所有回放任务" in replay_block
    assert "回放结果" in replay_block
    assert "资金曲线" in replay_block
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_quant_replay_uses_left_task_rail_and_right_result_panel`
Expected: FAIL until replay adopts the same shell.

- [ ] **Step 3: Write minimal implementation**

```python
task_col, result_col = st.columns([0.95, 2.1], gap="large")
with task_col:
    render_replay_configuration(...)
    render_replay_run_overview_list(...)
with result_col:
    render_replay_run_detail_panel(...)
    render_replay_results(...)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_quant_replay_uses_left_task_rail_and_right_result_panel`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add quant_sim/ui.py tests/test_quant_sim_replay_ui.py
git commit -m "refactor: align replay UI to unified workbench"
```

### Task 6: Run full verification and prepare the branch for design review

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\app.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_replay_ui.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_ui_feedback.py`

- [ ] **Step 1: Run the targeted UI tests**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py tests/test_quant_sim_ui_feedback.py`
Expected: PASS.

- [ ] **Step 2: Run broader quant/UI regression**

Run: `python -m pytest -q -p no:cacheprovider tests`
Expected: PASS.

- [ ] **Step 3: Run import and compile verification**

Run: `python -c "import app; print('app-import-ok')"`
Expected: `app-import-ok`

Run: `python -m compileall app.py quant_sim`
Expected: exit 0

- [ ] **Step 4: Commit**

```powershell
git add app.py quant_sim/ui.py tests/test_quant_sim_replay_ui.py tests/test_quant_sim_ui_feedback.py
git commit -m "feat: implement unified workbench UI shell"
```
