import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("med-agent-logo.svg", () => {
  it("bitmap, maske veya arka plan katmanı içermeyen saf vektördür", () => {
    const svg = readFileSync(resolve("public/med-agent-logo.svg"), "utf8");

    expect(svg).toContain('viewBox="0 0 564 638"');
    expect(svg).toContain("<linearGradient");
    expect(svg).toContain("<path");
    expect(svg).not.toContain("<image");
    expect(svg).not.toContain("<mask");
    expect(svg).not.toContain("data:image");
    expect(svg).not.toContain("<rect");
  });
});
