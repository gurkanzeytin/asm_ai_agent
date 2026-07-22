import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, generateReport, generateReportStream } from "./api";

describe("generateReport", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("accepts a response matching the consumed API contract", async () => {
    const payload = {
      success: true,
      question: "Soru",
      generated_sql: null,
      query_result: null,
      report: { markdown: "Yanıt" },
      metadata: null,
      timing: null,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload }),
    );

    await expect(generateReport("Soru", "conversation-1")).resolves.toMatchObject(payload);
  });

  it("rejects malformed successful responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ success: true, question: "Soru", query_result: { rows: [] } }),
      }),
    );

    await expect(generateReport("Soru", "conversation-1")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("generateReportStream", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reads progress events and returns the completed report", async () => {
    const encoder = new TextEncoder();
    const payload = {
      success: true,
      question: "Soru",
      report: { markdown: "Yanıt" },
    };
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            `${JSON.stringify({ type: "progress", stage: "executing_sql" })}\n${JSON.stringify({ type: "complete", data: payload })}\n`,
          ),
        );
        controller.close();
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status: 200 })));
    const onProgress = vi.fn();

    await expect(generateReportStream("Soru", "conversation-1", onProgress)).resolves.toMatchObject(
      payload,
    );
    expect(onProgress).toHaveBeenCalledWith("executing_sql");
  });

  it("preserves structured stream error codes", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            `${JSON.stringify({ type: "error", error_code: "SQL_GENERATION_ERROR", message: "failed" })}\n`,
          ),
        );
        controller.close();
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status: 200 })));

    await expect(generateReportStream("Soru", "conversation-1", vi.fn())).rejects.toMatchObject({
      code: "SQL_GENERATION_ERROR",
    });
  });
});
