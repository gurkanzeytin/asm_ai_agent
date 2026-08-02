# COLLOQUIAL-BLIND-001 — Walkthrough

## What was created

The supplemental resource now contains 70 manually written questions. They are not generated from metric/column templates and are not available to production retrieval.

- 35 cases remain true blind holdout cases in `colloquial_blind_v2`.
- 35 cases that influenced hardening were promoted to the non-blind `colloquial_regression_v2` suite.

The blind set spans 14 phrasing families, including typo-heavy duration/status questions, colloquial data-quality requests, demographic and organizational distributions, trends, period comparisons and repeat-patient behavior.

## Baseline result

Offline SQL-generation evaluation, without a live database:

| Suite | Passed | Failed | Accuracy |
|---|---:|---:|---:|
| Initial `colloquial_blind_v2` baseline | 13 | 22 | 37.14% |
| Same holdout after normalization hardening, before promotion | 24 | 11 | 68.57% |
| First refreshed `colloquial_blind_v2` | 15 | 20 | 42.86% |
| Same refreshed holdout after compositional matching, before promotion | 23 | 12 | 65.71% |
| Second refreshed `colloquial_blind_v2` | 23 | 12 | 65.71% |
| Same holdout after relationship/date hardening, before promotion | 34 | 1 | 97.14% |
| Third refreshed `colloquial_blind_v2` | 28 | 7 | 80.00% |
| `colloquial_regression_v2` | 35 | 0 | 100% |

Blind routing accuracy remains 100%. The refreshed holdout deliberately adds harder unseen language; its remaining weaknesses are:

- 7 metric mismatches
- 6 analysis-type mismatches
- 3 result-contract mismatches

`UNKNOWN_COLUMN` appears 11 times because the produced SQL did not use one or more columns required by the intended metric; it is generally a downstream symptom of the metric/analysis mismatch, not a claim that the physical catalog lacks those columns.

## Safety improvements locked as regressions

- “en düzgün çalışan” now asks for a measurable criterion.
- Satisfaction and colloquial collection/payment requests explain that the view lacks the required data.
- Raw patient name/surname listing requests are blocked with an aggregate alternative.
- Destructive table-delete wording is evaluated through the same fail-closed read-only guard used in production and produces no SQL.

## How to use the result

Fix one failure family at a time. Once a blind case directly influences a code/catalog change, move that case to a regression suite and add a fresh unseen replacement to the blind pool. This prevents the holdout score from becoming a memorization score.
