# Professional AI SQL Agent Scorecard

## Scope

This audit scores the current project as a professional natural-language-to-SQL and data-analysis agent. The score is not based on whether a module merely exists. Each area is scored by production reliability:

- 0-2: missing or only a placeholder.
- 3-4: prototype; works only on narrow happy paths.
- 5-6: MVP; usable, but inconsistent or weakly verified.
- 7-8: strong product foundation; remaining gaps are mostly hardening, eval, and observability.
- 9: production-grade; measured, traceable, regression-protected.
- 10: enterprise-grade; continuously evaluated, operationally observable, governed, and resilient.

## Evidence Snapshot

- Backend tests: 84 test files, 1749 test functions.
- Frontend tests: 16 test files.
- Multi-turn golden eval: 12 scenarios, 37 turns.
- 24-column golden eval: 56 cases.
- Metric catalog: 43 metrics.
- Verification run:
  - Backend targeted: `32 passed`.
  - Frontend targeted: `21 passed`.

Commands used:

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_asm_multi_turn_golden_eval.py tests/test_asm_24_column_golden_eval.py tests/test_sql_validator.py tests/test_output_policy.py
npm test -- --run src/lib/output-intent.test.ts src/components/asm/chat-ui-polish.test.tsx
```

## Overall Score

Current professional-readiness score: **7.1 / 10**.

This is above a basic MVP. The project already has a real agent graph, typed workflow models, SQL safety, semantic resources, context memory, reporting policy, and a meaningful test base. The main missing layer is not another big feature. The main gap is making every agent decision measurable, traceable, and regression-protected.

## Detailed Scorecard

| Area | Score | Why |
|---|---:|---|
| Clean Architecture | 8.0 | API routes mostly map DTOs and delegate to services. LLM access is behind provider layer. DB execution is behind service/repository layers. |
| Agent Graph | 8.0 | LangGraph pipeline is explicit: intent, context retrieval, value resolution, SQL generation, validation, execution, analysis, insight, observation, report. |
| Query Understanding / QueryPlan | 7.0 | Strong deterministic planner exists, but Turkish marker and heuristic accumulation increases brittleness on new phrasing. |
| Schema Grounding | 7.5 | Schema retriever, semantic catalog, metric catalog, view semantics, synonym resources exist. Needs stronger value profiling and schema confidence reporting. |
| SQL Generation | 7.5 | Deterministic SQL builder + LLM fallback + repair attempt + plan compliance checks are solid. Needs continuous scoring against complex queries. |
| SQL Safety | 8.5 | AST validator, read-only restriction, forbidden keyword/function checks, object whitelist, and pre-execution validation are strong. |
| Execution Safety | 7.0 | Result limits and truncation exist. Needs timeout/cost governance, slow-query diagnostics, and clearer operational limits. |
| Memory / Session Follow-up | 6.5 | Real context engine exists and supports follow-ups, but this is still the most fragile product area. Needs broader multi-turn regression testing. |
| Clarification | 6.5 | Ambiguity and pending clarification handling exist. Needs more natural, option-based, context-aware clarification UX. |
| Output Contract | 7.0 | `response_mode` and `visible_sections` give a good contract. Recent fixes reduce over-answering. Needs more live scenario hardening. |
| Result Reasoning | 7.0 | Analytics, insight, observation, and template layers exist. Needs stricter grounding and less verbose answer defaults. |
| Visualization UX | 7.0 | Chart selector and frontend rendering exist. Needs stronger chart choice rules and more polished chart-only/table-only transitions. |
| Evaluation Harness | 7.5 | Good test volume and golden sets exist. Missing piece is a daily score dashboard and failure taxonomy. |
| Observability / Debuggability | 6.5 | Workflow IDs, timings, node state fields and logs exist. Missing: first-class agent trace panel. |
| Provider / Model Management | 6.0 | Provider factory supports multiple providers. Needs fallback policy, prompt versioning, latency/cost tracking, and model-specific eval. |
| Production Readiness | 5.5 | Core app can run locally. Still needs auth, audit log, rate limiting, deployment checks, secret policy, and CI gates for professional production use. |

## Evidence By Area

### Clean Architecture

Evidence:

- `backend/app/api/v1/endpoints/reports.py` maps `WorkflowResult` to API schemas.
- `backend/app/services/reporting_service.py` owns workflow orchestration.
- `backend/app/services/execution_service.py` delegates SQL execution to `IAnalyticalRepository`.
- `backend/app/llm/provider.py` centralizes provider creation.

Score rationale:

The project is structurally healthy. The API layer does not appear to directly call DB execution or LLM generation. That earns a high score. It is not 9+ because some orchestration classes are now large and carry many responsibilities, especially around memory, fallback, and response assembly.

### Agent Graph

Evidence:

- `backend/app/agent/graph.py` defines the graph topology and conditional routing.
- Nodes are separated under `backend/app/agent/nodes`.
- Routing shortcuts exist for SQL-only, data-only, and visualization-only responses.

Score rationale:

This is one of the stronger areas. The graph is explicit and extensible. The risk is that routing logic is spread across graph routes, reporting service, output policy, and context resolver. A professional agent should expose a unified trace of every routing decision.

### Query Understanding / QueryPlan

Evidence:

- `backend/app/planning/planner.py`
- `backend/app/planning/models.py`
- `backend/app/planning/compliance.py`
- `backend/app/semantics/catalog.py`
- `backend/app/resources/metric_catalog.json`

Score rationale:

The QueryPlan layer is a major strength because the app does not rely only on free-form SQL generation. The weakness is heuristic growth: intent, grouping, date, ranking, status, and follow-up phrases are handled by many rules. That is acceptable for MVP, but professional level requires broader golden coverage and confidence diagnostics per parsed field.

### Schema Grounding

Evidence:

- `backend/app/database_intelligence/retriever.py`
- `backend/app/database_intelligence/schema_graph.py`
- `backend/app/database_intelligence/schema_embeddings.py`
- `backend/app/resources/view_semantics.json`
- `backend/app/resources/domain_synonyms.json`

Score rationale:

The schema grounding is better than a simple prompt dump. It uses semantic retrieval, graph expansion, token budgeting, view semantics, and domain synonyms. It is not yet top-tier because the agent should show which schema elements were selected, with confidence, and should have a value catalog/profile for common filter values.

### SQL Generation

Evidence:

- `backend/app/services/sql_service.py`
- `backend/app/services/deterministic_sql_builder.py`
- `backend/app/planning/compliance.py`
- `backend/app/prompts/sql_generation.md`

Score rationale:

The deterministic-first approach is professional. LLM fallback and bounded repair are also good. The gap is measurement: every complex failure should be classified as planner failure, schema failure, SQL generation failure, validation failure, execution failure, or answer formatting failure.

### SQL Safety

Evidence:

- `backend/app/sql_validator/validator.py`
- `backend/app/sql_validator/rules.py`
- `backend/app/services/execution_service.py`
- `backend/tests/test_sql_validator.py`

Score rationale:

This is near production-grade for read-only SQL safety. It validates AST shape, rejects multiple statements, rejects mutating nodes, checks forbidden functions/keywords, rejects comments, restricts system/temp objects, and validates again before execution. Remaining production work is policy/audit, not core SQL validator structure.

### Memory / Session Follow-up

Evidence:

- `backend/app/context/context_manager.py`
- `backend/app/context/resolver.py`
- `backend/app/context/session_store.py`
- `backend/app/resources/asm_multi_turn_golden_eval.json`
- `backend/tests/test_asm_multi_turn_golden_eval.py`
- `backend/tests/test_live_memory_followups.py`

Score rationale:

Memory exists and is typed enough to be useful. It handles previous context, pending clarification, inherited fields, overridden fields, and follow-up signals. This still gets 6.5 because real users phrase follow-ups in unpredictable ways. This is the highest business-risk area because memory bugs feel like intelligence failures.

### Clarification

Evidence:

- `backend/app/agent/nodes/generate_clarification.py`
- `backend/app/planning/value_resolver.py`
- `backend/app/context/models.py`
- `backend/app/services/answerability.py`

Score rationale:

The app can avoid guessing in several ambiguous cases. Professional level requires the agent to ask short, natural clarification questions, preserve the original task, and resume seamlessly after the answer. Some of that exists; it needs polish and broader scenario coverage.

### Output Contract

Evidence:

- `backend/app/reporting/output_policy.py`
- `backend/app/services/reporting_service.py`
- `backend/app/agent/nodes/generate_report.py`
- `frontend/src/lib/output-intent.ts`
- `frontend/src/components/asm/ChatMessage.tsx`

Score rationale:

The `response_mode` and `visible_sections` model is the right direction. It lets the user ask for answer/table/chart/SQL and keeps the UI from showing everything by default. The score is not higher because Turkish wording variants can still slip through, and verbose report generation needs more live-case validation.

### Evaluation Harness

Evidence:

- `backend/tools/evaluation/runner.py`
- `backend/tools/evaluation/scorers.py`
- `backend/app/resources/asm_multi_turn_golden_eval.json`
- `backend/app/resources/asm_24_column_golden_eval.json`
- `scripts/smoke_test_runner.py`
- `artifacts/smoke_tests/latest/*`

Score rationale:

The foundation is good. There are actual golden cases and smoke artifacts. To reach professional grade, this needs one command that produces an executive scorecard: pass rate by category, failed node, failed reason, SQL validity, memory correctness, output correctness, and latency.

### Observability

Evidence:

- `workflow_id` is propagated in `ReportingService`.
- Node timings are collected in `WorkflowMetrics`.
- `backend/app/services/workflow_progress.py`
- frontend has `chat-runtime-trace.ts`.

Score rationale:

The internals collect useful diagnostics, but they are not yet a user-facing or developer-facing trace. For this product, an Agent Trace panel would be a major professional upgrade.

### Frontend UX

Evidence:

- `frontend/src/components/asm/ChatMessage.tsx`
- `frontend/src/components/asm/SqlResultsTable.tsx`
- `frontend/src/components/asm/SqlChartPanel.tsx`
- `frontend/src/hooks/use-chat-controller.ts`

Score rationale:

The UI supports chat, streaming, tables, charts, metrics, and technical detail toggling. The biggest UX requirement now is answer minimalism: the UI should make the requested artifact obvious and hide everything else unless asked.

## Main Risks

1. Memory is still the biggest perceived-intelligence risk.
   A single wrong inheritance can make a correct SQL agent look unreliable.

2. Heuristic phrase matching is growing.
   Turkish output/action markers are necessary, but every new marker adds regression risk unless tied to golden evals.

3. Eval exists but is not yet productized.
   Tests pass, but the project needs a score dashboard that says what got better or worse after each change.

4. Observability is mostly log-level.
   A professional agent should explain internally: why it chose this intent, why it reused memory, why this SQL is safe, why this output mode was selected.

5. Production readiness is the lowest-scoring area.
   Auth, audit, rate limits, deployment health, secrets, and operational dashboards are not the current strength.

## Seven-Day Upgrade Plan

### Day 1: Agent Trace Contract

Add a structured trace object to every response:

- intent decision
- resolved question
- context applied
- inherited/overridden/removed fields
- query plan summary
- SQL source: deterministic or LLM
- validation result
- output policy decision

Target score impact:

- Observability: 6.5 -> 8.0
- Memory: 6.5 -> 7.0

### Day 2: Golden Scenario Expansion

Expand the multi-turn eval set from 37 turns to at least 100 turns.

Must include:

- answer -> table -> chart -> SQL
- table -> filter refinement -> compare period
- chart -> table-only correction
- SQL-only -> run it
- ambiguous value -> clarification -> continue
- memory reset/new session behavior

Target score impact:

- Evaluation: 7.5 -> 8.5
- Memory: 6.5 -> 7.5

### Day 3: Failure Taxonomy

Every failed case should be classified:

- INTENT_FAILURE
- CONTEXT_FAILURE
- PLANNER_FAILURE
- SCHEMA_GROUNDING_FAILURE
- SQL_GENERATION_FAILURE
- SQL_VALIDATION_FAILURE
- EXECUTION_FAILURE
- OUTPUT_POLICY_FAILURE
- UI_RENDERING_FAILURE

Target score impact:

- Evaluation: 8.5 -> 9.0
- Observability: 8.0 -> 8.5

### Day 4: Clarification UX

Clarification output should be short and actionable:

- one question
- max 3-5 options
- no technical wording
- original task preserved
- next answer resumes the pending plan

Target score impact:

- Clarification: 6.5 -> 8.0

### Day 5: Output Minimalism Hardening

Build explicit scenario tests for:

- scalar answer only
- table only
- chart only
- SQL only
- detailed report only when explicitly requested
- no duplicate metric/finding sections

Target score impact:

- Output contract: 7.0 -> 8.5
- Frontend UX: 7.0 -> 8.0

### Day 6: Schema/Value Grounding Diagnostics

Expose selected schema/view/metric/filter values in trace. Add tests for unknown or ambiguous values.

Target score impact:

- Schema grounding: 7.5 -> 8.3
- QueryPlan: 7.0 -> 8.0

### Day 7: Demo Readiness Gate

Create one command that runs:

- backend targeted tests
- frontend targeted tests
- multi-turn golden eval
- smoke scenarios
- score report generation

Target score impact:

- Overall: 7.1 -> about 8.1-8.4

## Definition Of Professional For This Project

This project reaches professional level when a change can be judged by numbers, not vibes:

- The agent answers 90%+ of golden NL-to-SQL cases correctly.
- Multi-turn memory passes 90%+ of chained scenarios.
- SQL validator blocks 100% of unsafe/adversarial SQL cases.
- Output mode matches the user request in 95%+ of cases.
- Every response has a trace explaining the agent's decisions.
- Every failed scenario gets a typed failure reason.
- The UI shows only the requested artifact by default.

## Current Verdict

The architecture is good enough to build on. The professionalization work should focus on:

1. traceability,
2. memory hardening,
3. eval expansion,
4. output minimalism,
5. clarification quality,
6. production guardrails.

Adding more random capabilities before these are hardened would increase surface area without increasing trust.
