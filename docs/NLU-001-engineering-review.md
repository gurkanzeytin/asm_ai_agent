# NLU-001 - Engineering Review

## Design Decisions

1. **Two query forms, one source of truth.** Retrieval embeds the natural-language `normalized_query` (better semantic match than ISO dates), while SQL generation receives `final_query` with relative dates resolved deterministically. Both derive from the same rewrite output, and `final_query` is the value published on `DatabaseContext.normalized_query`, so downstream nodes are unchanged.
2. **Operations are detected, not text-substituted.** Rewriting "kaç" to the literal token "COUNT" inside a Turkish sentence would damage grammar, retrieval, and the SQL prompt. Instead, LIST/COUNT/SUM/AVG, LIMIT N and ORDER DESC are detected as structured fields on `QueryAnalysis` and logged; the text keeps canonical Turkish. "son N gün/hafta/ay/yıl" is explicitly excluded from LIMIT detection because it is temporal.
3. **Ambiguity detection at the intent stage.** Running it in `AnalyzeIntentNode` means no new graph nodes or edges: ambiguous database queries reuse the existing `unknown → generate_clarification` route. Non-database intents (chat, help) are never diverted.
4. **Config-only extensibility.** All rewrite rules, operations and ambiguous patterns live in `domain_synonyms.json`. The loader accepts both the legacy flat `rewrites` list and the new `rewrite_groups` mapping, so older configs keep working.
5. **Rule ordering safety.** Groups run in declared order (conversational first so fillers cannot block later patterns; expansion last). Specific patterns precede generic ones inside a group ("en yoğun doktor" before "en yoğun") and `not_followed_by` guards make rules idempotent ("ortopedi ve travmatoloji" is not re-expanded).

## Bug Found and Fixed

`"İlk".lower()` in Python yields `i + U+0307` (combining dot), which silently broke `\b`-anchored matching for every word starting with Turkish İ ("İlk 5", "İç hastalıkları"). `_normalize_query_text` now maps İ → i before lowercasing and strips residual combining dots.

## Risks and Mitigations

- **Over-eager rewrites.** Guarded by `followed_by` context requirements ("kalp"/"çocuk"/"göz" only rewrite before doctor/department words) — verified by tests such as "Kaç çocuk hasta geldi" and "Göz rengi mavi olan hastalar".
- **Filler removal ("bana")** could in principle strip meaningful text; the affected words are non-informative for SQL over this schema, and operations are detected before rewriting so the original wording still drives structured signals.
- **Behavioral change:** "En yoğun klinik" now rewrites fully to "en fazla randevusu olan poliklinik" (previously only "klinik → poliklinik"). This is the intended NLU v2 semantics; the one affected test expectation was updated deliberately.

## Test Coverage

- `tests/test_nlu_v2.py` (62 tests): medical terminology, conversational normalization, 12 relative-date variants, date resolution into `final_query`, operation/limit/order detection, ranking/expansion rewrites, ambiguity detection (positive and negative), graph routing diversion, clarification rendering, Turkish suffix harmonization, diacritics-insensitive matching, composite success-criteria query.
- Existing suites unchanged except one deliberate expectation update in `test_query_analyzer.py`.

## Regression Results

Full backend suite: **255 passed, 0 failed** (`pytest backend/tests`).
