# AI-INTELLIGENCE-010 Implementation Plan

## Goal

Create a repeatable end-to-end evaluation harness that measures Turkish user
questions across routing, planning, SQL source selection, SQL generation,
validation, typed result contracts, result reasoning, and final answer checks.

## Approach

- Reuse existing `QueryAnalyzer`, `QueryPlanner`, `DeterministicSQLBuilder`,
  `SQLValidator`, typed result contracts, and benchmark-style reporting.
- Keep the harness under `backend/tools/evaluation`.
- Keep evaluation cases in `backend/app/resources/evaluation_cases.json`.
- Write reports to ignored `evaluation/results/` paths.

## Steps

1. Add Pydantic evaluation case/result models and failure taxonomy.
2. Add dataset loader with catalog validation for metrics, columns, analysis
   types, and result contract names.
3. Add deterministic scorers for routing, QueryPlan, SQL generation, SQL
   semantics, result contracts, and final answer checks.
4. Add a central runner with planner-only, SQL-generation, mocked-execution,
   live-db, and full-endpoint modes.
5. Add JSON/Markdown reporting and previous-run comparison.
6. Add CLI entrypoint: `python -m tools.evaluation`.
7. Add blind evaluation cases and seven acceptance cases.
8. Add tests for schema validation, scorer behavior, reports, CLI, live skip,
   stability, and critical acceptance exit-code behavior.
