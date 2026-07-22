import { formatNumberTr, formatPercentTr, formatValueTr, isRateAlias } from "./presentation";
import type { ColumnFormat } from "./presentation";

export interface FormattedSqlCell {
  display: string;
  raw: string;
  kind: "null" | "number" | "date" | "text";
}

const isoDatePattern = /^\d{4}-\d{2}-\d{2}(?:[T\s].*)?$/;
const numericPattern = /^-?\d+(?:\.\d+)?$/;

function formatDateValue(value: string): string | null {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const includesTime = /[T\s]\d{2}:\d{2}/.test(value);
  return new Intl.DateTimeFormat("tr-TR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    ...(includesTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(date);
}

/**
 * Formats a raw SQL result cell for display. `format`/`unit` come from the
 * column's presentation metadata (backend `column_metadata` or the frontend
 * fallback resolver in `presentation.ts`) when available; without them this
 * falls back to the same column-name heuristics used before. The raw value
 * is never mutated — only `display` changes.
 */
export function formatSqlCell(
  column: string,
  value: string | number | null,
  format?: ColumnFormat,
  unit?: string | null,
): FormattedSqlCell {
  if (value == null || (typeof value === "string" && value.trim() === "")) {
    return { display: "—", raw: value == null ? "NULL" : value, kind: "null" };
  }

  const raw = String(value);
  const numeric = typeof value === "number" ? value : Number(value);
  const looksNumeric =
    typeof value === "number" || (numericPattern.test(value.trim()) && Number.isFinite(numeric));

  if (looksNumeric) {
    if (format === "percentage") {
      return { display: formatPercentTr(numeric), raw, kind: "number" };
    }
    if (format === "duration") {
      return { display: `${formatNumberTr(numeric)} ${unit ?? "dakika"}`, raw, kind: "number" };
    }
    if (format === "integer" || format === "decimal") {
      const display = formatNumberTr(numeric);
      return { display: unit ? `${display} ${unit}` : display, raw, kind: "number" };
    }
    if (!format) {
      return {
        display: isRateAlias(column) ? formatValueTr(column, numeric) : formatNumberTr(numeric),
        raw,
        kind: "number",
      };
    }
    if (format === "text") {
      // e.g. id-like columns: never thousand-separate an identifier.
      return { display: raw, raw, kind: "number" };
    }
  }

  if (typeof value === "string" && (format === "date" || format === "datetime")) {
    const formatted = formatDateValue(value);
    if (formatted) return { display: formatted, raw, kind: "date" };
  }

  if (typeof value === "string" && !format && isoDatePattern.test(value.trim())) {
    const formatted = formatDateValue(value);
    if (formatted) return { display: formatted, raw, kind: "date" };
  }

  return { display: typeof value === "string" ? value : raw, raw, kind: "text" };
}
