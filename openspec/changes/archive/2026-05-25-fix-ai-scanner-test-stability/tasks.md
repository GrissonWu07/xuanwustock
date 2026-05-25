# Tasks: AI Scanner 测试隔离与排序稳定性

## 1. Implementation

- [x] 1.1 稳定 AI Scanner 排序并补齐单元测试隔离防回归
  - Related requirement: `AI Scanner 单元测试隔离历史行情 IO`, `AI Scanner 候选排序稳定`, `AI Scanner 稳定性测试面向回归`
  - Design reference: `Target Behavior`, `Reuse / Common Logic Plan`, `Test Strategy`, `Standalone Verification Plan`
  - Design review reference: `design-review.md` independent re-review no blocking findings
  - Applicable rules: `PIR-001`, `PIR-002`, `TEST-003`, `TEST-008`, `PY-005`, `ENC-001`
  - Target code paths: `app/discover/ai_stock_scanner.py`, `tests/test_ai_stock_scanner.py`
  - Multi-lens review: Product=发布回归稳定；Design=无 UI；Engineering=最小窄改；DevEx=CI 不依赖外部行情；Security=无新敏感面；QA=覆盖 original bug/no-real-IO/tie-break。
  - Reuse/common logic impact: reuse existing provider/client injection, `_preliminary_score()`, `_weighted_score()`, `_history_frame()`; no new scoring duplicate.
  - Requirement scope / fallback: implement only stable tie-break and unit test isolation; no new fallback/compatibility/degraded behavior.
  - Method/function parameter plan: no new public function expected; any new helper must have <= 5 parameters.
  - Comments/logging/traceability: one concise code comment allowed for stable tie-break; no new logs; no `trace_id` context.
  - Encoding/no-mojibake: preserve existing Chinese fixture text; test parameter and review docs must be readable UTF-8 with no garbled text.
  - File size guardrail: each generated/modified code file must stay <= 1000 lines; split plan: none expected.
  - Database impact: none.
  - Backend logic confirmation: confirmed by user 2026-05-25 with “确认”.
  - API contract/layers: none.
  - API path/parameters confirmation: not applicable; no API changed.
  - API IO / async: none.
  - UI mockup/function confirmation: not applicable; no UI changed.
  - Browser/UI QA: not applicable.
  - Config parameter confirmation: not applicable; no config changed.
  - Change: Add final ranking tie-breaker `scanner_score desc -> sector_score desc -> technical_score desc -> preliminary_score desc -> original_candidate_order asc -> 股票代码 asc`; add regression tests proving injected provider prevents real-history client calls and tied scores are stable.
  - Standalone verification: run `python -m pytest -q tests/test_ai_stock_scanner.py` and coverage command from design; expected all tests pass and coverage >= 85%.
  - Real E2E test: not applicable by confirmed design; bug-entry/unit-level behavior only, no API/UI/DB/job production boundary changed.
  - Requirement-to-test mapping: each spec scenario must map to focused tests in `tests/test_ai_stock_scanner.py`.
  - Counterexample matrix: include provider absent/present, market client sentinel, repeated scan, tied final scores, original hot sector fixture.
  - Masked-test analysis: no-real-IO test must fail if market client is called; tie-break test must make final scores equal so earlier score differences do not mask tie-break behavior.
  - Broad-qualifier audit: `same input`, `same final score`, `no real IO`, `only fake market client` must match code qualifiers.
  - Validation: red-green test evidence, focused pytest, coverage, file length check, task alignment/security review.
  - Test parameters: `openspec/changes/fix-ai-scanner-test-stability/test-params/ai-scanner-stability.md`
  - Coverage target: at least 85% code coverage for `app.discover.ai_stock_scanner`.
  - Required reviews after implementation:
    - Alignment review against spec, design, design review, task, tests, and changed code.
    - Security review against data exposure, external IO, logging, dependency, config, and sensitive-data risks.
  - Review gate: all findings must be fixed and re-reviewed before completion.
