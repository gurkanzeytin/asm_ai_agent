# Frontend Timing UI 005 - Engineering Review

## Decisions

- Backend workflow timing is authoritative because it measures processing stages consistently across clients.
- Report metadata latency remains a fallback for older or partial API responses.
- SQL execution and overall response duration remain separate metrics; neither is inferred from the other.

## Tests

- Frontend verifies that a response with report latency 210ms, workflow duration 4321ms, and SQL duration 87ms displays 4321ms as response time and 87ms for SQL.
- Backend endpoint mapping verifies `execute_sql_ms`, `generate_report_ms`, and `total_ms` are returned independently.
- Thinking-state layout verifies shared height and center alignment.
- Chart labels verify Turkish title casing.

## Residual Risk

`timing.total_ms` is the sum of recorded backend workflow node durations. Network transfer and client rendering time are intentionally excluded from the displayed response duration.
