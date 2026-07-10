# BUG-001 Implementation Plan

## Goal

Fix incorrect report classification that routed simple list queries with more than 20 rows to `ReportType.ANALYTICAL`, causing unnecessary LLM invocation and timeout/retry latency.

## Scope

- Update report classification to use query intent and result shape.
- Keep `TemplateReportRenderer` unchanged.
- Preserve API and frontend contracts.
- Add regression tests for list, summary, and analytical paths.

## Approach

1. Extend `ReportClassifier.classify` to accept optional `question` and `sql` context.
2. Detect list, summary, and analytical intent from normalized Turkish/English keywords.
3. Route list/table results to `ReportType.TABLE` regardless of row count.
4. Route count and single-row summary shapes to deterministic templates.
5. Route true trend, comparison, insight, and analysis prompts to `ReportType.ANALYTICAL`.
6. Pass question and SQL from `ReportService` into the classifier.
7. Add INFO logging for classifier decisions.
8. Cover regressions in reporting and performance tests.
