# AI-INTELLIGENCE-009 Engineering Review

## Design Review

The deterministic builder is integrated behind `SQLService` instead of creating
a parallel execution pipeline. This preserves endpoint behavior, validation,
execution, analytics, and report generation while preventing supported
`QueryPlan` shapes from reaching the LLM.

Metric formulas come from `metric_catalog.json`; metrics marked
`requires_verified_mapping` are not converted into SQL. Unsupported or
unverified plans fall back to the existing LLM generation path.

## Safety Review

- SQL remains read-only and goes through the existing SQL validator.
- Deterministic SQL also runs `PlanComplianceValidator`.
- Compliance checks cover fixed aliases, grouped dimensions, cohort filters,
  current/baseline periods, ratio numerator/denominator, `NULLIF`, raw detail
  projection, and accidental anomaly `HAVING` filtering.
- Deterministic failures raise explicit builder errors and never enter the LLM
  repair loop.

## Test Review

Added `backend/tests/test_deterministic_sql_pipeline.py` covering:

- Metric SQL mapping
- Deterministic builder selection
- LLM fallback selection
- Cohort, period, anomaly, and variance SQL generation
- Result alias contracts
- Decimal and null normalization
- Typed result validation
- Result reasoning
- Adaptive retry widening
- Deterministic SQL compliance
- Raw detail prevention
- Five acceptance questions

## Remaining Limits

The builder is intentionally conservative. Complex unsupported plans still use
the existing LLM fallback. Future work should add explicit date-pair extraction
for natural-language periods such as calendar month boundaries when those dates
are present in `QueryPlan`.
