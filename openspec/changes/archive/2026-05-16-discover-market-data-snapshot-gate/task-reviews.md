# Task Reviews: Discover Market Data Snapshot Gate

## Task 1.1 Create OpenSpec Test Parameter Files

### Validation

- Added explicit parameter files under `openspec/changes/discover-market-data-snapshot-gate/test-params/`.
- Parameters cover complete snapshot, missing snapshot, duplicate rows, provider failure, lifecycle gate blocking, UI diagnostics, and DB reset preserving cache.

### Alignment Review

- Finding: none.
- Closure: parameters map to the scenarios named in `tasks.md` and the approved spec.

### Security Review

- Finding: none.
- Closure: parameters contain only synthetic stock codes, fake names, and no credentials or private endpoints.

### Coverage Evidence

- Not applicable to parameter-only task. Coverage is enforced by the implementation tasks that consume these files.

## Task 2.1 Implement Discovery 30m Technical Snapshot Preparation

### Validation

- RED: `python -m pytest -q tests\test_discover_market_snapshot.py -p no:cacheprovider` failed because `app.discover.market_snapshot` did not exist.
- GREEN: `python -m pytest -q tests\test_discover_market_snapshot.py -p no:cacheprovider` passed.
- Coverage: `python -m pytest -q tests\test_discover_market_snapshot.py --cov=app.discover.market_snapshot --cov-report=term-missing -p no:cacheprovider` passed with `app\discover\market_snapshot.py` at 90%.

### Alignment Review

- Finding: pytest-cov initially failed before collecting coverage because importing `app.discover.market_snapshot` executed heavyweight package-level imports through `app.discover.__init__`.
- Fix: changed `app.discover.__init__` to lazy-load existing exported names, keeping the public export surface while avoiding unrelated eager imports.
- Re-review: no open alignment findings. Snapshot preparation is scoped to 30m readiness, duplicate-code batching, missing-field diagnostics, and no lifecycle writes.

### Security Review

- Finding: none.
- Closure: diagnostics include stock code, provider/status, and missing field names only. No secrets, credentials, private endpoints, or destructive filesystem operations were introduced.

### Test Parameters

- `openspec/changes/discover-market-data-snapshot-gate/test-params/discovery-snapshot-readiness.md`

### Coverage Evidence

- `app\discover\market_snapshot.py`: 90%.

## Task 2.2 Wire Snapshot Preparation into Discovery Task Lifecycle Ingestion

### Validation

- RED: `python -m pytest -q tests\test_discover_market_snapshot.py::test_discover_task_prepares_snapshots_before_lifecycle_ingest -p no:cacheprovider` failed because `_run_discover_task` called lifecycle ingestion before any snapshot preparation.
- GREEN: `python -m pytest -q tests\test_discover_market_snapshot.py::test_discover_task_prepares_snapshots_before_lifecycle_ingest -p no:cacheprovider` passed.
- Regression: `python -m pytest -q tests\test_discover_market_snapshot.py -p no:cacheprovider` passed.

### Alignment Review

- Finding: none.
- Closure: discovery now builds rows once, prepares technical snapshots before lifecycle ingestion, passes prepared rows to lifecycle ingestion, and adds `technicalSnapshotPreparation` to task result.

### Security Review

- Finding: none.
- Closure: task result exposes aggregate counts and safe per-stock diagnostics only. No credentials, secrets, or destructive operations were introduced.

### Test Parameters

- `openspec/changes/discover-market-data-snapshot-gate/test-params/discovery-snapshot-readiness.md`

### Coverage Evidence

- The task reuses the 90% covered snapshot preparation module and adds a targeted task-flow regression test for the changed discovery task path.

## Task 2.3 Persist and Hydrate Technical Snapshot Diagnostics in Lifecycle Rows

### Validation

- RED: `python -m pytest -q tests\test_discover_market_snapshot.py::test_candidate_event_payload_preserves_technical_snapshot_diagnostics tests\test_discover_market_snapshot.py::test_lifecycle_enrichment_hydrates_technical_snapshot_diagnostics -p no:cacheprovider` failed because candidate payloads and row enrichment did not expose technical snapshot diagnostics.
- GREEN: the same command passed after adding payload persistence and enrichment hydration.
- Regression: `python -m pytest -q tests\test_discover_market_snapshot.py -p no:cacheprovider` passed.

