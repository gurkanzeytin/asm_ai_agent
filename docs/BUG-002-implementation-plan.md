# BUG-002 Implementation Plan

## Goal

Fix aggregation SQL generation so entity answers return descriptive values, such as doctor name or department name, instead of user-facing IDs.

## Scope

- Keep API and frontend contracts unchanged.
- Do not change report rendering behavior.
- Fix only the SQL generation pipeline inputs and generated SQL normalization.
- Add regression coverage for the five reported aggregation questions.

## Approach

1. Verify whether IDs originate before or after SQL execution.
2. Improve schema retrieval so detected entity tables and bridge/fact tables are selected together.
3. Add a query-analysis fallback for "busy department" so it retrieves appointment context.
4. Tighten SQL prompt rules for aggregation entity projections.
5. Add a narrow SQLService guard that removes redundant `id` / `*_id` SELECT projections when the SQL already includes a descriptive column and aggregate.
6. Add deterministic regression tests for retrieval and SQL projection normalization.
