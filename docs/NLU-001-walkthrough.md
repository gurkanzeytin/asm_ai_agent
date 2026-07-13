# NLU-001 - Walkthrough

## Pipeline

```
User Question
  → Normalization        (lowercase, punctuation, Turkish İ/i̇ fix)
  → Rewrite Engine       (conversational → medical → domain → ranking groups)
  → Query Expansion      (expansion group, e.g. "en çok hasta bakan" → "en fazla hastası olan")
  → Structured Detection (operations LIST/COUNT/SUM/AVG, LIMIT, ORDER, entities, dates)
  → Ambiguity Check      (config-driven; diverts to clarification)
  → Date Resolution      (relative Turkish dates → explicit ISO ranges)
  → final_query          (single source of truth handed to SQL generation)
```

`QueryAnalyzer.analyze` now returns staged fields: `normalized_query` (natural-language rewrite used for schema retrieval), `rewritten_query`, `expanded_query`, and `final_query` (dates resolved). `SchemaRetriever` embeds/scores with the natural-language form and publishes `final_query` on `DatabaseContext.normalized_query`, which `GenerateSQLNode` already forwards to the SQL prompt.

## Ambiguity Flow

`AnalyzeIntentNode` calls `QueryAnalyzer.detect_ambiguity(question)`. If a configured phrase such as "en başarılı" matches, `AgentState.ambiguity` is populated and `route_by_intent` routes to `generate_clarification` instead of the SQL pipeline. `GenerateClarificationNode` renders the configured Turkish question and bullet options.

## Configuration (`backend/app/resources/domain_synonyms.json`)

- `entities` — domain entity terms (extended with iç hastalıkları, dermatoloji, ortopedi ve travmatoloji, göz hastalıkları...).
- `rewrite_groups.conversational` — filler removal ("lütfen", "acaba", "bana") and polite-request canonicalization ("görebilir miyim" → "göster").
- `rewrite_groups.medical` — department vocabulary (kalp → kardiyoloji, dahiliye → iç hastalıkları, cildiye → dermatoloji, göz → göz hastalıkları, ortopedi → ortopedi ve travmatoloji, KBB, kadın doğum, pediatri/çocuk).
- `rewrite_groups.domain` — hekim → doktor, muayene → randevu, klinik → poliklinik, kontrol → kontrol randevusu.
- `rewrite_groups.ranking` — en yoğun → en fazla randevusu olan, en boş → en az randevusu olan, en çok/az çalışan → en fazla/az işlem yapan.
- `rewrite_groups.expansion` — vague expressions to database concepts ("en çok hasta bakan" → "en fazla hastası olan").
- `operations` — action/aggregate keyword → LIST / COUNT / SUM / AVG.
- `ambiguous` — patterns ("en başarılı", "en iyi", "en kötü", "en verimli") with clarification question and options.

New expressions are added by editing this JSON only; no Python changes are needed. Groups apply in configuration order; `expansion` always runs last.

## Example Rewrites (today = 2026-07-13)

| Input | Final Query |
|---|---|
| Kalp doktorlarından bugün en yoğun olan ilk 5 kişiyi göster. | kardiyoloji doktorlarından 2026-07-13 tarihinde en fazla randevusu olan ilk 5 kişiyi göster (LIST, LIMIT 5) |
| Geçen ay en çok hasta bakan doktor kim? | 2026-06-01 ile 2026-06-30 tarihleri arasinda en fazla hastasi olan doktor kim |
| Bu hafta randevusu olmayan doktor var mı? | 2026-07-13 ile 2026-07-19 tarihleri arasinda randevusu olmayan doktor var mı |
| En yoğun bölüm hangisi? | en fazla randevusu olan bölüm hangisi |
| Hekimleri listele. | doktorları listele (LIST) |
| Bugün kaç randevu oluşturuldu? | 2026-07-13 tarihinde kaç randevu oluşturuldu (COUNT) |
| Lütfen bana dahiliye doktorlarını görebilir miyim | ic hastaliklari doktorlarını goster (LIST) |
| En başarılı doktor kim? | → clarification: "Başarı kriteri olarak neyi kullanmamı istersiniz? • Randevu sayısı • Hasta sayısı • Reçete sayısı • Başka bir kriter" |

## Relative Time Coverage

bugün, dün, yarın, bu hafta, geçen hafta, bu ay, geçen ay, bu yıl, geçen yıl, son N gün, son N hafta, son N ay, son N yıl, "<ay adı> ayında", "<yıl> yılında". All are resolved deterministically into ISO date ranges in `final_query` before SQL generation.

## Logging

`QueryAnalyzer._log_analysis` emits one structured record per query: Original → Normalized → Rewritten → Expanded → Detected Intent (operations/LIMIT/ORDER) → Detected Entities → Date Expressions → Ambiguous Yes/No → Final Query Sent to SQL Generation, with the same fields attached as structured `extra` data.

## Files Modified

- `backend/app/resources/domain_synonyms.json` — grouped rewrite config, operations, ambiguous patterns.
- `backend/app/resources/intent_keywords.json` — Turkish action verbs and temporal words for database_query intent.
- `backend/app/application_models/query_analysis.py` — `AmbiguityResult`; staged/structured fields on `QueryAnalysis`.
- `backend/app/services/query_analyzer.py` — staged rewrite engine, İ normalization fix, operation/limit/order detection, ambiguity detection, extended date detection, date resolution, pipeline logging; removed the hardcoded "yoğun bölüm" fallback.
- `backend/app/database_intelligence/retriever.py` — publishes `final_query` to `DatabaseContext`.
- `backend/app/agent/state.py` — `ambiguity` field.
- `backend/app/agent/nodes/analyze_intent.py` — ambiguity detection.
- `backend/app/agent/graph.py` — routing diversion for ambiguous database queries.
- `backend/app/agent/nodes/generate_clarification.py` — renders configured clarification.
- `backend/tests/test_nlu_v2.py` — new regression suite (62 tests).
- `backend/tests/test_query_analyzer.py` — one expectation updated for the new generic "en yoğun" rewrite.
