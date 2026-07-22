# Insight Routing, Deterministic Generation, and Schema Retrieval Repair

Covers: deterministic insight generation, complexity-based LLM routing,
bounded fallback, LLM timing/metadata propagation, and the FAISS/schema
view-indexing repair.

## Model strategy

- **qwen3:8b (Ollama)** is the default local model — used for medium-complexity
  insight wording and as the fallback leg whenever the remote model is
  unavailable or rejected by the remote data policy.
- **DeepSeek V4 Pro (NVIDIA)** is reserved for complex reasoning — multi-metric
  analysis, multi-period comparisons, anomaly reasoning, multi-dimensional
  breakdowns. It is never the default for simple requests.
- **Simple analytics use deterministic insight generation** — no LLM call at
  all for count, distribution, top-N/ranking, min/max, basic ratio/percentage,
  empty results, and single-row aggregates.
- **Raw patient-level data never goes to a remote provider.** The same
  `app.llm.remote_policy` guard NVIDIA already used is reused by the router
  itself, screened against the exact prompt the LLM would receive.
- Gemini is untouched and **not** part of this routing — it remains
  selectable only via `LLM_PROVIDER=gemini` for the primary pipeline provider,
  as before.

## Routing modes (`app.insights.routing.InsightGenerationMode`)

| Mode | Meaning |
|---|---|
| `deterministic` | Rendered from `app.insights.templates`, no LLM call. |
| `local_llm` | Ollama/qwen3. |
| `remote_llm` | NVIDIA/DeepSeek. |

Routing is a pure function of **structured analysis-family signals** already
computed by the deterministic layers — never the literal question text:

- confidence (`InsightConfidence`, from `InsightRulesEngine`)
- data shape (`DataShape`)
- detected intents (`analytics.intents`)
- fired business rules (`InsightRule`, especially `OUTLIER_DETECTED`)
- row count and metric richness

Examples:

- count / distribution / top-N / basic ratio → **deterministic**
- medium trend wording, moderate comparisons → **local (qwen3)**
- complex multi-metric / anomaly / multi-dimensional analysis → **remote
  (DeepSeek)**, only when `NVIDIA_API_KEY` is configured
- remote data policy rejection (a patient-level field reference anywhere in
  the would-be prompt) or remote unavailability → **local (qwen3)**

See `InsightRouter.compute_complexity()` / `InsightRouter.decide()` in
`backend/app/insights/routing.py` for the exact scoring.

## Fallback behavior

At most **one** cross-provider fallback, always remote → local, never the
reverse (no ping-pong), and no retries against the same provider:

1. Remote (DeepSeek) timeout / connection / rate-limit / auth error → fall
   back once to local (qwen3).
2. Remote rejected by the data policy → routed directly to local; remote is
   never attempted.
3. Local (qwen3) failure → falls back to the deterministic template renderer
   (always available once confidence/shape already cleared the deterministic
   gate above).

`InsightResult` (and the API's `InsightSchema`) record `fallback_used` /
`fallback_reason` / `routing_mode` / `routing_reason` / `remote_data_policy`
for every insight, so a fallback is always visible, never silent.

## Configuration (`backend/app/core/settings.py`)

```
INSIGHT_ROUTING_ENABLED=true                 # false => always local
INSIGHT_DETERMINISTIC_ENABLED=true           # false => never deterministic
INSIGHT_LOCAL_PROVIDER=ollama
INSIGHT_REMOTE_PROVIDER=nvidia
INSIGHT_REMOTE_COMPLEXITY_THRESHOLD=3        # min score to route remote
```

No new credentials were added — routing reuses `NVIDIA_API_KEY` /
`NVIDIA_BASE_URL` / `NVIDIA_MODEL` / `OLLAMA_BASE_URL` / `OLLAMA_MODEL` exactly
as configured for the primary pipeline provider.

## Legacy compatibility

`InsightEngine(llm_provider=...)` (the pre-routing single-provider
constructor) is **unchanged** — every call still resolves through
`self.llm_provider` with the original shape/confidence branching. Routing only
activates when `local_llm_provider` / `remote_llm_provider` / `router` is
explicitly supplied, which `AgentGraphBuilder` now does at graph-build time
(`backend/app/agent/graph.py`). This is why every pre-existing insight test
still passes unmodified.

## Timing/metadata fix

**Root cause**: `ReportingService`'s `llm_total_ms` ("LLM Inference" in the
workflow summary) only ever summed `generated_sql.latency_ms` +
`generated_report.latency_ms`. Whenever `ReportService` reused the Insight
Engine's narrative (the common "analytical" path), report generation's own
latency collapsed to ~0ms — but the Insight Engine's *own* LLM call (correctly
measured, 8–58s) was never added to that aggregate. Fixed in
`backend/app/services/reporting_service.py`: `llm_total_ms` now also sums
`insights.llm_latency_ms` and `observations.llm_latency_ms`. New
`WorkflowMetrics.insight_llm_ms` / `.observation_llm_ms` fields (and their
`TimingSchema` counterparts) expose each stage's real LLM cost separately.

