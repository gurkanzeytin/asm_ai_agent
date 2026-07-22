# Frontend Zero-Result Stream UI — Walkthrough

## Runtime path

The raw NDJSON integration passes through `generateReportStream`, `useChatController`, the active conversation message list, `ChatMessage`, and `ReactMarkdown`.

The observed trace for the zero-row fixture is:

1. `complete-parsed`: `type=complete`, `workflowId=workflow-zero-result`, and the Markdown length is non-zero.
2. `before-completion-update`: target and active conversation IDs match; the placeholder assistant ID is present.
3. `completion-updater`: the target is found, old content is empty, and new content is the complete Markdown report.
4. `state-committed`: the visible assistant has the same non-zero content length.
5. `chat-message-render`: the assistant is non-streaming and successful, outcome is `NO_RESULT_GUIDANCE`, row count is `0`, and neither the component nor a loading placeholder is returned in place of the report.

No boundary in the checked-in source drops the report. The supplied browser symptom therefore could not be reproduced in the available component runtime. The in-app browser surface was unavailable in this session, so the development-gated trace remains available for the affected live browser by setting:

```js
window.__ASM_CHAT_RUNTIME_TRACE__ = true;
```

The trace is disabled in production builds and emits nothing unless that flag is explicitly enabled in development.

## Defensive fix

A terminal assistant ID is recorded before the completion state update. Progress callbacks update only messages that are still streaming and are not terminal. This prevents late progress work from modifying a completed message after the report has committed.

Zero rows only suppress the SQL table. Report Markdown is always retained and rendered independently of rows, analytics, or visualization.

## Regression coverage

The raw-stream component integration asserts that:

- the loading state finishes;
- the Turkish zero-result heading and body are visible;
- no SQL table is rendered;
- the report remains visible after stream completion and cleanup;
- the response is attached to the selected active conversation;
- exactly one assistant terminal message exists;
- all five runtime trace boundaries retain the content.

A controller regression invokes a captured progress callback after completion and verifies that content, terminal status, and generation cleanup remain unchanged.

## Follow-up

The observed `session_id: "initial-conversation"` and `memory_turn_count: 4` are intentionally not changed here. Session-ID lifecycle cleanup should be investigated separately if live trace evidence shows the response targeting a different conversation.
