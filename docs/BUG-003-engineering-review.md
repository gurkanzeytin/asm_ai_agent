# BUG-003 Engineering Review

## Root Causes

1. The context extractor recognized only `YYYY yılında`; possessive, case, bare-year, and
   relative variants did not satisfy the date-only predicate.
2. A date fragment without a matching rule reached `AnswerabilityGuard` as raw text, where it
   naturally had no domain entity and was rejected before conversational meaning could help.
3. Analytics profiled a scalar aggregate cell as a one-value distribution, so generic
   count/total/average/median/min/max calculations described the result set rather than the
   business population.
4. The frontend rendered scalar keys from `analytics.metrics` without an authoritative KPI
   visibility contract.
5. Live bootstrap also exposed an eager semantic-package import cycle. The semantic engine
   export is now lazy and the context resolver reuses its own canonical fold directly.

## Answerability Before/After

- Before: input was the raw elliptical text; no appointment keyword meant `no_domain_signal`.
- After: input is the resolved question plus trusted typed signals. Metadata reports
  `answerability_input_source=resolved_context`, with signals such as
  `inherited_entity:Appointment`,
  `inherited_metric:appointment_duration_average`, and `explicit_date:2024`.

Complete unrelated questions do not trigger the date-only gate. `Faturalar?`, weather, and a
complete new patient-age analysis do not inherit the old appointment-duration metric.
Clarification and failed workflows do not overwrite the valid memory anchor.

## Result Semantics

Plan-aware shapes are `raw_record_rows`, `grouped_rows`, `scalar_aggregate`,
`multi_metric_scalar_aggregate`, `time_series`, `categorical_grouped_result`, and `empty`.
`technical_row_count` always describes the SQL result. `business_record_count` is populated
only when returned rows are business records. `displayable_kpis` is derived from planned
metrics, generated aliases, catalog labels, formats, and units.

Scalar aggregates bypass generic distribution statistics. Their metric summaries carry
`value`, `format`, and `unit`; total/average/min/max summary fields remain empty. This also
prevents downstream insight rules from treating a valid direct aggregate as “no data.”

## Validation

- New targeted backend tests: 18.
- Focused backend regression run: 294 passed.
- Full backend suite: 1,296 passed, 1 skipped.
- Full frontend suite: 92 passed across 13 files.
- Frontend production build: passed.
- Application-container bootstrap: passed after lazy semantic-engine initialization.

The first full backend run found one duplicate bare-year comparison regression (`2022 ile
2023`). The obsolete second bare-year detector was removed; the focused comparison suite and
the full suite then passed.

## Live Verification

The exact same-session workflow was attempted against the configured live services. The
application started, but Turn 1 could not connect to SQL Server through ODBC Driver 18 because
the configured encrypted connection could not establish SSL credentials/reach the server.
The workflow returned `SAFE_ERROR`, correctly did not write memory, and the next year-only
turns correctly requested clarification rather than inheriting a failed turn.

The independent live new-session case passed: `2024 yılının?` returned
`ASK_CLARIFICATION`, generated no SQL, and used the year-specific Turkish clarification.
The successful same-session path, SQL boundaries, memory replacement, and KPI payload are
covered deterministically by automated tests but could not be exercised against live data
until the SQL Server connection is available.

## Remaining Limitations

- Relative phrases are calendar-based; arbitrary natural-language fiscal-year expressions
  are not inferred.
- `bir önceki yıl` uses the current explicit-year anchor when present; otherwise it resolves
  to the previous calendar year.
- Older API payloads without `displayable_kpis` use a conservative raw-column fallback, which
  cannot provide all catalog metadata available from the new backend contract.
- Live value verification remains pending restoration of the configured SQL Server TLS/network
  connection.

