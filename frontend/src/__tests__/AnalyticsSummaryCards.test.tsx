import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AnalyticsSummaryCards } from "@/features/analytics/AnalyticsSummaryCards";
import { formatCurrency } from "@/lib/utils/format";
import type { MarketAnalyticsSummary } from "@/lib/api/types";

const makeSummary = (overrides: Partial<MarketAnalyticsSummary> = {}): MarketAnalyticsSummary => ({
  totalTrades: 1234,
  totalVolume: 56789.42,
  uniqueTraders: 312,
  bucketInterval: "day",
  lastUpdated: "2025-03-15T10:30:00Z",
  ...overrides,
});

describe("AnalyticsSummaryCards", () => {
  it("renders all four card labels", () => {
    render(<AnalyticsSummaryCards summary={makeSummary()} />);
    expect(screen.getByText("Total Activity")).toBeInTheDocument();
    expect(screen.getByText("Total Volume")).toBeInTheDocument();
    expect(screen.getByText("Unique Traders")).toBeInTheDocument();
    expect(screen.getByText("Last Update")).toBeInTheDocument();
  });

  it("renders correctly formatted values", () => {
    const summary = makeSummary();
    render(<AnalyticsSummaryCards summary={summary} />);

    expect(screen.getByText(summary.totalTrades.toLocaleString())).toBeInTheDocument();
    expect(screen.getByText(formatCurrency(summary.totalVolume))).toBeInTheDocument();
    expect(screen.getByText(summary.uniqueTraders.toLocaleString())).toBeInTheDocument();
    expect(
      screen.getByText(new Date(summary.lastUpdated).toLocaleString()),
    ).toBeInTheDocument();
  });

  it("renders the Last Update caption text", () => {
    render(<AnalyticsSummaryCards summary={makeSummary()} />);
    expect(
      screen.getByText("Accepted activity freshness for the selected market."),
    ).toBeInTheDocument();
  });

  it("handles zero values", () => {
    const summary = makeSummary({ totalTrades: 0, totalVolume: 0, uniqueTraders: 0 });
    render(<AnalyticsSummaryCards summary={summary} />);

    // totalTrades and uniqueTraders both render "0"
    const zeros = screen.getAllByText((0).toLocaleString());
    expect(zeros).toHaveLength(2);
    expect(screen.getByText(formatCurrency(0))).toBeInTheDocument();
  });

  it("handles large numbers", () => {
    const summary = makeSummary({
      totalTrades: 15000,
      totalVolume: 2500000,
      uniqueTraders: 8700,
    });
    render(<AnalyticsSummaryCards summary={summary} />);

    expect(screen.getByText((15000).toLocaleString())).toBeInTheDocument();
    expect(screen.getByText(formatCurrency(2500000))).toBeInTheDocument();
    expect(screen.getByText((8700).toLocaleString())).toBeInTheDocument();
  });
});
