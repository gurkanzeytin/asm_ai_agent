import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useAnimatedText } from "./animated-text";

describe("useAnimatedText", () => {
  afterEach(() => vi.useRealTimers());

  it("renders historical responses immediately when animation is disabled", () => {
    const { result } = renderHook(() => useAnimatedText("Tam yanıt", "", 0.012, false));
    expect(result.current).toBe("Tam yanıt");
  });

  it("finishes long responses within the maximum animation duration", () => {
    vi.useFakeTimers();
    const text = "A".repeat(5000);
    const { result } = renderHook(() => useAnimatedText(text, "", 0.012, true, 1200));

    act(() => vi.advanceTimersByTime(1250));

    expect(result.current).toBe(text);
  });
});
