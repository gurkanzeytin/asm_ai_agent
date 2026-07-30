# LIVE UI Patient Relationship Fix 004 - Walkthrough

## What Changed

- `patient_appointment_span_days` answers first-to-last appointment span questions with a `patient_spans` CTE.
- `multi_period_patient_overlap_count` answers "patients in both periods" questions with a two-period presence CTE.
- Follow-ups such as "Ortalama gun farkini goster" keep the prior year scope.
- Follow-ups such as "Bu hastalari subelere gore kir" keep the two explicit years and add the branch dimension.

## SQL Shape

Patient span:

- Group by `HastaId`.
- Compute `MIN(BaslangicTarihi)`, `MAX(BaslangicTarihi)`, and `DATEDIFF(day, MIN, MAX)`.
- Return scalar average/min/max by default, or `TOP (N)` patient rows for explicit top-list requests.

Patient overlap:

- Evaluate the two date periods with `OR`, not impossible `AND` filters.
- Mark each `HastaId` with `in_baseline_period` and `in_current_period`.
- Count only patients where both flags are `1`.
- For branch breakdown, join the overlap cohort back to the view and group by `SubeAdi`.

## Verification

- `ruff` passed for changed app and test files.
- Focused regression tests: 4 passed.
- Related broad set: 145 passed.
- Status semantics set: 53 passed.
- Live UI rerun of the patient-relationship session: 7/7 completed, no memory/error text.

