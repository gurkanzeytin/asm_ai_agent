# EXPERT-SQL-UI-REGRESSIONS-002 Implementation Plan

## Scope

Fix the second expert SQL UI batch:

- Do not parse HAVING thresholds such as `2000 den az` as calendar years.
- Recognize space-separated month ranges such as `Ocak Haziran arasi`.
- Use the requested date semantic column for monthly buckets, including `CreatedDate`.
- Support time bucket plus ordinary dimensions in deterministic SQL.
- Preserve analytical filters for `ayni filtreyle <year>` follow-ups.
- Prevent fixed-dimension count metrics from colliding with distinct-count metrics.

## Approach

1. Harden date parsing around threshold suffixes and month-range separators.
2. Extend view date semantics for `olusturulma`/`olusturma`/`kayit` wording.
3. Route dimensioned or multi-metric time trends through the grouped SQL builder.
4. Suppress redundant fixed-dimension `COUNT(*)` metrics when a more specific metric is present.
5. Treat `ayni filtreyle` as a deterministic follow-up marker.
6. Add regression coverage for every fixed query shape.
