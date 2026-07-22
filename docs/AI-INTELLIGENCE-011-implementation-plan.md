# AI-INTELLIGENCE-011 Implementation Plan

## Goal

Generalize two-period comparisons so no parser, SQL builder, compliance rule, or
result contract depends on a fixed year, month, date literal, or sample question.

## Design

1. Add an ordered `QueryPlan.periods` contract containing exactly two
   `label`, `start_inclusive`, and `end_exclusive` values.
2. Resolve explicit months, years, relative periods, and custom date ranges in
   the analyzer while preserving the user's mention order.
3. Convert parser-inclusive ranges to half-open plan periods once, in the planner.
4. Generate both conditional aggregates only from `QueryPlan.periods`; treat the
   first period as baseline and the second as current.
5. Validate each aliased aggregate against its own plan boundaries through the
   parsed SQL AST.
6. Cover required formats with one parameterized pipeline test and at least 50
   generated month pairs.
7. Add four live acceptance cases and run them through SQL Server and the real API.

## Acceptance

- Month length, leap years, December rollover, non-adjacent periods, years,
  relative periods, custom ranges, and reverse mention order are supported.
- SQL contains two distinct conditional aggregates and null-safe percentage change.
- Single-period and merged-wide-window SQL are rejected.
- `PeriodComparisonResult` remains complete when baseline is zero and percentage
  change is `NULL`.
- All four required live DB and full endpoint cases pass.

