# COMPOSITIONAL-METRIC-001 — Engineering Review

## Outcome

The fresh blind score rose from 15/35 to 23/35 while the promoted regression suite remained 24/24 and the full catalog matrix remained 887/887. The target of at least 22/35 was exceeded without querying SQL Server or adding production examples from the holdout.

## Design assessment

- Signal groups are catalog data, so business terminology remains outside planner condition chains.
- All groups are mandatory, preventing a lone word such as “doctor” or “queue” from forcing an unrelated metric.
- Existing synonym matching is retained. Compositional recognition is an additional deterministic surface, not an LLM or database shortcut.
- Specialized `having_*` repeat-behavior metrics take precedence over generic compositional metrics. This rule repaired a detected 15-case variation-matrix regression.
- Every SQL query continues through the existing deterministic builder and read-only SQL validator.

## Residual risks

1. A phrase can contain all configured groups but mean something else; negative tests reduce, but cannot eliminate, semantic false positives.
2. The remaining 12 blind failures are concentrated in compound repeat behavior, lead-time/date relationships, period comparison and indirect status wording.
3. The blind set is still synthetic and small. Real user utterances should be collected only after removing PII and should remain outside production retrieval until formally promoted.
4. Live schema/value grounding and final-answer correctness still require the SQL Server metadata and safe sample/profile information from the other computer.

## Next recommended slice

Implement compositional relationship recognition for date pairs and repeat behavior (same-day booking, protocol opening delay, same-day multi-doctor/service and cross-period comparisons), using the same promotion-and-refresh discipline.
