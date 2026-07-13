# AI-INTELLIGENCE-001 - Implementation Plan

## Objective

Redesign the response into independent intelligence layers: Data (truth), Analytics, Insights, Observations (NEW), and Visualization Metadata. The frontend decides which layers to render. No frontend work, no rendering, no RAG, no multi-agent, no breaking API changes.

## Plan

1. **Layer mapping.** Layers 1–3 and 5 already exist and only need exposure:
   - Layer 1 Data = `query_result` (raw DB truth, never LLM-touched) — already on the response.
   - Layer 2 Analytics = `analytics` (AI-ANALYTICS-001) — unchanged.
   - Layer 3 Insight = `insights` (AI-ANALYTICS-002) — unchanged.
   - Layer 5 Visualization = promote `analytics.visualization` to a top-level `visualization` response field (metadata only).
2. **Layer 4 Observations — new package `backend/app/intelligence/`:**
   - `models.py` — `Observation` (rule, category, text, evidence), `ObservationResult` (observations, confidence, llm_worded, rule_count, timings).
   - `templates.py` — neutral wordings per rule ("Sustained growth detected.", "One department clearly dominates.", "No significant imbalance detected.", "A downward trend is visible.") plus metric-driven wordings (top category, largest change, significant spread). Forbidden-word list (must/should/needs/recommend/advise).
   - `observation_rules.py` — deterministic transformation: insight rules + analytics metrics → observations with grounding evidence. No SQL, no calculations.
   - `observation_engine.py` — orchestration; reuses insight rules/confidence when present, recomputes via `InsightRulesEngine` otherwise. Optional LLM rewording (settings flag `OBSERVATION_LLM_WORDING`, default off) with hard validation: same count, same numbers, evidence strings preserved, no directive language — otherwise deterministic texts are kept.
3. **Pipeline**: new `GenerateObservationsNode` between `generate_insights` and `generate_report`, non-fatal like the other enrichment nodes.
4. **Plumbing (additive)**: `AgentState.observations`, `WorkflowResult.observations`, `WorkflowMetrics.generate_observations_ms`, `ObservationsSchema` + top-level `visualization` on `ReportResponse`, "Observation Engine" row in the timing table.
5. **Prompt** for optional rewording in `backend/app/prompts/observation_wording.md`.
6. **Tests** in `tests/test_observations.py`: high growth, stable/declining trend, balanced distribution, dominant category, single metric, empty analytics, determinism, LLM-rewording guardrails (changed numbers, directive language, count mismatch, provider failure), node integration, API layer schema. Full suite must stay green.
