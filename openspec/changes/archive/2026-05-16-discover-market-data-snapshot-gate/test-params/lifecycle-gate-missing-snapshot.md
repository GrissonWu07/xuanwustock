# Test Parameters: Lifecycle Gate Missing Snapshot

## score_without_snapshot

```json
{
  "event": {
    "stock_code": "600010",
    "stock_name": "高分缺快照",
    "source_type": "discover",
    "source_key": "main_force",
    "source_score": 0.95,
    "confidence": 0.92,
    "trend": "up",
    "reason_text": "技术偏强",
    "payload": {
      "technical_snapshot_ready": false,
      "technical_snapshot_status": "incomplete",
      "technical_snapshot_missing_fields": ["ma60", "rsi", "macd"],
      "source_score": 0.95,
      "confidence": 0.92
    }
  },
  "expected": {
    "passed": false,
    "status": "blocked",
    "reason_code": "missing_technical_snapshot",
    "missing_fields": ["ma60", "rsi", "macd"]
  }
}
```

## text_only_technical_reason

```json
{
  "event": {
    "stock_code": "600011",
    "stock_name": "文本强势股",
    "source_type": "discover",
    "source_key": "ai_scanner",
    "source_score": 0.93,
    "confidence": 0.9,
    "trend": "up",
    "reason_text": "价格站上均线，MACD 走强",
    "payload": {
      "technical_reasons": "价格站上均线，MACD 走强",
      "technical_snapshot_ready": false,
      "technical_snapshot_status": "incomplete",
      "technical_snapshot_missing_fields": ["ma5", "ma10", "ma20", "ma20_slope", "ma60", "amount", "volume_ratio", "rsi", "macd"]
    }
  },
  "expected": {
    "passed": false,
    "status": "blocked",
    "reason_code": "missing_technical_snapshot"
  }
}
```

## complete_snapshot_event

```json
{
  "event": {
    "stock_code": "600012",
    "stock_name": "完整快照事件",
    "source_type": "discover",
    "source_key": "main_force",
    "source_score": 0.78,
    "confidence": 0.76,
    "trend": "up",
    "payload": {
      "price": 12.34,
      "ma5": 12.1,
      "ma10": 11.9,
      "ma20": 11.5,
      "ma20_slope": 0.05,
      "ma60": 10.8,
      "amount": 120000000,
      "volume_ratio": 1.35,
      "rsi": 58.2,
      "macd": 0.18,
      "trend": "up",
      "technical_snapshot_at": "2026-05-15 14:30:00",
      "technical_snapshot_timeframe": "30m",
      "technical_snapshot_provider": "fixture",
      "technical_snapshot_indicator_version": "fixture-v1",
      "technical_snapshot_ready": true,
      "technical_snapshot_status": "ready",
      "technical_snapshot_missing_fields": []
    }
  },
  "expected": {
    "passed": true,
    "status": "active",
    "reason_code": ""
  }
}
```

## ready_flag_without_snapshot_fields

```json
{
  "event": {
    "stock_code": "600013",
    "stock_name": "伪完整快照",
    "source_type": "discover",
    "source_key": "main_force",
    "source_score": 0.92,
    "confidence": 0.88,
    "trend": "up",
    "payload": {
      "technical_snapshot_ready": true,
      "technical_snapshot_status": "ready",
      "technical_snapshot_missing_fields": []
    }
  },
  "expected": {
    "passed": false,
    "status": "blocked",
    "reason_code": "missing_technical_snapshot",
    "missing_fields": [
      "price",
      "ma5",
      "ma10",
      "ma20",
      "ma20_slope",
      "ma60",
      "amount",
      "volume_ratio",
      "rsi",
      "macd",
      "trend",
      "technical_snapshot_at",
      "technical_snapshot_timeframe",
      "technical_snapshot_provider",
      "technical_snapshot_indicator_version"
    ]
  }
}
```
