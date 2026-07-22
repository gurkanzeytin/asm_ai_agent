# Conversational Memory Repair — Phase 1 Implementation Plan

## Objective

Carry the latest successful structured `QueryPlan` through conversational
resolution and the next planning cycle without storing result rows, reports,
visualizations, or chart state.

## Scope

1. Add a serialized `QueryPlan` snapshot to volatile conversation context.
2. Expose that snapshot only when `ContextResolver` identifies a genuine
   follow-up.
3. Hand the validated snapshot and raw question through `AgentState` to
   `RetrieveContextNode`.
4. Merge the current explicit plan over the retained plan by field family:
   current date/filter/dimension/metric/ranking constraints win; untouched
   constraints inherit; independent questions receive no snapshot.
5. Make `ContextManager.update()` return its actual persistence outcome and
   propagate that value to `WorkflowResult.memory_updated`.
6. Add deterministic full-chain tests for the four required conversations,
   independent-question isolation, state handoff, and failed writes.

## Explicit non-goals

- No frontend or chart changes.
- No database schema or external persistence changes.
- No result-row, report, or visualization storage.
- No SQL-builder redesign; unsupported typed-filter rendering is recorded as
  Phase 2 work.

