# Test Parameters: AI Scanner 测试隔离与排序稳定性

## 场景 A：原始热门板块排序

- top sectors: `人工智能`
- constituents:
  - `688111` / `金山办公` / latest price `321.88` / change pct `4.2`
  - `000001` / `平安银行` / latest price `10.12` / change pct `1.1`
- history provider: returns empty `DataFrame`
- expected order: `688111`, `000001`
- expected repeated order: same as first scan

## 场景 B：注入 history provider 不调用 market client

- sectors: same as scenario A
- history provider: returns empty `DataFrame`
- market client sentinel: raises `AssertionError` if called
- expected: scanner completes and sentinel is unused

## 场景 C：fake market client 是唯一历史行情 IO

- sectors: same as scenario A
- history provider: omitted
- fake market client: returns deterministic rising history frame
- expected: fake market client records calls; real AkShare local client is not used

## 场景 D：最终分数并列 tie-break

- candidates: at least two rows with equal final `scanner_score`, `sector_score`, `technical_score`, and `preliminary_score`
- original candidate order: `688111` before `000001`
- expected order: original candidate order wins before stock code fallback
- masked-test guard: scores must be equal so score order cannot hide tie-break behavior

## Commands

```powershell
python -m pytest -q tests/test_ai_stock_scanner.py
python -m pytest -q tests/test_ai_stock_scanner.py --cov=app.discover.ai_stock_scanner --cov-report=term-missing --cov-fail-under=85
```
