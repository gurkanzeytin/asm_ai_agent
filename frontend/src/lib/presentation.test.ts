import { describe, expect, it } from "vitest";
import {
  buildAnalyticsCards,
  buildMetricCards,
  formatAnalyticsValue,
  getAnalyticsLabel,
  getColumnLabel,
  resolveColumnMetadata,
} from "./presentation";

describe("buildMetricCards", () => {
  it("tek satırlık metrikleri Türkçe etiket ve birimlerle kartlara dönüştürür", () => {
    expect(buildMetricCards(["appointment_count"], [{ appointment_count: 1250 }])).toEqual([
      { label: "Toplam Randevu", value: "1.250 randevu" },
    ]);
  });

  it("süre, oran ve hacmi doğal Türkçe biçimde gösterir", () => {
    expect(
      buildMetricCards(
        ["appointment_duration_average", "completed_appointment_rate", "appointment_count"],
        [
          {
            appointment_duration_average: 67,
            completed_appointment_rate: 0,
            appointment_count: 88,
          },
        ],
      ),
    ).toEqual([
      { label: "Ortalama Randevu Süresi", value: "67 dk" },
      { label: "Gerçekleşme Oranı", value: "%0" },
      { label: "Toplam Randevu", value: "88 randevu" },
    ]);
  });

  it("veri yok ile gerçek sıfırı birbirinden ayırır", () => {
    expect(
      buildMetricCards(
        ["appointment_duration_average", "completed_appointment_rate"],
        [{ appointment_duration_average: null, completed_appointment_rate: 0 }],
      ),
    ).toEqual([
      { label: "Ortalama Randevu Süresi", value: "Veri yok", isEmpty: true },
      { label: "Gerçekleşme Oranı", value: "%0" },
    ]);
  });
});

describe("getColumnLabel", () => {
  it("bilinen metrik alias'ları için Türkçe etiket döner", () => {
    expect(getColumnLabel("monthly_appointment_count")).toBe("Aylık Randevu Sayısı");
    expect(getColumnLabel("completed_appointment_rate")).toBe("Gerçekleşme Oranı");
  });

  it("bilinen görünüm (view) sütunları için Türkçe etiket döner", () => {
    expect(getColumnLabel("SubeAdi")).toBe("Şube");
    expect(getColumnLabel("RandevuDurumu")).toBe("Randevu Durumu");
    expect(getColumnLabel("DoktorId")).toBe("Doktor");
  });

  it("planlanan metrik/dimension listesi diğer eşleşmelerden önce gelir", () => {
    expect(getColumnLabel("branch", undefined, ["branch"])).toBe("Şube");
    expect(getColumnLabel("appointment_count", ["appointment_count"])).toBe("Toplam Randevu");
  });

  it("bilinmeyen sütun için okunur bir geri dönüş üretir, boş bırakmaz", () => {
    const label = getColumnLabel("some_unmapped_column");
    expect(label).toBeTruthy();
    expect(label).not.toContain("_");
  });
});

describe("resolveColumnMetadata", () => {
  it("ham anahtarları asla değiştirmez", () => {
    const resolved = resolveColumnMetadata(["SubeAdi", "appointment_count"]);
    expect(resolved.map((m) => m.key)).toEqual(["SubeAdi", "appointment_count"]);
  });

  it("backend column_metadata varsa onu kullanır", () => {
    const resolved = resolveColumnMetadata(
      ["SubeAdi"],
      [{ key: "SubeAdi", label: "Backend Etiketi", format: "text", unit: null }],
    );
    expect(resolved[0].label).toBe("Backend Etiketi");
  });

  it("column_metadata eksikse frontend etiketini güvenle türetir (çökmez)", () => {
    const resolved = resolveColumnMetadata(["SubeAdi", "unknown_xyz"], undefined);
    expect(resolved[0].label).toBe("Şube");
    expect(resolved[1].label).toBeTruthy();
  });

  it("aynı etiketle çakışan sütunlar için deterministik sonek ekler", () => {
    const resolved = resolveColumnMetadata(
      ["appointment_count", "appointment_count_2"],
      [
        { key: "appointment_count", label: "Toplam Randevu", format: "integer", unit: null },
        { key: "appointment_count_2", label: "Toplam Randevu", format: "integer", unit: null },
      ],
    );
    expect(resolved.map((m) => m.label)).toEqual(["Toplam Randevu", "Toplam Randevu (2)"]);
  });

  it("yüzde/süre formatları için doğru birimi çıkarır", () => {
    const resolved = resolveColumnMetadata(["completed_appointment_rate", "RandevuSuresi"]);
    const byKey = Object.fromEntries(resolved.map((m) => [m.key, m]));
    expect(byKey.completed_appointment_rate.format).toBe("percentage");
    expect(byKey.completed_appointment_rate.unit).toBe("%");
    expect(byKey.RandevuSuresi.format).toBe("duration");
    expect(byKey.RandevuSuresi.unit).toBe("dakika");
  });
});

