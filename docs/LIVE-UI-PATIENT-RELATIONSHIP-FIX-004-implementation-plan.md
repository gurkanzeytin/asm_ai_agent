# LIVE UI Patient Relationship Fix 004 - Implementation Plan

## Scope

Live UI testing found that patient relationship questions could fall back to plain appointment counts:

- Patient first-to-last appointment span.
- Patients present in both 2023 and 2024.
- Follow-up breakdown of the same overlap cohort by branch.

## Plan

1. Add catalog-backed relationship metrics for patient appointment span and multi-period patient overlap.
2. Resolve those intents in the planner before generic count/date-comparison fallback.
3. Render read-only deterministic SQL CTEs for both relationships.
4. Preserve conversational memory for follow-up ranking and branch breakdown questions.
5. Add regression tests covering planner, SQL generation, compliance, and live-style memory.
6. Rerun the affected live UI session using 2023/2024 data only.

