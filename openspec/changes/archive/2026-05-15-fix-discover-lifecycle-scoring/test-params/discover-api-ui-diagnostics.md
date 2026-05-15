# Test Parameters: Discover API UI Diagnostics

These parameters are consumed by `tests/test_discover_lifecycle_scoring.py` and
`ui/src/tests/discover-page.test.tsx`.

```json
{
  "api_candidate_diagnostics": {
    "selector_row": {
      "股票代码": "688111",
      "股票简称": "金山办公",
      "所属行业": "办公软件",
      "最新价": 321.88,
      "总市值": 1234.0,
      "市盈率": 48.5,
      "市净率": 8.2,
      "score": 0.91,
      "source_score": 0.91,
      "confidence": 0.88,
      "trend": "up",
      "ma5": 322.5,
      "ma10": 321.2,
      "ma20": 318.0,
      "ma20_slope": 0.04,
      "amount": 120000000,
      "volume_ratio": 1.6,
      "rsi": 61,
      "macd": 0.08,
      "technical_confirmation_count": 4,
      "technical_reasons": "trend=up; ma_short_up; close_above_ma20; ma20_slope_up",
      "lifecycle_score_diagnostics": {
        "score_source": "explicit",
        "confidence_source": "explicit",
        "reason_code": "",
        "evidence_buckets": ["rank", "market_data", "technical"],
        "strategy_key": "ai_scanner"
      },
      "理由": "AI scanner selected candidate"
    },
    "expected": {
      "code": "688111",
      "source_score": 0.91,
      "confidence": 0.88,
      "candidate_confidence": 0.88,
      "min_technical_confirmation_count": 4,
      "score_source": "explicit",
      "selected_at": "2026-04-24 10:00:00"
    }
  },
  "task_quant_auto_entry": {
    "expected": {
      "attempted": 1,
      "events": 1,
      "promoted": 1,
      "eligible": 0,
      "skipped": 0,
      "ui_summary": "Auto-entry: attempted 1, promoted 1, eligible 0, skipped 0"
    }
  },
  "ui_candidate_diagnostics": {
    "row": {
      "id": "600001",
      "cells": ["600001", "eligible 股", "行业A", "main_force", "10.00", "100", "20", "2"],
      "code": "600001",
      "name": "eligible 股",
      "eligible_status": "eligible",
      "blocking_reason": "",
      "candidate_score": 0.82,
      "candidate_confidence": 0.79,
      "source_score": 0.82,
      "confidence": 0.79,
      "technical_confirmation_count": 4,
      "lifecycle_score_diagnostics": {
        "score_source": "derived",
        "confidence_source": "derived",
        "reason_code": "",
        "evidence_buckets": ["rank", "market_data", "technical"]
      },
      "already_in_quant": false
    },
    "expected": {
      "score_text": "Score 0.82",
      "confidence_text": "Confidence 0.79",
      "status": "eligible"
    }
  }
}
```
