# RESULT-SIZE-SAFETY-001 Implementation Plan

## Objective

Prevent oversized SQL results from exhausting database, API, report-provider, or browser resources without changing NLU, intent classification, metric matching, context resolution, or QueryPlan semantics.

## Fixed limits

- `DEFAULT_TABLE_PAGE_SIZE = 100`
- `MAX_UI_ROWS_PER_PAGE = 100`
- `MAX_API_ROWS = 500`
- `MAX_DATABASE_FETCH_ROWS = 1000`
- `DEFAULT_GROUPED_RESULT_LIMIT = 100`
- LLM sample: top 10 plus bottom 10 safe aggregate rows

## Work plan

1. Stream arbitrary SELECT results and read one 1,001-row sentinel window.
2. Retain at most 1,000 execution rows and attach explicit truncation metadata.
3. Block oversized identifier-bearing analytical detail with a deterministic Turkish safe response.
4. Cap API serialization at 500 rows and keep source, group, returned, and displayed counts separate.
5. Cap deterministic report tables at 100 rows and generate truthful known/unknown-total notices.
6. Sanitize and reduce report-provider payloads to result shape, count/truncation metadata, and top/bottom samples.
7. Bound frontend message state and table rendering to 100 rows, with warning and pagination controls.
8. Hide tables for scalar, out-of-scope, clarification, no-result, and safe-error outcomes.
9. Add backend/frontend regression coverage, run full suites, build, and scoped lint.

## Non-goals

- No analytical planning or QueryPlan changes.
- No NLU, intent, matching, or context changes.
- No automatic `COUNT(*)` query.
- No heavy frontend pagination dependency.

