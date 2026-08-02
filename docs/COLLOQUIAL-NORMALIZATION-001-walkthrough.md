# COLLOQUIAL-NORMALIZATION-001 — Walkthrough

## Implemented behavior

- `2024te`, `2024'te` and `2024 ten` resolve to the same calendar-year filter.
- Threshold wording such as `2024ten fazla randevu` is not mistaken for a year filter.
- `randv`, `randvu`, `randavu`, `girsi` and `bekliyo` are normalized through a curated resource group.
- Metric resolution sees the normalized/expanded question, so normalization affects planning rather than only entity detection.
- Unique-patient, missing doctor/department, invalid date, non-positive duration, duration mismatch, in-progress and waiting-rate concepts received reusable phrase-level vocabulary.

## Evaluation result

- Initial fixed holdout: 13/35 (37.14%).
- The same holdout after these changes: 24/35 (68.57%).
- Cases used for the changes were promoted to regression.
- Refreshed, harder holdout: 15/35 (42.86%).
- Regression suite: 16/16 (100%).

Those measurements describe this normalization slice at completion. The subsequent `COMPOSITIONAL-METRIC-001` slice promoted the eight cases used for further hardening, added eight unseen replacements, and reached 23/35 blind plus 24/24 regression.

## Reproduction

```bash
cd backend
../.venv/bin/python -m tools.evaluation run --suite colloquial_blind_v2 --mode sql-generation --no-write
../.venv/bin/python -m tools.evaluation run --suite colloquial_regression_v2 --mode sql-generation --no-write
```
