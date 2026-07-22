# Frontend UI Polish 003 - Implementation Plan

## Scope

- Restyle the response-ready notification with the existing dark, cyan, and primary palette.
- Replace the thinking indicator with a continuously looping shiny text treatment.
- Correct SQL result table alignment and translate its user-facing interface to Turkish.
- Make bar, line, and pie chart transformations consistent and predictable.
- Keep response duration in the details panel while removing model and token rows.
- Animate newly inserted conversations from the left.

## Exclusions

- Mobile-specific layout work.
- Login or authentication screens.
- A functional light/dark theme system. The non-functional header control remains removed.

## Verification

- Unit tests for chart transformation, summary statistics, details-panel content, chat flow, and animated text.
- TypeScript compilation, ESLint, production build, and local HTTP smoke test.
- Desktop browser review when the in-app browser runtime is available.
