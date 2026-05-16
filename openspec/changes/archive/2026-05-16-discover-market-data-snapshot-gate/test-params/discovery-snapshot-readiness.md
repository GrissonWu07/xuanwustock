# Test Parameters: Discovery Snapshot Readiness

## complete_snapshot

```json
{
  "rows": [
    {
      "code": "600001",
      "name": "完整快照股",
      "source": "main_force",
      "source_score": 0.82,
      "confidence": 0.78
    }
  ],
  "snapshot": {
    "close": 12.34,
    "ma5": 12.1,
    "ma10": 11.9,
    "ma20": 11.5,
    "ma20_slope": 0.05,
    "ma60": 10.8,
    "amount": 120000000,
    "volume_ratio": 1.35,
    "rsi14": 58.2,
    "macd": 0.18,
    "trend": "up",
    "datetime": "2026-05-15 14:30:00",
    "provider": "fixture",
    "timeframe": "30m",
    "indicator_version": "fixture-v1"
  },
  "expected": {
    "technical_snapshot_ready": true,
    "technical_snapshot_status": "ready",
    "missing_fields": [],
    "unique_stocks": 1,
    "complete": 1,
    "incomplete": 0
  }
}
```

## missing_snapshot

```json
{
  "rows": [
    {
      "code": "600002",
      "name": "缺指标股",
      "source": "main_force",
      "source_score": 0.88,
      "confidence": 0.8
    }
  ],
  "snapshot": {
    "close": 9.8,
    "ma5": 9.7,
    "ma20": 9.2,
    "amount": 80000000,
    "trend": "up",
    "datetime": "2026-05-15 14:30:00",
    "provider": "fixture",
    "timeframe": "30m",
    "indicator_version": "fixture-v1"
  },
  "expected": {
    "technical_snapshot_ready": false,
    "technical_snapshot_status": "incomplete",
    "missing_fields": ["ma10", "ma20_slope", "ma60", "volume_ratio", "rsi", "macd"],
    "blocked_reason": "missing_technical_snapshot"
  }
}
```

## duplicate_rows

```json
{
  "rows": [
    {
      "code": "600003",
      "name": "重复股A",
      "source": "main_force"
    },
    {
      "code": "600003",
      "name": "重复股A",
      "source": "value_stock"
    }
  ],
  "expected": {
    "unique_stocks": 1,
    "rows": 2,
    "same_readiness_for_all_rows": true
  }
}
```

## provider_failure

```json
{
  "rows": [
    {
      "code": "600004",
      "name": "行情失败股",
      "source": "small_cap"
    }
  ],
  "snapshot": {},
  "expected": {
    "technical_snapshot_ready": false,
    "technical_snapshot_status": "failed",
    "blocked_reason": "missing_technical_snapshot",
    "failed": 1
  }
}
```
