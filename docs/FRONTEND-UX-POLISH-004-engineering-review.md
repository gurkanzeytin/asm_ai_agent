# Frontend UX Polish 004 - Engineering Review

## Decisions

- Disclosure state remains local to each message, preventing unrelated messages from rerendering their SQL panels.
- The SQL result remains lazy-loaded and is mounted only when technical details are opened.
- Splash lifecycle is event-driven rather than synchronized with a separate timeout. This removes timing drift between the progress bar and overlay.
- Notification content omits the model identifier to keep the user-facing status concise and consistent with the details-panel simplification.

## Accessibility

- The technical-details trigger exposes its open state through `aria-expanded`.
- The chevron rotates without replacing the readable button label.
- Toasts remain dismissible with a close control.

## Risks

- Splash completion depends on the Motion animation lifecycle. Motion still resolves reduced-motion animations and invokes completion, avoiding a permanently blocking overlay.
- Visual browser automation requires an attached in-app browser tab; automated component and serving checks are the fallback when none is available.
