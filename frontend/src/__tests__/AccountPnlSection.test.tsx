import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AccountPnlSection } from "@/features/analytics/AccountPnlSection";
import { formatCurrency } from "@/lib/utils/format";
import { formatSignedCurrency } from "@/features/analytics/chartUtils";
import type { AccountPnlResponse } from "@/lib/api/types";

function makeAccountPnlData(): AccountPnlResponse {
  return {
    account: {
      id: "acct-123",
      pnl: {
        totals: {
          costBasis: 12345,
          markedValue: 67890,
          realizedPnl: 350,
          unrealizedPnl: -150,
          netPnl: 0,
        },
        positions: [
          {
            marketId: "market-1",
            marketTitle: "Will BTC reach $100k?",
            marketStatus: "active",
            costBasis: 3000,
            markedValue: 3400,
            realizedPnl: 250,
            unrealizedPnl: -100,
          },
          {
            marketId: "market-2",
            marketTitle: "Will ETH reach $10k?",
            marketStatus: "resolved",
            costBasis: 2000,
            markedValue: 2100,
            realizedPnl: -50,
            unrealizedPnl: 75,
          },
          {
            marketId: "market-3",
            marketTitle: "Will SOL reach $500?",
            marketStatus: "active",
            costBasis: 480,
            markedValue: 520,
            realizedPnl: 100,
            unrealizedPnl: -25,
          },
        ],
        updatedAt: "2025-03-15T10:30:00Z",
      },
    },
    meta: {
      apiVersion: "v1",
      timestamp: "2025-03-15T10:30:00Z",
    },
  };
}

const defaultProps = {
  accountId: "acct-123",
  selectedMarketId: "",
  isLoading: false,
  error: null as unknown,
};

describe("AccountPnlSection", () => {
  it("shows empty state when no accountId is set", () => {
    render(<AccountPnlSection {...defaultProps} accountId="" />);
    expect(
      screen.getByText(/Set your Account ID in the header/),
    ).toBeTruthy();
  });

  it("shows loading state when isLoading is true", () => {
    const { container } = render(
      <AccountPnlSection {...defaultProps} isLoading={true} />,
    );
    expect(container.querySelector("svg")).toBeTruthy();
  });

  it("shows error message when error is truthy", () => {
    render(
      <AccountPnlSection {...defaultProps} error={new Error("fail")} />,
    );
    expect(
      screen.getByText(/Unable to load account P&L right now/),
    ).toBeTruthy();
  });

  it("renders all PnL metric cards with correct formatted values", () => {
    const data = makeAccountPnlData();
    render(<AccountPnlSection {...defaultProps} data={data} />);

    // Unique metric card labels
    expect(screen.getByText("Realized P&L")).toBeTruthy();
    expect(screen.getByText("Unrealized P&L")).toBeTruthy();
    expect(screen.getByText("Net P&L")).toBeTruthy();
    // Shared labels (metric card + table header)
    expect(screen.getAllByText("Cost Basis").length).toBeGreaterThanOrEqual(1);
    expect(
      screen.getAllByText("Marked Value").length,
    ).toBeGreaterThanOrEqual(1);

    // Formatted totals values
    expect(screen.getByText(formatCurrency(12345))).toBeTruthy();
    expect(screen.getByText(formatCurrency(67890))).toBeTruthy();
    expect(screen.getByText(formatSignedCurrency(350))).toBeTruthy();
    expect(screen.getByText(formatSignedCurrency(-150))).toBeTruthy();
    expect(screen.getByText(formatSignedCurrency(0))).toBeTruthy();
  });

  it("applies correct color tones for positive/negative/zero P&L values", () => {
    const data = makeAccountPnlData();
    render(<AccountPnlSection {...defaultProps} data={data} />);

    // Positive realizedPnl → success color
    expect(screen.getByText(formatSignedCurrency(350))).toHaveStyle({
      color: "var(--color-success)",
    });

    // Negative unrealizedPnl → danger color
    expect(screen.getByText(formatSignedCurrency(-150))).toHaveStyle({
      color: "var(--color-danger)",
    });

    // Zero netPnl → default text color
    expect(screen.getByText(formatSignedCurrency(0))).toHaveStyle({
      color: "var(--color-text)",
    });
  });

  it("renders selected market detail card when selectedMarketId matches a position", () => {
    const data = makeAccountPnlData();
    render(
      <AccountPnlSection
        {...defaultProps}
        data={data}
        selectedMarketId="market-1"
      />,
    );

    // Market title appears in both selected card and table
    expect(screen.getAllByText("Will BTC reach $100k?")).toHaveLength(2);

    // Status badge text present
    expect(
      screen.getAllByText("active").length,
    ).toBeGreaterThanOrEqual(1);

    // Selected card metric values (each appears in card + table = 2)
    expect(screen.getAllByText(formatCurrency(3000))).toHaveLength(2);
    expect(screen.getAllByText(formatCurrency(3400))).toHaveLength(2);
    expect(screen.getAllByText(formatSignedCurrency(250))).toHaveLength(2);
    expect(screen.getAllByText(formatSignedCurrency(-100))).toHaveLength(2);

    // Fallback should NOT be shown
    expect(
      screen.queryByText(
        "No recorded exposure in the selected market yet.",
      ),
    ).toBeNull();
  });

  it("shows fallback message when selectedMarketId does not match any position", () => {
    const data = makeAccountPnlData();
    render(
      <AccountPnlSection
        {...defaultProps}
        data={data}
        selectedMarketId="nonexistent"
      />,
    );
    expect(
      screen.getByText(
        "No recorded exposure in the selected market yet.",
      ),
    ).toBeTruthy();
  });

  it("renders positions table with all positions", () => {
    const data = makeAccountPnlData();
    render(<AccountPnlSection {...defaultProps} data={data} />);

    // All market titles
    expect(screen.getByText("Will BTC reach $100k?")).toBeTruthy();
    expect(screen.getByText("Will ETH reach $10k?")).toBeTruthy();
    expect(screen.getByText("Will SOL reach $500?")).toBeTruthy();

    // Spot-check formatted values per position
    expect(screen.getByText(formatCurrency(3000))).toBeTruthy();
    expect(screen.getByText(formatSignedCurrency(250))).toBeTruthy();
    expect(screen.getByText(formatCurrency(2000))).toBeTruthy();
    expect(screen.getByText(formatSignedCurrency(-50))).toBeTruthy();
    expect(screen.getByText(formatCurrency(480))).toBeTruthy();
    expect(screen.getByText(formatSignedCurrency(100))).toBeTruthy();
  });

  it("highlights the selected market row in the positions table", () => {
    const data = makeAccountPnlData();
    render(
      <AccountPnlSection
        {...defaultProps}
        data={data}
        selectedMarketId="market-1"
      />,
    );

    // Find highlighted row via table cell
    const elements = screen.getAllByText("Will BTC reach $100k?");
    const row = elements.map((el) => el.closest("tr")).find(Boolean);
    expect(row).toHaveStyle({ background: "rgba(99, 102, 241, 0.12)" });

    // Non-selected row should be transparent
    const otherCell = screen.getByText("Will ETH reach $10k?");
    const otherRow = otherCell.closest("tr");
    expect(otherRow).toHaveStyle({ background: "transparent" });
  });

  it("shows empty positions message when positions array is empty", () => {
    const data = makeAccountPnlData();
    data.account.pnl.positions = [];
    render(<AccountPnlSection {...defaultProps} data={data} />);
    expect(screen.getByText("No marked positions yet.")).toBeTruthy();
  });
});
