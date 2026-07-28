# EXPERT-SQL-UI-REGRESSIONS-001 Engineering Review

## Review

The fix stays inside planning, value resolution, conversational merge, SQL builder, and compliance. API routes and database access paths are unchanged.

SQL generation remains read-only and deterministic. Value filters still require grounded resolver matches; new short-filter extraction is only applied when a retained grouping dimension tells the resolver which field to check.

## Risks

- "artan sirala" is now interpreted as ascending sort when paired with sorting wording. Change-analysis wording still requires explicit change context.
- More than two dimensions can increase result cardinality. This matches the reporting request, but result-size safety should still control execution output.
- Bound thresholds can now render against a non-selected metric expression in HAVING. This is intentional for memory follow-ups where the selected metric changes but the cohort threshold remains.
