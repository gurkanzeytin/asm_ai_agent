import { describe, expect, it } from "vitest";
import { inferResponseMode, visibleSections } from "./output-intent";

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
});
