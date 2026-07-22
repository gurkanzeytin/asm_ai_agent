# AI-INTELLIGENCE-010 Engineering Review

## Architecture Review

The harness is not a parallel product pipeline. It directly reuses production
planning, deterministic SQL generation, SQL validation, and result contract
normalization. The runner is deliberately thin: it records what each production
layer did and maps mismatches into a stable failure taxonomy.

## Safety Review

- Reports do not include live patient row data.
- Live DB mode skips when SQL Server is not configured.
- SQL checks use `sqlglot` where possible and deterministic domain checks for
  cohort, period-pair, and denominator-protection features.
- Reference SQL smoke checks are stored separately from builder templates.

## Test Review

Added `backend/tests/test_evaluation_harness.py`, covering:

- Evaluation case schema validation
- Unknown column and metric rejection
- Blind-case exclusion from few-shot retrieval
- Routing and QueryPlan scoring
- SQL AST/semantic scoring
- Ratio, period, cohort, and raw-detail checks
- Result contract and final-answer checks
- JSON/Markdown report generation
- Previous-run comparison
- CLI single-case and suite execution
- Live DB skip behavior
- Deterministic three-run stability
- Critical acceptance exit-code behavior

## Known Limits

`multi_metric_performance` currently routes correctly but remains an LLM-fallback
SQL shape. The evaluation harness records this as `sql_source=llm` rather than
forcing deterministic SQL coverage.
