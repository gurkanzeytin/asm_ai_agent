import { useMemo } from "react";
import { tr } from "@/locales/tr";
import { computeStats, type SqlStatsRow } from "./sql-summary-stats-data";

interface Props {
  columns: string[];
  rows: SqlStatsRow[];
}
const fmt = (n: number) => {
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1000 || Number.isInteger(n))
    return n.toLocaleString("tr-TR", { maximumFractionDigits: 2 });
  return n.toLocaleString("tr-TR", { maximumFractionDigits: 3 });
};
export function SqlSummaryStats({ columns, rows }: Props) {
  const stats = useMemo(() => computeStats(columns, rows), [columns, rows]);
  return (
    <section className="border-b border-border/60 bg-background/30 px-4 py-4">
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
    </section>
  );
}
