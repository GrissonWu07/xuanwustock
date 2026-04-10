# Quant Kernel Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `quant_kernel` the real reusable strategy core for `quant_sim`, add dynamic `regime × 基本面质量 -> 风格 -> 时间框架` strategy selection, persist and display per-stock strategy basics, and keep replay/continuous simulation aligned with the approved spec.

**Architecture:** Keep `quant_sim` as the Streamlit/UI/persistence shell and move strategy semantics into `quant_kernel`. Reuse only main-project data/model providers, persist strategy profiles with every signal, and make replay/realtime both call the same kernel runtime. The first supported execution modes are `30m`, `1d`, and `1d+30m 共振`.

**Tech Stack:** Python, Streamlit, SQLite, pytest, pytdx-backed market data, main-project model providers, vendored `stockpolicy` strategy concepts

---

### Task 1: Define kernel strategy profile primitives

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_kernel\models.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_kernel\config.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_kernel_core.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_kernel_runtime_derives_dynamic_strategy_profile():
    ...
    assert strategy_profile["market_regime"]["label"] == "牛市"
    assert strategy_profile["fundamental_quality"]["label"] == "强基本面"
    assert strategy_profile["risk_style"]["label"] == "激进"
    assert strategy_profile["analysis_timeframe"]["key"] == "30m"


def test_kernel_runtime_changes_style_when_regime_weakens():
    ...
    assert bull_decision.strategy_profile["risk_style"]["label"] == "激进"
    assert weak_decision.strategy_profile["risk_style"]["label"] == "保守"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_quant_kernel_core.py
```

Expected: FAIL because `Decision` does not expose strategy profile data and runtime does not accept timeframe-aware dynamic profile inputs yet.

- [ ] **Step 3: Add the minimal model/config implementation**

```python
@dataclass(slots=True)
class StrategyProfile:
    market_regime: dict[str, object]
    fundamental_quality: dict[str, object]
    risk_style: dict[str, object]
    analysis_timeframe: dict[str, object]
    effective_thresholds: dict[str, object]


@dataclass(slots=True)
class Decision:
    ...
    strategy_profile: StrategyProfile | dict[str, object] | None = None
```

- [ ] **Step 4: Run tests to verify the models/config support the new shape**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_quant_kernel_core.py
```

Expected: fewer failures, with remaining failures isolated to runtime logic rather than missing fields/signatures.

- [ ] **Step 5: Commit**

```powershell
git add quant_kernel/models.py quant_kernel/config.py tests/test_quant_kernel_core.py
git commit -m "feat: add strategy profile kernel primitives"
```

### Task 2: Implement dynamic regime, quality, style, and timeframe selection in `quant_kernel`

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_kernel\runtime.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_kernel\decision_engine.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_kernel_core.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_stockpolicy_adapter.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_runtime_uses_timeframe_to_change_thresholds():
    ...
    assert daily_decision.strategy_profile["effective_thresholds"] != intraday_decision.strategy_profile["effective_thresholds"]


def test_adapter_passes_analysis_timeframe_to_runtime():
    ...
    assert fake_runtime.calls[0]["analysis_timeframe"] == "1d+30m"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_quant_kernel_core.py tests/test_quant_sim_stockpolicy_adapter.py
```

Expected: FAIL because runtime and adapter still do not compute/passthrough dynamic timeframe-aware strategy profiles.

- [ ] **Step 3: Implement the runtime logic**

```python
def evaluate_candidate(..., analysis_timeframe: str = "1d") -> Decision:
    regime = self._derive_market_regime(market_snapshot, current_time)
    quality = self._derive_fundamental_quality(candidate)
    style = self._derive_risk_style(regime, quality)
    timeframe_profile = self._resolve_timeframe_profile(analysis_timeframe)
    thresholds = self._build_effective_thresholds(style, timeframe_profile)
    ...
    return Decision(..., strategy_profile={...})
```

- [ ] **Step 4: Run tests to verify runtime behavior**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_quant_kernel_core.py tests/test_quant_sim_stockpolicy_adapter.py
```

