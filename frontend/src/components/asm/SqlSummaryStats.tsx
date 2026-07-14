import { useMemo } from "react";
import { tr } from "@/locales/tr";
type Row = Record<string, string | number | null>;
interface Props {
  columns: string[];
  rows: Row[];
}
interface ColStat {
  column: string;
  type: "numeric" | "text" | "mixed" | "empty";
  nulls: number;
  unique: number;
  min?: number;
  max?: number;
  avg?: number;
  sum?: number;
}
function computeStats(columns: string[], rows: Row[]): ColStat[] {
  return columns.map((c) => {
    const values = rows.map((r) => r[c]);
    const nonNull = values.filter((v) => v != null);
    const nulls = values.length - nonNull.length;
    const unique = new Set(nonNull.map((v) => String(v))).size;
    const nums = nonNull.filter((v) => typeof v === "number") as number[];
    const allNumeric = nonNull.length > 0 && nums.length === nonNull.length;
    if (nonNull.length === 0) {
      return { column: c, type: "empty", nulls, unique };
    }
    if (allNumeric) {
      const sum = nums.reduce((a, b) => a + b, 0);
      return {
        column: c,
        type: "numeric",
        nulls,
        unique,
        min: Math.min(...nums),
        max: Math.max(...nums),
        avg: sum / nums.length,
        sum,
      };
    }
    if (nums.length > 0) return { column: c, type: "mixed", nulls, unique };
    return { column: c, type: "text", nulls, unique };
  });
}
const fmt = (n: number) => {
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1000 || Number.isInteger(n))
    return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return n.toFixed(3);
};
export function SqlSummaryStats({ columns, rows }: Props) {
  const stats = useMemo(() => computeStats(columns, rows), [columns, rows]);
  return (
    <div className="border-b border-border/60 bg-background/40 px-3 py-3">
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-xs font-semibold text-foreground">{tr.sqlStats.title}</h4>
        <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
          {tr.sqlStats.rowsCols(rows.length.toLocaleString(), columns.length)}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th scope="col" className="px-2 py-1 font-medium">
                {tr.sqlStats.column}
              </th>
              <th scope="col" className="px-2 py-1 font-medium">
                {tr.sqlStats.type}
              </th>
              <th scope="col" className="px-2 py-1 font-medium">
                {tr.sqlStats.nulls}
              </th>
              <th scope="col" className="px-2 py-1 font-medium">
                {tr.sqlStats.unique}
              </th>
              <th scope="col" className="px-2 py-1 font-medium">
                {tr.sqlStats.min}
              </th>
              <th scope="col" className="px-2 py-1 font-medium">
                {tr.sqlStats.max}
              </th>
              <th scope="col" className="px-2 py-1 font-medium">
                {tr.sqlStats.avg}
              </th>
              <th scope="col" className="px-2 py-1 font-medium">
                {tr.sqlStats.sum}
              </th>
            </tr>
          </thead>
          <tbody>
            {stats.map((s) => (
              <tr key={s.column} className="border-t border-border/40">
                <td className="px-2 py-1 font-mono text-foreground/90">{s.column}</td>
                <td className="px-2 py-1">
                  <span className="rounded-full bg-accent/40 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                    {tr.sqlStats.types[s.type] ?? s.type}
                  </span>
                </td>
                <td className="px-2 py-1 text-foreground/80">{s.nulls}</td>
                <td className="px-2 py-1 text-foreground/80">{s.unique}</td>
                <td className="px-2 py-1 font-mono text-foreground/80">
                  {s.min != null ? fmt(s.min) : "—"}
                </td>
                <td className="px-2 py-1 font-mono text-foreground/80">
                  {s.max != null ? fmt(s.max) : "—"}
                </td>
                <td className="px-2 py-1 font-mono text-foreground/80">
                  {s.avg != null ? fmt(s.avg) : "—"}
                </td>
                <td className="px-2 py-1 font-mono text-foreground/80">
                  {s.sum != null ? fmt(s.sum) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
