# ANSWER-OUTPUT-CONTRACT-001 Implementation Plan

## Goal

Make assistant answers match the user's requested output shape:

- Single value questions return the value and minimal context.
- Table/list requests show table output without redundant prose.
- Chart requests show chart output without leaking report text.
- Comparison requests answer the comparison directly.
- Report-style sections appear only when the user explicitly asks for detail.

## Scope

- Backend output policy gains an explicit expanded-answer detector.
- Insight-reuse reports render compact output by default.
- Template reports remove redundant single-value and comparison sections.
- Reasoning sections are gated behind explicit detail requests.
- Frontend report-section parser handles assumptions as a separate section.

## Out Of Scope

- SQL planning changes.
- Database schema changes.
- New chart types.
- LLM provider routing changes.
