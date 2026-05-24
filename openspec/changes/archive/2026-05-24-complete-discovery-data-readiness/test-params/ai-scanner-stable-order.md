# Test Params: AI Scanner Stable Order

## Case: fake sector rows without real history IO

Input:

```json
{
  "sectors": [
    {"板块名称": "人工智能", "涨跌幅": 5.0, "成交额": 20000000000}
  ],
  "constituents": [
    {"代码": "688111", "名称": "金山办公", "最新价": 321.88, "涨跌幅": 4.2, "总市值": 1234.0},
    {"代码": "000001", "名称": "平安银行", "最新价": 10.12, "涨跌幅": 1.1, "总市值": 2000.0}
  ],
  "history_provider": "empty fixture"
}
```

Expected:

```json
{
  "ordered_codes": ["688111", "000001"],
  "no_real_history_network": true,
  "stable_across_runs": true
}
```
