# AG-HOTFIX-006 Walkthrough

## Configuration

Set text generation and embedding models separately:

```env
OLLAMA_MODEL=qwen3:8b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
```

Install the embedding model locally:

```bash
ollama pull nomic-embed-text
```

## Runtime Flow

1. The application initializes `OllamaProvider`.
2. Text generation uses `OLLAMA_MODEL` through `/api/generate`.
3. Embedding generation uses `OLLAMA_EMBEDDING_MODEL` through `/api/embeddings`.
4. Startup validation checks `/api/tags` for the configured embedding model.
5. If Ollama is reachable and the embedding model is missing, startup raises `ConfigurationError`.
6. If an embedding request fails, the provider logs endpoint, model, HTTP status, response body, and elapsed time.
7. The semantic index records the failure metadata and falls back to deterministic hash embeddings.
8. The retriever logs the fallback diagnostics before continuing.

## Manual Verification

Run the backend after installing the embedding model and ask:

```text
Dünkü randevuları listele
```

Expected behavior:

- No embedding request is sent with `qwen3:8b`.
- Embedding requests use `nomic-embed-text`.
- Logs include semantic candidate counts.
- Fallback schema context is not used when semantic retrieval succeeds.
