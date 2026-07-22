# Frontend Chat Composer 006 - Engineering Review

## Decisions

- Assistant and user messages intentionally use different surfaces: only user-authored content is represented as a chat bubble.
- The send control has fixed dimensions and absolute positioning so textarea growth cannot shift or resize it.
- Textarea right padding prevents typed content from running beneath the control.
- Animation is limited to transform properties and does not change layout dimensions.

## Accessibility

- Send and stop controls retain explicit accessible labels.
- Disabled send state remains visually distinct and non-interactive.
- Keyboard Enter and Shift+Enter behavior remains available even though the visible shortcut legend was removed.

## Tests

- Assistant and thinking surfaces do not carry the `glass` class.
- Send control remains inside the composer at a fixed size and position.
- Shortcut text is absent.
- Brand and conversation headings use the intended type scale.
