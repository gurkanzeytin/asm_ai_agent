# Frontend Details Alignment 007 - Engineering Review

## Decisions

- SQL copy is a separate action from disclosure to avoid accidental section toggles.
- Clipboard failure uses the existing shared error notification.
- Directional arrows communicate the side panel's movement and match the sidebar interaction model.
- Checkbox alignment is corrected at the layout source rather than with per-element transforms.
- Only the first Markdown heading loses its top margin; later headings preserve document rhythm.

## Tests

- Clipboard receives the exact SQL string after one click.
- Details close invokes the panel callback.
- Chat-header clear action is absent.
- Header and row selection cells share padding and the header control is left-aligned.
- The first assistant heading carries the zero-first-margin rule.

## Residual Risk

Clipboard access still depends on browser permissions. A denied permission produces the existing Turkish copy-failure notification.
