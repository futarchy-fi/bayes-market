import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { TraderLeaderboard } from "@/features/analytics/TraderLeaderboard";
import { formatCurrency } from "@/lib/utils/format";
import type { MarketAnalyticsTraderRow } from "@/lib/api/types";

const makeRow = (overrides: Partial<MarketAnalyticsTraderRow> = {}): MarketAnalyticsTraderRow => ({
  accountId: "acct-default-001",
  tradeCount: 42,
  volume: 12345.67,
  ...overrides,
});

describe("TraderLeaderboard", () => {
  it("renders empty state when rows is empty", () => {
    render(<TraderLeaderboard rows={[]} />);
    expect(screen.getByText("No accepted activity yet.")).toBeInTheDocument();
    expect(screen.queryByTestId("trader-leaderboard")).not.toBeInTheDocument();
  });

  it("renders table headers", () => {
    render(<TraderLeaderboard rows={[makeRow()]} />);
    const table = screen.getByTestId("trader-leaderboard");
    expect(within(table).getByText("#")).toBeInTheDocument();
    expect(within(table).getByText("Trader")).toBeInTheDocument();
    expect(within(table).getByText("Trades")).toBeInTheDocument();
    expect(within(table).getByText("Volume")).toBeInTheDocument();
  });

  it("renders rows with correct rank numbers", () => {
    const rows = [
      makeRow({ accountId: "trader-a" }),
      makeRow({ accountId: "trader-b" }),
      makeRow({ accountId: "trader-c" }),
    ];
    render(<TraderLeaderboard rows={rows} />);
    const table = screen.getByTestId("trader-leaderboard");
    const dataRows = within(table).getAllByRole("row").slice(1); // skip header row
    expect(dataRows).toHaveLength(3);
    expect(within(dataRows[0]!).getByText("1")).toBeInTheDocument();
    expect(within(dataRows[1]!).getByText("2")).toBeInTheDocument();
    expect(within(dataRows[2]!).getByText("3")).toBeInTheDocument();
  });

  it("renders trader accountId, tradeCount, and formatted volume", () => {
    const row = makeRow({ accountId: "acct-abc-999", tradeCount: 77, volume: 56789 });
    render(<TraderLeaderboard rows={[row]} />);
    expect(screen.getByText("acct-abc-999")).toBeInTheDocument();
    expect(screen.getByText("77")).toBeInTheDocument();
    expect(screen.getByText(formatCurrency(56789))).toBeInTheDocument();
  });

  it("renders formatted volume for large values", () => {
    const row = makeRow({ volume: 2500000 });
    render(<TraderLeaderboard rows={[row]} />);
    expect(screen.getByText(formatCurrency(2500000))).toBeInTheDocument();
  });
});
