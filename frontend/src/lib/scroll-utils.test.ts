import { describe, expect, it } from "vitest";
import { isNearScrollBottom } from "./scroll-utils";

describe("isNearScrollBottom", () => {
  it("alt eşiğin içindeki konumu yakın kabul eder", () => {
    expect(isNearScrollBottom({ scrollTop: 810, scrollHeight: 1000, clientHeight: 120 })).toBe(
      true,
    );
  });

  it("eski mesajları okuyan kullanıcıyı altta kabul etmez", () => {
    expect(isNearScrollBottom({ scrollTop: 300, scrollHeight: 1000, clientHeight: 400 })).toBe(
      false,
    );
  });
});
