# Conversational Memory Repair — Phase 1 Walkthrough

After a successful data-bearing turn, `ContextManager` stores the exact JSON
form of its `QueryPlan` in the existing volatile, TTL-bounded session context.
The snapshot contains analytical intent only.

On the next turn, `ContextResolver` first decides whether the question is a
genuine continuation. Constraint-editing wording such as “sadece”, “sınırla”,
and “ayır”, plus ranking requests that omit their metric, are recognized as
continuations only when a valid analytical context exists. A complete
independent question does not receive the snapshot.

`ReportingService` validates the snapshot back into a typed `QueryPlan` and
places it in `AgentState`. `RetrieveContextNode` plans the raw current question,
then merges it with retained structure. Explicit current values replace their
families; otherwise dates, dimensions, metrics, predicates, calculation intent,
ranking, order, and limits survive.

The required examples now produce these final contracts:

- January 2026 doctor count → completed only → top 10: `DoktorId`, exact
  January dates, completed predicate, `appointment_count`, descending, limit 10.
- female/male ratio → 2025 → branch split: gender and branch dimensions,
  unique-patient metric, ratio calculation intent, exact 2025 dates.
- nationality distribution → top 5 → women only: nationality dimension,
  descending limit 5, grounded gender code `K`.
- average duration by department → top 10: department dimension and retained
  `appointment_duration_average`, descending limit 10.

Memory writes now return a boolean. `ReportingService` reports
`memory_updated=false` when the session store rejects or fails the write.

