# Sidebar Navigation Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the heavy expander/button-based sidebar with a lighter card-group navigation while preserving all existing destinations and removing the low-value current-model block.

**Architecture:** Keep all existing page flags and routing behavior in `app.py`, but centralize sidebar rendering into helper functions plus local CSS for grouped cards and compact nav rows. The new sidebar will remove expander chrome, use grouped cards for `选股 / 策略 / 投资管理 / 系统`, and compute a selected-state cue from the current session flags.

**Tech Stack:** Python, Streamlit, existing session-state routing in `app.py`, pytest source assertions

---

### Task 1: Add source-level tests for the modern sidebar contract

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_replay_ui.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_sidebar_navigation_uses_grouped_cards_instead_of_expanders():
    source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")
    sidebar_block = source.split("with st.sidebar:", 1)[1].split("# 检查是否显示历史记录", 1)[0]

    assert "render_sidebar_navigation()" in source
    assert 'with st.expander("🎯 选股板块"' not in sidebar_block
    assert 'with st.expander("📊 策略分析"' not in sidebar_block
    assert 'with st.expander("💼 投资管理"' not in sidebar_block


def test_sidebar_navigation_removes_current_model_block():
    source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")

    assert "show_current_model_info()" not in source
    assert "当前模型:" not in source
    assert "🤖 AI模型" not in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_sidebar_navigation_uses_grouped_cards_instead_of_expanders tests/test_quant_sim_replay_ui.py::test_sidebar_navigation_removes_current_model_block`
Expected: FAIL because the sidebar still uses expanders and still renders the current-model block.

- [ ] **Step 3: Write minimal implementation**

```python
def render_sidebar_navigation() -> None:
    ...


with st.sidebar:
    render_sidebar_navigation()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_sidebar_navigation_uses_grouped_cards_instead_of_expanders tests/test_quant_sim_replay_ui.py::test_sidebar_navigation_removes_current_model_block`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app.py tests/test_quant_sim_replay_ui.py
git commit -m "refactor: add modern sidebar navigation helpers"
```

### Task 2: Build compact card-group sidebar styles and row renderers

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\app.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_replay_ui.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_sidebar_navigation_exposes_card_group_css_helpers():
    source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")

    assert "render_sidebar_nav_styles" in source
    assert "sidebar-nav-card" in source
    assert "sidebar-nav-item" in source
    assert "sidebar-nav-item active" in source or "sidebar-nav-item active" in source.replace("'", '"')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_sidebar_navigation_exposes_card_group_css_helpers`
Expected: FAIL because the CSS helper and nav-card classes do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def render_sidebar_nav_styles() -> None:
    st.markdown(
        '''
        <style>
        .sidebar-nav-card { ... }
        .sidebar-nav-item { ... }
        .sidebar-nav-item.active { ... }
        </style>
        ''',
        unsafe_allow_html=True,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_sidebar_navigation_exposes_card_group_css_helpers`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app.py tests/test_quant_sim_replay_ui.py
git commit -m "feat: add modern sidebar card styling"
```

### Task 3: Replace expander groups with compact navigation cards and selected-state rows

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\app.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_replay_ui.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_sidebar_navigation_lists_all_expected_groups_and_destinations():
    source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")

    for label in ["选股", "策略", "投资管理", "系统"]:
        assert label in source
    for destination in ["主力选股", "低价擒牛", "小市值策略", "净利增长", "低估值策略",
                        "智策板块", "智瞰龙虎", "新闻流量", "宏观分析", "宏观周期",
                        "持仓分析", "量化模拟", "历史回放", "AI盯盘", "实时监测",
                        "历史记录", "环境配置"]:
        assert destination in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_sidebar_navigation_lists_all_expected_groups_and_destinations`
Expected: FAIL or remain incomplete until grouped rendering is fully wired.

- [ ] **Step 3: Write minimal implementation**

```python
def render_sidebar_nav_group(title: str, items: list[dict], active_view: str) -> None:
    ...


def build_sidebar_nav_groups() -> list[dict]:
    return [...]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_sidebar_navigation_lists_all_expected_groups_and_destinations`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app.py tests/test_quant_sim_replay_ui.py
git commit -m "refactor: render grouped sidebar navigation cards"
```

### Task 4: Preserve existing routing behavior through a centralized nav-action helper

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\app.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_replay_ui.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_sidebar_navigation_keeps_quant_sim_and_replay_routes_accessible():
    source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")

    assert 'key="nav_quant_sim"' in source
    assert 'key="nav_quant_replay"' in source
    assert "show_quant_sim" in source
    assert "show_quant_replay" in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_sidebar_navigation_keeps_quant_sim_and_replay_routes_accessible`
Expected: If the refactor temporarily breaks these keys or flags, this test should fail before the final implementation settles.

- [ ] **Step 3: Write minimal implementation**

```python
def activate_sidebar_view(target_flag: str, clear_flags: list[str]) -> None:
    st.session_state[target_flag] = True
    for key in clear_flags:
        if key in st.session_state:
            del st.session_state[key]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py::test_sidebar_navigation_keeps_quant_sim_and_replay_routes_accessible`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app.py tests/test_quant_sim_replay_ui.py
git commit -m "refactor: centralize sidebar navigation routing"
```

### Task 5: Verify the refactor and remove the old sidebar-only model/meta noise

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\app.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_replay_ui.py`

- [ ] **Step 1: Run focused sidebar tests**

Run: `python -m pytest -q -p no:cacheprovider tests/test_quant_sim_replay_ui.py`
Expected: PASS.

- [ ] **Step 2: Run broader import validation**

Run: `python -c "import app; print('app-import-ok')"`
Expected: `app-import-ok`

- [ ] **Step 3: Run targeted compile validation**

Run: `python -m compileall app.py`
Expected: exit 0

- [ ] **Step 4: Commit**

```powershell
git add app.py tests/test_quant_sim_replay_ui.py
git commit -m "style: modernize sidebar navigation layout"
```
