# BUG-002 Walkthrough

## Root Cause

The incorrect value originated in SQL generation. For appointment aggregation, the prompt context sometimes included fact tables such as `randevular` but omitted the descriptive entity table `doktorlar`, so the model returned `doktor_id`. In one case, the model selected both `doktor_id` and `ad_soyad`, which caused the deterministic report template to show the ID.

## What Changed

`SchemaRetriever` now boosts directly detected entity tables and bridge tables that connect detected entities. This keeps tables such as `doktorlar`, `bolumler`, `randevular`, and `receteler` together in aggregation prompts.

`QueryAnalyzer` now normalizes "busy department" phrasing to appointment-count intent, so department aggregation retrieves appointment context.

`sql_generation.md` now explicitly instructs aggregation SQL to select descriptive names and aggregate values, not user-facing IDs.

`SQLService` now removes redundant ID projections from aggregation SELECT lists when a descriptive column is already present. GROUP BY and JOIN clauses remain intact, so the SQL still groups correctly while returning user-facing columns only.

## Validation Cases

- Most appointments -> `ad_soyad`, appointment count
- Least appointments -> `ad_soyad`, appointment count
- Most prescriptions -> `ad_soyad`, prescription count
- Most patients -> `ad_soyad`, patient count
- Busiest department -> `bolum_adi`, count
