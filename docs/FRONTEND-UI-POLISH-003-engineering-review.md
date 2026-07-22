# Frontend UI Polish 003 - Engineering Review

## Decisions

- Chart and summary transformations live in pure data modules so they are independently testable and do not interfere with React Fast Refresh.
- Invalid numeric values are omitted instead of silently becoming zero. This avoids fabricated data points.
- Category aggregation happens before chart limits are applied, so duplicate labels do not consume the visual budget.
- The requested shiny effect was implemented with the existing Motion-based text component and CSS variables; no third-party component code was copied.

## Risks And Limits

- Date ordering relies on JavaScript's `Date.parse`; ambiguous locale-specific date strings preserve source order when they cannot all be parsed.
- Pie charts intentionally exclude zero and negative values because those do not represent meaningful pie proportions.
- Mobile behavior and login flows were explicitly excluded.
- The in-app browser runtime was unavailable during implementation. Automated checks and an HTTP smoke test cover code and serving behavior; visual browser verification should be repeated when that runtime is available.

## Test Coverage

- Duplicate-category aggregation and invalid-value filtering.
- Numeric line-axis sorting without null-to-zero coercion.
- Pie overflow grouping and total preservation.
- Numeric-string summary statistics.
- Details-panel model/token removal.
