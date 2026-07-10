# AG-HOTFIX-006 - Ollama Embedding Separation & Retrieval Recovery

## Implementation Plan

1. Add a dedicated `OLLAMA_EMBEDDING_MODEL` configuration value and expose it in `.env.example`.
2. Keep Ollama text generation bound to `OLLAMA_MODEL` and embedding requests bound to `OLLAMA_EMBEDDING_MODEL`.
3. Validate the configured embedding model through Ollama `/api/tags` during provider startup when the provider is initialized from application settings.
4. Preserve explicit embedding failure diagnostics including model name, endpoint, HTTP status, response body, and duration.
5. Extend automated tests for model separation, missing embedding model validation, metadata, and failure diagnostics.

## Walkthrough

Text generation continues to call `/api/generate` with `self.model`, which is resolved from `OLLAMA_MODEL`.
Embedding generation calls `/api/embeddings` with `self.embedding_model`, which is resolved from `OLLAMA_EMBEDDING_MODEL`.

When startup validation runs and the configured embedding model is not present in the `/api/tags` response, the provider raises `ConfigurationError` with the remediation command:

```bash
ollama pull nomic-embed-text
```

If an embedding request fails at runtime, `OllamaProvider.embed()` logs the complete diagnostic payload and attaches the same fields to the raised `LLMResponseError`. The semantic schema index records those fields in `last_embedding_error`, allowing the retriever to report the retrieval degradation before using hash fallback behavior.

## Engineering Review

The change keeps Clean Architecture boundaries intact:

- API routes do not call Ollama directly.
- LLM calls remain inside the provider layer.
- Retrieval continues to depend on the provider abstraction instead of concrete endpoint logic.
- Prompt files and SQL validation behavior are unchanged.

Primary operational risk is local environment readiness: `nomic-embed-text` must be installed in Ollama for semantic retrieval to work. The fail-fast validation is scoped to missing model detection and returns a clear installation command.
