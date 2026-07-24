import { describe, expect, it } from "vitest";
import { tr } from "@/locales/tr";
import { buildChartData, chartTypeFromRecommendation, isNumericColumn } from "./sql-chart-data";

describe("SQL grafik veri hazırlama", () => {
  it("grafik türlerini baş harfi büyük gösterir", () => {
    expect(tr.sqlChart.types).toMatchObject({ bar: "Çubuk", line: "Çizgi", pie: "Pasta" });
  });

  it("backend grafik önerisini frontend türüne dönüştürür", () => {
    expect(chartTypeFromRecommendation("BAR_CHART")).toBe("bar");
    expect(chartTypeFromRecommendation("LINE_CHART")).toBe("line");
    expect(chartTypeFromRecommendation("PIE_CHART")).toBe("pie");
    expect(chartTypeFromRecommendation("TABLE")).toBeNull();
  });

  it("bar grafikte aynı kategorileri birleştirir ve geçersiz değerleri dışarıda bırakır", () => {
    const rows = [
      { kategori: "A", tutar: 2 },
      { kategori: "A", tutar: "3" },
      { kategori: "B", tutar: null },
      { kategori: "C", tutar: "" },
      { kategori: "D", tutar: "geçersiz" },
    ];

    expect(buildChartData(rows, "kategori", "tutar", "bar")).toEqual([{ name: "A", value: 5 }]);
  });

  it("line grafikte sayısal ekseni sıralar ve eksik değerleri sıfıra çevirmez", () => {
    const rows = [
      { ay: "10", tutar: 10 },
      { ay: "2", tutar: 2 },
      { ay: "1", tutar: 1 },
      { ay: "3", tutar: null },
    ];

    expect(buildChartData(rows, "ay", "tutar", "line")).toEqual([
      { name: "1", value: 1 },
      { name: "2", value: 2 },
      { name: "10", value: 10 },
    ]);
  });

  it("line grafikte 40'tan fazla noktada EN GÜNCEL noktaları tutar, en eskileri değil", () => {
    // A full year of daily counts (365 points) must keep the tail end (most
    // recent, decision-relevant days), not silently truncate to just the
    // first ~40 days of the year (2026-07-24 regression: slice(0, N) after
    // an ascending sort kept the OLDEST points instead of the newest).
    const rows = Array.from({ length: 60 }, (_, index) => {
      const date = new Date(Date.UTC(2026, 0, 1 + index));
      return { gun: date.toISOString().slice(0, 10), randevu: index };
    });

    const result = buildChartData(rows, "gun", "randevu", "line");

    expect(result).toHaveLength(40);
    // The kept window must be the tail (highest values, since `randevu`
    // increases monotonically with the date index) - not the head.
    expect(result[0].value).toBe(20);
    expect(result.at(-1)?.value).toBe(59);
  });

  it("pie grafikte pozitif dilimleri tutar ve kalanları Diğer altında toplar", () => {
    const rows = Array.from({ length: 10 }, (_, index) => ({
      kategori: `K${index + 1}`,
      tutar: 10 - index,
    })).concat([
      { kategori: "Sıfır", tutar: 0 },
      { kategori: "Eksi", tutar: -2 },
    ]);

    const result = buildChartData(rows, "kategori", "tutar", "pie");

    expect(result).toHaveLength(8);
    expect(result.at(-1)).toEqual({ name: "Diğer", value: 6 });
    expect(result.reduce((total, point) => total + point.value, 0)).toBe(55);
  });

  it("sayısal metin sütunlarını sayısal kabul eder", () => {
    expect(isNumericColumn([{ tutar: "1,5" }, { tutar: "2" }], "tutar")).toBe(false);
    expect(isNumericColumn([{ tutar: "1.5" }, { tutar: "2" }], "tutar")).toBe(true);
  });
});
