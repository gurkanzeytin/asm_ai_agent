import { tr } from "@/locales/tr";

export type ChartType = "bar" | "line" | "pie";
export type SqlChartRow = Record<string, string | number | null>;

export interface ChartDatum {
  name: string;
  value: number;
}

const MAX_BAR_ITEMS = 20;
const MAX_LINE_ITEMS = 40;
const MAX_PIE_ITEMS = 8;

export function chartTypeFromRecommendation(value?: string | null): ChartType | null {
  const normalized = value?.toUpperCase();
  if (normalized === "BAR_CHART" || normalized === "BAR") return "bar";
  if (normalized === "LINE_CHART" || normalized === "LINE") return "line";
  if (normalized === "PIE_CHART" || normalized === "PIE") return "pie";
  return null;
}

export function isNumericColumn(rows: SqlChartRow[], column: string) {
  const values = rows.map((row) => row[column]).filter((value) => value != null);
  return (
    values.length > 0 &&
    values.every(
      (value) =>
        typeof value === "number" ||
        (String(value).trim() !== "" && Number.isFinite(Number(value))),
    )
  );
}

function validPoints(rows: SqlChartRow[], xKey: string, yKey: string) {
  return rows.flatMap((row) => {
    const rawValue = row[yKey];
    if (rawValue == null || String(rawValue).trim() === "") return [];
    const value = Number(rawValue);
    if (!Number.isFinite(value)) return [];
    const rawLabel = String(row[xKey] ?? "").trim();
    return [{ name: rawLabel || tr.sqlChart.unknownLabel, value }];
  });
}

function aggregate(points: ChartDatum[]) {
  const totals = new Map<string, number>();
  for (const point of points) totals.set(point.name, (totals.get(point.name) ?? 0) + point.value);
  return Array.from(totals, ([name, value]) => ({ name, value }));
}

function sortLinePoints(points: ChartDatum[]) {
  const numeric = points.every((point) => Number.isFinite(Number(point.name)));
  if (numeric) return [...points].sort((a, b) => Number(a.name) - Number(b.name));

  const timestamps = points.map((point) => Date.parse(point.name));
  if (timestamps.every(Number.isFinite)) {
    return [...points].sort((a, b) => Date.parse(a.name) - Date.parse(b.name));
  }
  return points;
}

export function buildChartData(
  rows: SqlChartRow[],
  xKey: string,
  yKey: string,
  type: ChartType,
): ChartDatum[] {
  if (!xKey || !yKey) return [];
  const points = validPoints(rows, xKey, yKey);

  if (type === "line") return sortLinePoints(points).slice(0, MAX_LINE_ITEMS);

  const aggregated = aggregate(points);
  if (type === "bar") {
    return aggregated.sort((a, b) => Math.abs(b.value) - Math.abs(a.value)).slice(0, MAX_BAR_ITEMS);
  }

  const positive = aggregated.filter((point) => point.value > 0).sort((a, b) => b.value - a.value);
  if (positive.length <= MAX_PIE_ITEMS) return positive;

  const visible = positive.slice(0, MAX_PIE_ITEMS - 1);
  const otherValue = positive
    .slice(MAX_PIE_ITEMS - 1)
    .reduce((total, point) => total + point.value, 0);
  return [...visible, { name: tr.sqlChart.other, value: otherValue }];
}

export function isChartDataLimited(
  rows: SqlChartRow[],
  xKey: string,
  yKey: string,
  type: ChartType,
) {
  const points = validPoints(rows, xKey, yKey);
  if (type === "line") return points.length > MAX_LINE_ITEMS;

  const categoryCount = aggregate(points).length;
  return type === "bar" ? categoryCount > MAX_BAR_ITEMS : categoryCount > MAX_PIE_ITEMS;
}
