# Conversational Filter SQL Live Fix — Engineering Review

## Classification

Case B: SQL filter rendering failure. Case A was ruled out by the retained second-turn `QueryPlan` and `AgentState` trace.

## Design review

- The change stays inside the existing deterministic SQL builder and compliance boundary.
- `QueryPlan.extra_filters`, grounded `resolved_filters`, `branch_filters`, and the department filter converge on one renderer.
- Only allowlisted view columns are parsed into structured predicates.
- Text values use escaped `N'...'` T-SQL literals; numeric values remain numeric.
- Duplicate column/value predicates are emitted once.
- Unrecognized legacy expressions retain the existing validator-controlled fallback rather than gaining broader SQL privileges.
- Compliance remains fail-closed for recognized planned filters and now validates the actual column/value predicate.
- Empty result handling changes only post-execution shape classification; mismatched non-empty schemas remain blocked.

## Regression coverage

The same-session regression passes through `ContextManager`, `ReportingService`, `AgentState`, `RetrieveContextNode`, filter resolution, deterministic SQL generation, SQL validation, execution, and plan compliance. It asserts both plans and both generated SQL statements. Additional cases assert SQL predicates for gender (`CinsiyetId`), nationality (`Uyruk`), status (`RandevuDurumu`), and branch (`SubeAdi`), plus duplicate suppression and missing-filter rejection.

## Risk assessment

The primary risk is accepting arbitrary filter text. The renderer limits canonical parsing to known view columns, escapes string values, and leaves SQL safety validation intact. The secondary risk is masking real result-shape defects; the empty-shape exception applies only when both `row_count` and `rows` are empty, so all result-bearing queries retain strict alias validation.

