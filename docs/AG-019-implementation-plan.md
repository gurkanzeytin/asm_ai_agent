# AG-019 - Implementation Plan

1. Introduce deterministic report classification under `backend/app/reporting`.
2. Add template rendering for empty, single-value, single-row, and small table results.
3. Refactor `ReportService` to try template rendering before prompt rendering or LLM invocation.
4. Add `REPORT_ANALYTICAL_ROW_THRESHOLD` to settings so large result sets continue through the LLM path.
5. Add telemetry for report type, renderer, selected template, latency, and whether the LLM was invoked.
6. Cover template rendering, analytical routing, and LLM bypass behavior with regression tests.
