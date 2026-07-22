import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MedAgentLogo } from "./MedAgentLogo";

describe("MedAgentLogo", () => {
  it("tüm logo yüzeylerinde merkezi SVG assetini kullanır", () => {
    const { container } = render(<MedAgentLogo size={72} noIntro />);

    const logo = screen.getByRole("img", { name: "Med Agent logosu" });
    expect(logo.getAttribute("src")).toBe("/med-agent-logo.svg?v=3");
    expect(logo.getAttribute("width")).toBe("72");
    expect(logo.parentElement?.className).toContain("overflow-hidden");
    expect(container.querySelector("svg")).toBeNull();
  });
});
