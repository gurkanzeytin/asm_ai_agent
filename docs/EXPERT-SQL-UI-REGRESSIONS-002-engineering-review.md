# EXPERT-SQL-UI-REGRESSIONS-002 Engineering Review

## Review

The changes remain in parser, semantic catalog, context resolution, planner-adjacent metric selection, and deterministic SQL generation. API routes and repository/database access are unchanged.

SQL remains read-only and validator-gated. The new threshold-year guard is scoped to year-like tokens followed by aggregate-bound wording, so normal `2024 yilinda` and month/year expressions remain supported.

## Risks

- Dimensioned time trends can produce more rows because they now preserve both `period_start` and the requested dimension.
- `ayni filtreyle` now inherits context aggressively; independent questions with that exact phrase are intentionally treated as filter-preserving follow-ups.
- Fixed-dimension count variants are suppressed when a more specific metric is present, which avoids duplicate `COUNT(*)` columns but relies on explicit wording when the user truly wants multiple metrics.
