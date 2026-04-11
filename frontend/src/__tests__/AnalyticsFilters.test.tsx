import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { AnalyticsFilters } from "@/features/analytics/AnalyticsFilters";
import type { AnalyticsInterval, MarketSummary } from "@/lib/api/types";

const makeMarket = (overrides: Partial<MarketSummary> = {}): MarketSummary => ({
  id: "market-1",
  title: "Will BTC exceed 100k?",
  status: "active",
  liquidity: 50000,
  volume: 120000,
  expires_at: "2027-12-31T23:59:59Z",
  ...overrides,
});

const defaultProps = () => ({
  markets: [makeMarket(), makeMarket({ id: "market-2", title: "Will ETH exceed 10k?" })],
  selectedMarketId: "market-1",
  interval: "day" as AnalyticsInterval,
  onMarketChange: vi.fn(),
  onIntervalChange: vi.fn(),
});

describe("AnalyticsFilters", () => {
  it("renders fallback text when no market is selected", () => {
    const props = defaultProps();
    renderWithProviders(<AnalyticsFilters {...props} />);

    expect(screen.getByText("Choose a market")).toBeInTheDocument();
    expect(screen.queryByText("Open Market")).not.toBeInTheDocument();
    expect(screen.queryByText(/Liquidity/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Volume/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Expires/)).not.toBeInTheDocument();
  });

  it("renders market details when selectedMarket is provided", () => {
    const market = makeMarket();
    const props = { ...defaultProps(), selectedMarket: market };
    renderWithProviders(<AnalyticsFilters {...props} />);

    expect(screen.getByRole("heading", { name: market.title })).toBeInTheDocument();
    expect(screen.getByText(/Liquidity/)).toBeInTheDocument();
    expect(screen.getByText(/Volume/)).toBeInTheDocument();
    expect(screen.getByText(/Expires/)).toBeInTheDocument();

    const link = screen.getByText("Open Market");
    expect(link).toBeInTheDocument();
    expect(link.closest("a")).toHaveAttribute("href", `/markets/${market.id}`);
  });

  it("renders market options in dropdown", () => {
    const props = defaultProps();
    renderWithProviders(<AnalyticsFilters {...props} />);

    const select = screen.getByTestId("market-select");
    const options = select.querySelectorAll("option");
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveTextContent("Will BTC exceed 100k?");
    expect(options[1]).toHaveTextContent("Will ETH exceed 10k?");
  });

  it("calls onMarketChange when dropdown selection changes", () => {
    const props = defaultProps();
    renderWithProviders(<AnalyticsFilters {...props} />);

    const select = screen.getByTestId("market-select");
    fireEvent.change(select, { target: { value: "market-2" } });

    expect(props.onMarketChange).toHaveBeenCalledWith("market-2");
  });

  it("calls onIntervalChange when interval button is clicked", () => {
    const props = defaultProps();
    renderWithProviders(<AnalyticsFilters {...props} />);

    fireEvent.click(screen.getByText("Hour"));

    expect(props.onIntervalChange).toHaveBeenCalledWith("hour");
  });

  it("highlights active interval button", () => {
    const props = defaultProps(); // interval = "day"
    const { unmount } = renderWithProviders(<AnalyticsFilters {...props} />);

    const dayButton = screen.getByText("Day");
    const hourButton = screen.getByText("Hour");

    expect(dayButton).toHaveStyle({ borderColor: "var(--color-primary)" });
    expect(hourButton).toHaveStyle({ borderColor: "var(--color-border)" });

    unmount();

    // Verify the inverse with interval = "hour"
    const propsHour = { ...defaultProps(), interval: "hour" as AnalyticsInterval };
    renderWithProviders(<AnalyticsFilters {...propsHour} />);

    const dayButton2 = screen.getByText("Day");
    const hourButton2 = screen.getByText("Hour");

    expect(dayButton2).toHaveStyle({ borderColor: "var(--color-border)" });
    expect(hourButton2).toHaveStyle({ borderColor: "var(--color-primary)" });
  });
});
