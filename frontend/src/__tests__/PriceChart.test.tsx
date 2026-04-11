import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PriceChart } from "@/features/analytics/PriceChart";
import { formatProbability } from "@/lib/utils/format";
import { formatTimestampLabel, getOutcomeColor } from "@/features/analytics/chartUtils";
import type { MarketAnalyticsSeries } from "@/lib/api/types";

const makeSeries = (
  overrides: Partial<MarketAnalyticsSeries> = {},
): MarketAnalyticsSeries => ({
  outcomeId: "outcome-1",
  outcomeName: "Yes",
  points: [
    { seq: 1, emittedAt: "2025-03-15T00:00:00Z", probability: 0.4 },
    { seq: 2, emittedAt: "2025-03-15T01:00:00Z", probability: 0.6 },
    { seq: 3, emittedAt: "2025-03-15T02:00:00Z", probability: 0.55 },
  ],
  ...overrides,
});

describe("PriceChart", () => {
  it("renders SVG with data-testid='price-chart' and role='img' aria-label", () => {
    render(<PriceChart series={[makeSeries()]} interval="hour" />);
    const svg = screen.getByTestId("price-chart");
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute("role", "img");
    expect(svg).toHaveAttribute("aria-label", "Probability history chart");
  });

  it("renders correct number of path and circle elements", () => {
    const series = [
      makeSeries({
        outcomeId: "o1",
        outcomeName: "Yes",
        points: [
          { seq: 1, emittedAt: "2025-03-15T00:00:00Z", probability: 0.4 },
          { seq: 2, emittedAt: "2025-03-15T01:00:00Z", probability: 0.6 },
        ],
      }),
      makeSeries({
        outcomeId: "o2",
        outcomeName: "No",
        points: [
          { seq: 1, emittedAt: "2025-03-15T00:00:00Z", probability: 0.6 },
          { seq: 2, emittedAt: "2025-03-15T01:00:00Z", probability: 0.4 },
        ],
      }),
    ];
    const { container } = render(
      <PriceChart series={series} interval="hour" />,
    );
    // Two series with >1 point each => 2 paths
    const paths = container.querySelectorAll("path");
    expect(paths).toHaveLength(2);
    // 2 points per series * 2 series = 4 circles
    const circles = container.querySelectorAll("circle");
    expect(circles).toHaveLength(4);
  });

  it("path stroke and circle fill colors match getOutcomeColor(index)", () => {
    const series = [
      makeSeries({ outcomeId: "o1", outcomeName: "Yes" }),
      makeSeries({
        outcomeId: "o2",
        outcomeName: "No",
        points: [
          { seq: 1, emittedAt: "2025-03-15T00:00:00Z", probability: 0.6 },
          { seq: 2, emittedAt: "2025-03-15T01:00:00Z", probability: 0.4 },
        ],
      }),
    ];
    const { container } = render(
      <PriceChart series={series} interval="hour" />,
    );

    const paths = container.querySelectorAll("path");
    expect(paths[0]).toHaveAttribute("stroke", getOutcomeColor(0));
    expect(paths[1]).toHaveAttribute("stroke", getOutcomeColor(1));

    // First series circles should match color 0, second series circles match color 1
    const circles = container.querySelectorAll("circle");
    // series 0 has 3 points, series 1 has 2 points
    for (let i = 0; i < 3; i++) {
      expect(circles[i]).toHaveAttribute("fill", getOutcomeColor(0));
    }
    for (let i = 3; i < 5; i++) {
      expect(circles[i]).toHaveAttribute("fill", getOutcomeColor(1));
    }
  });

  it("path elements have non-empty d attribute", () => {
    const { container } = render(
      <PriceChart series={[makeSeries()]} interval="hour" />,
    );
    const paths = container.querySelectorAll("path");
    expect(paths.length).toBeGreaterThan(0);
    for (const path of paths) {
      const d = path.getAttribute("d");
      expect(d).toBeTruthy();
      expect(d!.length).toBeGreaterThan(0);
    }
  });

  it("Y-axis renders gridline labels using formatProbability", () => {
    render(<PriceChart series={[makeSeries()]} interval="hour" />);
    const expectedLabels = [1, 0.75, 0.5, 0.25, 0].map(formatProbability);
    for (const label of expectedLabels) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("X-axis renders time labels using formatTimestampLabel", () => {
    const series = [makeSeries()];
    render(<PriceChart series={series} interval="hour" />);

    // With 3 timestamps, xTickCount = min(4, 3) = 3
    // ticks at domainStart, mid, domainEnd
    const timestamps = series
      .flatMap((s) => s.points.map((p) => Date.parse(p.emittedAt)))
      .filter((v) => Number.isFinite(v));
    const domainStart = Math.min(...timestamps);
    const domainEnd = Math.max(...timestamps);
    const xTickCount = Math.min(4, timestamps.length);
    const xTicks = Array.from({ length: xTickCount }, (_, i) =>
      domainStart + ((domainEnd - domainStart) * i) / (xTickCount - 1),
    );

    for (const tick of xTicks) {
      const label = formatTimestampLabel(new Date(tick).toISOString(), "hour");
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("responsive sizing — SVG has correct viewBox and style attributes", () => {
    render(<PriceChart series={[makeSeries()]} interval="hour" />);
    const svg = screen.getByTestId("price-chart");
    expect(svg).toHaveAttribute("viewBox", "0 0 760 320");
    expect(svg).toHaveStyle({ width: "100%", height: "auto" });
    expect(svg.style.minWidth).toBe("460px");
  });

  it("empty state renders chart frame without paths or circles", () => {
    const { container } = render(
      <PriceChart series={[]} interval="hour" />,
    );
    const svg = screen.getByTestId("price-chart");
    expect(svg).toBeInTheDocument();

    const paths = container.querySelectorAll("path");
    expect(paths).toHaveLength(0);

    const circles = container.querySelectorAll("circle");
    expect(circles).toHaveLength(0);

    // Gridlines and axes should still be present
    const lines = container.querySelectorAll("line");
    expect(lines.length).toBeGreaterThan(0);
  });

  it("legend renders outcome names with colored dots", () => {
    const series = [
      makeSeries({ outcomeId: "o1", outcomeName: "Yes" }),
      makeSeries({ outcomeId: "o2", outcomeName: "No" }),
    ];
    render(<PriceChart series={series} interval="hour" />);

    expect(screen.getByText("Yes")).toBeInTheDocument();
    expect(screen.getByText("No")).toBeInTheDocument();
  });
});
