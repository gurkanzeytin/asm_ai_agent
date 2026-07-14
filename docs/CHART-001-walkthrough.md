# CHART-001 Walkthrough

## Chart Library

The frontend chart uses Recharts.

## Changes

- Bar charts now use a reusable blue vertical SVG gradient with rounded top corners, capped bar width, subtle glow, and ease-out animation.
- Line charts now use a bright blue monotone line with small markers, active hover markers, and a subtle blue area fill.
- Pie charts now use a coordinated blue, cyan, and teal palette with slice separation and a compact legend.
- Axes use muted slate labels, low-opacity horizontal dashed grid lines, and no heavy axis lines.
- Tooltips use a dark navy panel, subtle blue border, soft shadow, Turkish number formatting, and Turkish month labels for `YYYY-MM` values.
- The chart type buttons now read as a compact segmented control with visible selected state and focus styles.
- Bar value labels render only for small datasets to avoid overcrowding.

## Preserved Behavior

- Existing chart type switching remains unchanged.
- X and Y selectors still use the current column lists.
- Data is still derived dynamically from backend SQL result rows.
- Table, statistics, search, copy, CSV export, and responsive container behavior are unchanged.
