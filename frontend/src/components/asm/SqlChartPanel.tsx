import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { cn } from "@/lib/utils";
import { tr } from "@/locales/tr";
import { chartTheme, trCompactNumberFormatter, trNumberFormatter } from "./chart-theme";

type Row = Record<string, string | number | null>;
type ChartType = "bar" | "line" | "pie";
type ChartDatum = { name: string; value: number };

interface Props {
  columns: string[];
  rows: Row[];
}

const axisTick = {
  fill: chartTheme.axis,
  fontSize: 11,
  fontWeight: 500,
};

const chartMargin = { top: 18, right: 16, left: 6, bottom: 10 };

function isNumericColumn(rows: Row[], col: string) {
  const nonNull = rows.map((r) => r[col]).filter((v) => v != null);
  if (nonNull.length === 0) return false;
  return nonNull.every(
    (v) => typeof v === "number" || (!isNaN(Number(v)) && String(v).trim() !== ""),
  );
}

function formatMaybeMonth(value: string) {
  const match = /^(\d{4})-(\d{2})$/.exec(value);
  if (!match) return value;

  const year = Number(match[1]);
  const monthIndex = Number(match[2]) - 1;
  if (monthIndex < 0 || monthIndex > 11) return value;

  return new Intl.DateTimeFormat("tr-TR", {
    month: "long",
    year: "numeric",
  }).format(new Date(Date.UTC(year, monthIndex, 1)));
}

function formatAxisLabel(value: string) {
  const month = formatMaybeMonth(value);
  if (month !== value) {
    return month.replace(" ", "\n");
  }
  return value.length > 16 ? `${value.slice(0, 15)}...` : value;
}

function formatValue(value: number) {
  return trNumberFormatter.format(value);
}

function formatCompactValue(value: number) {
  return Math.abs(value) >= 10000 ? trCompactNumberFormatter.format(value) : formatValue(value);
}

function ChartTooltip({
  active,
  payload,
  label,
  yKey,
}: {
  active?: boolean;
  payload?: Array<{ value?: unknown; name?: string; payload?: ChartDatum }>;
  label?: string | number;
  yKey: string;
}) {
  if (!active || !payload?.length) return null;

  const item = payload[0];
  const rawName = item.payload?.name ?? String(label ?? "");
  const rawValue = Number(item.value ?? item.payload?.value);

  return (
    <div className="min-w-36 rounded-lg border border-[rgba(59,130,246,0.35)] bg-[#0D172B]/95 px-3 py-2 text-xs shadow-[0_16px_40px_rgba(2,8,23,0.45),0_0_24px_rgba(34,184,255,0.12)] backdrop-blur">
      <div className="mb-1 font-semibold text-foreground">{formatMaybeMonth(rawName)}</div>
      <div className="flex items-center justify-between gap-4 text-muted-foreground">
        <span>{yKey}</span>
        <span className="font-mono font-semibold tabular-nums text-[#7DD3FC]">
          {Number.isFinite(rawValue) ? formatValue(rawValue) : "-"}
        </span>
      </div>
    </div>
  );
}

function PieLegend({ payload }: { payload?: Array<{ value?: string | number; color?: string }> }) {
  if (!payload?.length) return null;

  return (
    <div className="flex max-h-10 flex-wrap justify-center gap-x-3 gap-y-1 overflow-hidden px-2 text-[10px] text-muted-foreground">
      {payload.slice(0, 6).map((item) => (
        <span key={String(item.value)} className="inline-flex min-w-0 items-center gap-1.5">
          <span
            className="h-2 w-2 shrink-0 rounded-[2px]"
            style={{ backgroundColor: item.color }}
            aria-hidden="true"
          />
          <span className="max-w-24 truncate">{item.value}</span>
        </span>
      ))}
    </div>
  );
}

