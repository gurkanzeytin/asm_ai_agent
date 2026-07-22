# AI-INTELLIGENCE-010 Walkthrough

## Existing Pieces

The repository already had planner-level golden dataset tests, analytical
reasoning tests, deterministic SQL pipeline tests, endpoint tests, execution
tests, SQL validator tests, SQL Server integration tests, and an older
`tools.benchmark` model benchmark.

Those pieces were not a single layer-by-layer E2E evaluator. The new harness
connects them through one case model and one runner.

## Runner Flow

Each case is scored through these layers:

1. Routing and clarification detection
2. QueryPlan shape
3. SQL source and generated SQL metadata
4. SQL semantics with sqlglot-backed inspection
5. Optional execution or mocked execution
6. Typed result contract normalization
7. Deterministic final-answer quality checks

## CLI

Examples:

```powershell
python -m tools.evaluation run --suite blind
python -m tools.evaluation run --suite deterministic
python -m tools.evaluation run --suite live --mode live-db
python -m tools.evaluation run --case E2E-RW-004
python -m tools.evaluation report --latest
```

Live DB modes skip cleanly when SQL Server is not configured.

## Reports

Each written run produces:

- `evaluation/results/<timestamp>.json`
- `evaluation/results/<timestamp>.md`

The report omits patient rows and stores only case-level metadata, plan
summaries, generated SQL, result shape metadata, failure codes, and timings.
