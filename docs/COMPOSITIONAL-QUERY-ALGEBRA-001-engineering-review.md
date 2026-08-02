# COMPOSITIONAL-QUERY-ALGEBRA-001 — Engineering Review

## Outcome

The change removes several “Yanıt veremiyorum” paths without teaching the agent
individual questions. The core abstraction is a validated conditional
numerator/denominator plus an arbitrary list of catalog metrics and dimensions.

## Correctness

- Numerator and denominator scopes are explicit and independently testable.
- Metric cohort columns are removed from outer filters and grouping, preventing
  the silent 100% denominator-collapse failure.
- Date, organizational and requested breakdown scope remains outside the
  conditional metric and therefore applies to both numerator and denominator.
- A composite metric is rejected if any predicate is invalid; conditions are
  never partially dropped.
- Existing serialized single-predicate inline metrics remain valid.

## Security

- Predicates are data-only Pydantic models.
- Columns and operators pass existing allow-lists.
- Values pass existing T-SQL literal escaping.
- Generated statements remain read-only and pass the SQL validator.
- No endpoint gained business logic or direct LLM/database access.

## Performance

- Ordinary conditional rates remain a single scan.
- Multi-metric trends, multi-period UNION branches and multi-entity UNION
  branches compute several aggregates in each scan.
- A composite rate added to a two-period comparison currently uses scalar
  subqueries. This is correct and bounded but may scan the scoped view more
  than once. Measure it against the live view before optimizing; a derived-table
  per-period implementation is the likely next step if it is slow.

## Remaining boundaries

- Predicate groups currently support conjunction (`AND`). General nested `OR`
  and grouped `NOT` expressions need an explicit predicate-tree model; they
  must not be inferred by concatenating SQL text.
- Ambiguous or unknown deployment values still require clarification. That is
  intentional: broad coverage must not become confident guessing.
- Multiple specialized repeat-behavior metrics in one question remain an
  explicit unsupported builder shape.
- Grouped period comparisons of complex ratios still need a dedicated result
  contract and presentation path.
- Live SQL Server execution and the final UI smoke test are pending until the
  other development computer is available on Monday.

## Assumptions

- “A içinde B oranı” defines A as denominator scope and B as the measured
  numerator condition.
- Multiple independently grounded conditions on the measured side are joined
  with `AND`.
- “2024 yılı içinde” is temporal outer scope, not a cohort denominator; a side
  that cannot ground as a cohort is not composed.

## Follow-up priorities

1. Run the new suite and representative value-grounded questions against SQL
   Server on Monday.
2. Profile composite multi-period rates on realistic row counts.
3. Add a typed boolean predicate tree (`AND`/`OR`/`NOT`) after collecting real
   user phrasings and expected semantics.
4. Add grouped complex-rate period comparison if mentor questions demonstrate
   that shape is high frequency.
