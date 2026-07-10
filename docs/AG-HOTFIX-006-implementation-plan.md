# AG-HOTFIX-006 Implementation Plan

## Objective

Restore semantic schema retrieval by separating Ollama text generation from embedding generation and by surfacing embedding failures with actionable diagnostics.

## Scope

- Add `OLLAMA_EMBEDDING_MODEL` to environment configuration examples.
- Use `OLLAMA_MODEL` only for text generation.
- Use `OLLAMA_EMBEDDING_MODEL` only for embeddings.
- Validate the configured embedding model against Ollama tags when the default provider is initialized.
- Preserve offline testability by warning when Ollama is unreachable, while failing fast when Ollama is reachable and the model is missing.
- Store semantic index cache metadata against the embedding model, not the generation model.
- Log embedding failure diagnostics before hash fallback is used.
- Add automated tests for model separation, missing model validation, and diagnostic logging.

## Acceptance Criteria

- Embedding requests send `settings.OLLAMA_EMBEDDING_MODEL`.
- Generation requests continue sending `settings.OLLAMA_MODEL`.
- Missing embedding model raises `ConfigurationError` when Ollama tags are available.
- Embedding HTTP failures include model, endpoint, status, body, and duration in logs.
- Retriever logs embedding fallback diagnostics.
- Existing architecture boundaries remain intact.
