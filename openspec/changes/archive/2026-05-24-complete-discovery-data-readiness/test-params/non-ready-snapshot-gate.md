# Test Params: Non Ready Snapshot Gate

## Case: stale technical snapshot

Input:

```json
{
  "payload": {
    "price": 13.7,
    "ma5": 13.2,
    "ma10": 13.0,
    "ma20": 11.8,
    "ma20_slope": 0.035,
    "ma60": 9.4,
    "amount": 130000000,
    "volume_ratio": 3.2,
    "rsi": 78.0,
    "macd": 0.22,
    "trend": "up",
    "technical_snapshot_status": "stale",
    "technical_snapshot_at": "2026-05-16 14:30:00",
    "technical_snapshot_provider": "unit-test",
    "technical_snapshot_timeframe": "30m",
    "technical_snapshot_indicator_version": "technical-entry-v1"
  }
}
```

Expected:

```json
{
  "candidate_score": 0.0,
  "blocking_reason": "stale_required_snapshot",
  "no_penalty_scoring": true
}
```

## Case: same snapshot across source families

Input:

```json
{
  "sources": ["low_price", "main_force", "ai_scanner"],
  "snapshot_status": "ready"
}
```

Expected:

```json
{
  "entry_gate_result": "passed",
  "source_specific_block": false
}
```
