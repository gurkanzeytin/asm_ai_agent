# AG-022 — Answerability, Schema Guidance & Graceful Fallback — Walkthrough

The agent now resolves every request to exactly one controlled outcome and
never returns an empty, technical, misleading, or generic failure response.
No RAG, no long-term memory, no multi-agent orchestration, no frontend design
changes, no breaking API changes.

## Controlled Outcomes

Every `POST /report/` response now carries an additive `outcome` field:

| Outcome | When | Response |
|---|---|---|
| `EXECUTE_SQL` | Normal path, data returned | Existing analytical report |
| `ASK_CLARIFICATION` | Ambiguous ranking phrase or ambiguous context follow-up | Existing clarification question |
| `RETURN_HELP` | Help intent | Existing help guidance |
| `OUT_OF_SCOPE` | Database-bound question with no schema-domain signal | Guided list of what the agent CAN answer + examples |
| `REWRITE_AND_RETRY` | SQL failed at execution with an SQL-shaped DB error, one regeneration succeeded | Normal report (retry is transparent) |
| `NO_RESULT_GUIDANCE` | Query ran fine but matched zero rows | "No data matched" + actionable suggestions |
| `SAFE_ERROR` | Pipeline could not produce any report (e.g. LLM timeout) | Friendly, non-technical guidance — never leaks errors |

## What Was Built

**1. Answerability guard — [app/services/answerability.py](../backend/app/services/answerability.py)**
Deterministic (no LLM): a question is answerable when it carries a domain
entity (doctor/patient/appointment/…, via the NLU synonym config), a known
department name, or a date + aggregate operation. Rewrite-synonym matches are
deliberately NOT a signal (conversational fillers like "bana" match them).
The guard **fails open** — on any internal error the question proceeds to SQL.
Runs inside `AnalyzeIntentNode`; `route_by_intent` diverts
`database_query`-bound questions with `answerable=False` to the new
`generate_out_of_scope` node. Ambiguity clarification takes precedence.

**2. Out-of-scope guidance — [generate_out_of_scope.py](../backend/app/agent/nodes/generate_out_of_scope.py)**
Static Turkish markdown listing the answerable data areas (bölümler,
doktorlar, hastalar, randevular, reçeteler/tanılar, faturalar/lab/yatışlar)
plus example questions. Zero LLM calls, ~0 ms.

**3. Rewrite-and-retry loop — graph edge `execute_sql → generate_sql`**
A retryable database error (`no such column/table`, `syntax error`,
`ambiguous column`, `misuse of aggregate`, `no such function`) marks
`state.last_execution_error` WITHOUT appending to `state.errors`, and
`route_after_execution` loops back to `generate_sql` exactly once.
`WorkflowService.execute_sql_generation` appends the database error to the
regeneration prompt (`error_feedback` param, default `None` — non-breaking).
Second failure or non-retryable errors take the normal error path.

**4. No-result guidance — [template_renderer.py](../backend/app/reporting/template_renderer.py)**
The EMPTY template now explains that the query ran successfully but matched
nothing, with concrete suggestions (widen the date range, check the
department/doctor spelling, drop the filter). Note: `COUNT(...) = 0` is a
single-value answer ("Toplam: 0"), not an empty result — by design.

**5. Safe-error fallback — [reporting_service.py](../backend/app/services/reporting_service.py)**
After the graph runs, if no node produced a report, ReportingService
synthesizes friendly Turkish guidance (retry, rephrase shorter, example
patterns) with `provider="static", model="safe_error_fallback"`. Technical
errors stay in `errors[]` for observability but never reach the message. The
frontend already prefers `report.markdown` over its generic failure text, so
this required no frontend change.

**6. Outcome tagging** — help, clarification, report, and execute nodes set
`AgentState.outcome`; it flows through `WorkflowResult` to the API as an
additive optional field ([outcome.py](../backend/app/application_models/outcome.py)).

## Verification

- **Unit/regression:** `459 passed` (`pytest tests -q`) — 29 new tests in
  [test_ag022_answerability.py](../backend/tests/test_ag022_answerability.py)
  (guard verdicts + fail-open, routing incl. ambiguity precedence, retry loop
  state machine, retryable-error classifier, empty-template guidance,
  SAFE_ERROR synthesis without technical leakage, outcome tagging).
  Three pre-existing tests updated because their fixture questions ("List all
  active users") intentionally now divert to OUT_OF_SCOPE; one mock assertion
  updated for the new `error_feedback=None` kwarg.
- **Live API smoke:**
  - "Bitcoin fiyatı ne kadar oldu?" → `outcome=OUT_OF_SCOPE`, guided capabilities list.
  - "2030 yılındaki randevuları göster" → `outcome=NO_RESULT_GUIDANCE`, suggestions shown.
  - "2030 yılında kaç randevu oluşturuldu" → `outcome=EXECUTE_SQL`, "Toplam: 0" (valid answer).
