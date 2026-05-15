# Test Parameters: Lifecycle Event Handoff

These parameters are consumed by `tests/test_discover_lifecycle_scoring.py`.

```json
{
  "normalized_ai_event_row": {
    "row": {
      "code": "688111",
      "name": "金山办公",
      "source": "AI stock selection",
      "strategyKey": "ai_scanner",
      "source_score": 0.91,
      "score": 0.91,
      "confidence": 0.88,
      "candidate_confidence": 0.88,
      "trend": "up",
      "technical_confirmation_count": 4,
      "technical_reasons": "trend=up; ma_short_up; close_above_ma20; ma20_slope_up",
      "lifecycle_score_diagnostics": {
        "score_source": "explicit",
        "confidence_source": "explicit",
        "reason_code": "",
        "evidence_buckets": ["rank", "market_data", "technical"],
        "data_quality": 1.0,
        "rank_component": 1.0,
        "strategy_key": "ai_scanner"
      },
      "reason": "AI scanner selected candidate"
    },
    "expected": {
      "source_score": 0.91,
      "confidence": 0.88,
      "trend": "up",
      "technical_confirmation_count": 4,
      "score_source": "explicit"
    }
  },
  "eligible_event_enrichment": {
    "event": {
      "stock_code": "688111",
      "stock_name": "金山办公",
      "source_type": "discover",
      "source_key": "ai_scanner",
      "source_score": 0.91,
      "confidence": 0.88,
      "trend": "up",
      "status": "eligible",
      "reason_text": "AI scanner selected candidate",
      "payload": {
        "entry_gate": {"reason_code": ""},
        "technical_confirmation_count": 4,
        "lifecycle_score_diagnostics": {"score_source": "explicit"}
      }
    },
    "expected": {
      "candidate_score": 0.91,
      "candidate_confidence": 0.88,
      "eligible_status": "eligible"
    }
  },
  "zero_evidence_event_row": {
    "row": {
      "code": "300001",
      "name": "特锐德",
      "source": "Main force selection",
      "strategyKey": "main_force",
      "source_score": 0.0,
      "score": 0.0,
      "confidence": 0.0,
      "candidate_confidence": 0.0,
      "trend": "neutral",
      "technical_confirmation_count": 0,
      "lifecycle_score_diagnostics": {
        "score_source": "none",
        "confidence_source": "none",
        "reason_code": "insufficient_measurable_evidence",
        "evidence_buckets": [],
        "strategy_key": "main_force"
      },
      "reason": "source-only candidate"
    },
    "expected": {
      "source_score": 0.0,
      "confidence": 0.0,
      "trend": "neutral",
      "reason_code": "insufficient_measurable_evidence"
    }
  },
  "weak_ai_event_handoff": {
    "row": {
      "code": "688222",
      "name": "成都先导",
      "source": "AI stock selection",
      "strategyKey": "ai_scanner",
      "source_score": 0.0,
      "score": 0.0,
      "confidence": 0.0,
      "candidate_confidence": 0.0,
      "trend": "neutral",
      "technical_confirmation_count": 0,
      "technical_reasons": "technical_data_unavailable",
      "lifecycle_score_diagnostics": {
        "score_source": "none",
        "confidence_source": "none",
        "reason_code": "insufficient_measurable_evidence",
        "evidence_buckets": [],
        "strategy_key": "ai_scanner"
      },
      "reason": "AI scanner candidate without technical confirmation"
    },
    "expected": {
      "attempted": 1,
      "events": 1,
      "promoted": 0,
      "eligible": 0,
      "event_status": "recommended_only",
      "skip_reason": "ai_requires_technical_confirmation",
      "quant_status": "inactive"
    }
  }
}
```
