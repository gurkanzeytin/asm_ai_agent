# FRONTEND-ANIMATED-TEXT-001 Implementation Plan

## Goal

Use the 21st.dev Build UI Labs animated text behavior for assistant answers and remove non-functional light/dark theme controls from the frontend.

## Scope

- Add a local `useAnimatedText` UI hook compatible with the referenced component usage.
- Render assistant message content through animated text while preserving Markdown formatting.
- Remove the theme toggle from the chat header.
- Remove the theme selector from the settings dialog.

## Verification

- Run production build.
- Run ESLint against the touched frontend files.
