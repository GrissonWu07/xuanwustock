# Test Parameters: Discover UI Snapshot Readiness

## discover_api_row

```json
{
  "selector_row": {
    "股票代码": "600020",
    "股票简称": "准备完成股",
    "所属行业": "测试行业",
    "最新价": 12.34,
    "source_score": 0.8,
    "confidence": 0.76,
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
    "technical_snapshot_ready": true,
    "technical_snapshot_status": "ready",
    "technical_snapshot_timeframe": "30m",
    "technical_snapshot_provider": "fixture",
    "technical_snapshot_at": "2026-05-15 14:30:00"
  },
  "expected": {
    "ready_label": "ready",
    "timeframe": "30m",
    "provider": "fixture"
  }
}
```

## discover_ui_rows

```json
{
  "rows": [
    {
      "id": "600020",
      "code": "600020",
      "name": "准备完成股",
      "cells": ["600020", "准备完成股", "测试行业", "main_force", "12.34", "100", "20", "2"],
      "eligible_status": "eligible",
      "candidate_score": 0.8,
      "candidate_confidence": 0.76,
      "technical_snapshot_ready": true,
      "technical_snapshot_status": "ready",
      "technical_snapshot_timeframe": "30m",
      "technical_snapshot_provider": "fixture"
    },
    {
      "id": "600021",
      "code": "600021",
      "name": "缺指标股",
      "cells": ["600021", "缺指标股", "测试行业", "main_force", "9.80", "80", "18", "1.8"],
      "eligible_status": "blocked",
      "blocking_reason": "missing_technical_snapshot",
      "candidate_score": 0.88,
      "candidate_confidence": 0.8,
      "technical_snapshot_ready": false,
      "technical_snapshot_status": "incomplete",
      "technical_snapshot_missing_fields": ["ma10", "ma60", "rsi", "macd"],
      "technical_snapshot_timeframe": "30m",
      "technical_snapshot_provider": "fixture",
      "technical_snapshot_at": "2026-05-15 14:30:00"
    }
  ],
  "task_result": {
    "technicalSnapshotPreparation": {
      "uniqueStocks": 2,
      "prepared": 2,
      "complete": 1,
      "incomplete": 1,
      "failed": 0,
      "blocked": 1
    }
  },
  "expected": {
    "ready_text": "Technical snapshot ready",
    "incomplete_text": "missing_technical_snapshot",
    "missing_field_text": "ma10, ma60, rsi, macd",
    "task_summary": "Technical snapshot: checked 2, ready 1, incomplete 1, failed 0, blocked 1"
  }
}
```
