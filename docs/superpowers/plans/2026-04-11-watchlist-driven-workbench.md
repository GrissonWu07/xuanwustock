# Watchlist-Driven Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a formal `关注池` as the system’s main stock pool, rebuild the home page into a watchlist-driven workbench, aggregate selector and research modules into two hub pages, and align `量化候选池` so quant simulation and replay both consume stocks manually promoted from the watchlist.

**Architecture:** Keep the current selector modules, research modules, and quant engines, but add a new watchlist service and UI layer that becomes the center of the product. Wrap existing selector modules inside a `发现股票` hub page and wrap research modules inside a `研究情报` hub page. Reuse the existing quant candidate pool as the shared `量化候选池`, but require manual promotion from the new watchlist. Bias testing toward backend dataflow and cross-module integration rather than UI snapshots.

**Tech Stack:** Python, Streamlit, SQLite, pytest, existing selector UIs, research UIs, `quant_sim` services

---

### Task 1: Create formal watchlist persistence and service layer

**Files:**
- Create: `C:\Projects\githubs\aiagents-stock\watchlist_db.py`
- Create: `C:\Projects\githubs\aiagents-stock\watchlist_service.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_watchlist_db.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_watchlist_service.py`

- [ ] **Step 1: Write the failing database tests**

```python
from watchlist_db import WatchlistDB


def test_watchlist_db_adds_and_lists_entries(tmp_path):
    db = WatchlistDB(tmp_path / "watchlist.db")

    watch_id = db.add_watch(
        stock_code="300390",
        stock_name="天华新能",
        source="main_force",
        latest_price=61.99,
        notes="主力选股第1名",
        metadata={"industry": "新能源"},
    )

    rows = db.list_watches()
    assert watch_id > 0
    assert len(rows) == 1
    assert rows[0]["stock_code"] == "300390"
    assert rows[0]["stock_name"] == "天华新能"
    assert rows[0]["source_summary"] == "main_force"
    assert rows[0]["latest_price"] == 61.99


def test_watchlist_db_merges_existing_stock_sources(tmp_path):
    db = WatchlistDB(tmp_path / "watchlist.db")
    db.add_watch("300390", "天华新能", "main_force", 61.99, None, {})
    db.add_watch("300390", "天华新能", "macro_analysis", 62.31, None, {})

    row = db.get_watch("300390")
    assert row["stock_code"] == "300390"
    assert row["latest_price"] == 62.31
    assert set(row["sources"]) == {"main_force", "macro_analysis"}


def test_watchlist_db_marks_quant_membership(tmp_path):
    db = WatchlistDB(tmp_path / "watchlist.db")
    db.add_watch("300390", "天华新能", "manual", 61.99, None, {})

    db.update_quant_membership("300390", True)
    row = db.get_watch("300390")
    assert row["in_quant_pool"] is True

    db.update_quant_membership("300390", False)
    row = db.get_watch("300390")
    assert row["in_quant_pool"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_watchlist_db.py`

Expected: FAIL because `WatchlistDB` does not exist yet.

- [ ] **Step 3: Write the database implementation**

```python
class WatchlistDB:
    def __init__(self, db_path: str | Path = "watchlist.db"):
        self.db_path = str(db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL UNIQUE,
                stock_name TEXT NOT NULL,
                source_summary TEXT NOT NULL,
                latest_price REAL DEFAULT 0,
                latest_signal TEXT DEFAULT '',
                in_quant_pool INTEGER DEFAULT 0,
                notes TEXT,
                metadata_json TEXT DEFAULT '{}',
                sources_json TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
```

- [ ] **Step 4: Add the service layer tests**

