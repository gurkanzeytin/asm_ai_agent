# LIVE-UI-RELATIONSHIP-FIX-003 Implementation Plan

## Scope

Live UI regression testing exposed failures in appointment analytics questions that require relationships rather than simple counts:

- month-range wording such as `Nisan-Haziran doneminde`
- two-month increase/decrease comparisons
- repeat-patient and cross-branch patient behavior
- same-day multi-service behavior
- short follow-ups such as `Azalanlari goster`
- aggregate ranking requests phrased as `ilk 10 doktoru listele`

## Plan

1. Keep API routes untouched; fix deterministic NLU/planning/context/SQL layers.
2. Extend date parsing so month ranges with scope words resolve to one contiguous span.
3. Route catalog relationship metrics to `repeat_behavior` plans and render them through CTE/HAVING SQL.
4. Treat relation-condition columns as grouping dimensions only when the user explicitly asks for a breakdown.
5. Preserve period-comparison context for short direction follow-ups.
6. Add focused regression coverage for analyzer, deterministic SQL, and live-style memory chains.
7. Re-run live browser tests through the UI after local verification.
