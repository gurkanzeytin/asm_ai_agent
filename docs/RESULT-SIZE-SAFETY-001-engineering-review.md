# RESULT-SIZE-SAFETY-001 Engineering Review

## Safety invariants

- Arbitrary SELECT execution never calls `all()` or `fetchall()`.
- Database consumption stops after a single 1,001-row streamed fetch.
- Execution, API, and UI boundaries are independently capped at 1,000, 500, and 100 rows.
- Reports and provider prompts never receive the full execution window.
- Unknown totals stay unknown; no expensive count query is introduced.
- Technical row counts are excluded from analytical KPI cards.
- Oversized identifier-bearing analytical detail resolves through a deterministic safe response.
- Existing planning/NLU semantics are untouched.

## Count semantics

- `source_record_count`: underlying business records, only when established by complete aggregate analytics.
- `result_group_count`: complete number of analytical groups, only when known.
- `returned_row_count`: rows serialized at the current boundary.
- `displayed_row_count`: rows intended for the first visible page, maximum 100.
- `total_count`: exact total only when already known.
- `has_more`: a sentinel or downstream cap proves additional rows exist.
- `result_truncated`: one or more boundaries removed rows.

## Review findings

The caps are defense-in-depth rather than a single presentation-only slice. The streamed repository boundary protects server memory; downstream immutable result windows prevent accidental re-expansion. The API mapper remains structural and delegates cap/count decisions to the result-safety service. Frontend rendering is safe even if the API contract regresses.

No high-cost dependency or automatic `COUNT(*)` was added. Existing chart logic already caps categorical bar data at 20 and pie data below 10; the table guard prevents oversized chart input.

## Remaining risks

- Live SQL acceptance is still required in an environment where the configured SQL Server and ODBC encryption settings are reachable.
- Interactive browser acceptance is still required when the in-app browser surface is available.
- Client pagination operates over the defensively retained first 100 rows; browsing beyond that window requires a future server-side page endpoint. The current contract intentionally prefers safety and a truncation notice.
- Repository-wide frontend lint has unrelated formatting debt in files outside this hotfix scope, although all hotfix files lint cleanly.

