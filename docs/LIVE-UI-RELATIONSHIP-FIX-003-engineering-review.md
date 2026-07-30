# LIVE-UI-RELATIONSHIP-FIX-003 Engineering Review

## Review

The fix stays within Clean Architecture boundaries:

- no route-level business logic was added
- no direct database access was added
- no endpoint-level LLM calls were introduced
- SQL generation remains deterministic and read-only
- prompts were not hardcoded in Python

## Risks

Patient-level detail remains intentionally constrained. Relationship questions return counts and safe aggregate breakdowns rather than raw patient identity rows.

`GenelRandevuKaynakAdi` is still a shared/dirty semantic field for doctor/source style questions. This fix avoids raw-row leakage but does not redefine that database semantic.

## Test Coverage

Regression coverage now includes:

- scoped month ranges with `doneminde` and `kapsaminda`
- repeat-patient HAVING CTEs
- cross-branch repeat-patient CTEs
- same-day multi-service CTEs
- grouped period comparison with increase/decrease direction
- short memory follow-ups preserving period context
- aggregate handling for `ilk 10 doktoru listele`
