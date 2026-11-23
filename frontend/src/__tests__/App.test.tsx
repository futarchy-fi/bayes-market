import { beforeEach, describe, expect, it } from "vitest";
import { act, fireEvent, screen } from "@testing-library/react";
import { EXCHANGE_API, EXCHANGE_UNAUTHORIZED_EVENT, ExchangeApiError } from "@/lib/exchange/client";
import { EXCHANGE_RETURN_TO_STORAGE_KEY, EXCHANGE_SESSION_STORAGE_KEY, SESSION_EXPIRED_NOTICE } from "@/lib/exchange/session";
import { AppLayout } from "@/app/App";
import { shouldRetryQuery } from "@/app/providers";
import NotFound from "@/routes/NotFound";
import { renderWithProviders } from "./helpers";

describe("AppLayout", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
    window.localStorage.clear();
    window.sessionStorage.clear();
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

  it("shows session-expired notice in header on 401 recovery and stores return_to on sign-in click", () => {
    window.localStorage.setItem(
      EXCHANGE_SESSION_STORAGE_KEY,
      JSON.stringify({ apiKey: "k-exp", githubLogin: "alice" }),
    );
    renderWithProviders(<AppLayout />, { route: "/markets?sort=volume" });

    expect(screen.getByText("@alice")).toBeInTheDocument();

    act(() => {
      window.dispatchEvent(
        new CustomEvent(EXCHANGE_UNAUTHORIZED_EVENT, {
          detail: { apiKey: "k-exp", error: new ExchangeApiError(401, "invalid_api_key", "expired") },
        }),
      );
    });

    expect(screen.getByRole("status")).toHaveTextContent(SESSION_EXPIRED_NOTICE);
    const signInLinks = screen.getAllByRole("link", { name: "Sign in with GitHub" });
    expect(signInLinks[0]).toHaveAttribute("href", `${EXCHANGE_API}/v1/auth/github/login`);
    signInLinks[0]!.addEventListener("click", (e) => e.preventDefault());
    fireEvent.click(signInLinks[0]!);
    expect(window.sessionStorage.getItem(EXCHANGE_RETURN_TO_STORAGE_KEY)).toBe("/markets?sort=volume");
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
