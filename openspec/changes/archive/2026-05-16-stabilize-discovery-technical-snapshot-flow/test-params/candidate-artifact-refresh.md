# Test Parameters: Candidate Artifact Refresh

## candidate_artifact_ready_hydration

- run_id: `discover-test-001`
- selected_at: `2026-05-16 10:00:00`
- stock_code: `600001`
- stock_name: `测试股份`
- strategy_key: `low_price_bull`
- latest_price: `12.34`
- technical_snapshot_status: `ready`
- trend: `up`
- ma5: `12.50`
- ma10: `12.30`
- ma20: `12.00`
- ma20_slope: `0.02`
- ma60: `11.20`
- amount: `90000000`
- volume_ratio: `1.5`
- rsi: `58.2`
- macd: `0.12`

## stale_selector_fallback

- stock_code: `600002`
- expected_status: `stale_unprepared`
- expected_blocking_reason: `missing_technical_snapshot`

## scheduler_runtime_snapshot

- stock_code: `600003`
- stock_name: `刷新股份`
- realtime_price: `15.80`
- technical_snapshot_status: `ready`
- provider: `fixture`
- timeframe: `30m`
