# Frontend Timing UI 005 - Walkthrough

## Thinking State

The avatar and shiny thinking surface now use the same fixed 40px height. Their parent uses center alignment, removing the vertical offset visible when the text surface was taller than the logo frame.

## Chart Labels

The chart type labels are now `Çubuk`, `Çizgi`, and `Pasta` in the shared Turkish locale.

## Response Timing

The frontend previously preferred `metadata.latency_ms`, which represents only report generation. It now prefers the backend's `timing.total_ms` for response time. The SQL result header no longer displays that workflow total and instead uses `timing.execute_sql_ms`.

## Notifications

The compact notification design is retained, but its viewport position is now top-right for higher visibility.
