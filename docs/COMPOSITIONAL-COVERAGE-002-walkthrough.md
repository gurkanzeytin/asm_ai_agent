# COMPOSITIONAL-COVERAGE-002 Walkthrough

## Outcome

The agent now resolves the seven previously weak colloquial families through
catalog concepts rather than memorized complete questions:

1. Unbounded historical overlap asks which prior period to use.
2. Creation date and appointment date equality selects same-day booking count.
3. Protocol opening after appointment time selects average protocol delay.
4. Real duration expressed as start/end or minutes selects calculated duration.
5. Per-calendar-day wording selects daily average appointment count.
6. Same-date, multi-doctor patient wording selects the relationship metric.
7. Waiting-line share wording selects waiting rate without confusing `sirala`.

## Implementation

- Added reusable concept groups and safe Turkish variants to the metric catalog.
- Removed the ungrounded `ortalama randevu adedi` synonym from the patient-based
  ratio; patient language remains required for that metric.
- Allowed a specialized compositional relationship to suppress several broad
  keyword metrics only when every broad metric is a strict subset.
- Preserved directly matched sibling metrics and explicit multi-metric requests.
- Centralized unbounded-history markers and replacement in a shared helper.
- Expanded history clarification to `daha once`, `onceden`, `gecmiste`, and
  `evvelce`, while requiring repeat/current-period language to avoid lead-time
  false positives.

## Evaluation discipline

- The seven inspected failures were promoted from blind to regression.
- Fresh blind replacements were added only after implementation.
- The first fresh run scored 34/35. Its single failure was promoted to
  regression before a general precedence fix and a new unseen replacement.
- The second fresh run also scored 34/35. The failure was promoted, the
  same-date composition was generalized, and another unseen replacement added.
- Final fresh blind score: 35/35.
- Final promoted regression score: 44/44.

## Verification

- Focused tests: 66 passed.
- Catalog-generated variation matrix: 887/887 passed.
- Full backend suite: 2376 passed, 1 skipped.
- Ruff on all changed Python files: passed.
- Repository-wide Ruff remains outside this feature gate because the imported
  project already contains 671 unrelated legacy lint findings.
