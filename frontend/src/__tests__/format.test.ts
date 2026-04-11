import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { formatProbability, formatCurrency, truncateHash, statusColor, formatRelativeTime, timeUntil } from "@/lib/utils/format";

describe("formatProbability", () => {
  it("formats 0.65 as 65.0%", () => expect(formatProbability(0.65)).toBe("65.0%"));
  it("formats 0.01 as 1.0%", () => expect(formatProbability(0.01)).toBe("1.0%"));
  it("formats 0.999 as 99.9%", () => expect(formatProbability(0.999)).toBe("99.9%"));
});

describe("formatCurrency", () => {
  it("formats large numbers with K suffix", () => expect(formatCurrency(45000)).toBe("45.0K"));
  it("formats millions with M suffix", () => expect(formatCurrency(1500000)).toBe("1.5M"));
  it("formats small numbers with decimals", () => expect(formatCurrency(42.5)).toBe("42.50"));
  it("formats negative thousands with K suffix", () => expect(formatCurrency(-45000)).toBe("-45.0K"));
  it("formats negative millions with M suffix", () => expect(formatCurrency(-1500000)).toBe("-1.5M"));
});

describe("truncateHash", () => {
  it("truncates sha256 hashes", () => {
    expect(truncateHash("sha256:abcdef0123456789")).toBe("sha256:abcdef01…");
  });
  it("leaves short strings alone", () => {
    expect(truncateHash("short")).toBe("short");
  });
  it("truncates sha256 hashes with custom length", () => {
    expect(truncateHash("sha256:abcdef0123456789", 4)).toBe("sha256:abcd…");
  });
  it("truncates non-sha256 long strings", () => {
    expect(truncateHash("abcdef0123456789")).toBe("abcdef01…");
  });
});

describe("formatRelativeTime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2025-06-15T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns 'just now' for less than 1 minute ago", () => {
    expect(formatRelativeTime("2025-06-15T11:59:30Z")).toBe("just now");
  });
  it("returns minutes ago", () => {
    expect(formatRelativeTime("2025-06-15T11:45:00Z")).toBe("15m ago");
  });
  it("returns hours ago", () => {
    expect(formatRelativeTime("2025-06-15T09:00:00Z")).toBe("3h ago");
  });
  it("returns days ago", () => {
    expect(formatRelativeTime("2025-06-13T12:00:00Z")).toBe("2d ago");
  });
});

describe("timeUntil", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2025-06-15T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns 'expired' for past dates", () => {
    expect(timeUntil("2025-06-15T11:00:00Z")).toBe("expired");
  });
  it("returns hours and minutes remaining", () => {
    expect(timeUntil("2025-06-15T14:30:00Z")).toBe("2h 30m");
  });
  it("returns days and hours remaining", () => {
    expect(timeUntil("2025-06-17T18:00:00Z")).toBe("2d 6h");
  });
});

describe("statusColor", () => {
  it("returns green for active", () => expect(statusColor("active")).toBe("var(--color-active)"));
  it("returns blue for resolved", () => expect(statusColor("resolved")).toBe("var(--color-resolved)"));
  it("returns muted for unknown", () => expect(statusColor("unknown")).toBe("var(--color-text-muted)"));
});
