# COMPOSITIONAL-COVERAGE-002 Implementation Plan

## Goal

Reduce unanswered or misrouted analytical questions by covering seven remaining
colloquial concept families without adding whole-question memorization.

## Scope

- Extend catalog-driven compositional signals for date relationships, protocol
  delay, actual duration, calendar-day averages, same-day multi-doctor behavior,
  and waiting share.
- Preserve the safe clarification for an unbounded historical comparison.
- Promote all previously inspected blind cases to regression cases.
- Add seven fresh, unseen blind cases and measure them only after implementation.
- Keep every generated query on the deterministic read-only SQL path and SQL
  validator.

## Expected files

- `backend/app/resources/metric_catalog.json`
- `backend/app/semantics/catalog.py`
- `backend/app/planning/planner.py`
- `backend/app/services/query_analyzer.py`
- `backend/app/context/resolver.py`
- `backend/app/shared/history_period.py`
- `backend/tools/evaluation/resources/colloquial_blind_v2.json`
- `backend/tests/test_colloquial_normalization.py`
- `backend/tests/test_smart_clarification.py`
- `backend/tests/test_evaluation_harness.py`
- `docs/COMPOSITIONAL-COVERAGE-002-walkthrough.md`
- `docs/COMPOSITIONAL-COVERAGE-002-engineering-review.md`

## Risks and controls

- Broad Turkish stems can create false positives. Prefer multi-concept groups
  and phrase signals over single short stems.
- `sira` must not make the command `sirala` look like a waiting-status query.
  Only `bekleme sirasi`-anchored phrases are allowed.
- A question with an unspecified historical window must continue to ask for a
  period instead of silently inventing one.
- Existing question-variation, regression, and full test suites are release
  gates.

## Verification

1. Focused catalog/planner regression tests.
2. Promoted colloquial regression suite.
3. Fresh colloquial blind suite.
4. Full question-variation matrix.
5. Ruff and full backend pytest suite.
