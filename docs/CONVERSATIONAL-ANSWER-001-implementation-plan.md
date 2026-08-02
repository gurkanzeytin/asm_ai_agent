# CONVERSATIONAL-ANSWER-001 — Implementation Plan

## Goal

Turn ambiguous analytical questions into resumable, targeted clarification and guarantee useful deterministic commentary for common SQL result shapes.

## Scope

1. Detect an unbounded `daha önce` cohort when it is paired with a current-year patient-overlap request.
2. Detect average-duration wording that does not say whether the user wants stored/planned or actual start/end duration.
3. Persist these clarification fields without overwriting the last valid conversation context.
4. Resume the original question after a bounded answer such as `Bir önceki takvim yılı`, `2024`, `Planlanan süre` or `Fiili süre`.
5. Surface display-safe KPI labels and formatted values in deterministic insight narratives.
6. Add a runnable synthetic commentary evaluation covering scalar, ratio, distribution, comparison, trend, empty and data-quality results.

## Safety constraints

- No date lower bound or duration meaning is guessed.
- Only offered/recognized clarification answers resume the request.
- Resolved questions return to the same planner, deterministic SQL builder and read-only validator.
- Commentary is produced only from typed analytics values; no raw patient fields or invented claims are used.
- Empty results cannot emit leader, increase or decrease claims.

## Verification

Run smart-clarification tests, the commentary evaluator, conversation-memory tests, both colloquial suites, the variation matrix, Ruff and the complete backend suite.
