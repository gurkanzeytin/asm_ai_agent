# AI-ANALYTICS-001 - Engineering Review

## Design Decisions

1. **Non-fatal enrichment layer.** `AnalyzeResultsNode` swallows its own exceptions and skips when upstream errors exist or the query result is missing/unsuccessful. Analytics can never degrade the core question→report flow; this is asserted by dedicated tests (exploding-engine, missing-result, upstream-error cases).
2. **Zero LLM, fully deterministic.** All calculations are pure functions; ranking ties break alphabetically so repeated runs produce byte-identical output (tested). Trend direction compares half-means with a ±5% stability band, which is robust to single-point noise unlike first-vs-last.
3. **Registry-based extensibility.** `CALCULATORS` maps names to functions; future analytics (correlation, forecast) plug in without touching the engine. CORRELATION and FORECAST intents are detected today but deliberately compute nothing.
4. **Heuristic column profiling.** The metric column is the last non-id numeric column (SQL aggregates are conventionally aliased last); temporal columns are recognized by name fragments (tarih/ay/date/...) or uniformly date-shaped string values. Id-like columns are deprioritized for both metric and label roles (tested).
5. **Additive API only.** `ReportResponse.analytics` and `TimingSchema.analyze_results_ms` are optional fields with defaults — existing consumers and the frontend are unaffected. Internal DTO → transport mapping stays confined to `reports.py`, per the clean-architecture rule.
6. **Reuse of NLU output.** The engine analyzes the NLU-normalized question from `DatabaseContext.normalized_query`, so analytical wording matches the same canonical vocabulary the SQL was generated from.

## Risks and Mitigations

- **Shape misclassification** on exotic result sets falls through to TABULAR → TABLE, which is always a safe recommendation.
- **`ay` name fragment** could over-match column names; the pattern uses a word boundary (`ay\b`) and value-shape detection as a second signal.
- **Large results**: metrics are O(n log n) in rows (single ranking sort); measured ~0.7 ms for 1,200 rows, negligible against LLM latency.

## Performance Impact

- Analytics node average execution: **< 1 ms** for typical results (benchmarked 0.70 ms mean over 50 runs on a 1,200-row time series, ~0.1 ms on small results).
- No additional LLM calls, no I/O; workflow latency impact is effectively zero. The node's duration is tracked in `node_timings` / `analyze_results_ms` and shown in the timing table.

## Test Coverage

`tests/test_analytics.py` — 46 tests: intent detection (10 phrasings + precedence + diacritics), calculators (basics, change metrics, edge guards, trend classification, deterministic tie-breaking, largest change), engine (trend/comparison/growth/average/ranking, empty, single-value, single-row, 100-row large dataset, id-column handling, determinism, insight fields), visualization selection matrix (9 cases), and node integration (populate, skip, upstream-error, non-fatal failure).

## Regression Results

Full backend suite: **301 passed, 0 failed** (255 pre-existing + 46 new). The only pre-existing test change is the E2E node-sequence assertion in `test_execution.py`, extended with the new `analyze_results` node.