### Alignment Review

- Finding: the incomplete UI parameter row initially lacked timeframe/provider diagnostics.
- Fix: updated `discover-ui-snapshot-readiness.md` so incomplete rows include `technical_snapshot_timeframe`, provider, and snapshot time.
- Re-review: no open alignment findings. Candidate event payloads preserve readiness diagnostics, and row enrichment restores them for API/UI consumers.

### Security Review

- Finding: none.
- Closure: persisted diagnostics are bounded to readiness flags, provider/timeframe, local display timestamp, and missing-field names. No secrets or raw provider payloads are stored.

### Test Parameters

- `openspec/changes/discover-market-data-snapshot-gate/test-params/lifecycle-gate-missing-snapshot.md`
- `openspec/changes/discover-market-data-snapshot-gate/test-params/discover-ui-snapshot-readiness.md`

### Coverage Evidence

- Targeted persistence and enrichment tests passed. Changed logic is exercised through candidate payload creation and DB-backed row enrichment.

## Task 2.4 Harden Automatic Lifecycle Entry Gate for Incomplete Discovery Snapshots

### Validation

- RED: `python -m pytest -q tests\test_discover_market_snapshot.py::test_entry_gate_blocks_discovery_score_without_technical_snapshot tests\test_discover_market_snapshot.py::test_entry_gate_blocks_text_only_technical_reason_without_snapshot tests\test_discover_market_snapshot.py::test_entry_gate_allows_complete_discovery_snapshot_to_continue -p no:cacheprovider` failed because high-score discovery candidates without a structured snapshot passed or became `recommended_only`.
- GREEN: the same command passed after adding discovery-specific `missing_technical_snapshot` gate behavior.
- Regression: `python -m pytest -q tests\test_discover_lifecycle_scoring.py tests\test_discover_market_snapshot.py -p no:cacheprovider` passed.

### Alignment Review

- Finding: existing lifecycle scoring tests assumed weak AI discovery rows could be recommended-only without a structured snapshot.
- Fix: updated those regression fixtures to include complete but weak technical snapshots where they are testing weak confirmation rather than missing data.
- Re-review: no open alignment findings. Missing structured snapshots now block automatic discovery entry; complete weak snapshots still exercise the prior recommended-only confirmation rule.

### Security Review

- Finding: none.
- Closure: gate decisions only inspect candidate event payload data already inside the runtime DB. Returned diagnostics are reason codes and missing field names only.

### Test Parameters

- `openspec/changes/discover-market-data-snapshot-gate/test-params/lifecycle-gate-missing-snapshot.md`

### Coverage Evidence

- `app\discover\market_snapshot.py`: 93% from the targeted coverage command.
- Candidate gate behavior is covered by explicit pass/block/recommended-only regression tests.

## Task 3.1 Expose Snapshot Readiness in Discovery API and UI

### Validation

- RED backend: `python -m pytest -q tests\test_discover_market_snapshot.py::test_discover_api_exposes_technical_snapshot_readiness_fields -p no:cacheprovider` failed because discovery rows did not expose technical snapshot readiness fields.
- RED UI: `npm test -- src/tests/discover-page.test.tsx -t "technical snapshot"` failed because the discovery page did not render readiness badges or preparation counts.
- GREEN backend: the backend API test passed after mapping readiness fields into discovery rows.
- GREEN UI: `npm test -- src/tests/discover-page.test.tsx -t "technical snapshot"` passed after adding readiness badges and task summary text.
- Regression: `python -m pytest -q tests\test_discover_market_snapshot.py tests\test_discover_lifecycle_scoring.py -p no:cacheprovider` passed.
- Regression: `npm test -- src/tests/discover-page.test.tsx` passed.

### Alignment Review

- Finding: none.
- Closure: API fields are additive, UI renders ready/incomplete state and missing fields, and task feedback reports checked/ready/incomplete/failed/blocked counts.

### Security Review

- Finding: none.
- Closure: UI renders only safe diagnostic fields already returned by the API. No new client-side privileged action or secret handling was added.

### Test Parameters

- `openspec/changes/discover-market-data-snapshot-gate/test-params/discover-ui-snapshot-readiness.md`

### Coverage Evidence

- Backend readiness mapping is covered by an API-level pytest.
- UI readiness rendering and task summary are covered by Vitest tests.

