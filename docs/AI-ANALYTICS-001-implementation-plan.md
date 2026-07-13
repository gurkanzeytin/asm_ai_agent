# AI-ANALYTICS-001 - Implementation Plan

## Objective

Add a deterministic Analytics Intelligence Layer that runs AFTER successful SQL execution: detect analytical intents, calculate metrics, decide the best visualization, and prepare structured insight fields for a future LLM insight generator. No dashboards, no frontend charts, no RAG, no multi-agent, no changes to SQL generation.

## Plan

1. **New package `backend/app/analytics/`** with strictly separated responsibilities:
   - `models.py` — frozen DTOs: `AnalyticsIntent`, `DataShape`, `VisualizationType`, `VisualizationRecommendation`, `AnalyticsResult`.
   - `intent_detector.py` — rule-based Turkish analytical intent detection (TREND, COMPARISON, GROWTH_RATE, PERCENTAGE_CHANGE, RANKING, DISTRIBUTION, AVERAGE, MEDIAN, MINIMUM, MAXIMUM, TIME_SERIES, CORRELATION/FORECAST placeholders). Structured metadata, no prompt engineering.
   - `calculators.py` — pure deterministic functions plus a `CALCULATORS` registry: total, average, median, min, max, count, difference, percentage difference, growth rate, rank, top/bottom N, trend direction, largest change.
   - `analytics_engine.py` — profiles the SQL result (metric/label/temporal columns), classifies data shape (EMPTY, SINGLE_VALUE, SINGLE_ROW, TIME_SERIES, CATEGORICAL, TABULAR), computes shape-appropriate metrics, prepares insight fields.
   - `visualization_selector.py` — rule-based CARD / TABLE / BAR_CHART / LINE_CHART / PIE_CHART decision with reasons.
2. **Pipeline integration**: new `AnalyzeResultsNode` inserted between `execute_sql` and `generate_report`. Node is non-fatal by design — analytics failures are logged and swallowed so report generation always continues.
3. **State & DTO plumbing**: `AgentState.analytics`, `WorkflowResult.analytics`, `WorkflowMetrics.analyze_results_ms` (all optional, additive).
4. **API (additive only)**: optional `analytics` field on `ReportResponse` with `AnalyticsSchema`/`VisualizationSchema`; `analyze_results_ms` on `TimingSchema`. No existing field changed — non-breaking.
5. **Observability**: structured analytics log (intents, type, metrics, visualization decision, execution time) plus an "Analytics Engine" row in the existing workflow timing table.
6. **Tests**: `tests/test_analytics.py` covering intents, calculators, engine shapes (empty / single-row / time-series / categorical / large), visualization selection, determinism, and node integration. Update the one E2E test asserting the exact node sequence.

## Constraints honored

- Analytics engine uses zero LLM calls; every computation is deterministic and unit-tested for reproducibility.
- SQL generation, validation, and execution behavior untouched.
- Forecast/correlation are intent placeholders only — detected, never calculated.
