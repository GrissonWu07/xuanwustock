# Test Parameters: Discovery Lifecycle Normalization

These parameters are consumed by `tests/test_discover_lifecycle_scoring.py`.

```json
{
  "ai_structured_candidate": {
    "scanner_row": {
      "股票代码": "688111",
      "股票简称": "金山办公",
      "所属行业": "AI应用",
      "最新价": 321.88,
      "总市值": 1234.0,
      "市盈率": 48.5,
      "市净率": 8.2,
      "reason": "内部AI扫描候选",
      "scanner_score": 0.91,
      "sector_score": 0.8,
      "theme_score": 0.9,
      "technical_score": 0.75,
      "technical_reasons": "trend=up; ma_short_up; close_above_ma20; ma20_slope_up; macd_bullish"
    },
    "expected": {
      "code": "688111",
      "source_score": 0.91,
      "min_confidence": 0.7,
      "trend": "up",
      "min_technical_confirmation_count": 4
    }
  },
  "non_ai_ranked_candidate": {
    "row": {
      "股票代码": "000001",
      "股票简称": "平安银行",
      "所属行业": "银行",
      "最新价": 10.12,
      "总市值": 2000.0,
      "市盈率": 4.2,
      "市净率": 0.6,
      "amount": 80000000,
      "volume_ratio": 1.5,
      "ma5": 10.4,
      "ma10": 10.3,
      "ma20": 10.0,
      "ma20_slope": 0.02,
      "rsi": 60,
      "macd": 0.05,
      "主力净流入": 12000000,
      "理由": "低价高弹性"
    },
    "expected": {
      "min_source_score": 0.45,
      "min_confidence": 0.45,
      "trend": "up",
      "min_technical_confirmation_count": 4
    }
  },
  "source_only_candidate": {
    "row": {
      "股票代码": "300001",
      "股票简称": "特锐德",
      "理由": "主力选股"
    },
    "expected": {
      "source_score": 0.0,
      "confidence": 0.0,
      "trend": "neutral",
      "reason_code": "insufficient_measurable_evidence"
    }
  }
}
```
