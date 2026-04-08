import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import Portfolio from "@/routes/Portfolio";

vi.mock("@/lib/api/client");

describe("Portfolio", () => {
  it("renders account prompt when no session configured", () => {
    renderWithProviders(<Portfolio />);
    expect(screen.getByText(/Set your Account ID/)).toBeInTheDocument();
  });
});
