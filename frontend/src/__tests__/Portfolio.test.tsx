import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import Portfolio from "@/routes/Portfolio";
import * as api from "@/lib/api/client";
import type { AccountExposureResponse, AccountRiskResponse } from "@/lib/api/types";

vi.mock("@/lib/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/client")>("@/lib/api/client");
  return {
    ...actual,
    getAccountExposure: vi.fn(),
    getAccountRisk: vi.fn(),
    listMarkets: vi.fn(),
  };
});

const accountId = "acct-portfolio";

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();

  vi.mocked(api.listMarkets).mockResolvedValue({
    markets: [
      {
        id: "m1",
        title: "Election 2026",
        status: "active",
        liquidity: 1000,
        volume: 250,
        expires_at: "2026-12-31T23:59:59Z",
      },
    ],
    count: 1,
    meta: { apiVersion: "1.0", timestamp: "2026-04-10T00:00:00Z" },
  });
});

function configureSession() {
  localStorage.setItem("bayes-session", JSON.stringify({ accountId, agentId: "agent-1" }));
}

function createDeferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

describe("Portfolio", () => {
  it("renders account prompt when no session configured", () => {
    renderWithProviders(<Portfolio />);
    expect(screen.getByText(/Set your Account ID/)).toBeInTheDocument();
  });

  it("keeps the route loading when exposure is missing until risk settles", async () => {
    configureSession();
    const exposureDeferred = createDeferred<AccountExposureResponse>();
    const riskDeferred = createDeferred<AccountRiskResponse>();

    vi.mocked(api.getAccountExposure).mockReturnValue(exposureDeferred.promise);
    vi.mocked(api.getAccountRisk).mockReturnValue(riskDeferred.promise);

    renderWithProviders(<Portfolio />);

    await act(async () => {
      exposureDeferred.reject(new api.BayesApiError(404, "account_not_found", { accountId }));
      await Promise.resolve();
    });

    expect(screen.queryByRole("heading", { level: 1, name: "Portfolio" })).not.toBeInTheDocument();
    expect(screen.queryByText("No live EventTrade positions.")).not.toBeInTheDocument();
    expect(screen.queryByText("Account not found or no positions yet.")).not.toBeInTheDocument();

    await act(async () => {
      riskDeferred.resolve({
        account: {
          id: accountId,
          risk: {
            minAssets: {
              overall: 42,
              markets: [],
            },
            capacityIndicators: {
              limit: 100,
              available: 58,
              consumed: 42,
              utilization: 0.42,
              status: "healthy",
            },
            updatedAt: "2026-04-10T15:30:00Z",
          },
        },
        meta: { apiVersion: "1.0", timestamp: "2026-04-10T15:30:00Z" },
      });
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.getByText("Limit")).toBeInTheDocument();
    });

    expect(screen.getByText("Available")).toBeInTheDocument();
    expect(screen.getByText("No live EventTrade positions.")).toBeInTheDocument();
    expect(screen.getByText(/Last updated:/)).toBeInTheDocument();
  });

  it("keeps the route loading when risk is missing until exposure settles", async () => {
    configureSession();
    const exposureDeferred = createDeferred<AccountExposureResponse>();
    const riskDeferred = createDeferred<AccountRiskResponse>();

    vi.mocked(api.getAccountExposure).mockReturnValue(exposureDeferred.promise);
    vi.mocked(api.getAccountRisk).mockReturnValue(riskDeferred.promise);

    renderWithProviders(<Portfolio />);

    await act(async () => {
      riskDeferred.reject(new api.BayesApiError(404, "account_not_found", { accountId }));
      await Promise.resolve();
    });

    expect(screen.queryByRole("heading", { level: 1, name: "Portfolio" })).not.toBeInTheDocument();
    expect(screen.queryByText("Loading live holdings...")).not.toBeInTheDocument();
    expect(screen.queryByText("No live EventTrade positions.")).not.toBeInTheDocument();

    await act(async () => {
      exposureDeferred.resolve({
        account: {
          id: accountId,
          exposure: {
            maxPositionSize: 100,
            updatedAt: "2026-04-10T12:00:00Z",
            positions: [
              {
                marketId: "m1",
                outcomeId: "yes",
                netSize: 8.5,
                absSize: 8.5,
                lastTradePrice: 0.65,
                updatedAt: new Date(Date.now() - (6 * 60_000)).toISOString(),
                lastOrderId: "order-1",
                lastCommandId: "cmd-1",
              },
            ],
          },
        },
        meta: { apiVersion: "1.0", timestamp: "2026-04-10T12:00:00Z" },
      });
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Portfolio");
    });

    expect(screen.getByRole("link", { name: "Election 2026" })).toHaveAttribute("href", "/markets/m1");
    expect(screen.getByText("yes")).toBeInTheDocument();
    expect(screen.getByText("+8.50")).toBeInTheDocument();
    expect(screen.getByText("8.50")).toBeInTheDocument();
    expect(screen.getByText("65.0%")).toBeInTheDocument();
    expect(screen.getByText("6m ago")).toBeInTheDocument();
    expect(screen.queryByText("Limit")).not.toBeInTheDocument();
    expect(screen.queryByText(/Last updated:/)).not.toBeInTheDocument();
  });

  it("renders live exposure holdings when risk is missing", async () => {
    configureSession();
    vi.mocked(api.getAccountExposure).mockResolvedValue({
      account: {
        id: accountId,
        exposure: {
          maxPositionSize: 100,
          updatedAt: "2026-04-10T12:00:00Z",
          positions: [
            {
              marketId: "m1",
              outcomeId: "yes",
              netSize: 8.5,
              absSize: 8.5,
              lastTradePrice: 0.65,
              updatedAt: new Date(Date.now() - (6 * 60_000)).toISOString(),
              lastOrderId: "order-1",
              lastCommandId: "cmd-1",
            },
          ],
        },
      },
      meta: { apiVersion: "1.0", timestamp: "2026-04-10T12:00:00Z" },
    });
    vi.mocked(api.getAccountRisk).mockRejectedValue(
      new api.BayesApiError(404, "account_not_found", { accountId }),
    );

    renderWithProviders(<Portfolio />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Portfolio");
    });

    expect(screen.getByRole("link", { name: "Election 2026" })).toHaveAttribute("href", "/markets/m1");
    expect(screen.getByText("yes")).toBeInTheDocument();
    expect(screen.getByText("+8.50")).toBeInTheDocument();
    expect(screen.getByText("8.50")).toBeInTheDocument();
    expect(screen.getByText("65.0%")).toBeInTheDocument();
    expect(screen.getByText("6m ago")).toBeInTheDocument();
    expect(screen.queryByText("Limit")).not.toBeInTheDocument();
    expect(screen.queryByText(/Last updated:/)).not.toBeInTheDocument();
  });

  it("renders risk summary when risk data exists even without live exposure", async () => {
    configureSession();
    vi.mocked(api.getAccountExposure).mockRejectedValue(
      new api.BayesApiError(404, "account_not_found", { accountId }),
    );
    vi.mocked(api.getAccountRisk).mockResolvedValue({
      account: {
        id: accountId,
        risk: {
          minAssets: {
            overall: 42,
            markets: [],
          },
          capacityIndicators: {
            limit: 100,
            available: 58,
            consumed: 42,
            utilization: 0.42,
            status: "healthy",
          },
          updatedAt: "2026-04-10T15:30:00Z",
        },
      },
      meta: { apiVersion: "1.0", timestamp: "2026-04-10T15:30:00Z" },
    });

    renderWithProviders(<Portfolio />);

    await waitFor(() => {
      expect(screen.getByText("Limit")).toBeInTheDocument();
    });

    expect(screen.getByText("Available")).toBeInTheDocument();
    expect(screen.getByText("No live EventTrade positions.")).toBeInTheDocument();
    expect(screen.getByText(/Last updated:/)).toBeInTheDocument();
  });

  it("shows the empty account state when exposure and risk are both missing", async () => {
    configureSession();
    vi.mocked(api.getAccountExposure).mockRejectedValue(
      new api.BayesApiError(404, "account_not_found", { accountId }),
    );
    vi.mocked(api.getAccountRisk).mockRejectedValue(
      new api.BayesApiError(404, "account_not_found", { accountId }),
    );

    renderWithProviders(<Portfolio />);

    await waitFor(() => {
      expect(screen.getByText("Account not found or no positions yet.")).toBeInTheDocument();
    });
  });
});
