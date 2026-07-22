# Frontend UI Polish 003 - Walkthrough

## Response States

The response-ready Sonner toast now uses the application's primary/cyan accent, a left status rail, restrained glow, and dark glass surface. While a response is pending, `Düşünüyor...` is rendered through the shared `TextShimmer` component with a continuous background-position animation.

## SQL Results

The toolbar is split into a title/search row and a consistent action row. The selection checkbox and row number now share one fixed meta column; the first data column starts after that column, removing the previous sticky overlap and header/body mismatch.

All user-facing table, filter, pagination, chart, summary, copy, and export messages are sourced from the Turkish locale. Technical format names such as CSV and JSON remain unchanged.

## Charts

- Bar charts aggregate duplicate categories, rank by magnitude, and cap the visible set.
- Line charts discard missing or invalid values, preserve valid points, sort numeric/date labels, and require two points.
- Pie charts accept positive values only, sort slices, and combine small overflow categories as `Diğer`.
- Numeric strings are handled consistently by charts and summary statistics.

## Conversation And Details

New conversation rows enter with a short left-to-right motion while existing rows do not replay on initial mount. The details panel keeps response duration, agent status, and generated SQL; model and token rows were removed.