export function SqlChartPanel({ columns, rows }: Props) {
  const numericCols = useMemo(
    () => columns.filter((c) => isNumericColumn(rows, c)),
    [columns, rows],
  );
  const [type, setType] = useState<ChartType>("bar");
  const [xKey, setXKey] = useState<string>(columns[0] ?? "");
  const [yKey, setYKey] = useState<string>(numericCols[0] ?? "");

  const data = useMemo<ChartDatum[]>(() => {
    if (!xKey || !yKey) return [];
    if (type === "pie") {
      const map = new Map<string, number>();
      for (const r of rows) {
        const label = String(r[xKey] ?? "-");
        const val = Number(r[yKey]);
        if (!Number.isFinite(val)) continue;
        map.set(label, (map.get(label) ?? 0) + val);
      }
      return Array.from(map, ([name, value]) => ({ name, value })).slice(0, 12);
    }
    return rows.slice(0, 100).map((r) => ({
      name: String(r[xKey] ?? ""),
      value: Number(r[yKey]) || 0,
    }));
  }, [rows, xKey, yKey, type]);

  const hasData = xKey && yKey && data.length > 0;
  const showBarLabels = type === "bar" && data.length > 0 && data.length <= 12;

  return (
    <div className="border-b border-border/60 bg-background/40 px-3 py-3">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h4 className="mr-auto text-xs font-semibold text-foreground">{tr.sqlChart.title}</h4>
        <div
          role="radiogroup"
          aria-label={tr.sqlChart.chartType}
          className="flex h-8 items-center gap-1 rounded-lg border border-border/70 bg-[#0D172B]/60 p-0.5 shadow-inner shadow-black/20"
        >
          {(["bar", "line", "pie"] as ChartType[]).map((t) => (
            <button
              key={t}
              role="radio"
              aria-checked={type === t}
              type="button"
              onClick={() => setType(t)}
              className={cn(
                "h-7 rounded-md px-2.5 text-[11px] font-semibold capitalize transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/70 focus-visible:ring-offset-1 focus-visible:ring-offset-background",
                type === t
                  ? "bg-primary/20 text-[#7DD3FC] shadow-[inset_0_0_0_1px_rgba(34,184,255,0.18),0_0_16px_rgba(22,139,255,0.18)]"
                  : "text-muted-foreground hover:bg-primary/10 hover:text-foreground",
              )}
            >
              {tr.sqlChart.types[t] ?? t}
            </button>
          ))}
        </div>
        <label className="flex h-8 items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
          <span>{type === "pie" ? tr.sqlChart.label : "X"}</span>
          <select
            aria-label={tr.sqlChart.xAxis}
            value={xKey}
            onChange={(e) => setXKey(e.target.value)}
            className="h-8 rounded-lg border border-border/70 bg-[#0D172B]/70 px-2 text-[11px] text-foreground transition hover:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/70"
          >
            {columns.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="flex h-8 items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
          <span>{type === "pie" ? tr.sqlChart.value : "Y"}</span>
          <select
            aria-label={tr.sqlChart.yAxis}
            value={yKey}
            onChange={(e) => setYKey(e.target.value)}
            className="h-8 rounded-lg border border-border/70 bg-[#0D172B]/70 px-2 text-[11px] text-foreground transition hover:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/70"
          >
            {numericCols.length === 0 && <option value="">{tr.sqlChart.noNumericColumns}</option>}
            {numericCols.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="h-56 w-full rounded-xl bg-[#0D172B]/25 px-1 py-2">
        {hasData ? (
          <ResponsiveContainer width="100%" height="100%">
            {type === "bar" ? (
              <BarChart data={data} margin={chartMargin} barCategoryGap="24%">
                <defs>
                  <linearGradient id="asm-bar-gradient" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor={chartTheme.primaryLight} />
                    <stop offset="100%" stopColor={chartTheme.primaryDark} />
                  </linearGradient>
                  <filter id="asm-bar-glow" height="160%" width="160%" x="-30%" y="-30%">
                    <feDropShadow
                      dx="0"
                      dy="0"
                      floodColor={chartTheme.primaryLight}
                      floodOpacity="0.28"
                      stdDeviation="3"
                    />
                  </filter>
                </defs>
                <CartesianGrid stroke={chartTheme.grid} strokeDasharray="4 6" vertical={false} />
                <XAxis
                  dataKey="name"
                  axisLine={false}
                  tick={axisTick}
                  tickFormatter={(value) => formatAxisLabel(String(value))}
                  tickLine={false}
                  tickMargin={10}
                />
                <YAxis
                  axisLine={false}
                  tick={axisTick}
                  tickFormatter={(value) => formatCompactValue(Number(value))}
                  tickLine={false}
                  tickMargin={8}
                  width={42}
                />
                <Tooltip
                  content={<ChartTooltip yKey={yKey} />}
                  cursor={{ fill: "rgba(34, 184, 255, 0.08)" }}
                  isAnimationActive
                />
                <Bar
                  animationDuration={560}
                  animationEasing="ease-out"
                  dataKey="value"
                  fill="url(#asm-bar-gradient)"
                  filter="url(#asm-bar-glow)"
                  maxBarSize={42}
                  radius={[7, 7, 0, 0]}
                >
                  {showBarLabels && (
                    <LabelList
                      dataKey="value"
                      formatter={(value: number) => formatCompactValue(Number(value))}
                      position="top"
                      className="fill-[#BFE8FF] text-[10px] font-semibold"
                    />
                  )}
                </Bar>
              </BarChart>
            ) : type === "line" ? (
              <AreaChart data={data} margin={chartMargin}>
                <defs>
                  <linearGradient id="asm-line-area" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor={chartTheme.primaryLight} stopOpacity="0.32" />
                    <stop offset="100%" stopColor={chartTheme.primaryDark} stopOpacity="0.02" />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke={chartTheme.grid} strokeDasharray="4 6" vertical={false} />
                <XAxis
                  dataKey="name"
                  axisLine={false}
                  tick={axisTick}
                  tickFormatter={(value) => formatAxisLabel(String(value))}
                  tickLine={false}
                  tickMargin={10}
                />
                <YAxis
                  axisLine={false}
                  tick={axisTick}
                  tickFormatter={(value) => formatCompactValue(Number(value))}
                  tickLine={false}
                  tickMargin={8}
                  width={42}
                />
                <Tooltip
                  content={<ChartTooltip yKey={yKey} />}
                  cursor={{ stroke: "rgba(34, 184, 255, 0.35)", strokeDasharray: "4 4" }}
                  isAnimationActive
                />
                <Area
                  animationDuration={560}
                  animationEasing="ease-out"
                  dataKey="value"
                  fill="url(#asm-line-area)"
                  stroke="none"
                  type="monotone"
                />
                <Line
                  animationDuration={560}
                  animationEasing="ease-out"
                  activeDot={{
                    r: 5,
                    fill: chartTheme.cyan,
                    stroke: chartTheme.tooltipBackground,
                    strokeWidth: 2,
                  }}
                  dataKey="value"
                  dot={{
                    r: 2.5,
                    fill: chartTheme.primaryLight,
                    stroke: chartTheme.tooltipBackground,
                    strokeWidth: 1.5,
                  }}
                  stroke={chartTheme.primaryLight}
                  strokeWidth={2.5}
                  type="monotone"
                />
              </AreaChart>
            ) : (
              <PieChart margin={{ top: 6, right: 8, left: 8, bottom: 6 }}>
                <Tooltip content={<ChartTooltip yKey={yKey} />} isAnimationActive />
                <Legend content={<PieLegend />} verticalAlign="bottom" />
                <Pie
                  animationDuration={560}
                  animationEasing="ease-out"
                  data={data}
                  dataKey="value"
                  innerRadius={34}
                  nameKey="name"
                  outerRadius="72%"
                  paddingAngle={2}
                  stroke="#0D172B"
                  strokeWidth={2}
                >
                  {data.map((_, i) => (
                    <Cell key={i} fill={chartTheme.piePalette[i % chartTheme.piePalette.length]} />
                  ))}
                </Pie>
              </PieChart>
            )}
          </ResponsiveContainer>
        ) : (
          <div className="grid h-full place-items-center text-[11px] text-muted-foreground">
            {numericCols.length === 0 ? tr.sqlChart.noNumericToPlot : tr.sqlChart.selectAxes}
          </div>
        )}
      </div>
    </div>
  );
}
