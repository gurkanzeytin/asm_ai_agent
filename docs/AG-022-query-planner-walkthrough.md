# AG-022 — Query Planning Engine — Walkthrough

A deterministic Query Plan is now built between NLU and SQL generation and
becomes the contract the SQL prompt must implement. No LLM calls, no
embeddings, no architecture changes outside the planning stage, no frontend
changes.

## Architecture

```
User → Context Engine → NLU (QueryAnalyzer) → Query Planner (NEW) → Retriever
     → SQL Generation (prompt + Plan contract) → Compliance Check (NEW)
     → [existing single repair attempt if non-compliant] → …unchanged…
```

In code the planner runs inside `RetrieveContextNode` right after schema
retrieval: it re-uses the deterministic NLU output, plans against the
retrieved tables, and — critically — **extends the schema context with any
table the plan requires** (fact table, FK join hops) so the schema-identifier
guard can never reject correctly planned SQL, then re-plans against the
extended context to complete the FK join path.

## Files Created — `backend/app/planning/`

| File | Responsibility |
|---|---|
| `models.py` | `QueryPlan`, `DateFilterPlan`, `JoinStep`, `ComplianceResult` |
| `planner.py` | `QueryPlanner.build_plan()` + `format_plan_for_prompt()` |
| `compliance.py` | `PlanComplianceValidator.check(sql, plan)` |

Touched: `agent/state.py` (`query_plan` field), `agent/nodes/retrieve_context.py`,
`agent/nodes/generate_sql.py`, `services/workflow_service.py` (plan section in
prompt), `services/sql_service.py` (compliance-driven repair),
`services/prompt_service.py` (`extend_context_with_tables`),
`services/interfaces.py` (optional `query_plan` params — non-breaking),
`services/query_analyzer.py` (suffixed date forms: "Bugünkü", "yarınki", "dünkü").

## QueryPlan Model

Output entity/table, fact entity/table, date filters (ISO ranges + discovered
date column), department filter, extra filters (negation), aggregation
(COUNT/SUM/AVG), ranking direction, limit, order, analysis type, minimal FK
join path, projection column(s), distinct flag, planner timing.

## Planner Algorithm (deterministic)

1. **Entities**: Turkish is verb-final — the *last*-mentioned non-department
   entity is the output, the *first*-mentioned is the fact. "En yoğun X" with
   no stated fact implies Appointment volume.
2. **Constraints**: dates from `QueryAnalysis.detected_dates` (now including
   suffixed forms like "Bugünkü" — a real dropped-constraint bug this feature
   caught); department names via the context extractor; `ilk N` limits;
   ranking direction (ASC for "en az/en düşük"); negation markers
   ("olmayan") preserved as extra filters.
3. **Relationships**: BFS over declared foreign keys only — joins are never
   guessed; the path extends to `bolumler` when a department filter exists.
4. **Projection/Distinct**: descriptive column of the output table
   (`ad_soyad`, `*_adi`, …); DISTINCT when output ≠ fact and no aggregation;
   scalar aggregates get no projection requirement.

The plan renders into the SQL prompt as a compact `Plan (implement every
item):` section (~150–250 chars). The `sql_generation.md` template is
unchanged (its char-budget test still passes).

## Compliance Check

After generation, `PlanComplianceValidator` lexically verifies: date ISO
values present, department literal present, aggregation function, `ORDER BY`
for rankings, `LIMIT n`, projection column in the SELECT clause, and every
join-path table referenced. A miss feeds the **existing** single repair
attempt with an explicit "Missing: …" instruction — no new LLM call class.
Post-repair non-compliance is logged, never fatal. Compliance is skipped when
the SQL already failed structural/safety/schema checks (those drive their own
repair instructions) and fails open on internal errors.

## Verification

- **Tests**: `482 passed` — 23 new in `tests/test_query_planner.py` covering
  date+department, date+ranking, department+ranking, three simultaneous
  filters, negation, comparison, aggregation, context-continuation questions,
  single-constraint minimality, suffixed dates, "dünya"≠"dün", no-FK
  no-guessing, and all compliance detections.
- **Live** (`Ollama qwen3:8b`):
  - "Bugünkü randevular içerisinden çocuk sağlığındaki doktorları listele" →
    `SELECT DISTINCT doktorlar.ad_soyad FROM randevular JOIN doktorlar … JOIN
    bolumler … WHERE randevu_tarihi='2026-07-14' AND bolum_adi='Cocuk Sagligi'`
    — every constraint survived (previously the date filter was dropped).
  - "Bugün en yoğun bölüm hangisi?" → date filter + `GROUP BY` + `ORDER BY …
    DESC LIMIT 1` all present.

## Performance

Planning is pure regex/BFS: **< 1 ms** per question (test asserts < 50 ms);
compliance check is lexical, ~0 ms. The plan section adds ~50 prompt tokens.
No new LLM calls — single-constraint queries behave exactly as before, and
multi-constraint queries now reach the LLM with an explicit contract.
