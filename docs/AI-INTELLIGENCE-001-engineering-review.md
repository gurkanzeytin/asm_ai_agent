# AI-INTELLIGENCE-001 - Engineering Review

## Design Decisions

1. **Layers exposed, not rebuilt.** Data, Analytics, Insights, and Visualization already existed; this task adds only the Observation layer and promotes visualization to a top-level response field. The analytics and insight engines are byte-identical to AI-ANALYTICS-001/002 — "no regression to analytics" holds by construction.
2. **Deterministic-first observations.** Every observation originates from a template filled with computed metric values and carries its grounding `evidence`. The LLM is off by default (`OBSERVATION_LLM_WORDING=false`) and, when on, can only reword: validation rejects changed/added numbers, missing evidence strings, count drift, and directive language, then falls back to the deterministic texts. Tests cover each rejection path.
3. **Rule reuse over duplication.** The engine consumes `InsightResult.rules`/confidence when present and recomputes via the shared `InsightRulesEngine` otherwise — one source of truth for business rules (AGENTS.md: never duplicate code).
4. **No recommendations by design.** Templates use neutral phrasing ("may deserve attention", "is noteworthy"); a forbidden-word list (must/should/needs/recommend/advise) is asserted over all template outputs in tests and enforced against LLM rewordings at runtime.
5. **Independent layers, additive API.** All five layers are optional fields on `ReportResponse`; a schema test asserts each is independently omittable. Existing clients are unaffected.
6. **Non-fatal enrichment.** Like analytics and insights, the observations node skips without input and swallows failures — the truth layer and report always survive.

## Risks and Mitigations

- **Observation redundancy** (e.g. DOMINANT_CATEGORY and TOP_CATEGORY both naming the top category): texts are de-duplicated by exact wording; mild semantic overlap is acceptable since the frontend may filter by `category`.
- **Spread heuristic** (highest ≥ 2× lowest) can flag legitimate variation; the wording deliberately stays neutral ("may deserve attention") and the evidence values let the frontend qualify it.
- **LLM rewording quality vs. safety**: validation is strict enough that some valid rewordings are rejected (e.g. a number reformatted as "18.4 percent" survives, but "about 18%" does not) — the failure mode is always the safe deterministic text.

## Performance Impact

- Observation engine: **~1 ms** measured on a full time-series analytics object (rules + templates, no LLM). With `OBSERVATION_LLM_WORDING` enabled, one additional provider call whose latency is tracked as `llm_latency_ms` and `generate_observations_ms`.
- Default configuration adds no LLM calls to the workflow.

## Test Coverage

`tests/test_observations.py` — 23 tests: rule wordings (high growth, declining, stable, dominant, balanced, single metric, significant spread, empty analytics), forbidden-language sweep across all rules, engine behavior (insight-rule reuse, recompute path, LOW confidence on empty, determinism), LLM guardrails (valid rewording applied; rejected on changed numbers, directive language, count mismatch; provider failure; disabled flag ⇒ no call), node integration (populate/skip/non-fatal), and API layer schema independence.

## Regression Results

Full backend suite: **358 passed, 0 failed** (335 pre-existing + 23 new). Analytics and insight suites pass unmodified; the only pre-existing test edit is the E2E node-sequence assertion extended with `generate_observations`. New code is ruff-clean.
