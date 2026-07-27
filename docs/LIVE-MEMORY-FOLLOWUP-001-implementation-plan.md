# LIVE-MEMORY-FOLLOWUP-001 Implementation Plan

## Problem

Live UI testing showed that responses could be correct while API memory diagnostics
reported `follow_up_detected=false` for analytical follow-ups that start with bare
`bunu`, such as converting a prior status distribution into a yearly monthly trend.

## Plan

1. Treat bare `bunu` as a deterministic referential pronoun when prior analytical
   context exists.
2. Preserve existing output-action behavior for phrases such as `Bunu tabloya cevir`
   and `Bunu grafikte goster`.
3. When a follow-up explicitly asks for a time-grain trend without a new categorical
   dimension, clear the inherited categorical dimension instead of carrying stale
   `GROUP BY` state.
4. Expose API `resolved_metrics`, `resolved_dimensions`, and `resolved_filters` from
   the final `QueryPlan` when available, because the plan is the authoritative
   post-merge contract.
5. Add deterministic tests for the live UI regression and run the existing memory
   suites.
