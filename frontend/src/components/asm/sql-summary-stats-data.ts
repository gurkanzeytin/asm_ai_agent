export type SqlStatsRow = Record<string, string | number | null>;

export interface ColStat {
  column: string;
  type: "numeric" | "text" | "mixed" | "empty";
  nulls: number;
  unique: number;
  min?: number;
  max?: number;
  avg?: number;
  sum?: number;
}

export function computeStats(columns: string[], rows: SqlStatsRow[]): ColStat[] {
  return columns.map((column) => {
    const values = rows.map((row) => row[column]);
    const nonNull = values.filter((value) => value != null);
    const nulls = values.length - nonNull.length;
    const unique = new Set(nonNull.map((value) => String(value))).size;
    const numbers = nonNull.flatMap((value) => {
      if (String(value).trim() === "") return [];
      const numeric = Number(value);
      return Number.isFinite(numeric) ? [numeric] : [];
    });
    const allNumeric = nonNull.length > 0 && numbers.length === nonNull.length;

    if (nonNull.length === 0) return { column, type: "empty", nulls, unique };
    if (allNumeric) {
      const sum = numbers.reduce((total, value) => total + value, 0);
      return {
        column,
        type: "numeric",
        nulls,
        unique,
        min: Math.min(...numbers),
        max: Math.max(...numbers),
        avg: sum / numbers.length,
        sum,
      };
    }
    if (numbers.length > 0) return { column, type: "mixed", nulls, unique };
    return { column, type: "text", nulls, unique };
  });
}
