# LIVE-MEMORY-FOLLOWUP-002 Walkthrough

## Live Test Coverage

The following 2025-only session shapes were exercised:

- Q1 2025 monthly trend, then add completed rate, add no-show rate, show SQL, and split the same scope by gender.
- May 2025 department counts, then compare with June 2025, show percentage delta, show SQL, and split the same scope by branch.
- February 2025 top doctors as a data table, replace doctor with service, then reuse the same table for no-show appointments.
- January 2025 status distribution, then split by gender, add no-show rate, rank branches, and show SQL.

## Fixed Behaviors

- `2025 ilk ceyrek` now resolves to January 1, 2025 through March 31, 2025 before bare-year fallback.
- Metric-add follow-ups keep the previous trend bucket instead of collapsing to a scalar.
- `Haziran 2025 ile kiyasla` replays the previous May 2025 analysis as a period comparison without AND-ing both months.
- `Bu sonucun SQL sorgusunu goster` preserves the previous comparison SQL plan.
- `Simdi ayni kapsami kadin erkek olarak kir` keeps Q1 2025 scope and retained metrics while applying gender grouping.
- `Sadece gelmeyen randevular icin ayni tabloyu goster` keeps the previous February 2025 service table shape and adds the no-show filter.
- `Sonucu doktor yerine hizmet bazinda grupla` replaces the doctor dimension with service and no longer treats `Sonucu` as a doctor value.
- Data-only doctor tables enrich `DoktorId` into `DoktorAdi`, with `DoktorId` hidden in metadata.
- The frontend now hides backend-hidden columns even when a later result reuses the same column key.

## Validation

- Backend targeted and regression suite:
  - `85 passed`
- Frontend table suite:
  - `16 passed`
- Live services:
  - Backend health endpoint returned healthy.
  - Frontend returned HTTP 200 on `http://127.0.0.1:5173/`.

