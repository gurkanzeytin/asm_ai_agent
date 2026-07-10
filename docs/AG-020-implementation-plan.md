# AG-020 - Implementation Plan

1. Add `QueryAnalysis`, `DetectedEntity`, and `DateRange` application models.
2. Add deterministic `QueryAnalyzer` service backed by `domain_synonyms.json`.
3. Normalize casing, punctuation, whitespace, synonyms, domain entities, and temporal expressions without LLM calls.
4. Integrate query analysis inside `SchemaRetriever` while keeping `retrieve_context(question, schema)` compatible.
5. Use `normalized_query` for semantic search and keyword expansion.
6. Add entity-based additive ranking boost.
7. Add structured query-analysis diagnostics.
8. Cover analyzer behavior, hot reload, and normalized retrieval input with tests.
