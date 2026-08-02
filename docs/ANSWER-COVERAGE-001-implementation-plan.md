# ANSWER-COVERAGE-001 — Implementation Plan

## Goal

Reduce unsupported/generic answers for colloquial analytical questions while preserving read-only SQL safety and never inventing data.

## Scope

1. Add reusable compositional signals for per-patient averages, date relationships, actual/planned duration, time trends and repeat behavior.
2. Treat year pairs followed by a comparison word as two periods rather than one continuous date span.
3. Recognize `sene` as a calendar-year synonym in both single-turn analysis and conversation context.
4. Preserve explicit raw-list requests, explicit breakdown dimensions and more specific catalog synonym matches.
5. Replace the generic empty SAFE_ERROR copy with an actionable report describing the understood metric, dimension and period without exposing technical errors.
6. Promote all holdout cases used during development and replace them with unseen cases.

## Safety and rollout constraints

- Generated SQL remains deterministic and read-only validated.
- A more specific compositional metric may replace an existing metric only when its required-column set proves that it is a specialization, or the existing metric is generic appointment volume.
- Explicit multi-metric requests and specialized relationship metrics remain authoritative.
- An ambiguous unbounded period such as “daha önce” is not silently converted into an arbitrary date range.
- SAFE_ERROR guidance never contains exception messages, SQL internals or credentials.

## Verification

Run focused tests, the fresh blind suite, the promoted regression suite, the 887-question catalog matrix, Ruff and the complete backend test suite.
