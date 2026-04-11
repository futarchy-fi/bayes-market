import { describe, it, expect, beforeAll } from "vitest";
import {
  getOutcomeColor,
  scaleNumber,
  buildLinePath,
  formatTimestampLabel,
  formatBucketRangeLabel,
  formatSignedCurrency,
} from "@/features/analytics/chartUtils";

beforeAll(() => {
  process.env.TZ = "UTC";
});

describe("getOutcomeColor", () => {
  it("returns first color for index 0", () => expect(getOutcomeColor(0)).toBe("#818cf8"));
  it("returns second color for index 1", () => expect(getOutcomeColor(1)).toBe("#22c55e"));
  it("wraps around after 6 colors", () => expect(getOutcomeColor(6)).toBe("#818cf8"));
  it("wraps correctly for index 7", () => expect(getOutcomeColor(7)).toBe("#22c55e"));
  it("returns fallback for NaN index", () => expect(getOutcomeColor(NaN)).toBe("#818cf8"));
  it("returns fallback for negative index", () => expect(getOutcomeColor(-1)).toBe("#818cf8"));
});

describe("scaleNumber", () => {
  it("maps domain midpoint to range midpoint", () => {
    expect(scaleNumber(50, 0, 100, 0, 200)).toBe(100);
  });
  it("maps domain min to range min", () => {
    expect(scaleNumber(0, 0, 100, 10, 20)).toBe(10);
  });
  it("maps domain max to range max", () => {
    expect(scaleNumber(100, 0, 100, 10, 20)).toBe(20);
  });
  it("returns range midpoint when domain is zero-width", () => {
    expect(scaleNumber(5, 5, 5, 0, 100)).toBe(50);
  });
  it("handles inverted range", () => {
    expect(scaleNumber(0, 0, 100, 200, 0)).toBe(200);
  });
  it("extrapolates beyond domain", () => {
    expect(scaleNumber(200, 0, 100, 0, 100)).toBe(200);
  });
});

describe("buildLinePath", () => {
  it("returns empty string for empty array", () => {
    expect(buildLinePath([])).toBe("");
  });
  it("returns M command for single point", () => {
    expect(buildLinePath([{ x: 10, y: 20 }])).toBe("M 10.00 20.00");
  });
  it("builds M then L commands for multiple points", () => {
    expect(
      buildLinePath([
        { x: 0, y: 0 },
        { x: 50, y: 100 },
        { x: 100, y: 50 },
      ]),
    ).toBe("M 0.00 0.00 L 50.00 100.00 L 100.00 50.00");
  });
  it("formats decimals to two places", () => {
    expect(buildLinePath([{ x: 1.1234, y: 2.5678 }])).toBe("M 1.12 2.57");
  });
});

describe("formatTimestampLabel", () => {
  it("formats day interval as short date", () => {
    const result = formatTimestampLabel("2024-06-15T00:00:00Z", "day");
    expect(result).toMatch(/15/);
    expect(result).not.toMatch(/:/);
  });
  it("formats hour interval with date and time", () => {
    const result = formatTimestampLabel("2024-06-15T14:30:00Z", "hour");
    expect(result).toMatch(/15/);
    expect(result).toMatch(/(:30|30)/);
  });
  it("hour result is longer than day result for same timestamp", () => {
    const dayLabel = formatTimestampLabel("2024-06-15T14:30:00Z", "day");
    const hourLabel = formatTimestampLabel("2024-06-15T14:30:00Z", "hour");
    expect(hourLabel.length).toBeGreaterThan(dayLabel.length);
  });
});

describe("formatBucketRangeLabel", () => {
  it("returns date label for day interval (delegates to formatTimestampLabel)", () => {
    const bucket = formatBucketRangeLabel("2024-06-15T00:00:00Z", "2024-06-16T00:00:00Z", "day");
    const direct = formatTimestampLabel("2024-06-15T00:00:00Z", "day");
    expect(bucket).toBe(direct);
  });
  it("returns time range with separator for hour interval", () => {
    const result = formatBucketRangeLabel("2024-06-15T14:00:00Z", "2024-06-15T15:00:00Z", "hour");
    expect(result).toMatch(/ - /);
    expect(result).toMatch(/:00/);
  });
});

describe("formatSignedCurrency", () => {
  it("prepends + for positive values", () => expect(formatSignedCurrency(42.5)).toBe("+42.50"));
  it("prepends nothing extra for negative values", () => expect(formatSignedCurrency(-10)).toBe("-10.00"));
  it("no prefix for zero", () => expect(formatSignedCurrency(0)).toBe("0.00"));
  it("formats large positive with K suffix", () => expect(formatSignedCurrency(5000)).toBe("+5.0K"));
  it("formats large negative with K suffix", () => expect(formatSignedCurrency(-5000)).toBe("-5.0K"));
});
