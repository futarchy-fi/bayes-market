import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { createMockMutationResult, createMockQueryResult, renderWithProviders } from "./helpers";
import InstrumentDetail from "@/routes/InstrumentDetail";

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useParams: () => ({ instrumentId: "ship-it" }) };
});

vi.mock("@/lib/exchange/session", async () => {
  const actual = await vi.importActual<typeof import("@/lib/exchange/session")>("@/lib/exchange/session");
  return { ...actual, useExchangeSession: vi.fn() };
});

vi.mock("@/lib/exchange/TradeCreditsPanel", () => ({
  TradeCreditsPanel: () => <div>NET trade controls</div>,
  friendlyExchangeError: () => "Exchange error",
}));

vi.mock("@/lib/exchange/hooks", () => ({
  useInstruments: vi.fn(),
  useNetMarket: vi.fn(),
  useAmmMarket: vi.fn(),
  useTradeAmm: vi.fn(),
  useExchangeMe: vi.fn(),
  useBookMarket: vi.fn(),
  useBookDepth: vi.fn(),
  useBookOrders: vi.fn(),
  usePlaceBookOrder: vi.fn(),
  useCancelBookOrder: vi.fn(),
}));

import {
  useAmmMarket,
  useBookDepth,
  useBookMarket,
  useBookOrders,
  useCancelBookOrder,
  useExchangeMe,
  useInstruments,
  useNetMarket,
  usePlaceBookOrder,
  useTradeAmm,
} from "@/lib/exchange/hooks";
import { useExchangeSession } from "@/lib/exchange/session";

describe("InstrumentDetail", () => {
  beforeEach(() => {
    vi.mocked(useExchangeSession).mockReturnValue({
      session: { apiKey: "", githubLogin: "" },
      isSignedIn: false,
      setSession: vi.fn(),
      signOut: vi.fn(),
    });
    vi.mocked(useInstruments).mockReturnValue(createMockQueryResult({ data: [{
      instrumentId: "ship-it",
      title: "Will it ship?",
      listings: [
        { venue: "net", marketId: "net-1", yesPrice: 0.6, status: "active" },
        { venue: "amm", marketId: "2", yesPrice: 0.61, status: "open" },
        { venue: "book", marketId: "3", yesPrice: null, status: "open" },
      ],
    }] }) as ReturnType<typeof useInstruments>);
    vi.mocked(useNetMarket).mockReturnValue(createMockQueryResult({ data: {
      id: "net-1", variableId: "ship", title: "Will it ship?", status: "active",
      outcomes: [{ id: "yes", name: "Yes" }, { id: "no", name: "No" }], marginals: { yes: 0.6, no: 0.4 }, parents: [],
    } }) as ReturnType<typeof useNetMarket>);
    vi.mocked(useAmmMarket).mockReturnValue(createMockQueryResult({ data: {
      market_id: 2, question: "Will it ship?", status: "open", outcomes: ["yes", "no"], prices: { yes: "0.61", no: "0.39" },
    } }) as ReturnType<typeof useAmmMarket>);
    vi.mocked(useBookMarket).mockReturnValue(createMockQueryResult({ data: {
      id: 3, question: "Will it ship?", status: "open", outcomes: ["yes", "no"], bestBid: null, bestAsk: null, lastPrice: null,
    } }) as ReturnType<typeof useBookMarket>);
    vi.mocked(useBookDepth).mockReturnValue(createMockQueryResult({ data: {
      marketId: 3, bids: [], asks: [], outcomes: { yes: { bids: [], asks: [] }, no: { bids: [], asks: [] } },
    } }) as ReturnType<typeof useBookDepth>);
    vi.mocked(useBookOrders).mockReturnValue(createMockQueryResult({ data: { orders: [] } }) as ReturnType<typeof useBookOrders>);
    vi.mocked(useExchangeMe).mockReturnValue(createMockQueryResult() as ReturnType<typeof useExchangeMe>);
    vi.mocked(useTradeAmm).mockReturnValue(createMockMutationResult() as ReturnType<typeof useTradeAmm>);
    vi.mocked(usePlaceBookOrder).mockReturnValue(createMockMutationResult() as ReturnType<typeof usePlaceBookOrder>);
    vi.mocked(useCancelBookOrder).mockReturnValue(createMockMutationResult() as ReturnType<typeof useCancelBookOrder>);
  });

  it("lays out NET, AMM, and order-book panels for one instrument", () => {
    renderWithProviders(<InstrumentDetail />);

    expect(screen.getByRole("heading", { name: "Will it ship?" })).toBeInTheDocument();
    expect(screen.getByTestId("venue-grid")).toBeInTheDocument();
    expect(screen.getByTestId("net-panel")).toBeInTheDocument();
    expect(screen.getByTestId("amm-panel")).toBeInTheDocument();
    expect(screen.getByTestId("book-panel")).toBeInTheDocument();
    expect(screen.getByText("NET trade controls")).toBeInTheDocument();
    expect(screen.getAllByText(/Sign in with GitHub/)).toHaveLength(2);
  });
});