Expected: PASS.

- [ ] **Step 5: Review pass 1**

Check:
- runtime no longer hides strategy mapping in UI
- style mapping is deterministic in code
- thresholds differ across supported timeframe modes
- adapter is a provider-binding layer only

- [ ] **Step 6: Commit**

```powershell
git add quant_kernel/runtime.py quant_kernel/decision_engine.py tests/test_quant_kernel_core.py tests/test_quant_sim_stockpolicy_adapter.py
git commit -m "feat: add dynamic kernel strategy profiles"
```

### Task 3: Persist strategy profile and expose selector metadata to the kernel

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\signal_center_service.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\db.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\integration.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\candidate_pool_service.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_services.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_integration.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_signal_center_persists_strategy_profile():
    ...
    assert signals[0]["strategy_profile"]["risk_style"]["label"] == "激进"


def test_selector_sync_forwards_fundamental_metadata():
    ...
    assert call["metadata"]["profit_growth_pct"] == 35.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_quant_sim_services.py tests/test_quant_sim_integration.py
```

Expected: FAIL because signal persistence and selector sync still drop strategy/fundamental metadata.

- [ ] **Step 3: Implement persistence and metadata normalization**

```python
def _normalize_strategy_profile(profile: dict[str, object] | None) -> str | None:
    return json.dumps(profile, ensure_ascii=False) if profile else None


def sync_selector_dataframe_to_quant_sim(...):
    metadata = extract_selector_metadata(row)
    add_stock_to_quant_sim(..., metadata=metadata)
```

- [ ] **Step 4: Run tests to verify persistence works**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_quant_sim_services.py tests/test_quant_sim_integration.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add quant_sim/signal_center_service.py quant_sim/db.py quant_sim/integration.py quant_sim/candidate_pool_service.py tests/test_quant_sim_services.py tests/test_quant_sim_integration.py
git commit -m "feat: persist strategy profiles and selector metadata"
```

### Task 4: Fix replay datetime semantics and chronological metrics

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\replay_service.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_replay_engine.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_replay_ui.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_replay_service_uses_now_when_end_datetime_missing():
    ...
    assert run["end_datetime"] == "2026-04-09T15:00:00"


def test_replay_metrics_use_chronological_snapshots():
    ...
    assert metrics["max_drawdown_pct"] == expected_drawdown
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_quant_replay_engine.py tests/test_quant_sim_replay_ui.py
```

Expected: FAIL because replay still mishandles optional end datetime or reversed snapshots.

- [ ] **Step 3: Implement replay fixes**

```python
def _resolve_end_datetime(end_datetime):
    return parse_or_now(end_datetime)


def _sort_snapshots_chronologically(rows):
    return sorted(rows, key=lambda row: row["recorded_at"])
```

- [ ] **Step 4: Run tests to verify replay semantics**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_quant_replay_engine.py tests/test_quant_sim_replay_ui.py
```

Expected: PASS.

- [ ] **Step 5: Review pass 2**

Check:
- replay UI supports start/end datetime
- end may be omitted and means “through now”
- metrics and handoff consume chronological snapshots only

- [ ] **Step 6: Commit**

```powershell
git add quant_sim/replay_service.py quant_sim/ui.py tests/test_quant_replay_engine.py tests/test_quant_sim_replay_ui.py
git commit -m "fix: align replay datetime and metrics semantics"
```

