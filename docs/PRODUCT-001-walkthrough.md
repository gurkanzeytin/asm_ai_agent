# PRODUCT-001 — Conversational Context Engine — Walkthrough

Short-term, session-scoped conversational context so follow-up questions
("En yoğun bölüm hangisi?", "Bunlardan en yoğun olan kim?") are understood
without clarification. Not RAG, not long-term memory: in-memory only, cleared
by inactivity, no DB/schema/frontend changes, no embeddings.

## 1. Architecture Overview

```
User question
      ↓
ContextManager.resolve()          ← NEW (before the graph runs)
  ├─ ContextExtractor  — deterministic signal detection (dates, departments,
  │                      entities, pronouns, analysis type)
  ├─ SessionStore      — in-memory per-session context (TTL 30 min, last 8 turns)
  └─ ContextResolver   — rewrite rules + confidence gating + clarification
      ↓  resolved question (or seeded clarification)
LangGraph pipeline (unchanged): analyze_intent → retrieve_context → generate_sql
  → validate_sql → execute_sql → analyze_results → insights → observations → report
      ↓
ContextManager.update()           ← NEW (after the graph runs)
  └─ records latest explicit filters + turn window
```

Everything is deterministic (regex + folding, no LLM calls). Both `resolve()`
and `update()` swallow all exceptions and degrade to pass-through, honouring
the pipeline's "degrade, never raise" rule.

## 2. Files Created / Changed

**New module `backend/app/context/`** (independent of Analytics, SQL, RAG):

| File | Responsibility |
|---|---|
| `models.py` | `ExtractedSignals`, `ConversationTurn`, `ConversationContext`, `ResolutionResult` |
| `extractor.py` | Turkish-fold-insensitive detection of date expressions, departments, entity types, pronouns, analysis type |
| `session_store.py` | Thread-safe in-memory sessions, 30-min TTL, 8-turn sliding window |
| `resolver.py` | Resolution algorithm: pronoun substitution, date/department inheritance, date-only follow-up continuation, clarification |
| `context_manager.py` | Facade: `resolve()`, `update()`, `clear()` + structured logging |

**Integration (minimal touches):**

- `services/reporting_service.py` — resolves the question before the graph,
  updates context after; optional `session_id` param (`None` bypasses engine).
- `agent/nodes/analyze_intent.py` — one line: a pre-seeded `ambiguity`
  (context clarification) is preserved instead of being overwritten.
- `schemas/report.py` — optional `session_id` request field (frontend
  unchanged; omitted clients share the default session).
- `api/v1/endpoints/reports.py` — passes `session_id` through.
- `bootstrap.py` — wires a singleton `ContextManager`.
- `tools/benchmark/runner.py` — passes `session_id=None` so benchmark
  questions stay independent.

**Tests:** `backend/tests/test_context_engine.py` (30 tests).

## 3. Context Pipeline

1. `resolve(question, session_id)` extracts signals from the new question.
2. Rewrite rules run only when their deterministic confidence ≥ 0.80:
   - **Pronoun resolution (0.95)** — `bunlardan/onlar/o bölüm/aynı bölüm…`
     replaced by the unique referent; no unique referent → clarification.
   - **Date-only follow-up (0.92)** — "Peki geçen ay?" re-issues the previous
     anchored question with the new date (comparison/trend continuation).
   - **Date inheritance (0.90)** — analytical follow-ups without a date get the
     session's latest explicit date prepended. Plain listings are never
     silently date-scoped.
   - **Department inheritance (0.85)** — entity/analytical follow-ups without a
     department get the latest department prepended — unless the question
     itself asks about departments.
3. The resolved question flows into the existing NLU (`QueryAnalyzer`), which
   re-resolves the injected raw expressions ("bugun", "gecen ay") into ISO
   date ranges exactly as if the user had typed them.
4. `update(resolution, session_id)` — the latest **explicit** filter of each
   type replaces the previous one; small talk never becomes a continuation
   anchor; turns are trimmed to the last 8.

Clarification path: an ambiguous follow-up seeds `AgentState.ambiguity`, so the
existing `generate_clarification` node answers — no new response shape.

## 4. Context Model

`ConversationContext` per session: `date_expression`, `department`,
`entity_types` (Doctor/Patient/Appointment/…), `analysis_type`
(ranking/comparison/trend/count/list), `last_question` (continuation anchor),
`turns` (window), `updated_at` (TTL).

## 5. Resolution Algorithm — Safety Rules

- Explicit user input is **never** overwritten — enrichment only fills gaps.
- Pronouns referring to individuals ("o doktor", "o hasta") always ask for
  clarification (names are not retained by design).
- Pronouns with zero or multiple candidate referents → clarification with
  candidate options.
- Nothing is invented: only filters the user stated earlier can be inherited.

## 6. Example Conversations

| Previous | Follow-up | Resolved |
|---|---|---|
| Bugün kaç randevu oluşturuldu? | En yoğun bölüm hangisi? | **bugun** En yoğun bölüm hangisi? |
| Kardiyoloji doktorlarını göster | Bunlardan en yoğun olan kim? | **Kardiyoloji doktorlari arasindan** en yogun olan kim |
| Psikiyatri bölümünü göster | Doktorları listele | **Psikiyatri** Doktorları listele |
| Bu ay bölümlere göre randevuları karşılaştır | Peki geçen ay? | **gecen ay** bolumlere gore randevulari karsilastir |
| Bugün kaç randevu var? → Yarın kaç randevu var? | En yoğun bölüm hangisi? | **yarin** … (latest explicit filter wins) |
| — (empty session) | Bunlardan en yoğun olan kim? | Clarification question |

## 7. Performance Impact

- `resolve()` ≈ **0.07 ms** per question (measured over 1000 calls) — pure
  regex, zero LLM/DB/network calls. Negligible against the 16–38 s SQL
  generation stage.
- Memory: ≤ 8 turns per session, in-process dict; sessions expire after 30
  minutes of inactivity.

## 8. Regression Results

```
backend> ../.venv/Scripts/python.exe -m pytest tests -q
430 passed in 31.96s        (400 pre-existing + 30 new — zero regressions)
```

New coverage: date/department/doctor inheritance, pronoun resolution,
comparison and trend continuation, context replacement, TTL expiration,
turn-window bound, ambiguous follow-up clarification, session isolation,
new-conversation reset, explicit-input protection, resolver-failure
degradation to pass-through.