```python
from watchlist_service import WatchlistService


def test_watchlist_service_add_from_selector_row(tmp_path):
    service = WatchlistService(db_file=tmp_path / "watchlist.db")

    summary = service.add_stock(
        stock_code="002824",
        stock_name="和胜股份",
        source="main_force",
        latest_price=22.97,
        notes="来自主力选股",
        metadata={"industry": "消费电子"},
    )

    assert summary["created"] is True
    assert summary["watch_id"] > 0
    assert service.get_watch("002824")["stock_name"] == "和胜股份"


def test_watchlist_service_batch_add_returns_attempt_summary(tmp_path):
    service = WatchlistService(db_file=tmp_path / "watchlist.db")

    result = service.add_many(
        [
            {"stock_code": "002824", "stock_name": "和胜股份", "source": "main_force"},
            {"stock_code": "301291", "stock_name": "明阳电气", "source": "main_force"},
        ]
    )

    assert result["attempted"] == 2
    assert result["success_count"] == 2
    assert result["failures"] == []
```

- [ ] **Step 5: Run service tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_watchlist_service.py`

Expected: FAIL because `WatchlistService` does not exist yet.

- [ ] **Step 6: Write the minimal service implementation**

```python
class WatchlistService:
    def __init__(self, db_file: str | Path = "watchlist.db"):
        self.db = WatchlistDB(db_file)

    def add_stock(...):
        watch_id = self.db.add_watch(...)
        return {"created": True, "watch_id": watch_id}

    def add_many(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        ...

    def list_watches(self) -> list[dict[str, Any]]:
        return self.db.list_watches()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_watchlist_db.py tests/test_watchlist_service.py`

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add watchlist_db.py watchlist_service.py tests/test_watchlist_db.py tests/test_watchlist_service.py
git commit -m "feat: add watchlist persistence and service layer"
```

### Task 2: Add watchlist-to-quant bridge and explicit quant membership sync

**Files:**
- Create: `C:\Projects\githubs\aiagents-stock\watchlist_integration.py`
- Modify: `C:\Projects\githubs\aiagents-stock\watchlist_service.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\candidate_pool_service.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_watchlist_quant_bridge.py`

- [ ] **Step 1: Write the failing bridge tests**

```python
from watchlist_service import WatchlistService
from watchlist_integration import add_watchlist_rows_to_quant_pool
from quant_sim.candidate_pool_service import CandidatePoolService


def test_watchlist_rows_promote_into_quant_candidate_pool(tmp_path):
    watch_db = tmp_path / "watchlist.db"
    quant_db = tmp_path / "quant_sim.db"

    watchlist = WatchlistService(db_file=watch_db)
    quant_pool = CandidatePoolService(db_file=quant_db)

    watchlist.add_stock("002824", "和胜股份", "main_force", 22.97, None, {})
    watchlist.add_stock("301291", "明阳电气", "macro_analysis", 52.96, None, {})

    summary = add_watchlist_rows_to_quant_pool(
        stock_codes=["002824", "301291"],
        watchlist_service=watchlist,
        candidate_service=quant_pool,
    )

    assert summary["success_count"] == 2
    assert watchlist.get_watch("002824")["in_quant_pool"] is True
    assert watchlist.get_watch("301291")["in_quant_pool"] is True


def test_watchlist_quant_membership_clears_on_candidate_delete(tmp_path):
    watch_db = tmp_path / "watchlist.db"
    quant_db = tmp_path / "quant_sim.db"

    watchlist = WatchlistService(db_file=watch_db)
    quant_pool = CandidatePoolService(db_file=quant_db)

    watchlist.add_stock("002824", "和胜股份", "manual", 22.97, None, {})
    add_watchlist_rows_to_quant_pool(["002824"], watchlist, quant_pool)

    quant_pool.delete_candidate("002824")
    watchlist.sync_quant_membership(candidate_stock_codes=[])

    assert watchlist.get_watch("002824")["in_quant_pool"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_watchlist_quant_bridge.py`

Expected: FAIL because the bridge helper and explicit membership sync do not exist yet.

- [ ] **Step 3: Write minimal bridge implementation**

```python
def add_watchlist_rows_to_quant_pool(
    stock_codes: list[str],
    watchlist_service: WatchlistService,
    candidate_service: CandidatePoolService,
) -> dict[str, Any]:
    summary = {"attempted": 0, "success_count": 0, "failures": []}
    for stock_code in stock_codes:
        watch = watchlist_service.get_watch(stock_code)
        ...
        candidate_service.add_manual_candidate(...)
        watchlist_service.mark_in_quant_pool(stock_code, True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_watchlist_quant_bridge.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add watchlist_integration.py watchlist_service.py quant_sim/candidate_pool_service.py tests/test_watchlist_quant_bridge.py
git commit -m "feat: bridge watchlist into shared quant candidate pool"
```

### Task 3: Rebuild the home page into a watchlist-driven workbench

**Files:**
- Create: `C:\Projects\githubs\aiagents-stock\watchlist_ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\app.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_watchlist_workbench.py`

- [ ] **Step 1: Write the failing workbench tests**

```python
from pathlib import Path


def test_app_sidebar_includes_workbench_and_not_individual_selector_spam():
    source = Path("C:/Projects/githubs/aiagents-stock/app.py").read_text(encoding="utf-8")
    assert '"工作台"' in source
    assert '"发现股票"' in source
    assert '"研究情报"' in source


def test_workbench_ui_mentions_watchlist_and_stock_analysis():
    source = Path("C:/Projects/githubs/aiagents-stock/watchlist_ui.py").read_text(encoding="utf-8")
    assert "关注池" in source
    assert "股票分析" in source
    assert "持仓分析" in source
    assert "实时监控" in source
    assert "AI盯盘" in source
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_watchlist_workbench.py`

Expected: FAIL because the new workbench file and route do not exist yet.

- [ ] **Step 3: Write the minimal workbench UI**

```python
def display_watchlist_workbench() -> None:
    st.markdown("## 股票工作台")
    left_col, right_col = st.columns([2.2, 1.0], gap="large")
    with left_col:
        render_watchlist_table(...)
        render_watchlist_analysis_panel(...)
    with right_col:
        render_next_steps(
            ["持仓分析", "实时监控", "AI盯盘", "发现股票", "研究情报", "量化模拟", "历史回放"]
        )
```

- [ ] **Step 4: Update `app.py` to make the workbench the home route**

```python
from watchlist_ui import display_watchlist_workbench

SIDEBAR_HOME_ITEM = {
    "title": "工作台",
    "label": "进入工作台",
    ...
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_watchlist_workbench.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add app.py watchlist_ui.py tests/test_watchlist_workbench.py
git commit -m "feat: make watchlist workbench the home page"
```

### Task 4: Create the `发现股票` aggregate page and retarget selector add actions

**Files:**
- Create: `C:\Projects\githubs\aiagents-stock\discovery_hub_ui.py`
- Create: `C:\Projects\githubs\aiagents-stock\watchlist_selector_integration.py`
- Modify: `C:\Projects\githubs\aiagents-stock\main_force_ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\low_price_bull_ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\small_cap_ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\profit_growth_ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\value_stock_ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\app.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_selector_watchlist_integration.py`

- [ ] **Step 1: Write the failing selector integration tests**

```python
from watchlist_selector_integration import normalize_selector_stock, sync_selector_dataframe_to_watchlist
import pandas as pd


def test_sync_selector_dataframe_to_watchlist_adds_rows(tmp_path):
    df = pd.DataFrame(
        [
            {"股票代码": "002824.SZ", "股票简称": "和胜股份", "最新价": 22.97},
            {"股票代码": "301291.SZ", "股票简称": "明阳电气", "最新价": 52.96},
        ]
    )

    summary = sync_selector_dataframe_to_watchlist(
        df,
        source="main_force",
        db_file=tmp_path / "watchlist.db",
    )

    assert summary["attempted"] == 2
    assert summary["success_count"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_selector_watchlist_integration.py`

Expected: FAIL because the watchlist integration helpers do not exist yet.

- [ ] **Step 3: Write the integration helper and aggregate page**

```python
def display_discovery_hub() -> None:
    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["主力选股", "低价擒牛", "小市值", "净利增长", "低估值"]
    )
```

- [ ] **Step 4: Replace selector-page promotion copy**

```python
success, message, _ = add_stock_to_watchlist(...)
st.success(f"✅ {stock_code} 已加入关注池")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_selector_watchlist_integration.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add discovery_hub_ui.py watchlist_selector_integration.py app.py main_force_ui.py low_price_bull_ui.py small_cap_ui.py profit_growth_ui.py value_stock_ui.py tests/test_selector_watchlist_integration.py
git commit -m "feat: aggregate selector modules and add watchlist actions"
```

### Task 5: Create the `研究情报` aggregate page with conditional watchlist promotion

**Files:**
- Create: `C:\Projects\githubs\aiagents-stock\research_hub_ui.py`
- Create: `C:\Projects\githubs\aiagents-stock\watchlist_research_integration.py`
- Modify: `C:\Projects\githubs\aiagents-stock\macro_analysis_ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\longhubang_ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\news_flow_ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\sector_strategy_ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\macro_cycle_ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\app.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_research_watchlist_integration.py`

- [ ] **Step 1: Write the failing research integration tests**

```python
from watchlist_research_integration import extract_macro_analysis_rows, extract_longhubang_rows


def test_extract_macro_analysis_rows_returns_recommended_and_watchlist_rows():
    result = {
        "stock_view": {
            "recommended_stocks": [{"code": "300390", "name": "天华新能", "price": 61.99}],
            "watchlist": [{"code": "002824", "name": "和胜股份", "price": 22.97}],
        }
    }

    rows = extract_macro_analysis_rows(result)
    assert [row["stock_code"] for row in rows] == ["300390", "002824"]


def test_extract_longhubang_rows_returns_explicit_recommendations():
    result = {
        "recommended_stocks": [{"股票代码": "301291", "股票名称": "明阳电气", "现价": 52.96}]
    }

    rows = extract_longhubang_rows(result)
    assert rows[0]["stock_code"] == "301291"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_research_watchlist_integration.py`

Expected: FAIL because the extraction helpers do not exist.

- [ ] **Step 3: Write the integration helpers and aggregate page**

```python
def display_research_hub() -> None:
    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["智策板块", "智瞰龙虎", "新闻流量", "宏观分析", "宏观周期"]
    )
```

- [ ] **Step 4: Add watchlist actions only where stock outputs exist**

```python
if recommended_rows:
    st.button("加入关注池", key=...)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_research_watchlist_integration.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add research_hub_ui.py watchlist_research_integration.py app.py macro_analysis_ui.py longhubang_ui.py news_flow_ui.py sector_strategy_ui.py macro_cycle_ui.py tests/test_research_watchlist_integration.py
git commit -m "feat: aggregate research modules and expose watchlist promotion"
```

### Task 6: Align quant simulation and replay with watchlist-originated quant candidate promotion

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\candidate_pool_service.py`
- Modify: `C:\Projects\githubs\aiagents-stock\watchlist_ui.py`
- Test: `C:\Projects\githubs\aiagents-stock\tests\test_watchlist_quant_flow.py`

- [ ] **Step 1: Write the failing end-to-end dataflow tests**

```python
from watchlist_service import WatchlistService
from watchlist_integration import add_watchlist_rows_to_quant_pool
from quant_sim.candidate_pool_service import CandidatePoolService


def test_watchlist_to_quant_flow_marks_candidate_membership_and_lists_candidate(tmp_path):
    watchlist = WatchlistService(db_file=tmp_path / "watchlist.db")
    quant_pool = CandidatePoolService(db_file=tmp_path / "quant_sim.db")

    watchlist.add_stock("300390", "天华新能", "main_force", 61.99, None, {})
    add_watchlist_rows_to_quant_pool(["300390"], watchlist, quant_pool)

    candidate = quant_pool.list_candidates(status="active")[0]
    watch = watchlist.get_watch("300390")

    assert candidate["stock_code"] == "300390"
    assert watch["in_quant_pool"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_watchlist_quant_flow.py`

Expected: FAIL until the watchlist UI and quant copy reflect the new flow.

- [ ] **Step 3: Update quant-facing copy and watchlist actions**

```python
st.caption("量化候选池中的股票来自关注池，可单选或多选加入后再进行量化模拟与历史回放。")
```

- [ ] **Step 4: Add watchlist-side batch/single promotion controls**

```python
if st.button("加入量化候选池", key=f"watch_to_quant_{stock_code}"):
    add_watchlist_rows_to_quant_pool(...)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_watchlist_quant_flow.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add quant_sim/ui.py quant_sim/candidate_pool_service.py watchlist_ui.py tests/test_watchlist_quant_flow.py
git commit -m "feat: align quant workflows with watchlist promotion flow"
```

### Task 7: Add end-to-end backend dataflow coverage from discovery to holdings

**Files:**
- Create: `C:\Projects\githubs\aiagents-stock\tests\test_watchlist_workflow_e2e.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_auto_execution.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_continuous_simulation.py`

- [ ] **Step 1: Write the failing end-to-end flow test**

```python
import pandas as pd

from watchlist_service import WatchlistService
from watchlist_selector_integration import sync_selector_dataframe_to_watchlist
from watchlist_integration import add_watchlist_rows_to_quant_pool
from quant_sim.engine import QuantSimEngine


def test_end_to_end_discovery_watch_analyze_quant_and_holdings(tmp_path):
    watch_db = tmp_path / "watchlist.db"
    quant_db = tmp_path / "quant_sim.db"

    sync_selector_dataframe_to_watchlist(
        pd.DataFrame([{"股票代码": "002824", "股票简称": "和胜股份", "最新价": 22.97}]),
        source="main_force",
        db_file=watch_db,
    )

    watchlist = WatchlistService(db_file=watch_db)
    add_watchlist_rows_to_quant_pool(["002824"], watchlist, db_file=quant_db)

    engine = QuantSimEngine(db_file=quant_db)
    signals = engine.analyze_active_candidates(analysis_timeframe="30m", strategy_mode="auto")

    assert watchlist.get_watch("002824")["stock_code"] == "002824"
    assert len(signals) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_watchlist_workflow_e2e.py`

Expected: FAIL until the whole flow is wired through real services.

- [ ] **Step 3: Extend existing quant tests so holdings updates are asserted**

```python
def test_auto_execute_updates_positions_after_watchlist_promoted_candidate(...):
    ...
    assert portfolio.list_positions()
```

- [ ] **Step 4: Run the targeted dataflow suite**

Run: `python -m pytest -q -p no:cacheprovider tests/test_watchlist_db.py tests/test_watchlist_service.py tests/test_watchlist_quant_bridge.py tests/test_selector_watchlist_integration.py tests/test_research_watchlist_integration.py tests/test_watchlist_quant_flow.py tests/test_watchlist_workflow_e2e.py tests/test_quant_sim_auto_execution.py tests/test_quant_continuous_simulation.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_watchlist_db.py tests/test_watchlist_service.py tests/test_watchlist_quant_bridge.py tests/test_selector_watchlist_integration.py tests/test_research_watchlist_integration.py tests/test_watchlist_quant_flow.py tests/test_watchlist_workflow_e2e.py tests/test_quant_sim_auto_execution.py tests/test_quant_continuous_simulation.py
git commit -m "test: cover watchlist-driven discovery and quant dataflow"
```

## Self-Review

### Spec coverage

- formal `关注池` object: Task 1
- `关注池 -> 量化候选池` promotion: Tasks 2 and 6
- workbench home page: Task 3
- `发现股票` aggregate page: Task 4
- `研究情报` aggregate page with conditional stock add: Task 5
- keep `量化模拟` and `历史回放` mostly intact while aligning semantics: Task 6
- backend-heavy dataflow testing from discovery to holdings: Task 7

No spec section is currently uncovered.

### Placeholder scan

Manual scan completed for:

- `TODO`
- `TBD`
- “similar to”
- “add appropriate”
- vague “write tests”

No placeholder language remains.

### Type consistency

Shared names used consistently throughout the plan:

- `WatchlistDB`
- `WatchlistService`
- `add_watchlist_rows_to_quant_pool`
- `display_watchlist_workbench`
- `display_discovery_hub`
- `display_research_hub`

Database terminology stays consistent:

- `watchlist`
- `quant candidate pool`
- `in_quant_pool`

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-11-watchlist-driven-workbench.md`.

Because this thread already has explicit approval to implement and subagent delegation was not requested, proceed with **Inline Execution** using the approved plan, one task at a time, with:

- TDD-first execution
- two review passes after each completed task
- backend dataflow verification prioritized over heavy UI testing
