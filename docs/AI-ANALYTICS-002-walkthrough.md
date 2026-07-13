# AI-ANALYTICS-002 - Walkthrough

## Pipeline

```
execute_sql → analyze_results (Analytics Engine)
    → generate_insights (NEW: Insight Intelligence Engine)
    → generate_report → END
```

`GenerateInsightsNode` runs only when `AgentState.analytics` exists; it is skipped otherwise and swallows its own failures — the report pipeline can never be blocked by insights.

## Insight flow (inside `InsightEngine.generate`)

1. **Rules Engine (deterministic)** — evaluates the analytics object:
   - growth_rate > 15 → `HIGH_GROWTH`; 0–15 → `MODERATE_GROWTH`; < 0 → `DECLINING`
   - trend upward/downward/stable → `POSITIVE_TREND` / `NEGATIVE_TREND` / `STABLE_TREND`
   - one category > 50% share → `DOMINANT_CATEGORY`; shares within 10 percentage points → `BALANCED_DISTRIBUTION`
   - top categorical value > 1.5 × average → `OUTLIER_DETECTED`
   - single-value shape → `SINGLE_METRIC`; empty/zero-count analytics → `INSUFFICIENT_EVIDENCE`
2. **Confidence (deterministic, never LLM)** — LOW on insufficient evidence; MEDIUM when shape-expected metrics are missing (e.g. `growth_rate` is None on a time series) or no rule fired; HIGH when analytics are complete and rules exist.
3. **Narrative**:
   - Confidence LOW → the LLM is **not called**; the output is the canonical `"Insufficient analytical evidence."` structure.
   - Otherwise the LLM receives ONLY: whitelisted analytics JSON (scalar metrics, top-5 rankings, distribution percentages, insight fields), the detected rules, and the visualization decision. Never SQL, schema, or raw rows. It must answer with JSON in the fixed narrative shape; the response is parsed (think-block/code-fence tolerant) and validated against `InsightNarrative`; any `confidence` field from the LLM is discarded.
   - On any LLM failure or invalid JSON → deterministic template narrative built strictly from computed metrics (`llm_generated: false`).

## Output schema (structured, no markdown)

```json
{
  "title": "Appointment Trend Analysis",
  "summary": "Appointments increased steadily during the period.",
  "highlights": ["Growth reached 18.4%", "The largest increase occurred in 2026-05"],
  "observations": ["..."],
  "considerations": [],
  "rules": ["HIGH_GROWTH", "POSITIVE_TREND"],
  "confidence": "HIGH",
  "llm_generated": true
}
```

Exposed as the optional `insights` object on `ReportResponse` (additive, non-breaking), with `generate_insights_ms` added to the timing schema.

## Prompt design (`backend/app/prompts/insight_generation.md`)

Strict grounding instructions: use only provided numbers, no calculations, no invented statistics/trends/causes/recommendations, no SQL/database mentions, every number must appear verbatim in the analytics payload, JSON-only response. Rendered via the existing `PromptLoader`/`PromptRenderer` infrastructure.

## Logging / profiling

Each run emits a structured `INSIGHT ENGINE` block and `extra` fields: insight generation time, LLM duration, prompt tokens, completion tokens, rule count, confidence, and whether the narrative was LLM-generated. The workflow timing table gains an "Insight Engine" row.

## Files created / modified

Created: `backend/app/insights/{__init__,models,rules_engine,templates,prompt_builder,insight_engine}.py`, `backend/app/prompts/insight_generation.md`, `backend/app/agent/nodes/generate_insights.py`, `backend/tests/test_insights.py`.

Modified (plumbing only): `backend/app/agent/graph.py`, `backend/app/agent/state.py`, `backend/app/application_models/{workflow_result,workflow_metrics}.py`, `backend/app/services/reporting_service.py`, `backend/app/schemas/report.py`, `backend/app/api/v1/endpoints/reports.py`, `backend/tests/test_execution.py` (node-sequence assertion).
