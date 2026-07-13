# NLU-001 - Implementation Plan

## Objective

Improve the natural language understanding of the existing database question-answering pipeline so users can ask questions in natural Turkish without knowing schema vocabulary. No API changes, no frontend changes, no architecture refactoring.

## Root Cause of Previous Limitations

1. **Narrow rewrite coverage.** `domain_synonyms.json` held a flat list of ~11 rewrite rules covering only a handful of medical terms. Common vocabulary (dahiliye, cildiye, göz, ortopedi), ranking phrases (en boş, en çok çalışan) and conversational fillers were not handled.
2. **Hardcoded fallback.** The "en yoğun bölüm" rewrite lived in Python (`_apply_domain_rewrite_fallbacks`) instead of configuration, violating the config-driven design.
3. **Relative dates were detected but never normalized.** `QueryAnalyzer` produced `DateRange` objects for observability only; the query text sent to SQL generation still contained "geçen ay", leaving interpretation to the LLM. Coverage also lacked "bu hafta", "bu ay", "son N ay/yıl/hafta".
4. **No canonical action/aggregate mapping.** "Göster/listele/getir/kaç/toplam/ortalama" carried no structured signal.
5. **No ambiguity detection.** "En iyi doktor" went straight to SQL generation with an arbitrary metric chosen by the LLM.
6. **Turkish capital İ bug.** `"İlk".lower()` produces `i + U+0307` in Python, so word-boundary matching silently failed for any word starting with İ.

## Plan

1. Restructure `domain_synonyms.json` into grouped rewrite rules (`rewrite_groups`: conversational → medical → domain → ranking → expansion) plus new `operations` and `ambiguous` sections. Keep backward compatibility with the flat `rewrites` list.
2. Extend `QueryAnalyzer` with a staged pipeline: normalize → rewrite → expand → detect operations/limit/order → detect dates → resolve dates into the final query → detect ambiguity.
3. Add `rewritten_query`, `expanded_query`, `final_query`, `detected_operations`, `detected_limit`, `detected_order`, `is_ambiguous`, `ambiguity` to `QueryAnalysis` (all defaulted; backward compatible).
4. `SchemaRetriever` keeps using the natural-language `normalized_query` for embedding search but hands `final_query` (relative dates resolved to ISO ranges) to SQL generation via `DatabaseContext.normalized_query`.
5. Ambiguity routing: `AnalyzeIntentNode` runs `QueryAnalyzer.detect_ambiguity`; `route_by_intent` diverts ambiguous database queries to `GenerateClarificationNode`, which renders the configured clarification question and options.
6. Full-pipeline observability logging in `QueryAnalyzer._log_analysis`.
7. Regression tests in `tests/test_nlu_v2.py`; run the full backend suite.
