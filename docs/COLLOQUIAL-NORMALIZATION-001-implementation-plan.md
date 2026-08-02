# COLLOQUIAL-NORMALIZATION-001 — Implementation Plan

## Goal

Improve deterministic understanding of common Turkish chat spelling without memorizing complete evaluation questions.

## Slices

1. Recognize apostrophe-free year suffixes (`2024te`, `2025ten`) while preserving aggregate-threshold meaning.
2. Normalize narrow appointment/status spelling variants before semantic catalog resolution.
3. Let the planner resolve catalogs from the analyzer's expanded surface while keeping literal filters on the original question.
4. Expand metric vocabulary for unique-patient, data-quality, in-progress and waiting-rate concept families.
5. Promote every holdout case used for a change to regression and replace it with a fresh case.

## Affected files

- `backend/app/services/query_analyzer.py`
- `backend/app/context/extractor.py`
- `backend/app/planning/planner.py`
- `backend/app/resources/domain_synonyms.json`
- `backend/app/resources/metric_catalog.json`
- `backend/tools/evaluation/resources/colloquial_blind_v2.json`
- `backend/tests/test_colloquial_normalization.py`
- `backend/tests/test_evaluation_harness.py`

## Safety constraints

- No fuzzy edit-distance correction over arbitrary user values.
- Only curated domain spellings are rewritten.
- Generated SQL still passes the read-only SQL validator.
- No live database or PII is used.

## Verification

```bash
cd backend
../.venv/bin/pytest -q tests/test_colloquial_normalization.py tests/test_evaluation_harness.py
../.venv/bin/python -m tools.evaluation run --suite colloquial_blind_v2 --mode sql-generation --no-write
../.venv/bin/python -m tools.evaluation run --suite colloquial_regression_v2 --mode sql-generation --no-write
```
