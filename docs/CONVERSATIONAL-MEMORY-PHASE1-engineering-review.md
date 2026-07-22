# Conversational Memory Repair — Phase 1 Engineering Review

## Architecture

The change keeps ownership boundaries intact: the context layer owns volatile
conversation state, the planner remains the producer of `QueryPlan`, the agent
state carries typed workflow data, and API routes remain unchanged. No LLM or
database access was introduced into endpoints.

The snapshot is a serialized `QueryPlan`, not a second memory model. Pydantic
validation restores it before use. It cannot contain rows, generated reports,
or visualization state because those fields are absent from the contract and a
regression test checks the retained payload.

## Precedence and safety review

- Snapshot exposure is gated by the resolver's follow-up verdict.
- Explicit current dates replace all prior date/period fields.
- Filter predicates replace only predicates for the same column family.
- Filter-only wording does not accidentally replace grouping dimensions.
- Additive split wording unions dimensions; ordinary explicit dimensions
  replace them.
- Planner-default count metrics on terse ranking turns cannot overwrite an
  explicit retained metric such as average duration.
- SQL remains read-only and passes through the existing SQL validator in the
  production workflow.
- Persistence exceptions degrade to `False`; success is never fabricated.

## Verification

`backend/tests/test_conversational_memory_phase1.py` executes all four required
multi-turn chains across resolver, `AgentState`, retrieve/planning, grounded
filter resolution, persistence, and deterministic SQL where supported. Focused
regression execution passed 296 tests. The complete backend suite passed with
1,388 tests and one intentional skip in 64.87 seconds.

## Phase 2 findings

The Phase 1 tests prove the nationality chain's final `QueryPlan` contains a
grounded `gender=K` typed filter. The existing deterministic SQL builder does
not consume `resolved_filters`, so its SQL omits `CinsiyetId`. Likewise, the
female-to-male cohort ratio is retained as structured calculation intent, but
the builder has no dedicated cohort-ratio rendering path. These are SQL-builder
integration tasks for Phase 2; Phase 1 deliberately does not modify the
builder.
