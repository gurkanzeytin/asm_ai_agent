# Frontend Productivity 008 - Walkthrough

## Conversation Flow

Automatic scrolling now follows new content only while the user is already near the bottom. Reading older messages preserves the viewport and reveals `Son yanıta git`. Failed and stopped messages retain their original prompt so retry is deterministic. Errors also expose `Soruyu düzenle`; successful responses expose regenerate and shorten actions.

Backend `ASK_CLARIFICATION`, `NO_RESULT_GUIDANCE`, and visualization metadata produce small follow-up controls. Selecting one sends it as the next turn in the same backend session.

## SQL Results

SQL values are formatted for display without mutating export or filtering data. Numeric strings and numbers use Turkish separators, recognized rate columns use percentage notation, ISO dates use Turkish dates, and empty values use a restrained dash. Hover titles preserve changed raw values.

The density icon cycles through `Sıkı`, `Normal`, and `Rahat`. Virtualized row estimates change with the selected density so large-result scrolling remains stable.

## Charts

Backend `BAR_CHART`, `LINE_CHART`, and `PIE_CHART` recommendations open the chart panel with the corresponding initial type. Bar and pie categories can be applied to the SQL table as equality filters. Keyboard users select a chart point with arrow keys and apply it with Enter or Space.
