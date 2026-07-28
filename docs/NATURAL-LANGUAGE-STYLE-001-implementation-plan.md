# NATURAL-LANGUAGE-STYLE-001 Implementation Plan

## Goal

Improve Med Agent's Turkish answer style so short answers, tables, clarifications, and LLM-generated narratives read less mechanically.

## Scope

- Add shared natural Turkish style rules to the system, report, insight, and observation prompts.
- Update deterministic report templates for single-value, single-row, table, empty-result, comparison-fallback, and clarification-fallback responses.
- Keep SQL generation, validation, execution, routing, and database behavior unchanged.
- Add regression tests for the new prompt contract and deterministic wording.

## Validation

- Run focused backend tests for prompts, report templates, result-size wording, answerability fallback, and intent/greeting coverage.
- Verify the local UI with a representative non-2026 question.
