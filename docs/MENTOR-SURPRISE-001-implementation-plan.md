# MENTOR-SURPRISE-001 Implementation Plan

## Goal

Measure and reduce the probability that an unseen, in-scope mentor question is
rejected or mapped to the wrong SQL, using manually authored questions that are
independent from the production catalogs and golden examples.

## Scope

- Add a separate `mentor_surprise_v1` evaluation suite.
- Cover cross-compositions such as metric + period + multiple dimensions,
  ratio + ranking, data quality + trend, and repeat behaviour + grouping.
- Treat the first run as a probe. A failed probe may not be edited into a pass:
  after a general fix it is promoted to a non-blind regression case and replaced
  by a fresh blind question.
- Keep SQL deterministic, read-only, catalog-grounded, and SQL-validator checked.
- Defer live values, SQL Server execution, and UI interaction to Monday's final
  verification because this workstation has no production database profile.

## Expected files

- `backend/tools/evaluation/resources/mentor_surprise_v1.json`
- `backend/tools/evaluation/dataset.py`
- `backend/tests/test_evaluation_harness.py`
- `backend/tests/test_composed_cohort_share.py`
- `backend/tests/test_planner_metric_consistency.py`
- Focused planner/analyzer tests for any capability gaps found by the probe
- `docs/MENTOR-SURPRISE-001-walkthrough.md`
- `docs/MENTOR-SURPRISE-001-engineering-review.md`

## Risks and controls

- A plan can mention one requested dimension while silently dropping another.
  Every multi-dimensional case also asserts all physical columns in SQL.
- A plausible SQL query can still answer the wrong denominator. Ratio cases
  assert null-safe division and prohibit status filtering that collapses the
  denominator.
- Test questions must not become production few-shot examples; the supplemental
  evaluation resource remains outside `app/resources` and all fresh cases are
  marked blind.
- Offline success does not prove real database values or UI rendering. Those
  remain explicit Monday gates.

## Verification

1. Record the untouched probe score and failure categories.
2. Add focused regressions for each general capability fix.
3. Re-run the promoted regression and fresh replacement suites.
4. Run the existing colloquial blind, variation, and full backend tests.
5. On Monday, run live SQL Server and UI smoke tests with PII-safe profiling.
