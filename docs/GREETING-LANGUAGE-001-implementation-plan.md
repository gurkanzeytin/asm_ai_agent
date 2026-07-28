# GREETING-LANGUAGE-001 Implementation Plan

## Goal

Ensure greeting responses are Turkish in the UI and never fall back to the previous English copy.

## Scope

- Update the static greeting resource used for greeting intent responses.
- Update the resilient fallback in `GenerateChatResponseNode`.
- Add focused backend regression coverage for the default resource and fallback text.

## Validation

- Run the focused backend intent service tests.
- Verify the UI by sending `Merhaba` from the browser and checking the assistant response.
