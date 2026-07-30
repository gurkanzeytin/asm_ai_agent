# FRONTEND-TABLE-SQL-OVERFLOW-018 Walkthrough

## User Flow

When an assistant answer contains a markdown table, the table remains inside the chat width and can be scrolled horizontally. A maximize icon appears on the table surface. Selecting it opens the table in a wide modal with both horizontal and vertical scrolling.

When SQL is opened from the details panel, the enlarged modal uses the shared SQL renderer. SQL keywords, functions, strings, and numbers are highlighted consistently with SQL blocks shown in chat messages, and long SQL lines stay inside a scrollable code area.

## Files

- `frontend/src/components/asm/ChatMessage.tsx` adds the markdown table wrapper and expansion dialog.
- `frontend/src/components/asm/InfoPanel.tsx` renders SQL through `SqlCode`.
- `frontend/src/components/asm/SqlCode.tsx` accepts `preClassName` for context-specific scroll sizing.
- `frontend/src/locales/tr.ts` adds generic table expansion copy.
- `frontend/src/components/asm/InfoPanel.test.tsx` and `frontend/src/components/asm/chat-ui-polish.test.tsx` cover the regression cases.
