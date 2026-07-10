# AG-019 - Walkthrough

The agent graph is unchanged. `GenerateReportNode` still calls `WorkflowService.execute_report_generation`, which still delegates to `ReportService`.

Inside `ReportService`, the executed `QueryResult` is classified first:

- `EMPTY`: no rows.
- `SINGLE_VALUE`: one row with one field.
- `SINGLE_ROW`: one row with multiple fields.
- `TABLE`: multiple rows within `REPORT_ANALYTICAL_ROW_THRESHOLD`.
- `ANALYTICAL`: row count above `REPORT_ANALYTICAL_ROW_THRESHOLD`.

For all non-analytical types, `TemplateReportRenderer` returns deterministic markdown and no LLM call is made. For analytical results, the existing prompt rendering and LLM report generator path is used.
