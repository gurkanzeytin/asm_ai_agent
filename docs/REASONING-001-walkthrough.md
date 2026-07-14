# REASONING-001 — Semantic Understanding Engine — Walkthrough

A deterministic semantic interpretation layer that runs before every
database-related decision and produces a structured `SemanticFrame` — the
contract consumed by the Query Planner. No LLM calls, no embeddings, no
vector search, no SQL awareness. Measured latency ≈ **1.9 ms** (target < 5 ms).

## 1. Architecture

```
User → Conversation Context (PRODUCT-001)
     → Semantic Understanding Engine (NEW, inside AnalyzeIntentNode)
     → NLU / intent routing → Query Planner (consumes the frame) → Retriever
     → SQL → … unchanged …
```

Module: `backend/app/semantics/` — `models.py` (semantic model),
`ontology.py` (domain knowledge), `engine.py` (extraction pipeline).
`AgentState.semantic_frame` carries the frame; `QueryPlanner.build_plan`
treats it as the authoritative interpretation when present. The engine fails
open (frame = None) so it can never break the pipeline.

## 2. Semantic Model (`SemanticFrame`)

goal (LIST/COUNT/COMPARE/ANALYZE/RANK/SUMMARIZE/TREND/FIND/AGGREGATE),
primary_subject, fact_subject, secondary_subjects, requested_output
(doctor_names/count/average/ranking/time_series/distribution/boolean/summary/…),
constraints (typed: date+ISO detail, department, negation, limit, order),
question_type (information_retrieval/aggregation/comparison/trend/ranking/
distribution/negative/existence/analytical/follow_up/general_help/out_of_scope),
relationships (semantic, from the ontology), ambiguities (phrase + reason),
confidence, duration_ms.

## 3. Extraction Pipeline

1. NLU analysis (`QueryAnalyzer`) + context signals (`ContextExtractor`) on
   both the raw question and the synonym-expanded query — so medical synonyms
   ("kalp" → Kardiyoloji, "pediatri" → Cocuk Sagligi) resolve semantically.
2. Subjects → goal → constraints → ambiguities → question type → secondary
   subjects → relationships → requested output → confidence.

## 4. Entity Understanding

- Turkish is verb-final: the **last-mentioned** entity is the primary subject,
  the **first-mentioned** is the fact.
- Entities surfaced only by synonym rewrites are facts, never the output
  (fixes "En yoğun bölüm hangisi?" → primary Department, fact Appointment).
- Two implied-fact rules: volume rankings ("yoğun") imply Appointment; a date
  filter on a non-event subject implies Appointment ("bugünkü doktorlar" =
  doctors with appointments today — a real live bug this engine fixed, where
  the date had bound to the doctor's hire-date column).

## 5. Relationship Understanding

Static ontology (`ontology.RELATIONSHIPS`): Doctor works_in Department,
Appointment belongs_to Doctor, Patient has Appointment, Prescription
written_by Doctor, … The frame reports every relationship whose both ends are
among the detected subjects — semantic edges, not SQL joins (the planner maps
them to FK paths later).

## 6. Ambiguity Strategy

`ontology.AMBIGUOUS_PHRASES` maps each ambiguous phrase ("en iyi",
"en başarılı", "en kötü", "en verimli", "performans") to an **explanation of
why** it cannot be resolved (no measurable metric in the schema). The engine
never guesses: ambiguities lower confidence and the existing clarification
path asks the user.

## 7. Confidence Model (deterministic)

0.5 base, +0.2 primary subject, +0.15 goal, +0.05 per constraint (cap 0.15),
−0.35 ambiguity, −0.2 unresolved pronouns, capped ≤ 0.4 for out-of-scope.
Spec example "Bugünkü çocuk doktorlarını göster" scores 0.95 with goal LIST,
subject Doctor, constraints {date: bugun, department: Cocuk Sagligi},
output doctor_names — matching the spec's expected output.

## 8. Logging

One structured block per question: original/normalized question, goal,
subjects, constraints, question type, requested output, relationships,
ambiguities, confidence, duration — plus the full frame as structured extra.

## 9. Performance

Pure regex/dictionary/ontology work: ~1.9 ms average (test enforces < 5 ms
over 50 runs). No additional LLM call, no vector search, no embeddings.

## 10. Regression Results

```
backend> pytest tests -q
525 passed        (482 pre-existing + 43 new — zero regressions)
```

New: `tests/test_semantic_engine.py` — single/multiple entities, date and
department expressions, compound (3-constraint) questions, ranking,
aggregation, comparison, trend, negative, existence, out-of-scope,
general-help, follow-up, every medical synonym family, relationships,
ambiguity reasons, confidence bands, latency, and planner integration.
Live verification: "Bugünkü çocuk doktorlarını göster" now yields
`… FROM randevular JOIN doktorlar … WHERE randevu_tarihi='2026-07-14' AND
bolum_adi='Cocuk Sagligi'` (3 rows) — previously the date incorrectly bound
to the doctor hire-date column.
