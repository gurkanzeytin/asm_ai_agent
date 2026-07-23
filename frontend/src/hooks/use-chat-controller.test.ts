import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { generateReportStream } from "@/lib/api";
import { shouldShowSqlTable, useChatController } from "./use-chat-controller";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    info: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  generateReportStream: vi.fn(),
}));

const mockedGenerateReport = vi.mocked(generateReportStream);

describe("useChatController", () => {
  beforeEach(() => {
    mockedGenerateReport.mockReset();
  });

  it("passes the conversation id as backend session context", async () => {
    mockedGenerateReport.mockResolvedValue({
      success: true,
      question: "Soru",
      report: { markdown: "Yanıt" },
    });
    const { result } = renderHook(() => useChatController());

    await act(async () => {
      await result.current.send("Soru");
    });

    expect(mockedGenerateReport).toHaveBeenCalledWith(
      "Soru",
      "initial-conversation",
      expect.any(Function),
      expect.any(AbortSignal),
    );
    expect(result.current.messages.at(-1)).toMatchObject({
      role: "assistant",
      content: "Yanıt",
      streaming: false,
    });
  });

  it("LIVE-FOLLOWUP-NO-RESPONSE-FORENSICS-003: a zero-row follow-up in the same conversation still renders a visible terminal answer", async () => {
    mockedGenerateReport.mockResolvedValueOnce({
      success: true,
      question: "Ocak 2026 için doktor bazında randevu sayılarını göster.",
      outcome: "EXECUTE_SQL",
      generated_sql:
        "SELECT DoktorId, COUNT(*) AS appointment_count FROM dbo.vw_RandevuRaporu GROUP BY DoktorId",
      query_result: {
        columns: ["DoktorId", "appointment_count"],
        rows: [{ DoktorId: 42, appointment_count: 3 }],
        row_count: 1,
      },
      report: { markdown: "# Doktor Bazında Randevu Sayıları\n\nDoktor 42: 3 randevu." },
    });
    mockedGenerateReport.mockResolvedValueOnce({
      success: true,
      question: "Yalnız gerçekleşenleri göster.",
      outcome: "NO_RESULT_GUIDANCE",
      generated_sql:
        "SELECT DoktorId, COUNT(*) AS appointment_count FROM dbo.vw_RandevuRaporu " +
        "WHERE RandevuDurumu = N'Gerçekleşti' GROUP BY DoktorId",
      query_result: { columns: [], rows: [], row_count: 0 },
      report: {
        title: "Sonuç Bulunamadı",
        markdown: "Belirtilen kriterlere uygun kayıt bulunamadı.",
      },
    });
    const { result } = renderHook(() => useChatController());

    await act(async () => {
      await result.current.send("Ocak 2026 için doktor bazında randevu sayılarını göster.");
    });
    await act(async () => {
      await result.current.send("Yalnız gerçekleşenleri göster.");
    });

    expect(mockedGenerateReport).toHaveBeenCalledTimes(2);
    const firstSessionId = mockedGenerateReport.mock.calls[0][1];
    const secondSessionId = mockedGenerateReport.mock.calls[1][1];
    // Same conversation both turns: the frontend must never mint a fresh
    // session id for a follow-up sent into the same active conversation.
    expect(secondSessionId).toBe(firstSessionId);

    const assistantMessages = result.current.messages.filter((m) => m.role === "assistant");
    expect(assistantMessages).toHaveLength(2);
    const secondAnswer = assistantMessages[1];
    // The actual live symptom under investigation: turn 2 must render a
    // non-empty, non-streaming, non-error terminal message — never a blank
    // or perpetually-loading placeholder.
    expect(secondAnswer.streaming).toBe(false);
    expect(secondAnswer.status).toBe("success");
    expect(secondAnswer.content.trim()).not.toBe("");
    expect(secondAnswer.content).toBe("Belirtilen kriterlere uygun kayıt bulunamadı.");
  });

  it("finishes the assistant message when generation is stopped", async () => {
    mockedGenerateReport.mockImplementation(
      (_question, _sessionId, _onProgress, signal) =>
        new Promise((_resolve, reject) => {
          signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        }),
    );
    const { result } = renderHook(() => useChatController());

    act(() => {
      void result.current.send("Uzun rapor");
    });
    await waitFor(() => expect(result.current.isGenerating).toBe(true));

    act(() => result.current.stop());

    await waitFor(() => expect(result.current.isGenerating).toBe(false));
    expect(result.current.messages.at(-1)).toMatchObject({
      role: "assistant",
      streaming: false,
      status: "stopped",
      prompt: "Uzun rapor",
    });
    expect(result.current.messages.at(-1)?.content).not.toBe("");
  });

  it("failed requests retain their prompt for retry and editing", async () => {
    mockedGenerateReport.mockRejectedValue(new Error("network"));
    const { result } = renderHook(() => useChatController());

    await act(async () => {
      await result.current.send("Tekrar kullanılacak soru");
    });

    expect(result.current.messages.at(-1)).toMatchObject({
      role: "assistant",
      status: "error",
      streaming: false,
      prompt: "Tekrar kullanılacak soru",
    });
  });

  it("renders a controlled backend error report instead of hiding it behind a generic card", async () => {
    mockedGenerateReport.mockResolvedValue({
      success: false,
      question: "Soru",
      outcome: "SAFE_ERROR",
      report: { markdown: "Veri kaynağına şu anda bağlanılamıyor." },
    });
    const { result } = renderHook(() => useChatController());

    await act(async () => result.current.send("Soru"));

    expect(result.current.messages.at(-1)).toMatchObject({
      role: "assistant",
      content: "Veri kaynağına şu anda bağlanılamıyor.",
      status: "success",
      streaming: false,
    });
  });

  it("replaces the loading placeholder with visible NO_RESULT_GUIDANCE text", async () => {
    mockedGenerateReport.mockResolvedValue({
      success: true,
      question: "Sadece gerçekleşenleri göster.",
      outcome: "NO_RESULT_GUIDANCE",
      query_result: { columns: [], rows: [], row_count: 0 },
      report: {
        title: "Sonuç Bulunamadı",
        markdown: "Belirtilen kriterlere uygun kayıt bulunamadı.",
      },
      analytics: null,
      insights: null,
      visualization: null,
    });
    const { result } = renderHook(() => useChatController());

    let sending!: Promise<void>;
    act(() => {
      sending = result.current.send("Sadece gerçekleşenleri göster.");
    });
    expect(result.current.messages.at(-1)).toMatchObject({
      role: "assistant",
      content: "",
      streaming: true,
    });

    await act(async () => sending);

    expect(result.current.messages.at(-1)).toMatchObject({
      role: "assistant",
      content: "Belirtilen kriterlere uygun kayıt bulunamadı.",
      streaming: false,
      status: "success",
      showSqlTable: false,
    });
  });

  it("ignores a stale progress callback after the terminal message commits", async () => {
    let staleProgress!: (stage: "reporting") => void;
    mockedGenerateReport.mockImplementation(async (_question, _sessionId, onProgress) => {
      staleProgress = onProgress as typeof staleProgress;
      return {
        success: true,
        question: "Sadece gerçekleşenleri göster.",
        outcome: "NO_RESULT_GUIDANCE",
        query_result: { columns: [], rows: [], row_count: 0 },
        report: { markdown: "Sonuç bulunamadı ancak rapor görünür kalmalı." },
      };
    });
    const { result } = renderHook(() => useChatController());

    await act(async () => result.current.send("Sadece gerçekleşenleri göster."));
    act(() => staleProgress("reporting"));

    expect(result.current.messages.at(-1)).toMatchObject({
      role: "assistant",
      content: "Sonuç bulunamadı ancak rapor görünür kalmalı.",
      streaming: false,
      status: "success",
      progressStage: undefined,
    });
    expect(result.current.isGenerating).toBe(false);
  });

  it("uses backend workflow timing for response duration and SQL timing for the table", async () => {
    mockedGenerateReport.mockResolvedValue({
      success: true,
      question: "Soru",
      generated_sql: "SELECT 1",
      query_result: {
        columns: ["değer"],
        rows: [{ değer: 1 }],
        row_count: 1,
      },
      report: { markdown: "Yanıt" },
      metadata: {
        provider: "test",
        model: "report-model",
        latency_ms: 210,
      },
      timing: {
        execute_sql_ms: 87,
        total_ms: 4321,
      },
      visualization: { type: "LINE_CHART", reason: "Zaman serisi" },
    });
    const { result } = renderHook(() => useChatController());

    await act(async () => {
      await result.current.send("Soru");
    });

    expect(result.current.metrics.responseMs).toBe(4321);
    expect(result.current.messages.at(-1)?.metadata?.latencyMs).toBe(4321);
    expect(result.current.messages.at(-1)?.sqlResult?.durationMs).toBe(87);
    expect(result.current.messages.at(-1)?.sqlResult?.visualization).toBe("LINE_CHART");
  });

  it("renders only SQL when the user asks for the SQL query", async () => {
    mockedGenerateReport.mockResolvedValue({
      success: true,
      question: "Sadece SQL sorgusunu ver",
      response_mode: "sql",
      visible_sections: ["sql"],
      generated_sql: "SELECT COUNT(*) AS appointment_count FROM dbo.vw_RandevuRaporu;",
      query_result: {
        columns: ["appointment_count"],
        rows: [{ appointment_count: 42 }],
        row_count: 1,
      },
      report: {
        markdown: "```sql\nSELECT COUNT(*) AS appointment_count FROM dbo.vw_RandevuRaporu;\n```",
      },
    });
    const { result } = renderHook(() => useChatController());

    await act(async () => result.current.send("Sadece SQL sorgusunu ver"));

    const message = result.current.messages.at(-1);
    expect(message?.responseMode).toBe("sql");
    expect(message?.content).toBe(
      "SELECT COUNT(*) AS appointment_count FROM dbo.vw_RandevuRaporu;",
    );
    expect(message?.content).not.toContain("```");
    expect(message?.visibleSections).toEqual(["sql"]);
    expect(message?.showSqlTable).toBe(false);
    expect(message?.showResultInline).toBe(false);
    expect(message?.metricCards).toEqual([]);
  });

  it("shows the result table inline when the user asks to fetch data", async () => {
    mockedGenerateReport.mockResolvedValue({
      success: true,
      question: "Son 100 randevuyu getir",
      response_mode: "data",
      visible_sections: ["table"],
      generated_sql: "SELECT TOP (100) Id, BaslangicTarihi FROM dbo.vw_RandevuRaporu;",
      query_result: {
        columns: ["Id", "BaslangicTarihi"],
        rows: [{ Id: 1, BaslangicTarihi: "2026-01-01T09:00:00" }],
        row_count: 1,
      },
      report: { markdown: "Sonuçlar aşağıda listelenmiştir." },
    });
    const { result } = renderHook(() => useChatController());

    await act(async () => result.current.send("Son 100 randevuyu getir"));

    const message = result.current.messages.at(-1);
    expect(message?.responseMode).toBe("data");
    expect(message?.content).toBe("");
    expect(message?.showSqlTable).toBe(true);
    expect(message?.showResultInline).toBe(true);
    expect(message?.metricCards).toEqual([]);
  });

  it("opens the visualization result inline when the user asks for a chart", async () => {
    mockedGenerateReport.mockResolvedValue({
      success: true,
      question: "Şubelere göre randevu grafiği çiz",
      generated_sql:
        "SELECT SubeAdi, COUNT(*) AS appointment_count FROM dbo.vw_RandevuRaporu GROUP BY SubeAdi;",
      query_result: {
        columns: ["SubeAdi", "appointment_count"],
        rows: [{ SubeAdi: "Merkez", appointment_count: 42 }],
        row_count: 1,
      },
      report: { markdown: "Grafik aşağıda gösterilmiştir." },
      visualization: { type: "BAR_CHART", reason: "Kategorik karşılaştırma" },
      response_mode: "visualization",
      visible_sections: ["chart"],
      analytics: {
        analytics_type: "distribution",
        intents: [],
        data_shape: "categorical",
        metrics: {},
        insights: {},
        row_count: 1,
        result_shape: "categorical_grouped_result",
      },
    });
    const { result } = renderHook(() => useChatController());

    await act(async () => result.current.send("Şubelere göre randevu grafiği çiz"));

    const message = result.current.messages.at(-1);
    expect(message?.responseMode).toBe("visualization");
    expect(message?.content).toBe("");
    expect(message?.showSqlTable).toBe(true);
    expect(message?.showResultInline).toBe(true);
    expect(message?.metricCards).toEqual([]);
    expect(message?.sqlResult?.visualization).toBe("BAR_CHART");
  });

  it("honors chart-only backend sections without leaking report text", async () => {
    mockedGenerateReport.mockResolvedValue({
      success: true,
      question: "Bunu grafik yap",
      response_mode: "visualization",
      visible_sections: ["chart"],
      generated_sql:
        "SELECT SubeAdi, COUNT(*) AS appointment_count FROM dbo.vw_RandevuRaporu GROUP BY SubeAdi;",
      query_result: {
        columns: ["SubeAdi", "appointment_count"],
        rows: [{ SubeAdi: "Merkez", appointment_count: 42 }],
        row_count: 1,
      },
      report: { markdown: "Bu rapor metni grafik-only istekte görünmemeli." },
      visualization: { type: "BAR_CHART", reason: "Categorical comparison" },
      analytics: {
        analytics_type: "distribution",
        intents: [],
        data_shape: "categorical",
        metrics: {},
        insights: {},
        row_count: 1,
        result_shape: "categorical_grouped_result",
      },
    });
    const { result } = renderHook(() => useChatController());

    await act(async () => result.current.send("Bunu grafik yap"));

    const message = result.current.messages.at(-1);
    expect(message?.responseMode).toBe("visualization");
    expect(message?.visibleSections).toEqual(["chart"]);
    expect(message?.content).toBe("");
    expect(message?.showSqlTable).toBe(true);
    expect(message?.showResultInline).toBe(true);
    expect(message?.metricCards).toEqual([]);
  });

  it("honors answer plus chart without showing SQL text", async () => {
    mockedGenerateReport.mockResolvedValue({
      success: true,
      question: "Subelere gore randevu grafigini ciz ve kisaca yorumla",
      response_mode: "visualization",
      visible_sections: ["answer", "chart"],
      generated_sql:
        "SELECT SubeAdi, COUNT(*) AS appointment_count FROM dbo.vw_RandevuRaporu GROUP BY SubeAdi;",
      query_result: {
        columns: ["SubeAdi", "appointment_count"],
        rows: [{ SubeAdi: "Merkez", appointment_count: 42 }],
        row_count: 1,
      },
      report: { markdown: "Merkez subesinde 42 randevu var." },
      visualization: { type: "BAR_CHART", reason: "Categorical comparison" },
      analytics: {
        analytics_type: "distribution",
        intents: [],
        data_shape: "categorical",
        metrics: {},
        insights: {},
        row_count: 1,
        result_shape: "categorical_grouped_result",
      },
    });
    const { result } = renderHook(() => useChatController());

    await act(async () =>
      result.current.send("Subelere gore randevu grafigini ciz ve kisaca yorumla"),
    );

    const message = result.current.messages.at(-1);
    expect(message?.responseMode).toBe("visualization");
    expect(message?.visibleSections).toEqual(["answer", "chart"]);
    expect(message?.content).toBe("Merkez subesinde 42 randevu var.");
    expect(message?.content).not.toContain("SELECT");
    expect(message?.showSqlTable).toBe(true);
    expect(message?.showResultInline).toBe(true);
  });

  it("shows only requested mixed SQL and table artifacts", async () => {
    mockedGenerateReport.mockResolvedValue({
      success: true,
      question: "SQL sorgusunu yaz ve calistirip tabloyu getir",
      response_mode: "data",
      visible_sections: ["sql", "table"],
      generated_sql: "SELECT TOP (20) Id FROM dbo.vw_RandevuRaporu;",
      query_result: {
        columns: ["Id"],
        rows: [{ Id: 1 }],
        row_count: 1,
      },
      report: { markdown: "Tablo hazir." },
    });
    const { result } = renderHook(() => useChatController());

    await act(async () => result.current.send("SQL sorgusunu yaz ve calistirip tabloyu getir"));

    const message = result.current.messages.at(-1);
    expect(message?.responseMode).toBe("data");
    expect(message?.visibleSections).toEqual(["sql", "table"]);
    expect(message?.content).toBe("SELECT TOP (20) Id FROM dbo.vw_RandevuRaporu;");
    expect(message?.showSqlTable).toBe(true);
    expect(message?.metricCards).toEqual([]);
  });

  it("does not persist conversations in localStorage", () => {
    const storageSpy = vi.spyOn(Storage.prototype, "setItem");
    const { rerender } = renderHook(() => useChatController());

    rerender();

    expect(storageSpy).not.toHaveBeenCalled();
    storageSpy.mockRestore();
  });

  it("renders only backend-approved KPIs for a scalar aggregate", async () => {
    mockedGenerateReport.mockResolvedValue({
      success: true,
      question: "2025 yılının randevu süreleri",
      query_result: {
        columns: ["appointment_duration_average"],
        rows: [{ appointment_duration_average: 31.85 }],
        row_count: 1,
      },
      report: { markdown: "Ortalama randevu süresi 31,9 dakikadır." },
      analytics: {
        analytics_type: "average",
        intents: ["average"],
        data_shape: "single_value",
        metrics: {
          count: 1,
          total: 31.85,
          average: 31.85,
          median: 31.85,
          minimum: 31.85,
          maximum: 31.85,
        },
        insights: {},
        row_count: 1,
        technical_row_count: 1,
        business_record_count: null,
        result_shape: "scalar_aggregate",
        aggregate_result: true,
        displayable_kpis: [
          {
            key: "appointment_duration_average",
            label: "Ortalama Randevu Süresi",
            value: 31.85,
            format: "duration",
            unit: "dakika",
          },
        ],
      },
    });
    const { result } = renderHook(() => useChatController());

    await act(async () => result.current.send("2025 yılının randevu süreleri"));

    expect(result.current.messages.at(-1)?.metricCards).toEqual([
      { label: "Ortalama Randevu Süresi", value: "31,9 dk" },
    ]);
  });

  it("uses raw aggregate columns as the safe scalar fallback", async () => {
    mockedGenerateReport.mockResolvedValue({
      success: true,
      question: "randevu metrikleri",
      query_result: {
        columns: ["appointment_count", "appointment_duration_average"],
        rows: [{ appointment_count: 12345, appointment_duration_average: 31.85 }],
        row_count: 1,
      },
      report: { markdown: "Yanıt" },
      analytics: {
        analytics_type: "summary",
        intents: [],
        data_shape: "single_row",
        metrics: { count: 1, total: 31.85 },
        insights: {},
        row_count: 1,
        result_shape: "multi_metric_scalar_aggregate",
      },
    });
    const { result } = renderHook(() => useChatController());

    await act(async () => result.current.send("randevu metrikleri"));

    expect(result.current.messages.at(-1)?.metricCards?.map((card) => card.label)).toEqual([
      "Toplam Randevu",
      "Ortalama Randevu Süresi",
    ]);
  });

  it("oversized API payloads are bounded to 100 rows before message state", async () => {
    mockedGenerateReport.mockResolvedValue({
      success: true,
      question: "tüm randevuları listele",
      query_result: {
        columns: ["appointment"],
        rows: Array.from({ length: 500 }, (_, index) => ({ appointment: index })),
        row_count: 500,
        returned_row_count: 500,
        displayed_row_count: 100,
        result_truncated: true,
        has_more: true,
      },
      report: { markdown: "İlk 100 sonuç gösteriliyor." },
      analytics: {
        analytics_type: "list",
        intents: [],
        data_shape: "tabular",
        metrics: {},
        insights: {},
        row_count: 500,
        result_shape: "raw_record_rows",
      },
    });
    const { result } = renderHook(() => useChatController());

    await act(async () => result.current.send("tüm randevuları listele"));

    const sqlResult = result.current.messages.at(-1)?.sqlResult;
    expect(sqlResult?.rows).toHaveLength(100);
    expect(sqlResult?.resultTruncated).toBe(true);
    expect(sqlResult?.hasMore).toBe(true);
    expect(result.current.messages.at(-1)?.showSqlTable).toBe(true);
  });

  it.each(["OUT_OF_SCOPE", "ASK_CLARIFICATION", "NO_RESULT_GUIDANCE", "SAFE_ERROR"])(
    "%s sonucunda tabloyu gizler",
    (outcome) => {
      expect(
        shouldShowSqlTable(
          { success: true, question: "soru", outcome },
          { columns: ["value"], rows: [{ value: 1 }] },
        ),
      ).toBe(false);
    },
  );

  it("scalar aggregate sonucunda tabloyu gizler", () => {
    expect(
      shouldShowSqlTable(
        {
          success: true,
          question: "kaç",
          analytics: {
            analytics_type: "count",
            intents: [],
            data_shape: "single_value",
            metrics: {},
            insights: {},
            row_count: 1,
            result_shape: "scalar_aggregate",
          },
        },
        { columns: ["appointment_count"], rows: [{ appointment_count: 42 }] },
      ),
    ).toBe(false);
  });
});
