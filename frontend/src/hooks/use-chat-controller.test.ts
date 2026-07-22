import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { generateReport } from "@/lib/api";
import { useChatController } from "./use-chat-controller";

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
  generateReport: vi.fn(),
}));

const mockedGenerateReport = vi.mocked(generateReport);

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
      expect.any(AbortSignal),
    );
    expect(result.current.messages.at(-1)).toMatchObject({
      role: "assistant",
      content: "Yanıt",
      streaming: false,
    });
  });

  it("finishes the assistant message when generation is stopped", async () => {
    mockedGenerateReport.mockImplementation(
      (_question, _sessionId, signal) =>
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

  it("does not persist conversations in localStorage", () => {
    const storageSpy = vi.spyOn(Storage.prototype, "setItem");
    const { rerender } = renderHook(() => useChatController());

    rerender();

    expect(storageSpy).not.toHaveBeenCalled();
    storageSpy.mockRestore();
  });
});
