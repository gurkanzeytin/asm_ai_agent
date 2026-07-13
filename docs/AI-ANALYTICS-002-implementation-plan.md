# AI-ANALYTICS-002 - Implementation Plan

## Objective

Add an Insight Intelligence Engine that converts the deterministic analytics produced by AI-ANALYTICS-001 into executive-level structured insights. Hard constraint: the LLM never calculates, never infers statistics, and never generates confidence — it only verbalizes analytics it is handed.

## Plan

1. **New package `backend/app/insights/`**, fully independent of the analytics package (consumes `AnalyticsResult`, never modifies it):
   - `models.py` — `InsightRule` (HIGH_GROWTH, MODERATE_GROWTH, DECLINING, POSITIVE/NEGATIVE/STABLE_TREND, DOMINANT_CATEGORY, BALANCED_DISTRIBUTION, OUTLIER_DETECTED, SINGLE_METRIC, INSUFFICIENT_EVIDENCE), `InsightConfidence` (HIGH/MEDIUM/LOW), `InsightNarrative` (validation schema for LLM output), `InsightResult` (frozen DTO).
   - `rules_engine.py` — deterministic business rules + deterministic confidence model.
   - `templates.py` — deterministic fallback narratives assembled only from computed metrics; canonical "Insufficient analytical evidence." output.
   - `prompt_builder.py` — whitelisted analytics payload (scalar metrics, truncated rankings, insight fields, rules, visualization). Never SQL, schema, or raw rows.
   - `insight_engine.py` — orchestration: rules → confidence → LLM narrative (JSON validated) with template fallback on any failure.
2. **Prompt** in `backend/app/prompts/insight_generation.md` (repo rule: prompts never hardcoded in Python), demanding JSON-only output in the fixed narrative shape and forbidding invented facts.
3. **Pipeline**: new `GenerateInsightsNode` between `analyze_results` and `generate_report`, non-fatal like the analytics node; LLM provider injected from `AgentGraphBuilder`.
4. **Confidence (deterministic)**: LOW when evidence is insufficient (empty/zero-count analytics) — in that case the LLM is not called at all; MEDIUM when shape-expected metrics are missing or no rule fired; HIGH when analytics are complete and rules are consistent. Any `confidence` field returned by the LLM is stripped.
5. **Plumbing (additive)**: `AgentState.insights`, `WorkflowResult.insights`, `WorkflowMetrics.generate_insights_ms`, `InsightSchema` on `ReportResponse`, "Insight Engine" row in the timing table. No breaking API changes.
6. **Profiling**: structured log with insight generation time, LLM duration, prompt/completion tokens, rule count, and confidence.
7. **Tests** in `tests/test_insights.py` with a fake LLM provider (no network): growth/decline/stable, comparison, ranking/distribution, single metric, empty analytics, missing metrics, low confidence, prompt construction, rule generation, output schema, fallback paths.
