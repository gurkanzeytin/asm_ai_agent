# AG-020 - Walkthrough

The agent graph is unchanged. `RetrieveContextNode` still passes the original user question to `PromptService`, and `PromptService` still calls `SchemaRetriever.retrieve_context`.

Inside `SchemaRetriever`, the new deterministic `QueryAnalyzer` produces a `QueryAnalysis` object. The retriever uses `normalized_query` for semantic search and keyword scoring, then applies an additive entity boost based on detected domain entities.

Temporal expressions such as `bugun`, `dun`, `gecen ay`, `son 7 gun`, `Ocak ayinda`, and `2025 yilinda` are converted into deterministic `DateRange` objects for observability and future prompt/query planning.
