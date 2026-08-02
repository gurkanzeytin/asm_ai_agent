# COMPOSITIONAL-QUERY-ALGEBRA-001 — Walkthrough

## What changed

The agent now carries analytical questions as composable plan data instead of
requiring a catalog entry for every complete sentence.

### Conditional numerator and denominator

`InlineMetric` can carry:

- multiple numerator predicates;
- multiple denominator predicates;
- the legacy single predicate for backward compatibility.

For example, “Yabancı hastalar içinde kadınların gelmeme oranı” becomes:

- denominator: `Uyruk <> Türkiye`;
- numerator: `Uyruk <> Türkiye AND CinsiyetId = K AND RandevuDurumu = Gelmedi`.

The SQL builder validates every column, operator and value, joins the conditions
with `AND`, and renders a null-safe conditional denominator. No question text
or LLM-produced SQL fragment enters this structure.

The same path accepts metadata-defined cohorts, statuses, gender aliases and
ordinary values grounded by `ValueResolver`. This makes the behavior depend on
column values and semantic metadata rather than a list of complete questions.

### Multiple metrics and breakdowns

The deterministic builder now preserves multiple verified metrics in:

- ordinary one- or multi-dimension breakdowns;
- time trends;
- two-period comparisons, including composite rates;
- three-or-more-period breakdowns;
- three-or-more grounded entity comparisons.

Composite rates in a two-period comparison are evaluated in read-only scalar
subqueries for each period. This avoids invalid aggregate nesting while keeping
the requested rate instead of listing it as skipped.

### Coverage diagnostics

Columns used inside composed metric predicates now count as consumed. They must
not appear in the outer `WHERE` or `GROUP BY`, so the previous coverage checker
incorrectly reported them as dropped even when the SQL used them correctly.

## Examples now represented by general shapes

- “Kadın hastalar arasında yabancıların oranı” — two conditional predicates.
- “Yabancı hastalar içinde kadınların gelmeme oranı” — three conditional
  predicates.
- “Bölüm ve şube bazında sayı, gelmeme oranı ve ortalama süre” — three metrics,
  two dimensions.
- “Aylık sayı, gelmeme oranı ve ortalama süre eğilimi” — three-metric trend.
- “2024 ile 2025 için sayı, oran ve süreyi karşılaştır” — three metrics, two
  periods.

## Evaluation

`compositional_query_algebra_v1.json` is a separate seven-case deterministic
regression suite covering the shapes above. Focused unit tests also exercise
grounded department containment, the temporal “içinde” false-positive guard,
outer-filter leakage and fail-closed predicate validation.

## Verification commands

```bash
PYTHONPATH=backend .venv/bin/pytest -q backend/tests/test_composed_cohort_share.py
PYTHONPATH=backend .venv/bin/pytest -q backend/tests/test_evaluation_harness.py -k compositional_query_algebra
PYTHONPATH=backend .venv/bin/pytest -q
.venv/bin/ruff check backend
```

Real SQL Server values are not available on this computer. Value-specific
grounding and final UI behavior therefore remain Monday's live smoke-test step;
the current automated tests use the same repository/value-resolver interfaces
with deterministic fixtures.
