# LIVE-MEMORY-FOLLOWUP-001 Engineering Review

## Scope

The change is limited to conversational memory resolution, query-plan merge
semantics, API diagnostics, and deterministic tests.

## Risk Review

- Bare `bunu` is now a pronoun only within the existing resolver path. Ambiguous
  references still require prior context.
- Output-only commands retain `output_action_followup`, so existing table/chart
  follow-ups continue to receive the retained query-plan snapshot.
- Trend follow-ups clear stale categorical dimensions only when the new turn has a
  time grain and does not state a replacement dimension.
- API `resolved_*` fields now prefer the final `QueryPlan`, aligning metadata with
  executed SQL.

## Tests

Passed:

- `pytest tests/test_live_memory_followups.py tests/test_context_engine.py::TestOutputActionFollowup tests/test_conversational_memory_phase1.py::test_gender_ratio_date_override_branch_split_full_chain -q`
- `pytest tests/test_chat_memory_architecture.py tests/test_conversational_memory_phase1.py tests/test_ai_intelligence_018.py tests/test_year_followup_and_aggregate_semantics.py -q`

Known local warning: pytest could not write cache files under `.pytest_cache`
because of a Windows permission denial. This did not affect test execution.
