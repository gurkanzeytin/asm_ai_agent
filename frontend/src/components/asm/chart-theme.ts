export const chartTheme = {
  primary: "#168BFF",
  primaryLight: "#22B8FF",
  primaryDark: "#2563EB",
  cyan: "#38D5FF",
  teal: "#2DD4BF",
  navy: "#0D172B",
  grid: "rgba(148, 163, 184, 0.10)",
  axis: "#7F8DA8",
  tooltipBackground: "#0D172B",
  tooltipBorder: "rgba(59, 130, 246, 0.35)",
  piePalette: ["#22B8FF", "#168BFF", "#2563EB", "#38D5FF", "#2DD4BF", "#0EA5E9"],
} as const;

export const trNumberFormatter = new Intl.NumberFormat("tr-TR");

export const trCompactNumberFormatter = new Intl.NumberFormat("tr-TR", {
  notation: "compact",
  maximumFractionDigits: 1,
});
