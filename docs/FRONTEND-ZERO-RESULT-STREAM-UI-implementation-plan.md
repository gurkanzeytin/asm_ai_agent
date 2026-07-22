# Frontend Zero-Result Stream UI — Implementation Plan

## Scope

Trace the frontend-only path from an NDJSON `complete` event to the active conversation's rendered `ChatMessage`. Keep backend memory, planning, SQL, validation, reporting, and the streaming response contract unchanged.

## Plan

1. Instrument complete parsing, completion state replacement, committed visible state, and `ChatMessage` rendering behind an explicit development-only flag.
2. Make terminal assistant messages immutable to later progress callbacks.
3. Carry outcome and row count as presentation metadata so render traces can distinguish report visibility from SQL-table visibility.
4. Exercise the actual parser → controller → React message → Markdown path with a raw `ReadableStream` integration test.
5. Verify zero-row visibility, active-conversation attachment, placeholder removal, exactly one assistant terminal message, and stale-progress safety.
6. Run the full frontend tests and production build.

## Out of scope

- Backend session/memory changes
- QueryPlan merging
- SQL generation or validation
- Result validation or reporting
- Streaming API contract changes
