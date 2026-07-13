# AI-INTELLIGENCE-001 - Walkthrough

## Layered response architecture

```
execute_sql → analyze_results → generate_insights → generate_observations (NEW) → generate_report
```

Every successful database answer is now a five-layer intelligence package on `ReportResponse`; each layer is optional and independently usable by the frontend:

| Layer | Field | Producer | LLM involvement |
|---|---|---|---|
| 1 Data (truth) | `query_result` | SQL execution | Never |
| 2 Analytics | `analytics` | Analytics Engine | Never |
| 3 Insight | `insights` | Insight Engine | Narrative only |
| 4 Observations | `observations` | Observation Engine (NEW) | Optional rewording only |
| 5 Visualization | `visualization` | Visualization selector | Never |

Layer 5 mirrors `analytics.visualization` as a top-level field so the frontend can consume it without unpacking analytics.

## Observation pipeline (`backend/app/intelligence/`)

1. **Rule source** — reuses `InsightResult.rules` and confidence when the insight node produced them; otherwise recomputes both via the shared `InsightRulesEngine` (no logic duplication).
2. **Deterministic observation building** (`observation_rules.py`) — each fired rule maps to a neutral template wording filled with metric values, carrying its grounding `evidence` dict. Metric-driven observations fire independently: top category ("'Psikiyatri' has the highest volume in this result."), largest change, and significant spread (highest ≥ 2× lowest → "…is significant and may deserve attention.").
3. **Optional LLM rewording** (`OBSERVATION_LLM_WORDING` setting, default off) — the LLM receives only the observation texts and must return the same number of reworded sentences. Validation rejects the result if numbers change, evidence strings disappear, the count differs, or directive language (must/should/needs/recommend/advise) appears — falling back to the deterministic texts.
4. **Non-fatal node** — `GenerateObservationsNode` skips without analytics and swallows failures.

## Observation rules

| Trigger | Wording |
|---|---|
| HIGH_GROWTH | "Sustained growth detected: values increased by {growth_rate}%." |
| MODERATE_GROWTH | "Growth has remained positive over the period ({growth_rate}%)." |
| DECLINING | "A downward change of {growth_rate}% is visible over the period." |
| POSITIVE/NEGATIVE/STABLE_TREND | "The overall trend is upward." / "A downward trend is visible." / "Values have remained stable over the period." |
| DOMINANT_CATEGORY | "One category clearly dominates: '{top_category}' holds the largest share." |
| BALANCED_DISTRIBUTION | "No significant imbalance detected across categories." |
| OUTLIER_DETECTED | "'{top_category}' is significantly above the average and is noteworthy." |
| SINGLE_METRIC | "The result is a single metric value of {total}." |
| INSUFFICIENT_EVIDENCE | "The result set does not contain enough data for observations." |
| TOP_CATEGORY (metric) | "'{top_category}' has the highest volume in this result." |
| LARGEST_CHANGE (metric) | "The largest change occurred in {largest_change}." |
| SIGNIFICANT_SPREAD (metric) | "The difference between the highest and lowest values is significant and may deserve attention." |

No wording is a recommendation; the forbidden-word list is enforced both on templates (tested) and on LLM rewordings (validated at runtime).

## Example output (time-series growth, measured 0.97 ms)

```json
{
  "observations": [
    {"rule": "HIGH_GROWTH", "category": "growth",
     "text": "Sustained growth detected: values increased by 18.4%.",
     "evidence": {"growth_rate": 18.4}},
    {"rule": "POSITIVE_TREND", "category": "trend",
     "text": "The overall trend is upward.", "evidence": {}},
    {"rule": "LARGEST_CHANGE", "category": "change",
     "text": "The largest change occurred in 2026-05.",
     "evidence": {"largest_change": "2026-05"}},
    {"rule": "SIGNIFICANT_SPREAD", "category": "distribution",
     "text": "The difference between the highest (412.0) and lowest (201.0) values is significant and may deserve attention.",
     "evidence": {"highest_value": 412.0, "lowest_value": 201.0}}
  ],
  "confidence": "HIGH",
  "llm_worded": false
}
```

## Logging / profiling

Structured `OBSERVATION ENGINE` log block with observation engine time, rule count, confidence, and LLM duration; `generate_observations_ms` joins workflow metrics, the timing schema, and the timing table ("Observation Engine" row).

## Files created / modified

Created: `backend/app/intelligence/{__init__,models,templates,observation_rules,observation_engine}.py`, `backend/app/prompts/observation_wording.md`, `backend/app/agent/nodes/generate_observations.py`, `backend/tests/test_observations.py`.

Modified (plumbing only): `backend/app/agent/graph.py`, `backend/app/agent/state.py`, `backend/app/application_models/{workflow_result,workflow_metrics}.py`, `backend/app/services/reporting_service.py`, `backend/app/schemas/report.py`, `backend/app/api/v1/endpoints/reports.py`, `backend/app/core/settings.py` (`OBSERVATION_LLM_WORDING`), `backend/tests/test_execution.py` (node sequence).
