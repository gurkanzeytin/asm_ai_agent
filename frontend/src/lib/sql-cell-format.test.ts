import { describe, expect, it } from "vitest";
import { formatSqlCell } from "./sql-cell-format";

describe("formatSqlCell", () => {
  it("sayıları Türkçe binlik ayracıyla biçimler", () => {
    expect(formatSqlCell("hasta_sayisi", 1250000).display).toBe("1.250.000");
  });

  it("oran alanlarını yüzde olarak biçimler", () => {
    expect(formatSqlCell("gerceklesme_orani", 73.4).display).toBe("%73,4");
  });

  it("ISO tarihini Türkçe gösterip ham değeri korur", () => {
    const result = formatSqlCell("tarih", "2026-07-21");
    expect(result.display).toBe("21.07.2026");
    expect(result.raw).toBe("2026-07-21");
  });

  it("boş değeri sakin bir çizgiyle gösterir", () => {
    expect(formatSqlCell("değer", null)).toMatchObject({ display: "—", kind: "null" });
  });

  it("column_metadata format ipucuyla yüzde biçimler", () => {
    const result = formatSqlCell("completed_appointment_rate", 96, "percentage", "%");
    expect(result.display).toBe("%96");
    expect(result.raw).toBe("96");
  });

  it("column_metadata format ipucuyla süreyi birimiyle biçimler", () => {
    const result = formatSqlCell("appointment_duration_average", 67, "duration", "dakika");
    expect(result.display).toBe("67 dakika");
  });

  it("ham değeri asla mutasyona uğratmaz", () => {
    const result = formatSqlCell("completed_appointment_rate", 96.456, "percentage", "%");
    expect(result.raw).toBe("96.456");
  });
});
