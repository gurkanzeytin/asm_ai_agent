# ANSWER-UX-REFINEMENT-001 Walkthrough

## Empty Results

When a query returns no rows, the renderer now inspects the question for scope signals such as date range, appointment status, department, branch, doctor, service, and source. The answer names the likely scope and gives targeted next steps, for example widening the date range or temporarily removing the appointment-status filter.

## Context Notice

The backend already returns `context_applied`. The frontend now preserves that metadata in `ReportResponse` and prefixes visible answer text with a short note when prior context was used. SQL-only and table-only modes remain unchanged.

## Language Cleanup

Static report titles and fallback messages now use neutral labels such as `Yanıt`, `Sonuçlar`, and `Grafik`. Prompt instructions describe the desired natural style without repeating old mechanical phrases as examples.
