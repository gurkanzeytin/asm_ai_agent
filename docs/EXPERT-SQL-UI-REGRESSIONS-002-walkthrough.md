# EXPERT-SQL-UI-REGRESSIONS-002 Walkthrough

## Behavior

`2024 Mayis ... 2000 den az` now keeps May 2024 as the only date filter and renders `HAVING COUNT(*) < 2000`.

`protokol acilis ayina ve subeye gore` now returns `period_start`, `SubeAdi`, and `protocol_created_count`, grouped by both the month bucket and branch.

`2024 Ocak Haziran arasi ... olusturulma ayina gore` now resolves January-June 2024 and buckets by `CreatedDate`.

`randevu tipine gore tekil hasta sayisi` now selects only `RandevuTipiAdi` and `COUNT(DISTINCT HastaId)`, with no `HastaId` GROUP BY.

`ayni filtreyle 2024 yilini goster` keeps the retained analytical metric, dimension, and grounded filter while replacing the year.

## Verification

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_expert_sql_ui_regressions.py
```
