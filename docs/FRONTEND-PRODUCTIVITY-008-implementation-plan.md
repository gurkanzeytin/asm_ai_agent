# Frontend Productivity 008 - Implementation Plan

## Implemented Scope

- Smart conversation scrolling with a jump-to-latest control.
- Retry, edit-question, regenerate, shorten, and contextual follow-up actions.
- Clickable clarification suggestions derived from backend outcome metadata.
- Turkish SQL number, percentage, date, and null display formatting.
- Compact, normal, and comfortable SQL row density modes.
- Automatic chart opening and chart type selection from backend visualization metadata.
- Bar and pie category filtering by pointer or keyboard.

## Deliberate Exclusions

- Token-level streaming: the current report endpoint and LLM provider contract return a completed response and expose no token stream.
- Server-persisted conversation history: the backend stores analytical context by session but exposes no conversation-message repository or history API.
- Simulated progress stages were not added because elapsed-time labels would claim backend work that cannot be observed reliably.

## Verification

- Pure-function tests for scrolling, SQL formatting, suggestions, and chart recommendations.
- Component and controller behavior tests.
- TypeScript, ESLint, production build, and local HTTP smoke test.
