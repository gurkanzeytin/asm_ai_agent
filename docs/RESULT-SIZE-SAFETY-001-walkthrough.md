# RESULT-SIZE-SAFETY-001 Walkthrough

## Data flow

The repository uses an async streamed result and calls `fetchmany(1001)` once. The 1,001st row is a sentinel: execution retains the first 1,000 rows and reports `has_more=true` and `result_truncated=true`. The result cursor is closed in a guarded finally path. Scalar execution also closes its cursor. No implicit total-count query is issued.

The API creates a separate transport window of at most 500 rows. Its contract exposes `source_record_count`, `result_group_count`, `returned_row_count`, `displayed_row_count`, `result_truncated`, `applied_limit`, `has_more`, and `total_count`. `total_count` remains null unless an upstream operation genuinely established it.

Deterministic table reports retain at most 100 grouped/list rows. Notices distinguish complete grouped results, known-total truncation, and unknown-total truncation. A source count such as 552,240 is never described as 552,240 listed rows.

Oversized analytical results containing identifiers such as `Id` or `HastaId` are not forwarded to analytics narration, the report provider, the API row payload, or the frontend. They receive the required deterministic Turkish safety message and a `SAFE_ERROR` outcome.

Report-provider prompts receive at most 20 sanitized rows: top 10 and bottom 10. Identifier/PII fields are removed. The payload includes result shape plus group/source/total and truncation metadata.

The frontend bounds response rows before storing them in chat state, and the table independently slices to 100 as a second guard. It maps only that bounded set, renders at most 100 data rows, shows known/unknown truncation wording, and exposes `Önceki`, `Sonraki`, and `Sayfa X` controls without a new dependency. Scalar and controlled non-table outcomes do not mount the table.

## Validation summary

- Focused backend: 19 passed.
- Focused frontend: 24 passed.
- Full backend: 1,377 passed, 1 skipped.
- Full frontend: 102 passed.
- Frontend production build: passed.
- Hotfix-scoped Python and frontend lint: passed.
- Repository-wide frontend lint: blocked by 14 pre-existing formatting errors in `ChatMessage.tsx` and `InfoPanel.test.tsx`, plus 6 existing fast-refresh warnings; hotfix files are clean.

## Live acceptance

Interactive browser acceptance could not be completed because the in-app browser was unavailable. A local API probe returned controlled responses without a server crash, but the configured SQL Server later rejected the connection with an ODBC encryption/connectivity error. Therefore the three live scenarios remain environment-blocked rather than recorded as passes. Automated tests cover the oversized payload, bounded DOM rendering, notice, pagination, and controlled fallback behavior.