## Task 4.1 Lock DB Reset Behavior to Preserve Market-Data Cache

### Validation

- Regression: `python -m pytest -q tests\test_reset_stock_universe_deployment.py -p no:cacheprovider` passed.
- The new test creates database files plus `local_sources/tdx/kline/kline_type=minute30/600001.parquet`, runs reset with `--yes --recreate`, and asserts the cache file remains untouched while runtime DB files are recreated.

### Alignment Review

- Finding: none.
- Closure: no script behavior change was required; existing reset logic is database-file scoped and now has explicit cache-preservation coverage.

### Security Review

- Finding: none.
- Closure: the reset script did not gain broader filesystem deletion behavior. The test guards against accidental cache-directory deletion.

### Test Parameters

- `openspec/changes/discover-market-data-snapshot-gate/test-params/reset-preserves-market-cache.md`

### Coverage Evidence

- Reset script behavior is covered by the existing reset test module plus the new cache-preservation regression.

## Task 5.1 Run Final Validation and Reviews

### Validation

- `openspec validate discover-market-data-snapshot-gate --strict` passed.
- `python -m pytest -q tests\test_discover_market_snapshot.py tests\test_discover_lifecycle_scoring.py tests\test_reset_stock_universe_deployment.py -p no:cacheprovider` passed with `30 passed`.
- `python -m pytest -q tests\test_discover_market_snapshot.py --cov=app.discover.market_snapshot --cov-report=term-missing -p no:cacheprovider` passed with `app\discover\market_snapshot.py` at `93%` coverage.
- `npm test -- src/tests/discover-page.test.tsx` passed with `6 passed`.
- Changed-file length check: `app\discover\market_snapshot.py` 270 lines, `app\discover\discover.py` 924 lines, `app\gateway\quant_universe_entry.py` 381 lines, `app\quant_sim\candidate_entry_gate.py` 276 lines, `app\data\services\market_data_service.py` 67 lines, `ui\src\features\discover\discover-page.tsx` 796 lines.

### Alignment Review

- Finding: `MarketDataService(provider="tdx")` still used an empty `remote_fetcher`, so discovery could classify an empty cache as unavailable without attempting the required TDX pull.
- Fix: changed the TDX service path to call the existing `SmartMonitorTDXDataFetcher.get_kline_data_range` remote path and added `test_tdx_market_data_service_uses_remote_fetcher_when_local_cache_is_empty`.
- Finding: the discovery entry gate trusted `technical_snapshot_ready=true` before verifying required structured fields.
- Fix: changed the gate to compute required-field completeness first, added snapshot metadata fields to the persisted payload, and added `test_entry_gate_blocks_ready_flag_without_structured_snapshot_fields`.
- Finding: lifecycle candidate payload construction used `or`, dropping valid zero-valued indicators such as `ma20_slope=0.0` and `macd=0.0`.
- Fix: changed payload construction to use first-present value selection and re-ran the weak-complete-snapshot lifecycle regression.
- Re-review: no open alignment findings. Discovery task orchestration remains asynchronous: market-data preparation runs inside `_run_discover_task`, after task creation and before lifecycle ingestion.

### Security Review

- Finding: none.
- Closure: no new credentials, secrets, destructive deletes, schema migrations, or privileged UI actions were introduced. External TDX IO remains behind the existing market-data service/fetcher path and tests mock that IO.

### Test Parameters

- `openspec/changes/discover-market-data-snapshot-gate/test-params/discovery-snapshot-readiness.md`
- `openspec/changes/discover-market-data-snapshot-gate/test-params/lifecycle-gate-missing-snapshot.md`
- `openspec/changes/discover-market-data-snapshot-gate/test-params/discover-ui-snapshot-readiness.md`
- `openspec/changes/discover-market-data-snapshot-gate/test-params/reset-preserves-market-cache.md`

### Coverage Evidence

- New focused snapshot preparation module coverage: `93%`.
- Integration behavior across discovery task flow, lifecycle payload persistence, gate blocking, API hydration, reset cache preservation, and UI rendering is covered by targeted pytest/Vitest tests.
- Tooling note: broader `coverage/pytest-cov` source runs that include pandas-importing modules fail in this Windows Python 3.13 environment with `numpy: cannot load module more than once per process`; the same tests pass without coverage instrumentation, and the focused changed module coverage command succeeds.
