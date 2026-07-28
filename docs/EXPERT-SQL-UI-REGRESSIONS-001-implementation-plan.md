# EXPERT-SQL-UI-REGRESSIONS-001 Implementation Plan

## Scope

Fix UI-observed analytical SQL regressions for 2023/2024 appointment reporting questions:

- Distinguish sort wording from percentage-change wording.
- Preserve HAVING thresholds and bind them to the intended metric.
- Support monthly grouping phrases such as "ayina gore".
- Preserve three explicit report dimensions.
- Ground terse follow-up filters such as "sadece Radyoloji".
- Keep creator/person wording on the creator dimension.

## Approach

1. Update semantic catalog/planner matching for sort direction, threshold ranking, and month granularity.
2. Update conversational merge so retained thresholds stay attached to their original metric.
3. Update deterministic SQL generation to support more than two dimensions and render HAVING against the bound metric expression.
4. Update value resolution for two-entity "X ve Y bolumlerini karsilastir" and short filter-only follow-ups.
5. Add DB-free regression tests that exercise planner, resolver, merge policy, SQL builder, and compliance.
