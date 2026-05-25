# Task Reviews: AI Scanner 测试隔离与排序稳定性

## Task 1.1: 稳定 AI Scanner 排序并补齐单元测试隔离防回归

### Implementation Summary

- 在 `AIStockScanner._rank_rows()` 中为 final candidate sort 增加显式 tie-breaker：
  `scanner_score desc -> sector_score desc -> technical_score desc -> preliminary_score desc -> _candidate_order asc -> 股票代码 asc`。
- `_candidate_order` 在进入 final scoring 前生成，作为同分候选的稳定来源顺序，返回结果前删除内部字段。
- 在 `tests/test_ai_stock_scanner.py` 增加 no-real-IO、final score tie-break、full-tie original order、helper/edge-case 覆盖，保证覆盖率门禁。

### TDD / Red-Green Evidence

- RED:
  - Command: `python -m pytest -q tests/test_ai_stock_scanner.py::test_ai_stock_scanner_tied_final_scores_use_sector_tiebreaker`
  - Result: failed as expected.
  - Failure evidence: expected `["688111", "000001"]`, actual `["000001", "688111"]`.
  - Meaning: current implementation only sorted by `scanner_score` and did not apply explicit `sector_score` tie-break.
- GREEN:
  - Command: `python -m pytest -q tests/test_ai_stock_scanner.py::test_ai_stock_scanner_tied_final_scores_use_sector_tiebreaker tests/test_ai_stock_scanner.py::test_ai_stock_scanner_tied_final_scores_keep_original_candidate_order tests/test_ai_stock_scanner.py::test_ai_stock_scanner_injected_history_provider_blocks_market_client_access`
  - Result: `3 passed`.

### Standalone Verification Evidence

- Command: `python -m pytest -q tests/test_ai_stock_scanner.py`
  - Result: `21 passed`.
- Command: `python -m pytest -q tests/test_ai_stock_scanner.py --cov=app.discover.ai_stock_scanner --cov-report=term-missing --cov-fail-under=85`
  - Result: `21 passed`.
  - Coverage: `85.71%`, required `85%`.

### Requirement-to-Test Mapping

| Requirement / Scenario | Tests / Evidence |
|---|---|
| AI Scanner 单元测试隔离历史行情 IO / 注入 history provider 阻止真实历史客户端访问 | `test_ai_stock_scanner_injected_history_provider_blocks_market_client_access` |
| AI Scanner 单元测试隔离历史行情 IO / fake market client 是唯一市场 IO 边界 | `test_ai_stock_scanner_fetches_history_without_proxy_env`, `test_ai_stock_scanner_uses_injected_tdx_fetcher_for_fallback_history` |
| AI Scanner 候选排序稳定 / 重复扫描返回相同顺序 | `test_ai_stock_scanner_selects_candidates_from_hot_sector_constituents` |
| AI Scanner 候选排序稳定 / 最终分数并列时使用显式 tie-breaker | `test_ai_stock_scanner_tied_final_scores_use_sector_tiebreaker`, `test_ai_stock_scanner_tied_final_scores_keep_original_candidate_order` |
| AI Scanner 稳定性测试面向回归 / 原始热门板块成分股测试保持稳定 | `test_ai_stock_scanner_selects_candidates_from_hot_sector_constituents` |
| AI Scanner 稳定性测试面向回归 / no-real-IO 回归被独立断言 | `test_ai_stock_scanner_injected_history_provider_blocks_market_client_access` |

### Requirement Counterexample Matrix

| Requirement / Scenario | Dimensions | Positive Test | Negative Test | Non-Default Variants | Adversarial Variant | Masked-Test Risk | Proving Evidence | Finding |
|---|---|---|---|---|---|---|---|---|
| 注入 history provider 阻止真实历史客户端访问 | provider present/absent, market client sentinel | injected provider returns empty frame and scan completes | sentinel raises if called | empty history frame, two candidates | market client raises `AssertionError` on any call | Not masked: scan still computes technical score path for both candidates | `test_ai_stock_scanner_injected_history_provider_blocks_market_client_access` | None |
| fake market client 是唯一市场 IO 边界 | provider absent, fake client present, proxy env | fake client records proxy removal and returns history | real client unavailable by construction | proxy env set, primary market path used | fake client would expose proxy leak | Not masked: no provider means `_history_frame()` must use market client | `test_ai_stock_scanner_fetches_history_without_proxy_env` | None |
| 重复扫描返回相同顺序 | same sector, same rows, same history | scan twice returns same ordered list | ordering would fail if unstable | empty technical history, no themes | repeated scan after same scanner state | Not masked: assertion compares both result and repeated result | `test_ai_stock_scanner_selects_candidates_from_hot_sector_constituents` | None |
| 最终分数并列使用显式 tie-breaker | equal scanner score, sector difference, full tie source order | higher `sector_score` wins tied final score; full tie keeps original source order before stock code | RED showed previous code returned source order instead | sector-score tie and full tie | final scores equal so only tie-break can decide; full tie conflicts with stock-code lexical order | Not masked: tests assert equality for earlier sort keys before relying on `_candidate_order` | `test_ai_stock_scanner_tied_final_scores_use_sector_tiebreaker`, `test_ai_stock_scanner_tied_final_scores_keep_original_candidate_order` | None |
| 原始热门板块成分股测试保持稳定 | hot sector fixture, empty history | `688111`, `000001` order retained | regression would swap order | repeated execution | empty technical data could otherwise neutralize differences | Not masked: expected exact ordered codes | `test_ai_stock_scanner_selects_candidates_from_hot_sector_constituents` | None |

