import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { ResolveMarketPanel } from "@/features/market/ResolveMarketPanel";
import * as api from "@/lib/api/client";
import type { Market } from "@/lib/api/types";

vi.mock("@/lib/api/client");

const accountId = "acct-resolver";

const makeMarket = (overrides: Partial<Market> = {}): Market => ({
  id: "m1",
  title: "Test Market",
  description: "Test",
  variableId: "var1",
  status: "active",
  outcomes: [
    { id: "yes", name: "Yes" },
    { id: "no", name: "No" },
  ],
  marginals: { yes: 0.6, no: 0.4 },
  liquidity: 1000,
  volume: 500,
  created_at: "2026-01-01T00:00:00Z",
  expires_at: "2026-12-31T23:59:59Z",
  ...overrides,
});

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem(
    "bayes-session",
    JSON.stringify({ accountId, agentId: "agent-1" }),
  );
  vi.clearAllMocks();
});

describe("ResolveMarketPanel", () => {
  it("shows resolved summary with single outcome", () => {
    renderWithProviders(
      <ResolveMarketPanel
        market={makeMarket({ status: "resolved", resolution: "yes" })}
      />,
    );
    expect(screen.getByText("Resolved")).toBeInTheDocument();
    expect(screen.getByText(/Outcome: yes/)).toBeInTheDocument();
  });

  it("shows resolved summary with probability distribution", () => {
    renderWithProviders(
      <ResolveMarketPanel
        market={makeMarket({
          status: "resolved",
          resolutionProbabilities: { yes: 0.7, no: 0.3 },
        })}
      />,
    );
    expect(
      screen.getByText(/Distribution: yes 70\.0%, no 30\.0%/),
    ).toBeInTheDocument();
  });

  it("returns null for draft market", () => {
    const { container } = renderWithProviders(
      <ResolveMarketPanel market={makeMarket({ status: "draft" })} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("returns null when no accountId is set", () => {
    localStorage.clear();
    const { container } = renderWithProviders(
      <ResolveMarketPanel market={makeMarket()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders resolve UI with disabled button when no outcome selected", () => {
    renderWithProviders(<ResolveMarketPanel market={makeMarket()} />);
    expect(screen.getByText("Resolve Market")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resolve" })).toBeDisabled();
  });

  it("enables resolve button after selecting an outcome", () => {
    renderWithProviders(<ResolveMarketPanel market={makeMarket()} />);
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "yes" },
    });
    expect(screen.getByRole("button", { name: "Resolve" })).toBeEnabled();
  });

  it("shows two-step confirmation UI on first click", () => {
    renderWithProviders(<ResolveMarketPanel market={makeMarket()} />);
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "yes" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }));

    expect(screen.getByText(/Confirm resolve to/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Yes, Resolve/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("cancels confirmation and returns to resolve button", () => {
    renderWithProviders(<ResolveMarketPanel market={makeMarket()} />);
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "yes" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByText(/Confirm resolve to/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resolve" })).toBeInTheDocument();
  });

  it("resets confirmation when outcome selection changes", () => {
    renderWithProviders(<ResolveMarketPanel market={makeMarket()} />);
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "yes" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
    expect(screen.getByText(/Confirm resolve to/)).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "no" },
    });
    expect(screen.queryByText(/Confirm resolve to/)).not.toBeInTheDocument();
  });

  it("calls resolveMarket on confirmation and shows success", async () => {
    vi.mocked(api.resolveMarket).mockResolvedValue({} as any);

    renderWithProviders(<ResolveMarketPanel market={makeMarket()} />);
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "yes" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
    fireEvent.click(screen.getByRole("button", { name: /Yes, Resolve/ }));

    await waitFor(() => {
      expect(api.resolveMarket).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(
        screen.getByText("Market resolved successfully."),
      ).toBeInTheDocument();
    });
  });

  it("shows error message on mutation failure", async () => {
    vi.mocked(api.resolveMarket).mockRejectedValue(
      new Error("Network error"),
    );

    renderWithProviders(<ResolveMarketPanel market={makeMarket()} />);
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "yes" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
    fireEvent.click(screen.getByRole("button", { name: /Yes, Resolve/ }));

    await waitFor(() => {
      expect(screen.getByText("Network error")).toBeInTheDocument();
    });
  });

  it("renders panel for closed market", () => {
    renderWithProviders(
      <ResolveMarketPanel market={makeMarket({ status: "closed" })} />,
    );
    expect(screen.getByText("Resolve Market")).toBeInTheDocument();
  });
});
