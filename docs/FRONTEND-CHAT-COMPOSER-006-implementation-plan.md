# Frontend Chat Composer 006 - Implementation Plan

## Scope

- Remove framed chat-bubble surfaces from assistant responses and the thinking state.
- Keep the existing user-message bubble unchanged.
- Remove keyboard shortcut copy beneath the composer controls.
- Place a stable animated send/stop control inside the textarea surface.
- Increase sidebar brand and chat header typography without changing layout density significantly.

## Verification

- Component tests for assistant surface classes, thinking state, prompt controls, and heading typography.
- TypeScript, ESLint, full frontend tests, production build, and local HTTP smoke test.
