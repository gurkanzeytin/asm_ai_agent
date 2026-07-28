# EXPERT-SQL-UI-REGRESSIONS-001 Walkthrough

## Behavior

The agent now treats "azalan sirala" as descending sort, not as a percentage-change analysis. "En az 1000 randevusu olan doktorlari ... sirala" renders a HAVING threshold and sorts the remaining groups by appointment count descending.

Monthly date-column variants such as "olusturulma ayina gore" and "protokol acilis ayina gore" render `DATEFROMPARTS(YEAR(<date_column>), MONTH(<date_column>), 1)` with the requested date column.

Follow-up thresholds are metric-bound. If a conversation filters appointment-count groups with "30000 den az" and then asks to sort by no-show rate, the SQL selects no-show rate but keeps `HAVING COUNT(*) < 30000`.

Short follow-ups such as "sadece Radyoloji'yi goster" are grounded against the retained report dimension before SQL generation. Two-department comparison wording with "ve" before the department cue now grounds both sides all-or-nothing.

## Verification

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_expert_sql_ui_regressions.py
```
