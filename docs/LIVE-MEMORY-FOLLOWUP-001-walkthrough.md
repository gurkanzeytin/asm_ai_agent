# LIVE-MEMORY-FOLLOWUP-001 Walkthrough

## User Flow

1. The user asks for a 2025 January appointment count.
2. The user refines the same session into a gender breakdown.
3. The user filters to completed appointments.
4. The user switches to all appointment statuses.
5. The user asks: `Bunu 2025 yili boyunca aylik trend olarak goster`.

## Expected Behavior

- The final question is detected as a follow-up because `bunu` refers to the
  previous analytical result.
- The date range changes to the full 2025 calendar year.
- The output becomes a monthly time series.
- The previous status distribution dimension is cleared unless the user asks to
  keep status as a grouped series.
- API diagnostics match the executed plan instead of the pre-planning raw signal
  fallback.

## Verification

Targeted regression coverage was added in
`backend/tests/test_live_memory_followups.py`.
