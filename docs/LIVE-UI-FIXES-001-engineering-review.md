# LIVE-UI-FIXES-001 Engineering Review

## Review

- API routes remain thin. The sensitive-data decision is made in `app.services.result_safety` and enforced through the existing workflow/result DTO boundary.
- No LLM calls or prompt hardcoding were added.
- No database access was added outside repositories.
- The single-branch behavior is presentation-only and derived from the returned result shape, so it does not hardcode today's database cardinality into planning.
- Inline reset clears the session before resolving the rest of the question, preserving same-session testing while giving users an explicit way to stop memory inheritance.
- Full independent comparison questions no longer inherit stale filters solely because they contain `karşılaştır` plus a date.

## Test Coverage

Focused tests were added or updated for:

- Patient identifier list blocking.
- Aggregate patient-count allowance.
- Deterministic sensitive-data report generation.
- Inline context reset inside the same session.
- Single-branch result wording.
- Branch-specific insight wording for one-row `SubeAdi` results.
- Stale status-filter isolation before a full branch comparison.

Verified with:

`..\.venv\Scripts\python.exe -m pytest -q tests -p no:cacheprovider` from `backend`

Result: `1835 passed, 1 skipped`.

## Residual Risk

The larger live-test issues around exact date-range comparison, month-to-month department diffs, chart type selection, and meta-conversation summaries are still open and should be handled as separate changes because they touch planning, SQL generation, visualization routing, and chat-memory answerability.
