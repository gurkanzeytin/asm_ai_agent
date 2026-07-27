# LIVE-MEMORY-FOLLOWUP-002 Implementation Plan

## Scope

Live UI/API fuzzing exposed follow-up memory issues around output actions, period comparisons, dimension replacement, same-scope references, and table reuse. The fixes stay in the context/planning/UI presentation layers; API routes and LLM provider boundaries are unchanged.

## Plan

1. Extend referential follow-up detection for bare Turkish continuation phrases:
   - `bunu`
   - `bu kapsam`
   - `bu sonuc`
   - `ayni kapsam`
   - `ayni tablo`

2. Preserve analytical shape across follow-ups:
   - Keep time buckets when adding metrics to a trend.
   - Replace dimensions on `yerine` instead of adding stale dimensions.
   - Treat `ayni tablo` as reuse of the previous table plan, not a raw row-list request.
   - Drop fixed period-comparison shape when a later turn asks for a new grouping dimension.

3. Keep date scope authoritative:
   - Resolve inherited date text into the final `QueryPlan`.
   - Clear stale period filters when a later non-period follow-up uses the inherited single-date scope.
   - Avoid applying this date correction to SQL output-action turns that should replay the previous SQL plan unchanged.

4. Improve output presentation:
   - Data-only mode still passes through result analysis so hidden doctor IDs can be enriched with visible doctor names.
   - Frontend hidden-column state honors backend `hidden` metadata on later table rerenders.

5. Add focused regression tests for each live failure.

