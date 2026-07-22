import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InfoPanel } from "./InfoPanel";

describe("InfoPanel", () => {
  it("yanıt süresini gösterir; model ve token bilgilerini göstermez", () => {
    render(<InfoPanel open responseMs={1250} isThinking={false} sql={null} />);

    expect(screen.getByText("1.25s")).toBeTruthy();
    expect(screen.queryByText(/token/i)).toBeNull();
    expect(screen.queryByText(/model/i)).toBeNull();
  });

  it("SQL sorgusunu tek tıkla kopyalar ve ikinci panel oku göstermez", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(<InfoPanel open responseMs={1250} isThinking={false} sql="SELECT 1" />);

    fireEvent.click(screen.getByRole("button", { name: "SQL sorgusunu kopyala" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("SELECT 1"));

    expect(screen.queryByRole("button", { name: "Paneli kapat" })).toBeNull();
  });
});
