import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { VolumeChart } from "@/features/analytics/VolumeChart";
import { formatCurrency } from "@/lib/utils/format";
import { formatBucketRangeLabel } from "@/features/analytics/chartUtils";
import type { MarketAnalyticsVolumeBucket } from "@/lib/api/types";

const makeBucket = (
  overrides: Partial<MarketAnalyticsVolumeBucket> = {},
): MarketAnalyticsVolumeBucket => ({
  bucketStart: "2025-03-15T00:00:00Z",
  bucketEnd: "2025-03-15T01:00:00Z",
  tradeCount: 10,
  volume: 500,
  ...overrides,
});

describe("VolumeChart", () => {
  it("renders SVG with data-testid and role='img'", () => {
    render(
      <VolumeChart buckets={[makeBucket()]} interval="hour" />,
    );
    const svg = screen.getByTestId("volume-chart");
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute("role", "img");
  });

  it("renders correct number of bars", () => {
    const buckets = [
      makeBucket({ bucketStart: "2025-03-15T00:00:00Z", bucketEnd: "2025-03-15T01:00:00Z" }),
      makeBucket({ bucketStart: "2025-03-15T01:00:00Z", bucketEnd: "2025-03-15T02:00:00Z" }),
      makeBucket({ bucketStart: "2025-03-15T02:00:00Z", bucketEnd: "2025-03-15T03:00:00Z" }),
    ];
    const { container } = render(
      <VolumeChart buckets={buckets} interval="hour" />,
    );
    const rects = container.querySelectorAll("rect");
    expect(rects).toHaveLength(3);
  });

  it("bar heights are proportional to volume", () => {
    const buckets = [
      makeBucket({ volume: 100, bucketStart: "2025-03-15T00:00:00Z", bucketEnd: "2025-03-15T01:00:00Z" }),
      makeBucket({ volume: 200, bucketStart: "2025-03-15T01:00:00Z", bucketEnd: "2025-03-15T02:00:00Z" }),
      makeBucket({ volume: 50, bucketStart: "2025-03-15T02:00:00Z", bucketEnd: "2025-03-15T03:00:00Z" }),
    ];
    const { container } = render(
      <VolumeChart buckets={buckets} interval="hour" />,
    );
    const rects = container.querySelectorAll("rect");
    const heights = Array.from(rects).map((r) =>
      parseFloat(r.getAttribute("height") ?? "0"),
    );

    // volume ratios: 100/200 = 0.5, 50/200 = 0.25
    // height ratios should match
    expect(heights[0]! / heights[1]!).toBeCloseTo(100 / 200, 5);
    expect(heights[2]! / heights[1]!).toBeCloseTo(50 / 200, 5);
  });

  it("displays trade count labels above bars", () => {
    const buckets = [
      makeBucket({ tradeCount: 7, bucketStart: "2025-03-15T00:00:00Z", bucketEnd: "2025-03-15T01:00:00Z" }),
      makeBucket({ tradeCount: 42, bucketStart: "2025-03-15T01:00:00Z", bucketEnd: "2025-03-15T02:00:00Z" }),
    ];
    render(<VolumeChart buckets={buckets} interval="hour" />);
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("empty state renders chart frame without bars", () => {
    const { container } = render(
      <VolumeChart buckets={[]} interval="hour" />,
    );
    const svg = screen.getByTestId("volume-chart");
    expect(svg).toBeInTheDocument();

    const rects = container.querySelectorAll("rect");
    expect(rects).toHaveLength(0);

    // gridlines and axes should still be present
    const lines = container.querySelectorAll("line");
    expect(lines.length).toBeGreaterThan(0);
  });

  it("renders x-axis time labels", () => {
    const buckets = [
      makeBucket({ bucketStart: "2025-03-15T00:00:00Z", bucketEnd: "2025-03-15T01:00:00Z" }),
      makeBucket({ bucketStart: "2025-03-15T01:00:00Z", bucketEnd: "2025-03-15T02:00:00Z" }),
    ];
    render(<VolumeChart buckets={buckets} interval="hour" />);

    const expectedLabel = formatBucketRangeLabel(
      "2025-03-15T00:00:00Z",
      "2025-03-15T01:00:00Z",
      "hour",
    );
    expect(screen.getByText(expectedLabel)).toBeInTheDocument();
  });

  it("renders y-axis currency labels", () => {
    const maxVolume = 1000;
    const buckets = [
      makeBucket({ volume: maxVolume, bucketStart: "2025-03-15T00:00:00Z", bucketEnd: "2025-03-15T01:00:00Z" }),
    ];
    render(<VolumeChart buckets={buckets} interval="hour" />);

    // Component renders labels at 0, 50%, and 100% of maxVolume
    expect(screen.getByText(formatCurrency(0))).toBeInTheDocument();
    expect(screen.getByText(formatCurrency(maxVolume * 0.5))).toBeInTheDocument();
    expect(screen.getByText(formatCurrency(maxVolume))).toBeInTheDocument();
  });
});