`InsightSchema` (API response) gained additive, backward-compatible fields:
`llm_invoked`, `provider`, `model`, `llm_inference_ms`, `prompt_tokens`,
`completion_tokens`, `finish_reason`, `routing_mode`, `routing_reason`,
`fallback_used`, `fallback_reason`, `remote_data_policy`. All are optional/
defaulted — no existing field was renamed or removed.

## Schema retrieval expectations

**Root cause**: `SemanticSchemaIndex.build_index()` only ever iterated
`schema.tables`; a view-only allowed-object deployment
(`DATABASE_ALLOWED_OBJECTS=["dbo.vw_RandevuRaporu"]`, zero tables) produced
zero indexable documents, so FAISS stayed empty and every query fell through
to the "select all views" safety net with zero prompt-budget accounting.

Fixed in `backend/app/database_intelligence/schema_embeddings.py`:
`construct_view_document()` (PII columns always excluded, per
`app.llm.remote_policy.PROHIBITED_PATIENT_FIELDS`) and a second, independent
FAISS index (`self.view_index`/`self.view_names`, `search_views()`) built
alongside the existing table index — the table-only `search()` contract used
by every current caller is unchanged. `backend/app/database_intelligence/retriever.py`
now also scores view **columns** (previously name/comment only, same gap
`_score_table` never had) and combines that with the new semantic view
search, and finally accounts selected views' estimated tokens into the prompt
budget (previously always 0 for views).

Expected behavior now:

- A view-only schema produces indexable documents and a non-empty view index.
- `dbo.vw_RandevuRaporu` is retrieved for appointment questions via real
  scoring, not the blanket fallback.
- Prompt Budget Utilization reflects the views actually selected.
- The "select all views" fallback remains as a safety net, not the normal path.
- No new embedding provider or network dependency was introduced — the
  existing local `nomic-embed-text` (Ollama) / hash-embedding-fallback
  architecture is unchanged; a missing/unreachable embedding model still
  degrades safely (see `SemanticSchemaIndex._get_embedding`).

## Manual comparison command

```
cd backend
python scripts/compare_insight_modes.py "Randevu durumlarının dağılımı nedir?"
```

Runs the real pipeline once (schema retrieval → SQL generation → execution →
analytics), then generates the insight for that *same* analytics result under
`deterministic` / `ollama` / `nvidia` / `auto` and prints provider, model,
routing reason, LLM timing, token usage, fallback status, and the final
answer. Never prints API keys, raw rows, or full prompts — SQL is shown only
as a SHA-256 hash. Not run automatically by the test suite; requires a real
database connection.

## Security rules

- Deterministic insight text is built exclusively from already-computed
  `AnalyticsResult` fields — no re-querying, no LLM, no invented metrics or
  thresholds beyond what `InsightRulesEngine` explicitly detected (e.g. an
  "anomaly" is never claimed unless `InsightRule.OUTLIER_DETECTED` fired).
- Every remote-bound payload is screened by the same
  `app.llm.remote_policy.find_prohibited_fields` guard already used for
  NVIDIA — a match routes to the local provider instead of failing the
  request.
- No API key, raw prompt, or patient row is ever logged by the router,
  `InsightEngine`, or `compare_insight_modes.py`.
