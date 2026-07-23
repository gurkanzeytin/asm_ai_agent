import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SqlResultsTable, type SqlResult } from "./SqlResultsTable";

const baseData: SqlResult = {
  columns: ["SubeAdi", "appointment_duration_average", "completed_appointment_rate"],
  rows: [
    { SubeAdi: "Merkez", appointment_duration_average: 67, completed_appointment_rate: 96.04 },
    { SubeAdi: "Kadıköy", appointment_duration_average: 45, completed_appointment_rate: 88.1 },
  ],
};

describe("SqlResultsTable — sütun etiketleri (AI-INTELLIGENCE-013)", () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn().mockReturnValue("blob:mock");
    URL.revokeObjectURL = vi.fn();
  });

  it("başlıklarda Türkçe etiketleri gösterir, ham SQL/backend anahtarlarını değil", () => {
    render(<SqlResultsTable data={baseData} />);

    expect(screen.getByRole("columnheader", { name: /Şube/ })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: /Ortalama Randevu Süresi/ })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: /Gerçekleşme Oranı/ })).toBeTruthy();

    const table = screen.getByRole("table");
    expect(within(table).queryByText("SubeAdi")).toBeNull();
    expect(within(table).queryByText("appointment_duration_average")).toBeNull();
    expect(within(table).queryByText("completed_appointment_rate")).toBeNull();
  });

  it("hücre verilerini biçimlendirilmiş şekilde gösterir (ham değer değişmez, sadece görünüm)", () => {
    render(<SqlResultsTable data={baseData} />);
    expect(screen.getByText("%96")).toBeTruthy();
    expect(screen.getByText("67 dakika")).toBeTruthy();
  });

  it("sıralama ham anahtar üzerinden çalışır: başlığa tıklamak aria-sort günceller", () => {
    render(<SqlResultsTable data={baseData} />);
    const header = screen.getByRole("columnheader", { name: /Şube/ });
    expect(header.getAttribute("aria-sort")).toBe("none");
    fireEvent.click(within(header).getByRole("button", { name: /Şube sütununu artan sırala/ }));
    expect(header.getAttribute("aria-sort")).toBe("ascending");
  });

  it("filtre başlığı Türkçe etiketi kullanır ama ham sütuna filtre uygular", () => {
    render(<SqlResultsTable data={baseData} />);
    fireEvent.click(screen.getByRole("button", { name: "Şube sütununu filtrele" }));
    expect(screen.getByText("Şube filtresi")).toBeTruthy();
  });

  it("backend'den column_metadata gelmezse çökmez, güvenli etiket türetir", () => {
    const dataWithoutMetadata: SqlResult = {
      columns: ["unknown_backend_column"],
      rows: [{ unknown_backend_column: 1 }],
    };
    render(<SqlResultsTable data={dataWithoutMetadata} />);
    const headers = screen.getAllByRole("columnheader");
    const dataHeader = headers[headers.length - 1];
    expect(dataHeader.textContent).toBeTruthy();
    expect(dataHeader.textContent).not.toContain("_");
  });

  it("hiçbir görünür başlıkta ham snake_case tanımlayıcı kalmaz", () => {
    render(<SqlResultsTable data={baseData} />);
    const headers = screen.getAllByRole("columnheader");
    for (const header of headers) {
      expect(header.textContent ?? "").not.toMatch(/[a-z]+_[a-z]+/);
    }
  });

  it("SQL sonucunu geniş inceleme görünümünde açar", () => {
    render(<SqlResultsTable data={baseData} />);
    fireEvent.click(screen.getByRole("button", { name: "Tam ekran incele" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeTruthy();
    expect(screen.getByText("SQL Sonucu - Geniş Görünüm")).toBeTruthy();
    expect(within(dialog).getByRole("table")).toBeTruthy();
  });
  it("chart-only modda tablo kabugunu ve tablo kontrollerini gizler", () => {
    render(
      <SqlResultsTable data={{ ...baseData, visualization: "BAR_CHART" }} displayMode="chart" />,
    );

    expect(screen.getByText("Grafik")).toBeTruthy();
    expect(screen.queryByText("SQL Sonucu")).toBeNull();
    expect(screen.queryByPlaceholderText("Satırlarda ara")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("SqlResultsTable chart-only scalar metric", () => {
  it("tek sayisal sonucu tablo yerine metrik kart olarak gosterir", () => {
    render(
      <SqlResultsTable
        data={{
          columns: ["appointment_count"],
          rows: [{ appointment_count: 42 }],
          visualization: "BAR_CHART",
        }}
        displayMode="chart"
      />,
    );

    expect(screen.getByText("Grafik")).toBeTruthy();
    expect(screen.getByText("Tek değerli sonuç")).toBeTruthy();
    expect(screen.getByText("42 randevu")).toBeTruthy();
    expect(screen.getByText("Toplam Randevu")).toBeTruthy();
    expect(screen.queryByPlaceholderText("Satırlarda ara")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("SqlResultsTable — DOCTOR-DISPLAY-NAME-ENRICHMENT-001 hidden columns", () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn().mockReturnValue("blob:mock");
    URL.revokeObjectURL = vi.fn();
  });

  const doctorData: SqlResult = {
    columns: ["DoktorAdi", "DoktorId", "appointment_count"],
    rows: [
      { DoktorAdi: "ÇAĞATAY ÖKTENLİ", DoktorId: 7773, appointment_count: 43232 },
      { DoktorAdi: "NAMIK KEMAL AKPINAR", DoktorId: 2549, appointment_count: 120 },
    ],
    columnMetadata: [
      { key: "DoktorAdi", label: "Doktor", format: "text", unit: null },
      { key: "DoktorId", label: "Doktor", format: "text", unit: null, hidden: true },
      { key: "appointment_count", label: "Randevu Sayısı", format: "integer", unit: null },
    ],
  };

  it("hides a column flagged hidden by backend column_metadata by default", () => {
    render(<SqlResultsTable data={doctorData} />);
    expect(screen.getByRole("columnheader", { name: /Doktor/ })).toBeTruthy();
    expect(screen.queryByText("7773")).toBeNull();
    expect(screen.getByText("ÇAĞATAY ÖKTENLİ")).toBeTruthy();
  });

  it("does not hide DoktorId when column_metadata does not flag it", () => {
    const visibleIdData: SqlResult = {
      ...doctorData,
      columnMetadata: doctorData.columnMetadata?.map((m) =>
        m.key === "DoktorId" ? { ...m, hidden: false } : m,
      ),
    };
    render(<SqlResultsTable data={visibleIdData} />);
    expect(screen.getByText("7773")).toBeTruthy();
  });
});

describe("SqlResultsTable — result-size safety", () => {
  it("backend yanlışlıkla daha fazlasını gönderse de en fazla 100 veri satırı render eder", () => {
    const rows = Array.from({ length: 150 }, (_, index) => ({
      SubeAdi: `Şube ${index}`,
      appointment_count: index,
    }));

    render(
      <SqlResultsTable
        data={{
          columns: ["SubeAdi", "appointment_count"],
          rows,
          resultTruncated: true,
          hasMore: true,
        }}
      />,
    );

    const dataRows = within(screen.getByRole("table")).getAllByRole("button", {
      name: /satırın detaylarını görüntüle/,
    });
    expect(dataRows).toHaveLength(100);
    expect(screen.queryByText("Şube 100")).toBeNull();
  });

  it("kesilme uyarısını ve bilinmeyen toplam için daha-fazla mesajını gösterir", () => {
    render(
      <SqlResultsTable
        data={{
          columns: ["appointment"],
          rows: Array.from({ length: 100 }, (_, index) => ({ appointment: index })),
          resultTruncated: true,
          hasMore: true,
        }}
      />,
    );

    expect(screen.getByRole("status").textContent).toContain("İlk 100 sonuç gösteriliyor");
    expect(screen.getByRole("status").textContent).toContain("Daha fazla sonuç bulunmaktadır");
  });

  it("Önceki, Sonraki ve Sayfa kontrolleriyle güvenli sayfalar arasında gezinir", () => {
    render(
      <SqlResultsTable
        pageSize={20}
        data={{
          columns: ["department"],
          rows: Array.from({ length: 42 }, (_, index) => ({ department: `Bölüm ${index}` })),
          resultGroupCount: 42,
        }}
      />,
    );

    expect(screen.getByText("Bölüm 0")).toBeTruthy();
    expect(screen.getByText(/Sayfa 1/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Sonraki sayfa" }));
    expect(screen.queryByText("Bölüm 0")).toBeNull();
    expect(screen.getByText("Bölüm 20")).toBeTruthy();
    expect(screen.getAllByText(/Sayfa 2/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Önceki sayfa" })).toBeTruthy();
  });

  it("42 satırlık gruplu sonucu kesmeden erişilebilir tutar", () => {
    render(
      <SqlResultsTable
        data={{
          columns: ["department"],
          rows: Array.from({ length: 42 }, (_, index) => ({ department: `Bölüm ${index}` })),
          resultGroupCount: 42,
        }}
      />,
    );

    expect(
      within(screen.getByRole("table")).getAllByRole("button", {
        name: /satırın detaylarını görüntüle/,
      }),
    ).toHaveLength(42);
    expect(screen.queryByRole("status")).toBeNull();
  });
});
