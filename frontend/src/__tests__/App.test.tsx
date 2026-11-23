import { beforeEach, describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { AppLayout } from "@/app/App";
import { shouldRetryQuery } from "@/app/providers";
import NotFound from "@/routes/NotFound";
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

describe("NotFound 404 page", () => {
  it("renders a styled Page not found view with Back to Network link", () => {
    renderWithProviders(<NotFound />);
    expect(screen.getByText("404")).toBeInTheDocument();
    expect(screen.getByText("Page not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Network" })).toHaveAttribute("href", "/");
  });
});

describe("shouldRetryQuery", () => {
  it("never retries 4xx HTTP errors including 409 context_contradicted", () => {
    expect(shouldRetryQuery(0, { status: 409, code: "context_contradicted" })).toBe(false);
    expect(shouldRetryQuery(0, { status: 400 })).toBe(false);
    expect(shouldRetryQuery(0, { status: 404 })).toBe(false);
  });

  it("retries network and 5xx errors up to 2 times", () => {
    expect(shouldRetryQuery(0, { status: 503 })).toBe(true);
    expect(shouldRetryQuery(1, { status: 500 })).toBe(true);
    expect(shouldRetryQuery(2, { status: 500 })).toBe(false);
    expect(shouldRetryQuery(0, new Error("network failure"))).toBe(true);
  });
});
