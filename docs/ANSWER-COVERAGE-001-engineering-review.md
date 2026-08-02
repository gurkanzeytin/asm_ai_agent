# ANSWER-COVERAGE-001 — Engineering Review

## Outcome

Fresh unseen accuracy increased from 65.71% to 80.00%. The regression suite grew from 24 to 35 cases and remains 100%, while the 887-case generated catalog matrix remains 100%.

## Important design decisions

1. Compositional recognition is still deterministic catalog logic, not an unrestricted fuzzy or LLM guess.
2. Specificity uses required-column containment. For example, same-day multi-doctor behavior requires the generic patient column plus date and doctor columns, so it may safely supersede a generic unique-patient reading.
3. Explicit dimensions block an unrelated time-trend upgrade, protecting demographic and organizational breakdowns.
4. Raw-list intent wins over analytical fallbacks unless the resolved intent is genuinely a time trend.
5. A safe failure produces useful commentary but never fabricates a number.

## Remaining risks

- `daha önce` has no objective lower bound; a user or deployment policy must define whether it means all history, previous year or a fixed lookback.
- Fresh wording around “same date”, “start minus end”, “calendar day average” and “waiting line share” still needs a future holdout-driven slice.
- The 80% result measures planning and SQL generation against a synthetic, PII-free set. Live execution and final narrative quality still require SQL Server access.
- A system/provider outage cannot produce requested data. The improved fallback explains the understood request and next action, but correctly does not claim a result.

## Next recommended slice

`CONVERSATIONAL-ANSWER-001` now asks for and resumes a bounded prior period instead of guessing unbounded history, and adds deterministic KPI-commentary evaluation. The remaining schema/value expansion waits for Monday's PII-free profile.
