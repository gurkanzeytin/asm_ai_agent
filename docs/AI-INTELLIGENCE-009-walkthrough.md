# AI-INTELLIGENCE-009 Walkthrough

## Previous Flow

`RetrieveContextNode` builds a `QueryPlan`, `WorkflowService` appends the plan to
the SQL prompt, and `SQLService` sends the prompt to the LLM. SQL is then parsed,
validated, checked for plan compliance, and repaired once when needed.

## New Flow

`SQLService.generate_sql` first asks `DeterministicSQLBuilder` whether the
`QueryPlan` is supported. Supported plans produce SQL Server SQL directly and do
not call the LLM. Unsupported plans return to the existing LLM path with the same
single repair attempt and compliance checks.

## Supported Deterministic Shapes

- Counts and distinct counts
- Grouped distributions, rankings, top/bottom N
- Ratio and percentage queries with `NULLIF`
- Average, minimum, maximum, data quality metrics
- Time trends and cross analyses
- Period and baseline comparisons using conditional aggregation
- Cohort analysis for last-minute appointments
- Anomaly comparison by branch
- Variance analysis by verified organizational dimension

## Typed Results

Deterministic SQL emits fixed snake_case aliases. `TypedResultNormalizer`
normalizes `Decimal`, datetime, and null values, validates expected aliases, and
selects a central result contract such as `CohortResult`,
`PeriodComparisonResult`, `AnomalyResult`, `VarianceResult`, or `RatioResult`.

`AnalyzeResultsNode` uses the normalized result for analytics, validation, and
reasoning. `ResultReasoner` uses typed summaries when available and falls back to
generic numeric-column reasoning for legacy LLM SQL results.
