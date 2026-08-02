# COMPOSITIONAL-QUERY-ALGEBRA-001 — Implementation Plan

## Goal

Allow the agent to answer broad two- and three-part analytical questions by
composing grounded conditions, rather than adding a special metric or phrase
rule for every example.

The first reviewable slice is conditional-rate algebra:

- numerator = one or more grounded row predicates joined with `AND`;
- denominator = either all rows in the outer query scope or one or more
  grounded row predicates joined with `AND`;
- date, branch and requested breakdown filters remain outer query scope;
- predicates used to define numerator/denominator must not also leak into the
  outer `WHERE` or `GROUP BY`, which would collapse the result to 100%.

Examples are test cases for the algebra, not hard-coded capabilities:

- foreign appointments **within which** female share;
- women **within which** foreign-nationality share;
- a grounded department **within which** no-show share;
- the same compositions beside a date range or a requested breakdown.

## Expected file changes

- `backend/app/planning/models.py`: add backward-compatible numerator and
  denominator predicate collections to inline metrics.
- `backend/app/services/deterministic_sql_builder.py`: render validated
  predicate conjunctions and conditional denominators.
- `backend/app/planning/value_resolver.py`: extract the structural
  `denominator cohort -> measured cohort` relation.
- `backend/app/agent/nodes/resolve_filter_values.py`: ground both sides and
  attach one general composed-rate plan.
- `backend/tests/test_composed_cohort_share.py`: cover algebra, grounding,
  safety invariants and several value/condition combinations.
- Feature walkthrough and engineering review documents.

## Compatibility and safety

- Existing `InlineMetric.predicate` remains supported; old plans render the
  same SQL.
- Every predicate still passes the builder's column/operator allow-lists and
  literal escaping. If any member is invalid, the whole inline metric fails
  closed.
- No raw SQL is accepted from the question or the LLM.
- Only read-only aggregate `SELECT` statements are generated and they continue
  through the SQL validator.
- Unknown or ambiguous cohort text is not guessed; the existing clarification
  and partial-reading paths remain authoritative.

## Verification

1. Run focused composed-share and builder tests.
2. Run all backend tests.
3. Run Ruff on changed Python files.
4. Validate generated SQL with the existing SQL validator tests.
5. On Monday, run representative questions against the real SQL Server values
   and complete the final UI smoke test.
