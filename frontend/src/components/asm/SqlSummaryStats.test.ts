import { describe, expect, it } from "vitest";
import { computeStats } from "./sql-summary-stats-data";

describe("SQL özet istatistikleri", () => {
  it("sayısal metinleri sayıya çevirerek hesaplar", () => {
    const [stat] = computeStats(
      ["tutar"],
      [{ tutar: "10" }, { tutar: 20 }, { tutar: "30.5" }, { tutar: null }],
    );

    expect(stat).toMatchObject({
      type: "numeric",
      nulls: 1,
      unique: 3,
      min: 10,
      max: 30.5,
      sum: 60.5,
    });
    expect(stat.avg).toBeCloseTo(20.1667, 3);
  });

  it("sayısal ve metinsel değerleri karışık olarak işaretler", () => {
    const [stat] = computeStats(["değer"], [{ değer: "10" }, { değer: "yok" }]);
    expect(stat.type).toBe("mixed");
  });
});
