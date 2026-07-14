import { beforeEach, describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { AppLayout } from "@/app/App";
import { EXCHANGE_MODE_KEY } from "@/lib/exchangeMode";
import { renderWithProviders } from "./helpers";

describe("AppLayout", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
    window.localStorage.removeItem(EXCHANGE_MODE_KEY);
  });

  it("keeps Exchange out of the navigation and hides paper identity by default", () => {
    renderWithProviders(<AppLayout />);

    expect(screen.getByRole("link", { name: "Markets" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Compare" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Exchange" })).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Account ID")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Agent ID (optional)")).not.toBeInTheDocument();
  });

  it("keeps paper identity inputs behind the opt-out", () => {
    window.history.replaceState({}, "", "/?exchange=0");

    renderWithProviders(<AppLayout />);

    expect(screen.getByText("paper mode")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Account ID")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Agent ID (optional)")).toBeInTheDocument();
  });
});
