# Test Params: Discover API Data Readiness E2E

## Flow

1. Start a FastAPI TestClient using `create_app` with isolated temporary SQLite files.
2. Trigger `POST /api/v1/discover/actions/run-strategy` with fake selector and market data boundaries.
3. Poll or inspect `GET /api/v1/tasks/{task_id}`.
4. Read `GET /api/v1/discover`.

## Assertions

```json
{
  "non_ready_candidate_score": 0.0,
  "non_ready_candidate_confidence": 0.0,
  "non_ready_blocking_reason": "missing_technical_snapshot",
  "source_score_not_used_as_candidate_score": true,
  "api_routes_exercised": [
    "POST /api/v1/discover/actions/run-strategy",
    "GET /api/v1/tasks/{task_id}",
    "GET /api/v1/discover"
  ]
}
```
