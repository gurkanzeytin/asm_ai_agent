# ANSWER-UX-REFINEMENT-001 Implementation Plan

## Scope

- Make empty-result answers more helpful by deriving guidance from the user's question scope.
- Surface prior-turn context usage in the assistant answer when the backend marks context as applied.
- Remove old mechanical answer phrasing from production prompts, deterministic report titles, and static fallback reports.

## Approach

- Keep the empty-result guidance deterministic in `TemplateReportRenderer`; do not call the LLM for this path.
- Reuse the backend's existing `context_applied` response field in the frontend instead of adding a new API contract.
- Replace report-service fallback titles and data/visualization-only static text with shorter natural Turkish wording.
- Update focused unit tests for template rendering, prompt wording, fallback titles, and frontend answer content.
