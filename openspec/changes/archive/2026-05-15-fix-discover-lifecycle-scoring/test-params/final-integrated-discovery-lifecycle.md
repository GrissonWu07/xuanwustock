# Test Parameters: Final Integrated Discovery Lifecycle

These parameters define the final `/sp-impl` completion gate for
`fix-discover-lifecycle-scoring`.

```json
{
  "required_task_param_files": [
    "discovery-lifecycle-normalization.md",
    "lifecycle-event-handoff.md",
    "discover-api-ui-diagnostics.md",
    "final-integrated-discovery-lifecycle.md"
  ],
  "backend_validation": {
    "pytest": [
      "tests/test_discover_lifecycle_scoring.py",
      "tests/test_ui_backend_api_actions.py::test_discover_snapshot_exposes_read_only_lifecycle_entry_fields",
      "tests/test_ui_backend_api_actions.py::test_discover_run_strategy_auto_trial_promotes_discovered_stocks",
      "tests/test_ui_backend_api_actions.py::test_discover_run_strategy_executes_real_selector_runners_and_persists_results"
    ],
    "changed_code_coverage_min_pct": 90
  },
  "frontend_validation": {
    "vitest": ["ui/src/tests/discover-page.test.tsx"],
    "build": "npm --prefix ui run build"
  },
  "file_length_limit": 1000,
  "expected_findings": {
    "alignment": 0,
    "security": 0,
    "unresolved": 0
  }
}
```
