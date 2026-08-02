# CONVERSATIONAL-ANSWER-001 — Engineering Review

## Outcome

Clarification is now a resumable workflow rather than a terminal question for two high-risk ambiguity families. Deterministic scalar commentary names the actual KPI, and a 7-case executable evaluation protects the main result shapes.

## Design assessment

- Pending clarification is isolated from valid conversation memory and cleared through the existing resolution lifecycle.
- History replies are limited to a previous calendar year or an explicit four-digit year; `all history` is not offered because the current period model needs a safe start boundary.
- Duration clarification is narrow. Canonical `randevu süresi`, `planlanan`, `fiili`, `gerçek`, `başlangıç` or `bitiş` wording bypasses it.
- Patient overlap carries both periods into the relationship SQL builder instead of AND-ing incompatible date filters.
- KPI commentary uses already-approved display labels and typed analytics values, not raw SQL rows or an LLM guess.

## Residual risks

1. Process-local conversation memory does not survive a backend restart or move across workers; production multi-worker deployment needs a shared store.
2. An explicit `all history` cohort still needs a deployment policy or verified minimum date.
3. The commentary evaluator validates deterministic narrative claims, not final LLM prose; provider-output validation remains a separate layer.
4. Real execution and narrative quality still need the PII-free SQL Server profile and controlled live tests.

## Next recommended slice

Add a mentor demo/evaluation pack that runs question → plan → SQL → mocked typed result → final report for each major analytical family.
