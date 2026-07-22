import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { BarChart3, ChartLine, ChartPie, Contrast } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { tr } from "@/locales/tr";
import { trCompactNumberFormatter, trNumberFormatter } from "./chart-theme";
import {
  buildChartData,
  isChartDataLimited,
  isNumericColumn,
  type ChartDatum,
  type ChartType,
  type SqlChartRow,
} from "./sql-chart-data";

interface Props {
  columns: string[];
  rows: SqlChartRow[];
  initialType?: ChartType;
  onCategorySelect?: (column: string, value: string) => void;
}

const PALETTE_THEME = [
  "var(--primary)",
  "var(--cyan)",
  "var(--success)",
  "var(--warning)",
  "var(--destructive)",
  "var(--muted-foreground)",
];
const PALETTE_HIGH_CONTRAST = ["#FFFFFF", "#F0E442", "#56B4E9", "#E69F00", "#009E73", "#CC79A7"];

function formatNumber(value: number) {
  return trNumberFormatter.format(value);
}

function truncateLabel(value: string) {
  return value.length > 16 ? `${value.slice(0, 15)}…` : value;
}

const chartTypes = [
  { value: "bar" as const, icon: BarChart3 },
  { value: "line" as const, icon: ChartLine },
  { value: "pie" as const, icon: ChartPie },
];

