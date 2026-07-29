# LIVE-UI-FIXES-001 Implementation Plan

## Scope

Live UI tests found three high-signal issues that can be fixed without changing API route responsibilities or prompt files:

- Block row-level patient/contact identity output before API/report presentation.
- Let users reset conversational memory inside the same session with natural reset phrases.
- Make single-branch branch breakdowns explicit in deterministic report templates.
- Prevent a complete branch comparison question from inheriting stale status filters just because it contains comparison wording.

## Planned Changes

1. Add a result-safety detector for sensitive detail columns such as `HastaId`, patient name, identity, phone, email, address, and birth date fields.
2. Reuse the existing `unsafe_detail_output` transport boundary so blocked rows are not forwarded to API/table consumers.
3. Add a deterministic report message for sensitive detail blocking.
4. Add inline context reset detection in `ContextManager.resolve`, clearing the session before resolving the remaining question text.
5. Add a single-branch note in deterministic single-row/table rendering when the result contains exactly one branch row.
6. Use the analytics/insight label column to word single-branch comparison narratives as branch results instead of generic category/status results.
7. Narrow generic comparison follow-up detection so full independent comparison questions do not inherit stale status filters.
8. Add focused backend tests for safety, memory reset, single-branch presentation, insight wording, and stale-filter isolation.

## Out Of Scope

- Full repair of complex month-to-month comparison SQL generation.
- Full meta-conversation memory answers such as "son üç sorumda ne istemiştim?"
- Frontend chart type enforcement for pie chart requests.
