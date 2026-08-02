# COLLOQUIAL-BLIND-001 — Implementation Plan

## Goal

Measure how the appointment-reporting agent handles previously unseen, everyday Turkish questions without copying catalog labels or adding the questions to prompts/few-shot retrieval.

## Scope

- Add a manually curated holdout suite under `backend/tools/evaluation/resources`.
- Cover missing diacritics, abbreviations, ordinary speech, typos, multi-period questions, dimensions, status metrics, durations, repeat behavior, ambiguity, privacy and unsafe SQL requests.
- Reuse the existing evaluation runner and typed expected-plan/SQL contracts.
- Keep the dataset out of `app/resources/golden_dataset.json` and all production prompts.
- Promote any case used to change production behavior from blind holdout to a non-blind regression suite.

## Expected file changes

- `backend/tools/evaluation/resources/colloquial_blind_v2.json`
- `backend/tools/evaluation/dataset.py`
- `backend/tools/evaluation/runner.py`
- `backend/tools/evaluation/scorers.py`
- `backend/app/resources/domain_synonyms.json`
- `backend/app/resources/column_intelligence.json`
- `backend/tests/test_evaluation_harness.py`

## Rollout and risk

- The supplemental file is loaded only by the offline evaluation package.
- Explicit-path dataset loads remain isolated and do not merge supplements.
- The runner uses the production answerability guard only for its fail-closed unsafe-write verdict; context-dependent `no_domain_signal` is not treated as final offline.
- No SQL Server connection or patient data is required.

## Verification

```bash
cd backend
../.venv/bin/python -m tools.evaluation run --suite colloquial_blind_v2 --mode sql-generation --no-write
../.venv/bin/python -m tools.evaluation run --suite colloquial_regression_v2 --mode sql-generation --no-write
../.venv/bin/pytest -q tests/test_evaluation_harness.py
```
