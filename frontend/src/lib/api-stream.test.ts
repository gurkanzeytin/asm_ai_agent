import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, generateReportStream } from "./api";

const turkishEmptyReport = "# Sonuç Bulunamadı\n\nBelirtilen kriterlere uygun kayıt bulunamadı.";

function completeData(overrides: Record<string, unknown> = {}) {
  return {
    success: true,
    question: "Sadece gerçekleşenleri göster.",
    outcome: "NO_RESULT_GUIDANCE",
    query_result: { columns: [], rows: [], row_count: 0 },
    report: { title: "Sonuç Bulunamadı", markdown: turkishEmptyReport },
    analytics: null,
    insights: null,
    visualization: null,
    ...overrides,
  };
}

function responseFromLines(lines: string[], status = 200) {
  return new Response(`${lines.join("\n")}\n`, {
    status,
    headers: { "Content-Type": "application/x-ndjson" },
  });
}

function event(type: string, value: Record<string, unknown>) {
  return JSON.stringify({ type, ...value });
}

afterEach(() => vi.unstubAllGlobals());

describe("generateReportStream terminal delivery", () => {
  it("accepts the live zero-row complete event without optional analysis fields", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          responseFromLines([
            event("progress", { stage: "understanding" }),
            event("complete", { data: completeData() }),
          ]),
        ),
    );
    const progress: string[] = [];

    const parsed = await generateReportStream("Soru", "same-session", (stage) =>
      progress.push(stage),
    );

    expect(progress).toEqual(["understanding"]);
    expect(parsed.outcome).toBe("NO_RESULT_GUIDANCE");
    expect(parsed.query_result?.rows).toEqual([]);
    expect(parsed.report?.markdown).toContain("kayıt bulunamadı");
  });

  it("accepts a successful complete event with rows", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        responseFromLines([
          event("complete", {
            data: completeData({
              outcome: "EXECUTE_SQL",
              query_result: { columns: ["count"], rows: [{ count: 3 }], row_count: 1 },
              report: { markdown: "Toplam 3 kayıt bulundu." },
            }),
          }),
        ]),
      ),
    );

    const parsed = await generateReportStream("Soru", "session", () => undefined);
    expect(parsed.query_result?.rows).toEqual([{ count: 3 }]);
    expect(parsed.report?.markdown).toBe("Toplam 3 kayıt bulundu.");
  });

  it("accepts SAFE_ERROR complete events with controlled report text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        responseFromLines([
          event("complete", {
            data: completeData({
              success: false,
              outcome: "SAFE_ERROR",
              report: { markdown: "İstek güvenli biçimde tamamlanamadı." },
            }),
          }),
        ]),
      ),
    );

    const parsed = await generateReportStream("Soru", "session", () => undefined);
    expect(parsed.outcome).toBe("SAFE_ERROR");
    expect(parsed.report?.markdown).not.toBe("");
  });

  it("rejects an explicit workflow error terminal event", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          responseFromLines([
            event("error", { error_code: "WORKFLOW_ERROR", message: "İş akışı başarısız." }),
          ]),
        ),
    );

    await expect(generateReportStream("Soru", "session", () => undefined)).rejects.toMatchObject({
      name: "ApiError",
      code: "WORKFLOW_ERROR",
    });
  });

  it("rejects malformed NDJSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(responseFromLines(["{not-json"])));

    await expect(generateReportStream("Soru", "session", () => undefined)).rejects.toBeInstanceOf(
      ApiError,
    );
  });

  it("rejects a stream that closes without a terminal event", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(responseFromLines([event("progress", { stage: "reporting" })])),
    );

    await expect(generateReportStream("Soru", "session", () => undefined)).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });
});
