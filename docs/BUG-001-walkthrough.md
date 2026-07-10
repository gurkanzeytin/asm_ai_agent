# BUG-001 Walkthrough

## What Changed

`ReportClassifier` no longer treats `row_count > REPORT_ANALYTICAL_ROW_THRESHOLD` as analytical by itself. It now evaluates the submitted question and SQL text for intent signals, then combines that with the result shape.

Simple list queries such as `Doktorlari listele`, `Hastalari listele`, and `Randevulari listele` now select `ReportType.TABLE`. Because `TemplateReportRenderer` already renders `TABLE`, these responses bypass the report LLM.

Summary queries such as `Kac doktor var?` continue to use deterministic templates through single-value or single-row result shapes.

Analytical prompts such as trend, comparison, insight, or analysis requests still select `ReportType.ANALYTICAL`, so the existing LLM fallback path remains available for true analytical reports.

## Key Flow

1. `ReportService.generate_report` normalizes the query result.
2. It calls `ReportClassifier.classify(query_result, question=question, sql=sql)`.
3. The classifier logs the detected intent, selected report type, and whether the LLM will be invoked.
4. `TemplateReportRenderer` renders deterministic `EMPTY`, `SINGLE_VALUE`, `SINGLE_ROW`, and `TABLE` responses.
5. Only `ANALYTICAL` returns `None` from the renderer and proceeds to LLM generation.
