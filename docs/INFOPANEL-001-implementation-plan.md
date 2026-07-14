# INFOPANEL-001 Implementation Plan

## Goal

Inspect the right-side InfoPanel retrieved-documents section and remove it if it is static mock data rather than backend-connected data.

## Findings

- `InfoPanel` receives only panel state, close handler, response time, and thinking state.
- No retrieved-document list is passed into `InfoPanel`.
- The route API response mapping does not populate retrieved documents.
- The displayed document filenames, scores, and badge are hard-coded in the component.

## Plan

- Remove the retrieved-documents expandable section from `InfoPanel`.
- Remove the static document rows, hard-coded filenames, hard-coded relevance scores, and document icon import.
- Remove the Turkish locale key used only by that section.
- Keep SQL query, tool calls, agent status, response time, and process summary unchanged.
- Validate TypeScript, targeted lint, and production build.
