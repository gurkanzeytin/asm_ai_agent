# BUG-003 Implementation Plan

## Objective

Make calendar-year-only conversational continuations safe and deterministic, evaluate
answerability after context resolution, and prevent SQL result-row cardinality from being
presented as a business KPI for aggregate queries.

## Architecture

1. Extend the deterministic context/date extractor with Turkish calendar-year forms and
   relative-year phrases. Keep date precedence in the resolver: current explicit date,
   inherited date only when absent, analytical default, fallback.
2. Gate date-only inheritance on a successful session anchor containing an entity plus a
   metric or analysis type. Route an unanchored date fragment to clarification.
3. Pass the resolved question and typed inherited signals into the answerability guard and
   expose raw/resolved input diagnostics at the workflow/API boundary.
4. Classify executed results from the `QueryPlan` as raw rows, grouped rows, scalar aggregate,
   multi-metric scalar aggregate, time series, or categorical grouped result.
5. Preserve physical SQL row count as technical metadata. Emit user-facing
   `displayable_kpis` only from planned metrics and their actual result aliases.
6. Make the frontend consume `displayable_kpis`; retain a result-shape-aware compatibility
   fallback that never renders generic scalar distribution artifacts.
7. Add backend/frontend regressions, run full suites, production build, and attempt the live
   same-session scenario.

## Safety Boundaries

- No SQL validator, read-only enforcement, allowed-object, provider-routing, session TTL,
  session isolation, or PII rule changes.
- No year or acceptance sentence is hard-coded.
- Metric formulas remain sourced from `metric_catalog.json`.
- Database access remains outside API routes.

