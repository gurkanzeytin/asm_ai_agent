# Conversational Filter SQL Live Fix — Walkthrough

## Confirmed trace

The second turn loaded and retained the successful first-turn plan: January 2026, `DoktorId`, `appointment_count`, and descending order. `RetrieveContextNode` added only `RandevuDurumu = 'Gerçekleşti'`. The defect was therefore not the memory handoff.

Before the repair, `DeterministicSQLBuilder._where` copied `extra_filters` directly into SQL. It produced a non-Unicode SQL Server literal:

```sql
AND RandevuDurumu = 'Gerçekleşti'
```

The compliance validator checked only that the column and value text appeared, so it accepted the unsafe rendering. The canonical renderer now emits:

```sql
AND RandevuDurumu = N'Gerçekleşti'
```

The same path handles grounded filters and the supported view columns, escapes embedded quotes, and de-duplicates filters represented in more than one plan field.

## Empty live result

The live January 2026 data contains `Beklemede` and `Giriş Yapılmış`, but no `Gerçekleşti` rows. After the SQL correction, execution therefore returns zero rows. The repository represents that result with no column metadata. `ResultValidator.check_shape` previously interpreted the absent metadata as missing planned aliases and forced `SAFE_ERROR`.

An empty result now has a valid `empty` shape. Non-empty results still undergo the exact expected-alias checks. The existing report flow consequently returns `NO_RESULT_GUIDANCE` and “Sonuç Bulunamadı” instead of a false schema error.

## Result

The live two-turn request uses the same session, produces deterministic compliant SQL, executes it, and completes through the normal empty-result outcome. No memory model, planner, database, endpoint, or frontend architecture was added or changed.