### Task 5: Show per-stock strategy basics in the Streamlit UI

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_ui_feedback.py`

- [ ] **Step 1: Write the failing test**

```python
def test_strategy_signal_ui_renders_strategy_basics():
    rendered = render_strategy_profile_summary(
        {
            "market_regime": {"label": "牛市"},
            "fundamental_quality": {"label": "强基本面"},
            "risk_style": {"label": "激进"},
            "analysis_timeframe": {"key": "30m"},
        }
    )
    assert "市场状态" in rendered
    assert "基本面质量" in rendered
    assert "当前风格" in rendered
    assert "时间框架" in rendered
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_quant_sim_ui_feedback.py
```

Expected: FAIL because the UI does not render strategy basics yet.

- [ ] **Step 3: Implement the minimal UI renderer**

```python
def render_strategy_profile_summary(strategy_profile: dict[str, object] | None) -> str:
    ...
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_quant_sim_ui_feedback.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add quant_sim/ui.py tests/test_quant_sim_ui_feedback.py
git commit -m "feat: show strategy basics for each quant signal"
```

### Task 6: Add repo-local `pytdx` host configuration

**Files:**
- Create: `C:\Projects\githubs\aiagents-stock\config\pytdx_hosts.json`
- Create: `C:\Projects\githubs\aiagents-stock\pytdx_host_config.py`
- Modify: `C:\Projects\githubs\aiagents-stock\config.py`
- Modify: `C:\Projects\githubs\aiagents-stock\smart_monitor_tdx_data.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_smart_monitor_tdx_data.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_fetcher_loads_repo_local_pytdx_hosts_before_bundled_defaults(tmp_path, monkeypatch):
    ...
    assert fetcher.hosts[0] == ("上证云成都电信一", "218.6.170.47", 7709)


