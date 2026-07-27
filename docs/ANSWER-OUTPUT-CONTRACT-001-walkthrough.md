# ANSWER-OUTPUT-CONTRACT-001 Walkthrough

## User Experience

Default answers now stay concise. For example, an average question returns the
average value rather than a full report with findings, assumptions, metrics, and
table sections.

If the user asks for a chart, the frontend suppresses unrelated report text and
shows the chart area. If the user asks for a table or list, the table is shown
inline without extra narrative. If the user asks for "detayli rapor",
"metrikler", "bulgular", or "varsayimlar", the expanded sections remain
available.

## Backend Flow

`should_render_expanded_answer()` detects explicit detail wording. `ReportService`
uses it when rendering insight-reuse analytical reports. `GenerateReportNode`
also uses it before appending "Sorgulanan metrikler" and "One cikan bulgular".
Required limitations can still appear as short `Not:` lines in compact mode.

## Frontend Flow

`ChatMessage` now recognizes "Varsayimlar ve Sinirlamalar" as its own report
section, so it no longer gets merged into the last metric chip.
