# AI-ANALYTICS-002 - Engineering Review

## Design Decisions

1. **Facts vs. narrative strictly separated.** Rules, confidence, and every number come from the deterministic layer; the LLM contributes sentences only. The parser strips any `confidence` field the LLM returns, and a dedicated test proves a lying LLM cannot override computed confidence.
2. **LLM is optional and untrusted.** Three graceful degradation paths: (a) confidence LOW → LLM never called, canonical "Insufficient analytical evidence." output; (b) provider missing → deterministic template narrative; (c) LLM error or invalid JSON → deterministic template narrative. In all cases the output structure is identical, so downstream consumers never branch.
3. **Prompt data minimization.** `InsightPromptBuilder` exposes a whitelisted payload: scalar metrics, top-5 rankings, distribution percentages, insight fields. SQL, schema, and raw rows are structurally unreachable from the builder — verified by tests.
4. **Grounded templates.** The fallback narrative interpolates only values present in `analytics.metrics`; there is no free-form generation anywhere in the deterministic path.
5. **Independence of packages.** `app.insights` imports `AnalyticsResult` read-only; `app.analytics` has no knowledge of insights. The node wiring is the only integration point.
6. **Prompt under `/prompts`.** Per repo rules, the LLM instructions live in `insight_generation.md` (loaded via the existing PromptLoader/Renderer), with `{{ }}` escaping for the JSON example since the renderer uses `str.format`.

## Rule / Confidence Semantics

- Growth thresholds: >15% HIGH_GROWTH, 0–15% MODERATE_GROWTH, <0 DECLINING (boundary 15.0 is MODERATE — tested).
- DOMINANT_CATEGORY (>50% share) and BALANCED_DISTRIBUTION (spread ≤10 pp) are mutually exclusive by construction.
- OUTLIER_DETECTED fires only on categorical shapes (top value > 1.5 × average).
- Confidence: LOW = insufficient evidence; MEDIUM = shape-expected metrics missing or no rule fired; HIGH = complete analytics + consistent rules. Pure function, order-stable, tested for determinism.

## Risks and Mitigations

- **LLM hallucination in narrative text** cannot be fully prevented, but is bounded: the prompt forbids unlisted numbers, the payload is minimal, and structure is schema-validated; a stricter post-hoc number-verification pass is a clean future extension point in `_parse_narrative`.
- **Latency**: one additional LLM call per analytical query. Mitigated by skipping the LLM entirely for LOW-confidence/empty results, and by the non-fatal node design. Deterministic path overhead is <1 ms.
- **Provider output variance** (think blocks, code fences, prose around JSON) handled by a tolerant extractor with template fallback.

## Performance Impact

- Deterministic path (rules + confidence + templates): sub-millisecond.
- LLM path adds one provider round-trip, tracked separately as `llm_latency_ms` plus prompt/completion tokens in logs and `generate_insights_ms` in workflow metrics/timing table.

## Test Coverage

`tests/test_insights.py` — 34 tests with a deterministic fake provider: growth boundaries (6 cases), trends (3), dominant/balanced/outlier distribution rules, single metric, empty analytics, rule determinism, confidence HIGH/MEDIUM/LOW, prompt content and payload truncation/safety, LLM-path structure, confidence-override protection, fenced-JSON parsing, LLM failure and invalid-JSON fallbacks, no-LLM-call-on-LOW guarantee, structural validity across five analytics scenarios, and node integration (populate / skip / non-fatal failure).

## Regression Results

Full backend suite: **335 passed, 0 failed** (301 pre-existing + 34 new). Deterministic analytics calculations untouched — all AI-ANALYTICS-001 tests pass unmodified; the only pre-existing test change is the E2E node-sequence assertion extended with `generate_insights`. New code is ruff-clean.
