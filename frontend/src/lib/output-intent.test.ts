import { describe, expect, it } from "vitest";
import { buildResponseContent, inferResponseMode, visibleSections } from "./output-intent";

describe("output intent", () => {
  it("detects real Turkish chart suffixes without backend mode", () => {
    expect(
      inferResponseMode("\u015eubelere g\u00f6re randevu grafi\u011fi \u00e7iz", {
        success: true,
        question: "\u015eubelere g\u00f6re randevu grafi\u011fi \u00e7iz",
      }),
    ).toBe("visualization");
  });

  it("keeps backend visible section contract as the source of truth", () => {
    expect(
      visibleSections({
        success: true,
        question: "q",
        visible_sections: ["sql", "table", "unknown"],
      }),
    ).toEqual(["sql", "table"]);
  });

  it("prefixes answer text when prior context was applied", () => {
    expect(
      buildResponseContent(
        {
          success: true,
          question: "Bunu randevu durumuna göre dağıtır mısın?",
          context_applied: true,
          report: { markdown: "# Yanıt\n\nToplam 5 durum bulundu." },
        },
        "answer",
      ),
    ).toBe("_Önceki cevaptaki kapsam kullanıldı._\n\n# Yanıt\n\nToplam 5 durum bulundu.");
  });

  it("does not prefix SQL-only responses with context text", () => {
    expect(
      buildResponseContent(
        {
          success: true,
          question: "Bunun SQL sorgusunu ver",
          context_applied: true,
          generated_sql: "SELECT 1;",
          report: { markdown: "# Yanıt\n\nSQL aşağıda." },
        },
        "sql",
      ),
    ).toBe("SELECT 1;");
  });

  it("shows context notice for table-only responses without answer markdown", () => {
    expect(
      buildResponseContent(
        {
          success: true,
          question: "Bunları bölümlere göre ilk 5 olacak şekilde sırala.",
          context_applied: true,
          visible_sections: ["table"],
          report: { markdown: "# Sonuçlar\n\n| Bölüm | Toplam Randevu |" },
        },
        "data",
      ),
    ).toBe("_Önceki cevaptaki kapsam kullanıldı._");
  });
});
