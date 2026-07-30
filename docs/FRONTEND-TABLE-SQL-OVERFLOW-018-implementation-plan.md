# FRONTEND-TABLE-SQL-OVERFLOW-018 Implementation Plan

## Scope

Fix two frontend overflow issues reported from the live UI:

- Markdown report tables can exceed the chat column and need an expand control.
- SQL shown in the details panel modal should not overflow the dialog and should use the same syntax-highlighted presentation as chat SQL blocks.

## Plan

1. Reuse the existing `SqlCode` component for details-panel SQL rendering.
2. Add sizing hooks to `SqlCode` so compact and modal contexts can set max height without duplicating SQL rendering logic.
3. Wrap markdown-rendered tables in a dedicated component that keeps inline horizontal scrolling and opens a wide dialog for inspection.
4. Improve markdown table cell/header wrapping so long labels and values do not force the chat layout wider than its container.
5. Add focused frontend regression tests for SQL modal highlighting and markdown table expansion.
