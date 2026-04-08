import { describe, it, expect } from "vitest";
import { formatProbability, formatCurrency, truncateHash, statusColor } from "@/lib/utils/format";

describe("formatProbability", () => {
  it("formats 0.65 as 65.0%", () => expect(formatProbability(0.65)).toBe("65.0%"));
  it("formats 0.01 as 1.0%", () => expect(formatProbability(0.01)).toBe("1.0%"));
  it("formats 0.999 as 99.9%", () => expect(formatProbability(0.999)).toBe("99.9%"));
});

describe("formatCurrency", () => {
  it("formats large numbers with K suffix", () => expect(formatCurrency(45000)).toBe("45.0K"));
  it("formats millions with M suffix", () => expect(formatCurrency(1500000)).toBe("1.5M"));
  it("formats small numbers with decimals", () => expect(formatCurrency(42.5)).toBe("42.50"));
});

describe("truncateHash", () => {
  it("truncates sha256 hashes", () => {
    expect(truncateHash("sha256:abcdef0123456789")).toBe("sha256:abcdef01…");
  });
  it("leaves short strings alone", () => {
    expect(truncateHash("short")).toBe("short");
  });
});

describe("statusColor", () => {
  it("returns green for active", () => expect(statusColor("active")).toBe("var(--color-active)"));
  it("returns blue for resolved", () => expect(statusColor("resolved")).toBe("var(--color-resolved)"));
  it("returns muted for unknown", () => expect(statusColor("unknown")).toBe("var(--color-text-muted)"));
});
