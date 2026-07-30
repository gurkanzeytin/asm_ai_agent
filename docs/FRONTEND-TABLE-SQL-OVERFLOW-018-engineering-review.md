# FRONTEND-TABLE-SQL-OVERFLOW-018 Engineering Review

## Review

The change stays in the presentation layer and does not touch API routes, repositories, database access, prompts, or LLM provider code.

The SQL rendering path now uses a shared component instead of duplicate `<pre>` markup. This reduces visual drift between chat SQL blocks and the details-panel modal.

Markdown table expansion is scoped to assistant message rendering. The inline table remains scrollable, while the modal provides a larger inspection surface for wide result tables. Numeric table cells retain right alignment through the existing helper logic.

## Verification

- `npm test -- src/components/asm/InfoPanel.test.tsx src/components/asm/chat-ui-polish.test.tsx`
- `npm run build`

Both commands passed.
