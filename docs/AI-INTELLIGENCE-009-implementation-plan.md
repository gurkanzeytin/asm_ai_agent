# AI-INTELLIGENCE-009 Implementation Plan

## Goal

Reduce LLM dependence after `QueryPlan` creation by adding a deterministic SQL
builder, typed result contracts, deterministic compliance checks, and focused
acceptance tests for analytical appointment questions.

## Scope

- Reuse existing `QueryPlan`, `SQLService`, validation, execution, and analysis nodes.
- Do not add catalogs, synonyms, LLM providers, frontend changes, or database schema changes.
- Prefer deterministic builder output for supported analytical plans and keep LLM fallback for unsupported plans.

## Steps

1. Locate existing handoff from `QueryPlan` to LLM SQL generation.
2. Add `DeterministicSQLBuilder` for catalog-backed analysis types.
3. Wire builder selection into `SQLService.generate_sql` before provider calls.
4. Track internal SQL source and deterministic result schema on `GeneratedSQL`.
5. Extend `PlanComplianceValidator` with deterministic analytical checks.
6. Add typed result contracts and value normalization.
7. Route normalized typed results into `AnalyzeResultsNode` and `ResultReasoner`.
8. Add tests for metric mapping, builder selection/fallback, SQL generation, typed normalization, compliance, adaptive retry, and five acceptance questions.
