# AG-020 - Engineering Review

This implementation keeps the existing workflow compatible:

- No API contract changes.
- No agent graph topology changes.
- No LLM call is introduced for NLU.
- Retrieval still exposes the same `retrieve_context(question, schema)` interface.

The main tradeoff is that deterministic NLU depends on curated synonym and rewrite rules. This is intentional for latency and predictability. The dictionary is resource-backed and reloads in `DEBUG`, so domain vocabulary can be expanded without changing service code.