export function SqlChartPanel({ columns, rows, initialType = "bar", onCategorySelect }: Props) {
  const numericColumns = useMemo(
    () => columns.filter((column) => isNumericColumn(rows, column)),
    [columns, rows],
  );
  const [type, setType] = useState<ChartType>(initialType);
  const [yKey, setYKey] = useState(numericColumns[0] ?? "");
  const [xKey, setXKey] = useState(
    columns.find((column) => column !== numericColumns[0] && !numericColumns.includes(column)) ??
      columns.find((column) => column !== numericColumns[0]) ??
      columns[0] ??
      "",
  );
  const [highContrast, setHighContrast] = useState(false);
  const [focusIndex, setFocusIndex] = useState(0);
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => {
    if (!numericColumns.includes(yKey)) setYKey(numericColumns[0] ?? "");
    if (!columns.includes(xKey) || (xKey === yKey && columns.length > 1)) {
      setXKey(columns.find((column) => column !== yKey) ?? columns[0] ?? "");
    }
  }, [columns, numericColumns, xKey, yKey]);

  const palette = highContrast ? PALETTE_HIGH_CONTRAST : PALETTE_THEME;
  const data = useMemo(() => buildChartData(rows, xKey, yKey, type), [rows, xKey, yKey, type]);
  const hasData = data.length > 0 && (type !== "line" || data.length > 1);
  const isLimited = useMemo(
    () => isChartDataLimited(rows, xKey, yKey, type),
    [rows, xKey, yKey, type],
  );

  useEffect(() => setFocusIndex(0), [type, xKey, yKey]);

  const summary = useMemo(() => {
    if (!hasData) return "";
    const total = data.reduce((sum, item) => sum + item.value, 0);
    const highest = data.reduce((current, item) => (item.value > current.value ? item : current));
    return tr.sqlChart.summary(
      tr.sqlChart.types[type],
      yKey,
      xKey,
      data.length,
      formatNumber(total),
      highest.name,
      formatNumber(highest.value),
    );
  }, [data, hasData, type, xKey, yKey]);

  const handleChartKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!hasData) return;
    if ((event.key === "Enter" || event.key === " ") && type !== "line" && onCategorySelect) {
      event.preventDefault();
      onCategorySelect(xKey, data[focusIndex].name);
      setAnnouncement(tr.sqlChart.categoryFilterApplied(data[focusIndex].name));
      return;
    }
    let next = focusIndex;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      next = Math.min(data.length - 1, focusIndex + 1);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      next = Math.max(0, focusIndex - 1);
    } else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = data.length - 1;
    else return;
    event.preventDefault();
    setFocusIndex(next);
    setAnnouncement(
      tr.sqlChart.pointAnnouncement(
        data[next].name,
        formatNumber(data[next].value),
        next + 1,
        data.length,
      ),
    );
  };

  const tooltipStyle = {
    fontSize: 12,
    background: "var(--popover)",
    border: "1px solid var(--border)",
    borderRadius: 8,
    color: "var(--popover-foreground)",
    boxShadow: "var(--shadow-panel)",
  } as const;

  return (
    <section className="border-b border-border/60 bg-background/30 px-4 py-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="mr-auto">
          <h4 id="chart-heading" className="text-sm font-semibold text-foreground">
            {tr.sqlChart.title}
          </h4>
          <p className="mt-0.5 text-[11px] text-muted-foreground">{tr.sqlChart.description}</p>
        </div>

        <div
          role="radiogroup"
          aria-label={tr.sqlChart.chartType}
          className="flex h-8 items-center rounded-lg border border-border bg-background/60 p-0.5"
        >
          {chartTypes.map(({ value, icon: Icon }) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={type === value}
              aria-label={tr.sqlChart.types[value]}
              onClick={() => setType(value)}
              className={`flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[11px] font-medium transition ${
                type === value
                  ? "bg-primary/15 text-primary shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden="true" />
              {tr.sqlChart.types[value]}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={() => setHighContrast((value) => !value)}
          aria-pressed={highContrast}
          aria-label={tr.sqlChart.highContrast}
          title={tr.sqlChart.highContrast}
          className={`grid h-8 w-8 place-items-center rounded-lg border border-border bg-background/60 transition ${
            highContrast ? "text-foreground" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          <Contrast className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3">
        <label className="grid gap-1 text-[10px] font-medium uppercase text-muted-foreground">
          {type === "pie" ? tr.sqlChart.label : tr.sqlChart.xAxis}
          <select
            aria-label={type === "pie" ? tr.sqlChart.label : tr.sqlChart.xAxis}
            value={xKey}
            onChange={(event) => setXKey(event.target.value)}
            className="h-9 min-w-0 rounded-lg border border-border bg-background/60 px-2.5 text-xs font-normal normal-case text-foreground outline-none focus:ring-2 focus:ring-primary/60"
          >
            {columns.map((column) => (
              <option key={column} value={column}>
                {column}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-[10px] font-medium uppercase text-muted-foreground">
          {type === "pie" ? tr.sqlChart.value : tr.sqlChart.yAxis}
          <select
            aria-label={type === "pie" ? tr.sqlChart.value : tr.sqlChart.yAxis}
            value={yKey}
            onChange={(event) => setYKey(event.target.value)}
            className="h-9 min-w-0 rounded-lg border border-border bg-background/60 px-2.5 text-xs font-normal normal-case text-foreground outline-none focus:ring-2 focus:ring-primary/60"
          >
            {numericColumns.length === 0 && (
              <option value="">{tr.sqlChart.noNumericColumns}</option>
            )}
            {numericColumns.map((column) => (
              <option key={column} value={column}>
                {column}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>
      {isLimited && (
        <p className="mt-2 text-[10px] text-muted-foreground">{tr.sqlChart.limitedData}</p>
      )}

      <div
        role="img"
        aria-labelledby="chart-heading"
        aria-describedby="chart-description"
        tabIndex={hasData ? 0 : -1}
        onKeyDown={handleChartKeyDown}
        className="relative mt-3 h-72 w-full overflow-hidden rounded-lg border border-border/50 bg-background/35 p-2 focus:outline-none focus:ring-2 focus:ring-primary/60"
      >
        <p id="chart-description" className="sr-only">
          {hasData ? `${summary} ${tr.sqlChart.keyboardHelp}` : tr.sqlChart.noChartData}
        </p>
        {hasData ? (
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={`${type}-${highContrast}`}
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -5 }}
              transition={{ duration: 0.2 }}
              className="absolute inset-2"
              aria-hidden="true"
            >
              <ResponsiveContainer width="100%" height="100%" debounce={80}>
                {type === "bar" ? (
                  <BarChart data={data} margin={{ top: 12, right: 12, left: 4, bottom: 36 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                    <XAxis
                      dataKey="name"
                      interval="preserveStartEnd"
                      minTickGap={18}
                      angle={-22}
                      textAnchor="end"
                      height={48}
                      tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
                      tickFormatter={truncateLabel}
                    />
                    <YAxis
                      width={58}
                      tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
                      tickFormatter={(value: number) => trCompactNumberFormatter.format(value)}
                    />
                    <Tooltip
                      contentStyle={tooltipStyle}
                      formatter={(value) => [formatNumber(Number(value)), yKey]}
                      labelFormatter={(label) => `${xKey}: ${label}`}
                      cursor={{ fill: "var(--accent)", opacity: 0.25 }}
                    />
                    <Bar dataKey="value" name={yKey} radius={[4, 4, 0, 0]} animationDuration={450}>
                      {data.map((item, index) => (
                        <Cell
                          key={item.name}
                          fill={palette[0]}
                          fillOpacity={index === focusIndex ? 1 : 0.78}
                          stroke={index === focusIndex ? "var(--foreground)" : "transparent"}
                          strokeWidth={index === focusIndex ? 1.5 : 0}
                          cursor={onCategorySelect ? "pointer" : undefined}
                          onClick={() => onCategorySelect?.(xKey, item.name)}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                ) : type === "line" ? (
                  <LineChart data={data} margin={{ top: 12, right: 16, left: 4, bottom: 36 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                    <XAxis
                      dataKey="name"
                      interval="preserveStartEnd"
                      minTickGap={20}
                      angle={-22}
                      textAnchor="end"
                      height={48}
                      tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
                      tickFormatter={truncateLabel}
                    />
                    <YAxis
                      width={58}
                      tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
                      tickFormatter={(value: number) => trCompactNumberFormatter.format(value)}
                    />
                    <Tooltip
                      contentStyle={tooltipStyle}
                      formatter={(value) => [formatNumber(Number(value)), yKey]}
                      labelFormatter={(label) => `${xKey}: ${label}`}
                    />
                    <Line
                      type="monotone"
                      dataKey="value"
                      name={yKey}
                      stroke={palette[0]}
                      strokeWidth={highContrast ? 3 : 2.25}
                      dot={{ r: 2.5, fill: palette[0], strokeWidth: 0 }}
                      activeDot={{ r: 5 }}
                      connectNulls={false}
                      animationDuration={450}
                    />
                  </LineChart>
                ) : (
                  <PieChart>
                    <Tooltip
                      contentStyle={tooltipStyle}
                      formatter={(value) => [formatNumber(Number(value)), yKey]}
                    />
                    <Legend
                      verticalAlign="bottom"
                      height={42}
                      wrapperStyle={{ fontSize: 10, color: "var(--muted-foreground)" }}
                      iconType="circle"
                      formatter={(value) => truncateLabel(String(value))}
                    />
                    <Pie
                      data={data}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="43%"
                      outerRadius="72%"
                      innerRadius="44%"
                      paddingAngle={2}
                      stroke="var(--background)"
                      strokeWidth={2}
                      animationDuration={450}
                    >
                      {data.map((item, index) => (
                        <Cell
                          key={item.name}
                          fill={palette[index % palette.length]}
                          stroke={index === focusIndex ? "var(--foreground)" : "var(--background)"}
                          strokeWidth={index === focusIndex ? 3 : 2}
                          cursor={onCategorySelect ? "pointer" : undefined}
                          onClick={() => onCategorySelect?.(xKey, item.name)}
                        />
                      ))}
                    </Pie>
                  </PieChart>
                )}
              </ResponsiveContainer>
            </motion.div>
          </AnimatePresence>
        ) : (
          <div className="grid h-full place-items-center text-xs text-muted-foreground">
            {numericColumns.length === 0
              ? tr.sqlChart.noNumericToPlot
              : type === "line" && data.length === 1
                ? tr.sqlChart.lineNeedsTwoPoints
                : tr.sqlChart.selectAxes}
          </div>
        )}
      </div>

      {hasData && (
        <table className="sr-only">
          <caption>{summary}</caption>
          <thead>
            <tr>
              <th scope="col">{xKey}</th>
              <th scope="col">{yKey}</th>
            </tr>
          </thead>
          <tbody>
            {data.map((item) => (
              <tr key={item.name}>
                <th scope="row">{item.name}</th>
                <td>{formatNumber(item.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
