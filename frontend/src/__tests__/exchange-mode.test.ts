import { afterEach, describe, expect, it } from "vitest";
import { EXCHANGE_MODE_KEY, resolveExchangeMode } from "@/lib/exchangeMode";

describe("exchange mode flag", () => {
  afterEach(() => localStorage.clear());

  it("defaults off and persists ?exchange=1", () => {
    expect(resolveExchangeMode("", localStorage)).toBe(false);
    expect(resolveExchangeMode("?exchange=1", localStorage)).toBe(true);
    expect(localStorage.getItem(EXCHANGE_MODE_KEY)).toBe("1");
    expect(resolveExchangeMode("", localStorage)).toBe(true);
  });

  it("clears the persisted flag with ?exchange=0", () => {
    localStorage.setItem(EXCHANGE_MODE_KEY, "1");
    expect(resolveExchangeMode("?exchange=0", localStorage)).toBe(false);
    expect(localStorage.getItem(EXCHANGE_MODE_KEY)).toBeNull();
  });
});
