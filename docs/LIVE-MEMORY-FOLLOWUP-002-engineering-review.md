# LIVE-MEMORY-FOLLOWUP-002 Engineering Review

## Review

The changes are scoped to deterministic context resolution, QueryPlan merge behavior, SQL builder shape selection, graph routing for data-only enrichment, and table presentation state. API routes still delegate to services, DB access remains through existing workflow/repository paths, and prompts were not added to Python code.

## Risk Areas

- Period-comparison follow-ups are intentionally narrow. A fully specified question with `onceki` is not replayed against prior context, while terse forms like `Haziran 2025 ile kiyasla` still replay the last analysis.
- `ayni tablo` now suppresses raw-list bypass only when a valid prior plan exists. This preserves table shape but still allows independent raw list questions to remain self-contained.
- A dimension follow-up after a period comparison now drops fixed comparison periods and keeps the inherited single date scope. This matches the tested MVP behavior but does not attempt a per-branch May-vs-June comparison.

## Test Evidence

- `tests/test_live_memory_followups.py` covers the live memory regressions found during UI/API fuzzing.
- `tests/test_ag022_answerability.py::TestRouting` covers data-only graph routing after the enrichment path change.
- `frontend/src/components/asm/SqlResultsTable.test.tsx` covers hidden-column rerender behavior.

## Remaining Notes

The test runner still reports a pytest cache permission warning for `.pytest_cache`; it does not affect pass/fail status. The browser logs also show external Statsig network noise from the Codex shell environment; it is unrelated to the local app behavior.

