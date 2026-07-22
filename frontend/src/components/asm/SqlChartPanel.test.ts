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