### Masked-Test Analysis

- `test_ai_stock_scanner_tied_final_scores_use_sector_tiebreaker` explicitly sets `weight_sector=0`, `weight_technical=0`, `weight_theme=1` and no themes, so both candidates receive equal final `scanner_score`. The assertion also checks score equality, preventing score differences from masking the sector-score tie-break rule.
- `test_ai_stock_scanner_tied_final_scores_keep_original_candidate_order` directly passes rows where `scanner_score`, `sector_score`, `technical_score`, and `preliminary_score` all tie, with input order `688111` before `000001` so stock-code ascending would otherwise reverse the result. This proves `_candidate_order` is not masked by earlier sort keys.
- `test_ai_stock_scanner_injected_history_provider_blocks_market_client_access` uses a sentinel market client that raises on any call, so a passing test proves the provider path blocks market-client access rather than silently tolerating it.
- `test_ai_stock_scanner_selects_candidates_from_hot_sector_constituents` runs `scan()` twice on the same scanner instance, proving repeated ordering rather than a single lucky sort.

### Broad-Qualifier Audit

| Spec Qualifier | Code/Test Qualifier | Result |
|---|---|---|
| `相同输入` | repeated `scanner.scan()` with fixed fake Ak data and fixed history provider | Aligned |
| `相同最终 scanner score` | test asserts equal `scanner_score` before accepting order | Aligned |
| `不得调用真实历史行情 IO` | injected provider with failing market client sentinel | Aligned |
| `只调用 fake market client` | provider absent plus injected fake market client | Aligned |
| `显式 tie-breaker` | code lists all sort fields and directions with stable mergesort | Aligned |

### File Size Evidence

- `app/discover/ai_stock_scanner.py`: 891 lines.
- `tests/test_ai_stock_scanner.py`: 591 lines.
- Both are <= 1000 lines.

### Requirement Scope / Fallback Evidence

- No new fallback, compatibility branch, config, API, UI, DB, or async behavior was added.
- Production history fallback behavior remains unchanged.

### Parameter / Data Object Evidence

- No new public method was added.
- No method/function signature exceeds 5 parameters due to this change.

### Comment / Logging / Traceability Evidence

- Added one concise code comment explaining deterministic tie-break.
- No new logs were added; no `trace_id` context exists for this pure computation/test path.
- No sensitive data is logged.

### Encoding / No-Mojibake Evidence

- New OpenSpec and test parameter docs use readable Chinese text.
- Test fixtures retain existing Chinese stock names and sector names without mojibake.

### Independent Final Review Finding Response

- Thread 1 P1: `test_ai_stock_scanner_falls_back_to_wencai_when_sector_data_is_empty` lacked injected history provider and could touch real history clients. Fixed by injecting `history_provider=lambda code: pd.DataFrame()` into that test.
- Thread 1 P2 / Thread 2 P2: original-order tie-break evidence was masked by `preliminary_score`. Fixed by rewriting `test_ai_stock_scanner_tied_final_scores_keep_original_candidate_order` to call `_rank_rows()` with all earlier sort keys equal and input order conflicting with stock-code order.
- Verification after fixes:
  - `python -m pytest -q tests/test_ai_stock_scanner.py` -> `21 passed`.
  - `python -m pytest -q tests/test_ai_stock_scanner.py --cov=app.discover.ai_stock_scanner --cov-report=term-missing --cov-fail-under=85` -> `21 passed`, coverage `85.71%`.

### Alignment Review

- Scope matches specs/design/tasks.
- Tie-breaker code exactly follows design order.
- Tests cover each scenario and the original bug entry.
- Coverage meets 85% gate.
- No open alignment finding.

### Security Review

- No auth/authz/tenant behavior.
- No new external dependency.
- No secret, credential, token, session identifier, or raw personal data exposure.
- External IO risk is reduced in unit tests through provider/fake-client boundaries.
- No open security finding.

### Closure

Task 1.1 status: complete.
Unresolved findings: 0.