describe("getAnalyticsLabel", () => {
  it("bilinen analitik KPI anahtarları için Türkçe etiket döner", () => {
    expect(getAnalyticsLabel("total")).toBe("Toplam");
    expect(getAnalyticsLabel("average")).toBe("Ortalama");
    expect(getAnalyticsLabel("median")).toBe("Medyan");
    expect(getAnalyticsLabel("percentage_change")).toBe("Yüzdesel Değişim");
    expect(getAnalyticsLabel("trend_direction")).toBe("Eğilim Yönü");
    expect(getAnalyticsLabel("comparison_sufficient")).toBe("Karşılaştırma Yeterliliği");
    expect(getAnalyticsLabel("comparable_period_count")).toBe("Karşılaştırılabilir Dönem Sayısı");
  });

  it("bilinmeyen anahtar için okunur bir geri dönüş üretir, çökmez", () => {
    const label = getAnalyticsLabel("some_future_kpi_key");
    expect(label).toBeTruthy();
    expect(label).not.toContain("_");
  });
});

describe("formatAnalyticsValue", () => {
  it("yön (trend_direction) değerlerini Türkçe gösterir", () => {
    expect(formatAnalyticsValue("trend_direction", "upward")).toBe("Yükseliş");
    expect(formatAnalyticsValue("trend_direction", "downward")).toBe("Düşüş");
    expect(formatAnalyticsValue("trend_direction", "flat")).toBe("Yatay");
    expect(formatAnalyticsValue("trend_direction", "mixed")).toBe("Karma");
    expect(formatAnalyticsValue("trend_direction", "insufficient_data")).toBe("Yetersiz Veri");
  });

  it("eğilim tutarlılığı (trend_consistency) değerlerini Türkçe gösterir", () => {
    expect(formatAnalyticsValue("trend_consistency", "consistent_upward")).toBe("Tutarlı Yükseliş");
    expect(formatAnalyticsValue("trend_consistency", "mixed")).toBe("Karma Eğilim");
  });

  it("comparison_sufficient boolean'ını Yeterli/Yetersiz olarak gösterir", () => {
    expect(formatAnalyticsValue("comparison_sufficient", true)).toBe("Yeterli");
    expect(formatAnalyticsValue("comparison_sufficient", false)).toBe("Yetersiz");
  });

  it("yüzde KPI'larını Türkçe yüzde biçiminde gösterir", () => {
    expect(formatAnalyticsValue("percentage_change", -46.15)).toBe("%-46,2");
  });

  it("tam sayı ve ondalık KPI'ları Türkçe sayı biçiminde gösterir", () => {
    expect(formatAnalyticsValue("total", 1683876)).toBe("1.683.876");
    expect(formatAnalyticsValue("average", 12.57)).toBe("12,6");
  });

  it("ay bazlı dönem değerini 'Ay Yıl' olarak gösterir", () => {
    expect(formatAnalyticsValue("highest_period", "2026-06")).toBe("Haziran 2026");
  });

  it("gün bazlı dönem değerini 'gün Ay Yıl' olarak gösterir", () => {
    expect(formatAnalyticsValue("lowest_period", "2026-07-01")).toBe("1 Temmuz 2026");
  });

  it("null değeri 'Veri yok' olarak gösterir, ham değeri asla değiştirmez", () => {
    expect(formatAnalyticsValue("average", null)).toBe("Veri yok");
  });
});

