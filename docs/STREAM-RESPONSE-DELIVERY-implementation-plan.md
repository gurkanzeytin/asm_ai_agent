# Stream Response Delivery — Implementation Plan

## Scope

Trace the existing two-turn response from `ReportingService` through FastAPI NDJSON serialization, the frontend parser, controller state, and visible assistant rendering. Do not change memory, planning, SQL, or database behavior without direct evidence.

## Plan

1. Send both reproduction questions to the actual FastAPI streaming endpoint with one session identifier.
2. Record HTTP status, every NDJSON event, the terminal payload, and connection termination.
3. Repeat through the running frontend development proxy.
4. Inspect `WorkflowResult` mapping, stream queue lifecycle, frontend parsing, controller placeholder replacement, and UI conditions.
5. Add endpoint and frontend regressions for row-bearing success, zero-row success, `SAFE_ERROR`, escaped exceptions, malformed NDJSON, and omitted optional analytical fields.
6. Change production code only if a failing boundary is reproduced.

