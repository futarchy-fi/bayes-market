import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import Portfolio from "@/routes/Portfolio";
import * as api from "@/lib/api/client";

vi.mock("@/lib/api/client");

describe("Portfolio", () => {
  it("renders account prompt when no session configured", () => {
    vi.mocked(api.listMarkets).mockResolvedValue({
      markets: [],
      count: 0,
      meta: { apiVersion: "1.0", timestamp: "2026-04-09T00:00:00Z" },
    });

    renderWithProviders(<Portfolio />);
    expect(screen.getByText(/Set your Account ID/)).toBeInTheDocument();
  });
});
