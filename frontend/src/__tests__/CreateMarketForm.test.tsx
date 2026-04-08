import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { CreateMarketForm } from "@/features/market/CreateMarketForm";

vi.mock("@/lib/api/client");

describe("CreateMarketForm", () => {
  it("renders the form heading", () => {
    renderWithProviders(<CreateMarketForm />);
    expect(screen.getByRole("heading", { name: "Create Market" })).toBeInTheDocument();
  });

  it("renders title and description inputs", () => {
    renderWithProviders(<CreateMarketForm />);
    expect(screen.getByPlaceholderText(/Will ETH trade/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Additional context/)).toBeInTheDocument();
  });

  it("renders default Yes/No outcomes", () => {
    renderWithProviders(<CreateMarketForm />);
    expect(screen.getByDisplayValue("yes")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Yes")).toBeInTheDocument();
    expect(screen.getByDisplayValue("no")).toBeInTheDocument();
    expect(screen.getByDisplayValue("No")).toBeInTheDocument();
  });

  it("renders the add outcome button", () => {
    renderWithProviders(<CreateMarketForm />);
    expect(screen.getByText("+ Add outcome")).toBeInTheDocument();
  });

  it("renders preview section", () => {
    renderWithProviders(<CreateMarketForm />);
    expect(screen.getByText("PREVIEW")).toBeInTheDocument();
    expect(screen.getByText("Untitled market")).toBeInTheDocument();
  });

  it("shows create button", () => {
    renderWithProviders(<CreateMarketForm />);
    const button = screen.getByRole("button", { name: "Create Market" });
    expect(button).toBeInTheDocument();
  });
});