def test_fetcher_deduplicates_repo_host_file_and_env_fallbacks(tmp_path, monkeypatch):
    ...
    assert fetcher.hosts == [
        ("primary", "1.1.1.1", 7709),
        ("成都", "218.6.170.47", 7709),
        ("fallback-123.125.108.14", "123.125.108.14", 7709),
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_smart_monitor_tdx_data.py
```

Expected: FAIL because no repo-local host loader exists yet.

- [ ] **Step 3: Implement the host-file loader and config wiring**

```python
def load_pytdx_hosts(config_file: str | Path | None) -> list[tuple[str, str, int]]:
    ...
    return hosts
```

- [ ] **Step 4: Run tests to verify host loading works**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_smart_monitor_tdx_data.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add config/pytdx_hosts.json pytdx_host_config.py config.py smart_monitor_tdx_data.py tests/test_smart_monitor_tdx_data.py
git commit -m "feat: externalize pytdx host configuration"
```

### Task 7: Move replay execution into a background task runner

**Files:**
- Create: `C:\Projects\githubs\aiagents-stock\quant_sim\replay_runner.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\db.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\replay_service.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_replay_engine.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_ui_feedback.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_replay_runner_starts_background_run_without_blocking_ui(tmp_path):
    ...
    assert run["status"] in {"queued", "running"}
    assert run["progress_total"] == 2


def test_replay_ui_source_shows_running_status_progress_and_cancel():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    assert "运行中" in ui_source
    assert "取消回放任务" in ui_source
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_quant_replay_engine.py tests/test_quant_sim_ui_feedback.py
```

Expected: FAIL because replay still runs synchronously and has no background-task state/progress/cancel UI.

- [ ] **Step 3: Implement the background replay runner and persistence**

```python
class QuantSimReplayRunner:
    def start_run(...):
        ...
        return run_id
```

- [ ] **Step 4: Run tests to verify replay-task workflow**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_quant_replay_engine.py tests/test_quant_sim_ui_feedback.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add quant_sim/replay_runner.py quant_sim/db.py quant_sim/replay_service.py quant_sim/ui.py tests/test_quant_replay_engine.py tests/test_quant_sim_ui_feedback.py
git commit -m "feat: run quant replay in background with progress"
```

### Task 8: End-to-end verification and final two-pass review

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\docs\superpowers\specs\2026-04-09-quant-kernel-design.md`
- Test: `C:\Projects\githubs\aiagents-stock\tests\`

- [ ] **Step 1: Review pass 1 - code/spec comparison**

Check every spec requirement against code:
- dynamic regime labels
- dynamic fundamental-quality labels
- derived risk style
- supported timeframe modes
- omitted replay end datetime
- repo-local `pytdx` host config
- replay background-task status/progress/cancel
- persisted strategy profile
- per-stock strategy basics in UI

- [ ] **Step 2: Review pass 2 - runtime verification**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests
python -m compileall C:\Projects\githubs\aiagents-stock\quant_kernel C:\Projects\githubs\aiagents-stock\quant_sim C:\Projects\githubs\aiagents-stock\app.py
python -c "import app; print('app-import-ok')"
```

Expected:
- all targeted and full tests pass
- compile succeeds
- app import succeeds

- [ ] **Step 3: Commit final cleanup if needed**

```powershell
git add docs/superpowers/specs/2026-04-09-quant-kernel-design.md quant_kernel quant_sim tests
git commit -m "fix: align quant kernel implementation with approved spec"
```

### Task 9: Turn replay results into a complete report with persisted strategy context

**Files:**
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\db.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\replay_service.py`
- Modify: `C:\Projects\githubs\aiagents-stock\quant_sim\ui.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_replay_engine.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_db.py`
- Modify: `C:\Projects\githubs\aiagents-stock\tests\test_quant_sim_ui_feedback.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_historical_replay_persists_run_strategy_signals(tmp_path):
    ...
    signals = db.get_sim_run_signals(run["id"])
    assert signals[0]["strategy_profile"]["analysis_timeframe"]["key"] == "30m"


def test_build_replay_report_summary_exposes_cash_positions_and_trade_analysis():
    ...
    assert summary["initial_cash"] == 100000.0
    assert summary["final_available_cash"] == 54250.0
    assert summary["ending_position_count"] == 2
    assert summary["trade_analysis"]["total_buy_amount"] == 30000.0


def test_quant_sim_replay_ui_source_mentions_strategy_and_position_report_sections():
    ui_source = Path("C:/Projects/githubs/aiagents-stock/quant_sim/ui.py").read_text(encoding="utf-8")
    assert "回放总览" in ui_source
    assert "结束持仓" in ui_source
    assert "交易分析" in ui_source
    assert "当前交易策略" in ui_source
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_quant_replay_engine.py tests/test_quant_sim_db.py tests/test_quant_sim_ui_feedback.py
```

Expected: FAIL because replay runs do not persist per-run strategy signals and the replay tab does not yet build a report-style summary.

- [ ] **Step 3: Implement minimal persistence and replay-report helpers**

```python
def replace_sim_run_results(..., signals: list[dict[str, Any]] | None = None) -> None:
    ...


def build_replay_report_payload(...):
    return {
        "initial_cash": ...,
        "final_available_cash": ...,
        "final_market_value": ...,
        "final_total_equity": ...,
        "trade_analysis": {...},
        "positions": positions,
        "signals": signals,
    }
```

- [ ] **Step 4: Run tests to verify replay reporting works**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_quant_replay_engine.py tests/test_quant_sim_db.py tests/test_quant_sim_ui_feedback.py
```

Expected: PASS.

- [ ] **Step 5: Review pass 1**

Check:
- replay result tab shows a selectable run, not only the latest run
- overview includes initial cash, final cash, market value, total equity, return, drawdown, win rate, trade count
- ending positions are visible with quantities and pnl
- strategy basics are visible in replay results
- per-run strategy signals are stored independently from live `strategy_signals`

- [ ] **Step 6: Review pass 2**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_quant_replay_engine.py tests/test_quant_sim_db.py tests/test_quant_sim_ui_feedback.py tests/test_quant_sim_replay_ui.py
python -m compileall quant_sim app.py
python -c "import app; print('app-import-ok')"
```

Expected: all pass.

- [ ] **Step 7: Commit**

```powershell
git add quant_sim/db.py quant_sim/replay_service.py quant_sim/ui.py tests/test_quant_replay_engine.py tests/test_quant_sim_db.py tests/test_quant_sim_ui_feedback.py docs/superpowers/specs/2026-04-09-quant-kernel-design.md docs/superpowers/plans/2026-04-09-quant-kernel-integration.md
git commit -m "feat: add replay report and persisted strategy context"
```
