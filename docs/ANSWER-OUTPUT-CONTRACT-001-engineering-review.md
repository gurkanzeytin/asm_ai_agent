# ANSWER-OUTPUT-CONTRACT-001 Engineering Review

## Review Notes

- The change is scoped to presentation policy and report rendering.
- API routes remain thin; no route-level business logic was added.
- LLM prompt behavior was changed only under `/prompts`.
- SQL generation, validation, and repository access were not changed.

## Risk

The main behavior change is that analytical answers are shorter by default.
Detailed report sections are still available when explicitly requested.

## Verification

- `python -m pytest tests/test_output_policy.py tests/test_qa002_optimizations.py tests/test_presentation_labels.py tests/test_report_templates.py tests/test_status_semantics.py`
- `npm test -- chat-ui-polish.test.tsx`
- `npm run build`
