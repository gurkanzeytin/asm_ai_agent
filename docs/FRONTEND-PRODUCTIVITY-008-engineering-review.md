# Frontend Productivity 008 - Engineering Review

## Architecture

- Scroll threshold logic, SQL display formatting, and follow-up selection are pure modules with isolated tests.
- Original SQL values remain authoritative; formatting affects rendering only.
- Message status and original prompt are explicit model fields rather than inferred from visible text.
- Visualization recommendations travel through the existing response-to-message-to-table data path.
- New surfaces reuse existing background, border, focus, reduced-motion, and shadow tokens.

## Safety And Accuracy

- No fake backend stages or fake token streaming are presented.
- Retry uses the exact original user prompt.
- Chart filtering replaces an existing filter for the same column instead of stacking contradictions.
- Automatic charts are limited to explicit backend recommendations; TABLE and CARD recommendations remain tables/cards.

## Remaining Backend Work

True streaming requires a streaming provider interface and an SSE or WebSocket report endpoint with cancellation semantics. Persistent history requires a repository-backed conversation/message model, API authorization boundaries, retention policy, and list/detail endpoints. Implementing either solely in browser storage would conflict with the project's previous privacy and architecture decisions.
