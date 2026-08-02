# COLLOQUIAL-BLIND-001 — Engineering Review

## Outcome

The repository now has an independent, reproducible measure of colloquial Turkish robustness. The baseline exposes a significant gap that the generated 887-case catalog matrix could not reveal: catalog-shaped questions pass while natural misspellings and indirect phrasing frequently collapse to generic appointment count.

## Important findings

1. **Metric recognition remains the highest-risk layer.** Seven of the current 35 blind questions select the wrong metric. Indirect date relationships remain especially vulnerable.
2. **Analysis type can still degrade to generic count.** Six current cases lose ratio, duration or repeat semantics.
3. **Year suffixes are now covered.** Explicit year-to-year phrasing without a comparison verb can still miss the period-pair contract.
4. **The previous evaluation runner skipped a production safety boundary.** Unsafe write intent is now scored through `AnswerabilityGuard`; context-dependent domain routing remains outside this offline runner's authority.
5. **Holdout hygiene matters.** All 35 cases that drove behavior changes are non-blind regressions; 35 independent cases remain in the holdout.

## Security and privacy

- The supplemental dataset contains no live data or PII values.
- It is outside production prompts and the golden few-shot dataset.
- Unsafe writes remain blocked before planning/SQL generation.
- Patient names/surnames are not offered as raw output.

## Assumptions and unknowns

- Results measure deterministic planning and SQL generation only; final natural-language quality against real rows requires SQL Server access.
- Column meanings and actual value distributions still require Monday's PII-free live profile.
- The initial 37.14% and first refreshed 42.86% blind scores are diagnostic baselines, not production-readiness claims. After the third promotion and refresh, the independent holdout is 80.00% (28/35).

## Recommended next slices

1. Improve repeat-behavior intent signals for “birden çok kere”, “iki ayrı doktor” and cross-period return language.
2. Compose date relationships for same-day booking, protocol opening delay and invalid temporal order.
3. Improve indirect status wording while keeping all signal groups mandatory.
4. Re-run the holdout; promote only cases used in fixes and replace them with new unseen cases.

## Verification

```bash
cd backend
../.venv/bin/pytest -q
../.venv/bin/ruff check tools/evaluation/dataset.py tools/evaluation/runner.py tools/evaluation/scorers.py tests/test_evaluation_harness.py
```
