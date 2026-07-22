# Conversational Filter SQL Live Fix — Implementation Plan

## Scope

Repair the confirmed SQL-rendering failure in the existing conversational analytics pipeline without changing the memory design or planner architecture.

## Plan

1. Reproduce both turns with one `session_id` and record the retained `QueryPlan`, analytical context, SQL source, compliance result, execution result, and terminal workflow outcome.
2. Keep the existing `ReportingService -> AgentState -> RetrieveContextNode` handoff unchanged if the prior plan retains the January 2026 date, `DoktorId`, `appointment_count`, and descending order.
3. Route structured `branch_filters`, `department_filter`, grounded `resolved_filters`, and allowlisted `extra_filters` through one deterministic filter renderer.
4. Render string values as escaped T-SQL Unicode literals and de-duplicate equivalent filters across structured sources.
5. Require every recognized planned filter in `PlanComplianceValidator`; do not accept a missing predicate or a non-Unicode non-ASCII value.
6. Treat a genuinely empty executed result as a valid empty shape so it reaches the existing `NO_RESULT_GUIDANCE` path, while retaining strict shape checks for non-empty results.
7. Add same-session full-chain and generic filter regression tests, then run focused and complete backend suites.