describe("buildAnalyticsCards", () => {
  it("total/average/median için Türkçe kartlar üretir", () => {
    const cards = buildAnalyticsCards({ total: 88, average: 12.57, median: 11 });
    expect(cards.map((c) => c.label)).toEqual(["Toplam", "Ortalama", "Medyan"]);
    expect(cards[0].value).toBe("88");
    expect(cards[1].value).toBe("12,6");
  });

  it("hiçbir kartta ham snake_case anahtar görünmez", () => {
    const cards = buildAnalyticsCards({
      total: 88,
      average: 12.57,
      median: 11,
      minimum: 3,
      maximum: 21,
      highest_value: 21,
      lowest_value: 3,
      percentage_change: -46.15,
      growth_rate: -46.15,
      trend_direction: "upward",
      top_category: "Merkez",
      bottom_category: "Kadıköy",
      comparison_sufficient: false,
    });
    for (const card of cards) {
      expect(card.label).not.toMatch(/[a-z]+_[a-z]+/);
    }
  });

  it("maximum/highest_value takma adını tekilleştirir (yalnız kanonik gösterilir)", () => {
    const cards = buildAnalyticsCards({ maximum: 21, highest_value: 21 });
    expect(cards).toHaveLength(1);
    expect(cards[0].label).toBe("En Yüksek Değer");
  });

  it("minimum/lowest_value takma adını tekilleştirir", () => {
    const cards = buildAnalyticsCards({ minimum: 3, lowest_value: 3 });
    expect(cards).toHaveLength(1);
  });

  it("percentage_change/growth_rate takma adını tekilleştirir", () => {
    const cards = buildAnalyticsCards({ percentage_change: -46.15, growth_rate: -46.15 });
    expect(cards).toHaveLength(1);
    expect(cards[0].label).toBe("Yüzdesel Değişim");
  });

  it("yalnızca alias mevcutsa (kanonik yoksa) alias'ı gösterir, hiç kartı düşürmez", () => {
    const cards = buildAnalyticsCards({ highest_value: 21 });
    expect(cards).toHaveLength(1);
    expect(cards[0].label).toBe("En Yüksek Değer");
  });

  it("sabit KPI sırasına göre sıralar (obje anahtar sırasına güvenmez)", () => {
    const cards = buildAnalyticsCards({
      median: 11,
      total: 88,
      trend_direction: "upward",
      average: 12.57,
    });
    expect(cards.map((c) => c.label)).toEqual(["Toplam", "Ortalama", "Medyan", "Eğilim Yönü"]);
  });

  it("liste/nesne değerleri (top_n, distribution, ranking, ...) asla karta dönüşmez", () => {
    const cards = buildAnalyticsCards({
      total: 88,
      top_n: [{ label: "Merkez", value: 40 }],
      distribution: { Merkez: 45.5 },
    });
    expect(cards).toHaveLength(1);
    expect(cards[0].label).toBe("Toplam");
  });

  it("tek bir çözülmüş metriği tekrar etmeden ortak kart bağlamı olarak taşır", () => {
    const cards = buildAnalyticsCards(
      { total: 88 },
      { resolvedMetrics: ["monthly_appointment_count"] },
    );
    expect(cards[0].label).toBe("Toplam");
    expect(cards[0].context).toBe("Aylık Randevu Sayısı");
  });

  it("birden fazla çözülmüş metrik varsa önek eklemez (belirsizliği önler)", () => {
    const cards = buildAnalyticsCards(
      { total: 88 },
      { resolvedMetrics: ["appointment_count", "completed_appointment_rate"] },
    );
    expect(cards[0].label).toBe("Toplam");
    expect(cards[0].context).toBeUndefined();
  });

  it("boş/eksik analytics.metrics için çökmeden boş dizi döner", () => {
    expect(buildAnalyticsCards(undefined)).toEqual([]);
    expect(buildAnalyticsCards(null)).toEqual([]);
    expect(buildAnalyticsCards({})).toEqual([]);
  });

  it("limit seçeneğini uygular", () => {
    const cards = buildAnalyticsCards(
      { total: 1, average: 2, median: 3, maximum: 4, minimum: 5 },
      { limit: 2 },
    );
    expect(cards).toHaveLength(2);
  });
});
