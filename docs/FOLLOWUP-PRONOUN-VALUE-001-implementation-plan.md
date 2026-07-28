# FOLLOWUP-PRONOUN-VALUE-001 Implementation Plan

## Goal

Prevent plural context pronouns such as `Bunlari` / `Bunları` from being
misread as grounded value-filter candidates before a dimension cue.

## Scope

- Extend the value-candidate stopset in `backend/app/planning/value_resolver.py`.
- Cover the pure phrase extractor.
- Cover the live-style session chain that mirrors the UI: base 2025 query,
  status filter follow-up, then department ranking follow-up.

## Non-Goals

- No API route logic changes.
- No direct database access changes.
- No prompt changes.
