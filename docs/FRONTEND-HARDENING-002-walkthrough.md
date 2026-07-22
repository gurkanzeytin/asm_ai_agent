# FRONTEND-HARDENING-002 Walkthrough

## Conversation Flow

`useChatController` now owns conversation state, report requests, abort handling, metadata, and the ID of the response eligible for animation. Conversations start in memory, and no message or SQL result is written to `localStorage`.

The frontend sends the active conversation ID as `session_id`, allowing follow-up questions to use the backend context store without sharing context across conversations. Stopped requests finish their placeholder message instead of leaving an empty streaming bubble.

## Interface Changes

- Removed the settings entry because its controls had no application behavior.
- Removed placeholder upload and microphone actions.
- Removed hard-coded tool calls, timings, and process summaries from the details panel.
- Conversation selection is now a keyboard-accessible button.
- Favorite and delete controls are always reachable and have accessible names.
- Empty pending responses display the existing thinking indicator.

## Reliability And Performance

- Report JSON is checked with Zod before the UI consumes it.
- Only the newest completed response animates, with a 1.2 second maximum duration.
- Historical responses render immediately.
- SQL results load only when technical details are opened.
- Chart code loads only when the chart panel is requested.
- XLSX export and its vulnerable dependency were removed; CSV, JSON, and SQL remain.

## Tests

Vitest and Testing Library cover session propagation, abort completion, absence of browser persistence, accepted/rejected API payloads, historical response rendering, and the animation duration limit.
