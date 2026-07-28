# FOLLOWUP-PRONOUN-VALUE-001 Engineering Review

## Review

- Business logic remains outside API routes.
- The change is isolated to the planning value-resolution layer.
- The fix does not loosen grounded-value matching; it only prevents known
  demonstrative pronouns from becoming candidate values.
- Existing explicit value filters are unaffected because real proper nouns and
  supported status words still resolve through their existing paths.

## Verification

- Pure value extraction regression test added.
- Live-style session regression test added.
- Existing session and streaming contract tests were run as part of the UI
  investigation.
