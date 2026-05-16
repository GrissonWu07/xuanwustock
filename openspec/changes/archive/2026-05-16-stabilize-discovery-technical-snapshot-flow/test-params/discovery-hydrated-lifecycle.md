# Test Parameters: Discovery Hydrated Lifecycle

## discovery_task_hydrates_before_lifecycle

- strategy: `low_price_bull`
- run_id_prefix: `discover-`
- stock_code: `600010`
- stock_name: `水位测试`
- raw_selector_has_technical_fields: `false`
- expected_snapshot_status: `ready`
- expected_trend_after_hydration: `up`
- expected_min_technical_confirmation_count: `3`

## discover_api_uses_artifact_rows

- stock_code: `600011`
- artifact_status: `current`
- expected_api_snapshot_status: `ready`
- expected_event_payload_snapshot_status: `ready`

## completed_strategy_scope

- selected_strategy: `low_price_bull`
- stale_unselected_strategy: `ai_scanner`
- stale_unselected_code: `000066`
- current_selected_code: `600011`
- expected_artifact_codes: `["600011"]`
- expected_discover_api_strategy_keys: `["low_price_bull"]`

## stale_fallback

- stock_code: `600012`
- expected_artifact_status: `stale_unprepared`
- expected_snapshot_status: `stale_unprepared`
- expected_blocking_reason: `missing_technical_snapshot`

## real_e2e

- endpoint_run_strategy: `POST /api/v1/discover/actions/run-strategy`
- endpoint_discover: `GET /api/v1/discover`
- strategy: `low_price_bull`
- top_n: `1`
- wait_ms: `180000`
- required_evidence: task diagnostics, discover row technical status, candidate event payload when event exists
