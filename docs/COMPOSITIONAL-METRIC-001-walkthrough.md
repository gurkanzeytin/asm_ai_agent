# COMPOSITIONAL-METRIC-001 — Walkthrough

## What changed

Metric definitions can now declare `compositional_signals`. Each inner group describes one required meaning component; at least one term from every group must appear. For example, a missing-doctor request combines a doctor concept with a missing/null operator, while a waiting-rate request combines waiting/queue language with ratio/share language.

This avoids encoding complete questions as aliases and lets the same concepts compose across new sentence structures. The first slice covers:

- unique patient count;
- missing doctor and missing department counts;
- invalid date ranges;
- zero or negative durations;
- stored/calculated duration mismatches;
- checked-in rate;
- in-progress count;
- waiting rate.

The planner also protects more specific catalog matches. “Different branches + repeat patient”, for example, remains `cross_branch_repeat_patient_count` instead of being reduced to generic `unique_patient_count`.

## Evaluation discipline

Eight cases used to build the feature (`COL-BLIND-043` through `050`) were moved to `colloquial_regression_v2`. Eight questions written after the code change (`052` through `059`) replaced them in the 35-case blind set.

| Measurement | Passed | Failed | Accuracy |
|---|---:|---:|---:|
| Refreshed holdout before this slice | 15 | 20 | 42.86% |
| Same holdout after this slice, before promotion | 23 | 12 | 65.71% |
| Fresh holdout after promotion/replacement | 23 | 12 | 65.71% |
| Colloquial regression | 24 | 0 | 100% |
| Catalog variation matrix | 887 | 0 | 100% |

Seven of the eight new replacement questions passed without further tuning. `COL-BLIND-059`, which expresses waiting as “standing in line”, remains blind and failed; it was not used to modify the implementation.

## How to verify

From `backend/`:

```bash
../.venv/bin/pytest -q tests/test_colloquial_normalization.py tests/test_evaluation_harness.py
../.venv/bin/python -m tools.evaluation run --suite colloquial_blind_v2 --mode sql-generation --no-write
../.venv/bin/python -m tools.evaluation run --suite colloquial_regression_v2 --mode sql-generation --no-write
../.venv/bin/python -m tools.evaluation.question_variations
```
