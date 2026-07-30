# LIVE UI Patient Relationship Fix 004 - Engineering Review

## Review Notes

- Business logic remains outside API routes.
- SQL generation remains deterministic and read-only.
- The new relationship SQL uses CTEs over the existing reporting view; no direct route-level database access was added.
- Patient list output selects `HastaId` only for explicit top-list requests and does not expose name/contact columns.
- The "Iptal" behavior was not converted into SQL because the verified live status catalog states that `Iptal` is not present in the view.

## Risks

- Patient span list results are intentionally privacy-sensitive. The UI may suppress row details depending on output policy.
- Multi-period overlap currently requires two explicit detected date ranges. Ambiguous "both periods" wording without dates remains unsupported.
- Branch breakdown counts appointments for overlapping patients inside the same two periods; this is a breakdown of the cohort's appointments, not a unique patient-home-branch assignment.

## Tests

- `backend/tests/test_deterministic_sql_pipeline.py`
  - Patient span CTE and top patient rows.
  - Multi-period patient overlap CTE and branch breakdown.
- `backend/tests/test_live_memory_followups.py`
  - Patient span follow-ups keep year scope.
  - Patient overlap branch follow-up keeps both years.

