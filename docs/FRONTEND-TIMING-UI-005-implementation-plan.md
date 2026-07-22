# Frontend Timing UI 005 - Implementation Plan

## Scope

- Align the thinking avatar and status bubble on one center line with equal heights.
- Capitalize Turkish chart type labels.
- Separate full workflow response duration from SQL execution duration according to the backend API contract.
- Move toast notifications back to the top-right.

## Timing Contract

- `timing.total_ms`: complete backend workflow duration shown as response time.
- `timing.execute_sql_ms`: database execution duration shown in the SQL result header.
- `metadata.latency_ms`: final report-generation latency, used only as a compatibility fallback when workflow timing is unavailable.

## Verification

- Frontend hook contract tests and component layout tests.
- Backend report endpoint timing mapping test.
- TypeScript, ESLint, production build, and local HTTP smoke test.
