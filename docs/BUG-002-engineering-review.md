# BUG-002 Engineering Review

## Validation

Targeted regression tests passed:

```text
38 passed
```

Manual end-to-end probes against the demo database showed the five reported aggregation questions now return descriptive columns:

- `ad_soyad`, `randevu_sayisi`
- `ad_soyad`, `recete_sayisi`
- `ad_soyad`, `hasta_sayisi`
- `bolum_adi`, count

## Risk Review

- API response shape is unchanged.
- Frontend code is unchanged.
- Report rendering is unchanged.
- SQL validation still runs after SQL normalization.
- The ID-removal guard only applies to aggregate SELECTs that already include a descriptive projection, so ordinary detail/list queries are not affected.

## Regression Coverage

Added `backend/tests/test_aggregation_sql_generation.py` covering:

- Retrieval includes descriptive entity tables for all five reported questions.
- Aggregation SQL projections remove IDs when descriptive fields exist.
- Generated SQL remains validator-safe.
