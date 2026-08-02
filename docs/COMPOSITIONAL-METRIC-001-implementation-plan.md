# COMPOSITIONAL-METRIC-001 — Implementation Plan

## Goal

Improve deterministic interpretation of previously unseen data-quality and operational-status questions without adding full-sentence aliases for every wording variation.

## Scope

1. Extend metric catalog entries with optional groups of reusable concept/operator signals.
2. Require at least one match from every configured group before selecting a compositional metric.
3. Preserve explicit, specialized relationship metrics when a broader compositional metric also matches.
4. Add focused positive, negative and precedence tests.
5. Promote every blind case used during implementation into regression and replace it with a fresh unseen case.

## Expected file changes

- `backend/app/semantics/catalog.py`: catalog model and compositional matcher.
- `backend/app/resources/metric_catalog.json`: reusable signal groups.
- `backend/app/planning/planner.py`: deterministic precedence rule.
- `backend/tests/test_colloquial_normalization.py`: matcher and planner regressions.
- `backend/tests/test_evaluation_harness.py`: blind/regression membership contracts.
- `backend/tools/evaluation/resources/colloquial_blind_v2.json`: promoted and replacement cases.

## Safety constraints

- No database access or live patient data is required.
- Generated SQL still passes through the existing read-only validator.
- A metric is not selected from a single loose keyword; every configured signal group must match.
- Existing specific relationship metrics outrank generic compositional matches.

## Verification

Run the focused unit tests, both colloquial suites, the 887-question variation matrix, Ruff and the complete backend test suite.
