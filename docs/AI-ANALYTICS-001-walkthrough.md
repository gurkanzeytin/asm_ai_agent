# AI-ANALYTICS-001 - Walkthrough

## Pipeline

```
analyze_intent → retrieve_context → generate_sql → validate_sql → execute_sql
    → analyze_results (NEW: Analytics Engine + Visualization Decision)
    → generate_report → END
```

`AnalyzeResultsNode` runs only on a successful `QueryResult`. It analyzes the NLU-normalized question (falling back to the raw question), stores an `AnalyticsResult` on `AgentState.analytics`, and never fails the pipeline: skip and error paths pass the state through untouched.

## Package layout (`backend/app/analytics/`)

| Module | Responsibility |
|---|---|
| `models.py` | Frozen DTOs and enums (`AnalyticsResult`, `AnalyticsIntent`, `DataShape`, `VisualizationType`) |
| `intent_detector.py` | Diacritic-insensitive, suffix-tolerant Turkish pattern matching → analytical intents |
| `calculators.py` | Pure deterministic metric functions + `CALCULATORS` registry |
| `analytics_engine.py` | Column profiling, shape classification, metric computation, insight preparation |
| `visualization_selector.py` | Shape+intent → visualization recommendation with reason |

## How the engine works

1. **Intent detection** — e.g. "Son 6 ayın randevularını analiz et" → `[trend, time_series]`; "En hızlı büyüyen bölüm" → `[ranking, growth_rate]`; a precedence list picks the primary `analytics_type`.
2. **Column profiling** — numeric columns (id-like names deprioritized; the last aggregate-style numeric column becomes the metric), temporal columns (name patterns like `tarih/ay/date` or ISO-formatted values), first non-numeric column becomes the label.
3. **Shape classification** — EMPTY, SINGLE_VALUE (1×1 numeric), SINGLE_ROW, TIME_SERIES (temporal + numeric), CATEGORICAL (label + numeric), TABULAR.
4. **Metrics** — always: count, total, average, median, min/max (highest/lowest value). Time series adds: difference, percentage_change, growth_rate, trend_direction, highest/lowest period, largest_change. Categorical adds: full ranking, top_n/bottom_n, top/bottom category, distribution percentages (≤12 categories).
5. **Insights (future LLM input)** — pre-digested fields: `trend`, `growth_rate`, `top_category`, `largest_change`, `highest_period`, `total`, `average`, `value`.
6. **Visualization decision** — EMPTY→TABLE, single metric→CARD, >30 rows→TABLE ("Large result list"), time series→LINE_CHART ("Time-series data detected"), distribution intent with ≤6 categories→PIE_CHART, categorical→BAR_CHART, single row→CARD, fallback→TABLE. Always includes a `reason`.

## Example output

"Son 6 ayın randevularını analiz et" over monthly appointment counts:

```json
{
  "analytics_type": "trend",
  "intents": ["trend", "time_series"],
  "data_shape": "time_series",
  "metrics": {
    "count": 6, "total": 1587, "average": 264.5, "median": 240.0,
    "highest_value": 412.0, "lowest_value": 201.0,
    "difference": 39.0, "growth_rate": 19.4,
    "trend_direction": "upward",
    "highest_period": "2026-05", "largest_change": "2026-05"
  },
  "insights": {
    "trend": "upward", "growth_rate": 19.4,
    "largest_change": "2026-05", "total": 1587.0, "average": 264.5
  },
  "visualization": {"type": "LINE_CHART", "reason": "Time-series data detected"},
  "row_count": 6
}
```

"Hangi bölüm daha yoğun?" over per-department counts → `analytics_type: "comparison"`, `top_category: "Psikiyatri"`, distribution percentages, `{"type": "BAR_CHART", "reason": "Category comparison detected"}`.

## API surface (additive, non-breaking)

`ReportResponse` gains an optional `analytics` object (`AnalyticsSchema` + nested `VisualizationSchema`); `TimingSchema` gains optional `analyze_results_ms`. All existing fields unchanged; clients that ignore the new fields are unaffected.

## Logging

Each run emits a structured `ANALYTICS ENGINE` block (intents, type, shape, scalar metrics, visualization decision + reason, execution time) with the same data as `extra` fields, and the workflow timing table now includes an "Analytics Engine" row.

## Files created / modified

Created: `backend/app/analytics/{__init__,models,intent_detector,calculators,analytics_engine,visualization_selector}.py`, `backend/app/agent/nodes/analyze_results.py`, `backend/tests/test_analytics.py`.

Modified: `backend/app/agent/graph.py` (node + edges), `backend/app/agent/state.py`, `backend/app/application_models/{workflow_result,workflow_metrics}.py`, `backend/app/services/reporting_service.py`, `backend/app/schemas/report.py`, `backend/app/api/v1/endpoints/reports.py`, `backend/tests/test_execution.py` (node-sequence assertion).
