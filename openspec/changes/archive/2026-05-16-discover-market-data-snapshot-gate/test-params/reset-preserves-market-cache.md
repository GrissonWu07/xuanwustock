# Test Parameters: Reset Preserves Market Cache

## db_reset_preserves_cache

```json
{
  "data_dir": "data",
  "cache_file": "local_sources/tdx/kline/kline_type=minute30/600001.parquet",
  "db_files": ["xuanwu_stock.db", "xuanwu_stock_replay.db"],
  "expected": {
    "cache_preserved": true,
    "db_removed_or_recreated": true
  }
}
```
