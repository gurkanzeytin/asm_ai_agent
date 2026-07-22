# AI-INTELLIGENCE-011 Engineering Review

## Review Outcome

The implementation is data-driven. Production code contains no fixed acceptance
date literals and no branch for a named month/year example. Month boundaries are
computed by calendar arithmetic and represented as half-open ranges. SQL aliases
come from `PeriodComparisonResult`, while date predicates come from `QueryPlan`.

## Endpoint Evidence

### Aralik 2022 vs Mart 2023

Plan:

- baseline: `Aralık 2022`, `2022-12-01 <= date < 2023-01-01`
- current: `Mart 2023`, `2023-03-01 <= date < 2023-04-01`

SQL predicates:

```sql
BaslangicTarihi >= '2022-12-01' AND BaslangicTarihi < '2023-01-01'
BaslangicTarihi >= '2023-03-01' AND BaslangicTarihi < '2023-04-01'
```

Compliance: `true`

API response row:

```json
{"current_period_label":"Mart 2023","baseline_period_label":"Aralık 2022","current_period_count":33271,"baseline_period_count":35361,"absolute_change":-2090,"percentage_change":-5.910466332965}
```

### Subat 2024 vs Mart 2024

Plan:

- baseline: `Şubat 2024`, `2024-02-01 <= date < 2024-03-01`
- current: `Mart 2024`, `2024-03-01 <= date < 2024-04-01`

SQL predicates:

```sql
BaslangicTarihi >= '2024-02-01' AND BaslangicTarihi < '2024-03-01'
BaslangicTarihi >= '2024-03-01' AND BaslangicTarihi < '2024-04-01'
```

Compliance: `true`

API response row:

```json
{"current_period_label":"Mart 2024","baseline_period_label":"Şubat 2024","current_period_count":30815,"baseline_period_count":28506,"absolute_change":2309,"percentage_change":8.100049112467}
```

### 2022 vs 2023

Plan:

- baseline: `2022`, `2022-01-01 <= date < 2023-01-01`
- current: `2023`, `2023-01-01 <= date < 2024-01-01`

SQL predicates:

```sql
BaslangicTarihi >= '2022-01-01' AND BaslangicTarihi < '2023-01-01'
BaslangicTarihi >= '2023-01-01' AND BaslangicTarihi < '2024-01-01'
```

Compliance: `true`

API response row:

```json
{"current_period_label":"2023","baseline_period_label":"2022","current_period_count":342846,"baseline_period_count":354303,"absolute_change":-11457,"percentage_change":-3.233672873218}
```

All three API responses returned `success=true`, `row_count=1`, and
`outcome=EXECUTE_SQL`.

## Risks Reviewed

- Equal explicit periods remain two periods instead of being de-duplicated.
- Reverse chronological wording preserves user order.
- Negative and greater-than-100 percentage changes are valid change values;
  only level rates are constrained to 0-100 by the evaluator.
- A zero baseline yields `NULL` through `NULLIF`, without making the typed result
  incomplete.
- Live evaluation disposes the async SQLAlchemy pool in the same event loop that
  used it, preventing cross-loop pooled connection failures.
