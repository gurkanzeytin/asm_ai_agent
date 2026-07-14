# CHART-001 Implementation Plan

## Goal

Improve the SQL result chart visuals in the dark ASM AI Agent interface without changing data flow, API contracts, chart switching behavior, table behavior, or responsive layout.

## Scope

- Keep the existing Recharts implementation.
- Keep `SqlChartPanel` inputs as `columns` and `rows`.
- Centralize reusable chart colors and Turkish number formatters in `frontend/src/components/asm/chart-theme.ts`.
- Update only chart presentation, tooltip rendering, axes, grid, and immediate controls.
- Preserve the SQL result table, statistics, search, copy, CSV export, and backend integration.

## Validation

- Run targeted ESLint for touched files.
- Run the frontend production build.
- Confirm the full-project lint limitation separately if existing unrelated lint output prevents completion.
