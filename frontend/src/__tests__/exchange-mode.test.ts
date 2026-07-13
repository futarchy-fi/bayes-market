import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { EXCHANGE_MODE_KEY, resolveExchangeMode } from "@/lib/exchangeMode";

describe("exchange mode flag", () => {
  beforeEach(() => localStorage.removeItem(EXCHANGE_MODE_KEY));
  afterEach(() => localStorage.clear());

  it("defaults ON (apex swap) and ?exchange=0 persists the paper opt-out", () => {
    expect(resolveExchangeMode("", localStorage)).toBe(true);
    expect(resolveExchangeMode("?exchange=0", localStorage)).toBe(false);
    expect(localStorage.getItem(EXCHANGE_MODE_KEY)).toBe("0");
    expect(resolveExchangeMode("", localStorage)).toBe(false);
  });

  it("clears the paper opt-out with ?exchange=1", () => {
    localStorage.setItem(EXCHANGE_MODE_KEY, "0");
    expect(resolveExchangeMode("?exchange=1", localStorage)).toBe(true);
    expect(localStorage.getItem(EXCHANGE_MODE_KEY)).toBeNull();
  });
});
