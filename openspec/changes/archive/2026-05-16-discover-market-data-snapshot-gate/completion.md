# Completion: Discover Market Data Snapshot Gate

## Summary

The OpenSpec change `discover-market-data-snapshot-gate` is complete. Discovery now prepares and verifies 30m technical snapshot readiness before automatic quant lifecycle entry, exposes readiness diagnostics to users/API consumers, blocks incomplete discovery candidates with `missing_technical_snapshot`, and preserves market-data cache during normal DB reset.

## Completion Gate Results

- Tasks complete: passed.
- Per-task Alignment Review and Security Review evidence: passed.
- `task-reviews.md` open findings: none.
- `review.md` unresolved findings: none.
- Coverage evidence: passed with `app\discover\market_snapshot.py` at `93%`.
- Test parameter files: present under `test-params/`.
- File length rule: passed; all modified/generated code files are under 1000 lines.
- Async rule: passed; discovery market-data work runs inside `_run_discover_task`.
- Database/runtime rule: passed; no migration added and existing DB runtime is reused.
- API/UI rule: passed; fields are additive and documented.
- Archive target: available.

## Task Completion Evidence

All tasks in `tasks.md` are marked `[x]`:

- 1.1 Create OpenSpec test parameter files.
- 2.1 Implement discovery 30m technical snapshot preparation.
- 2.2 Wire snapshot preparation into discovery task lifecycle ingestion.
- 2.3 Persist and hydrate technical snapshot diagnostics in lifecycle rows.
- 2.4 Harden automatic lifecycle entry gate for incomplete discovery snapshots.
- 3.1 Expose snapshot readiness in discovery API and UI.
- 4.1 Lock DB reset behavior to preserve market-data cache.
- 5.1 Run final validation and reviews.

## Per-Task Review Closure

`task-reviews.md` includes Alignment Review and Security Review evidence for every task. Final review findings for TDX remote fetch, false ready flags, and zero-valued indicators were fixed and re-reviewed with no open findings.

## Final Review Closure

`review.md` reports:

- Blocking issues: none.
- Unresolved findings: none.
- Recommended fixes: none for this change.

## Wiki Documentation

Generated wiki page:

- `docs/wiki/stock-discovery-technical-snapshot-readiness.md`

Title derivation basis:

- User-facing capability: stock discovery technical readiness before quant entry.
- Spec requirements: discovery snapshot readiness, lifecycle gate defense, user-visible diagnostics, and cache preservation.
- Implemented code: discovery snapshot preparation, candidate event diagnostics, UI readiness rendering, and reset cache-preservation tests.

## Spec / Design / Code Alignment

The implementation matches the approved spec and design:

- `app/discover/market_snapshot.py` implements the focused snapshot preparation boundary.
- `app/discover/discover.py` calls snapshot preparation before lifecycle ingestion.
- `app/data/services/market_data_service.py` uses the existing TDX remote fetcher when local cache is empty.
- `app/gateway/quant_universe_entry.py` persists and hydrates readiness payload fields, including consumed events after a stock enters quant.
- `app/quant_sim/candidate_entry_gate.py` enforces `missing_technical_snapshot`.
- UI files expose readiness status and task diagnostics.
- Reset tests verify DB cleanup preserves local market-data cache.

No behavior outside the approved OpenSpec scope was added.

## Implementation Standards Evidence

- Changed code paths match `design.md` and `tasks.md`.
- Equivalent readiness logic is centralized in the new snapshot module and candidate gate; avoidable duplication was not introduced.
- No schema migration or new DB connection path was added.
- Discovery remains asynchronous from the request perspective.
- External market-data IO is bounded by existing provider/fetcher boundaries and mocked in tests.
- Generated/modified code files remain under 1000 lines.
- Final implementation verification commands were run successfully:
  - `openspec validate discover-market-data-snapshot-gate --strict` before archival; after archival the CLI no longer resolves the original active change id.
  - `python -m pytest -q tests\test_discover_market_snapshot.py tests\test_discover_lifecycle_scoring.py tests\test_reset_stock_universe_deployment.py -p no:cacheprovider`
  - `python -m pytest -q tests\test_discover_market_snapshot.py --cov=app.discover.market_snapshot --cov-report=term-missing -p no:cacheprovider`
  - `npm test -- src/tests/discover-page.test.tsx`
  - `git diff --check`

## Real Discovery Verification

A real end-to-end discovery run was executed after implementation using the backend API path, without mocked selector or market-data services:

- API action: `POST /api/v1/discover/actions/run-strategy`
- Payload: `{"strategies": ["low_price_bull"], "topN": 1, "waitMs": 180000}`
- Selector result: pywencai returned `139` matching stocks and selected `003016 欣贺股份`.
- Task result: status `completed`, completed strategies `["low_price_bull"]`, failed strategies `[]`.
- Snapshot preparation: `uniqueStocks=1`, `prepared=1`, `complete=1`, `incomplete=0`, `failed=0`, `blocked=0`.
- Snapshot item: `003016`, status `ready`, `missing_fields=[]`.
- Market-data cache: `data/local_sources/tdx/kline/kline_type=minute30/003016.parquet` exists with `3241` 30m rows.
- Latest cached 30m bar: `2026-05-15 15:00:00`, close `8.14`, amount `4418145.0`, provider `tdx`.
- MarketDataService latest snapshot fields were complete: `close`, `ma5`, `ma10`, `ma20`, `ma20_slope`, `ma60`, `amount`, `volume_ratio`, `rsi14`, `macd`, `trend`, `datetime`, `provider`, `timeframe`, and `indicator_version`.
- Candidate event payload persisted the same technical fields and `entry_gate.passed=true`.
- Lifecycle did not promote the stock because candidate score was below trial threshold, not because of missing market data.
- Follow-up fix from real validation: `technical_snapshot_row_count` now reports the prepared 120-day indicator window row count. A rerun produced `technical_snapshot_row_count=601` in both the discovery row and candidate event payload.

A full default discovery validation was also executed through the backend API with no mocked selector or market-data services:

- API action: `POST /api/v1/discover/actions/run-strategy`
- Payload: `{"waitMs": 600000}`
- Strategies completed: `["main_force", "low_price_bull", "small_cap", "profit_growth", "value_stock"]`.
- Failed strategies: `[]`.
- Task result: status `completed`, task id `discover-1431e3c61b`, duration `102.02` seconds, `50` candidate rows.
- Snapshot preparation: `uniqueStocks=48`, `prepared=46`, `complete=45`, `incomplete=1`, `failed=2`, `blocked=3`.
- Blocked stocks: `001393` missing `ma10`, `ma20`, `ma60`, `rsi`; `920832` and `920017` failed with market data unavailable.
- Candidate event validation: `48` events persisted, `45` payloads ready, `3` blocked by `missing_technical_snapshot`, and no non-missing event lacked required snapshot fields.
- Discovery API validation over all `50` rows: `ready=47`, `incomplete=1`, `failed=2`, and no non-blocked row lacked a ready snapshot.
- Full-run finding fixed and revalidated: already-in-quant rows whose candidate events are marked `consumed` now hydrate snapshot diagnostics; `301081 严牌股份` rendered `technical_snapshot_ready=true`, status `ready`, row count `600`.

## Local Git Commit

Local git commit is required after `completion.md`, the wiki page, and the archived OpenSpec folder are finalized. Push is not part of this completion step unless explicitly requested.

## Archive Target

The change will be archived to:

- `openspec/changes/archive/2026-05-16-discover-market-data-snapshot-gate/`

## Blocking Issues

None.
