# AI-INTELLIGENCE-011 Walkthrough

## Data Flow

`QueryAnalyzer` emits ordered date ranges. `QueryPlanner` maps exactly two ranges
to half-open `PeriodPlan` values. `DeterministicSQLBuilder` consumes only these
structured periods and emits separate current/baseline conditional aggregates.
`PlanComplianceValidator` parses the SQL with `sqlglot` and checks that each
aggregate contains the matching start and exclusive end boundary.

The first user period is always baseline and the second is current. The builder
does not sort periods and does not inspect the question text.

## Supported Forms

- Explicit month/year pairs in either month-first or year-first form
- Cross-year, non-adjacent, leap-year, and December rollover month pairs
- Explicit year pairs
- Current/previous month and week pairs
- Last N days/previous N days
- Two custom date ranges
- Reverse chronological mention order

## Verification

- Focused parser/builder/compliance suite: `115 passed`
- Evaluation plus generalized suite: `79 passed`
- SQL-generation acceptance: `11/11 passed`
- Live SQL Server acceptance: `4/4 passed`
- Real `/api/v1/report/` acceptance: `4/4 passed`
- Full endpoint layer accuracy: routing, plan, SQL generation, SQL semantics,
  execution, result contract, and final answer all `100%`

Reports:

- `evaluation/results/20260717T133402Z-fbb1f25e.json` (live DB)
- `evaluation/results/20260717T133635Z-1449cf58.json` (full endpoint)

