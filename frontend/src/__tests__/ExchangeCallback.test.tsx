import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import ExchangeCallback from "@/routes/ExchangeCallback";
import {
  EXCHANGE_RETURN_TO_STORAGE_KEY,
  EXCHANGE_SELECT_ACCOUNT_STORAGE_KEY,
  EXCHANGE_SESSION_STORAGE_KEY,
  ExchangeSessionProvider,
} from "@/lib/exchange/session";
import { routerFuture } from "@/app/routerFuture";

function LocationEcho() {
  const location = useLocation();
  return <div data-testid="landed-path">{`${location.pathname}${location.search}`}</div>;
}

function renderCallback(initialEntry = "/exchange/callback") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ExchangeSessionProvider>
        <MemoryRouter future={routerFuture} initialEntries={[initialEntry]}>
          <Routes>
            <Route path="/exchange/callback" element={<ExchangeCallback />} />
            <Route path="*" element={<LocationEcho />} />
          </Routes>
        </MemoryRouter>
      </ExchangeSessionProvider>
    </QueryClientProvider>,
  );
}

describe("ExchangeCallback", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    window.history.replaceState(null, "", "/exchange/callback");
  });

  it("saves session, clears select_account, strips hash, and redirects to saved return_to", async () => {
    sessionStorage.setItem(EXCHANGE_SELECT_ACCOUNT_STORAGE_KEY, "1");
    sessionStorage.setItem(EXCHANGE_RETURN_TO_STORAGE_KEY, "/markets/m42?sort=volume");
    window.history.replaceState(null, "", "/exchange/callback#auth=secret-key&login=octocat");

    const replaceSpy = vi.spyOn(window.history, "replaceState");

    renderCallback("/exchange/callback");

    await waitFor(() => {
      expect(screen.getByTestId("landed-path")).toHaveTextContent("/markets/m42?sort=volume");
    });

    expect(JSON.parse(localStorage.getItem(EXCHANGE_SESSION_STORAGE_KEY) ?? "null")).toEqual({
      apiKey: "secret-key",
      githubLogin: "octocat",
    });
    expect(sessionStorage.getItem(EXCHANGE_SELECT_ACCOUNT_STORAGE_KEY)).toBeNull();
    expect(sessionStorage.getItem(EXCHANGE_RETURN_TO_STORAGE_KEY)).toBeNull();
    expect(replaceSpy).toHaveBeenCalledWith(null, "", "/exchange/callback");
    expect(window.location.hash).toBe("");
    replaceSpy.mockRestore();
  });

  it("defaults to /portfolio when return_to is absent or unsafe", async () => {
    sessionStorage.setItem(EXCHANGE_RETURN_TO_STORAGE_KEY, "//evil.example/steal");
    window.history.replaceState(null, "", "/exchange/callback#auth=tok-2&login=alice");

    renderCallback("/exchange/callback");

    await waitFor(() => {
      expect(screen.getByTestId("landed-path")).toHaveTextContent("/portfolio");
    });
    expect(sessionStorage.getItem(EXCHANGE_RETURN_TO_STORAGE_KEY)).toBeNull();
  });

  it("renders a friendly error card and strips URL fragment on #error=access_denied", () => {
    window.history.replaceState(null, "", "/exchange/callback#error=access_denied");

    renderCallback("/exchange/callback");

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("GitHub sign-in didn't complete");
    expect(alert).toHaveTextContent(/cancelled the GitHub authorization/i);
    expect(screen.getByRole("button", { name: "Try signing in again" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Network" })).toHaveAttribute("href", "/");
    expect(window.location.hash).toBe("");
    expect(localStorage.getItem(EXCHANGE_SESSION_STORAGE_KEY)).toBeNull();
    expect(screen.queryByTestId("landed-path")).not.toBeInTheDocument();
  });

  it("handles ?error=invalid_state and #error=code_exchange_failed with clear messages", () => {
    window.history.replaceState(null, "", "/exchange/callback?error=invalid_state");
    const first = renderCallback("/exchange/callback");
    expect(screen.getByRole("alert")).toHaveTextContent(/sign-in session expired/i);
    expect(window.location.search).toBe("");
    first.unmount();

    window.history.replaceState(null, "", "/exchange/callback#error=code_exchange_failed");
    renderCallback("/exchange/callback");
    expect(screen.getByRole("alert")).toHaveTextContent(/token exchange with GitHub/i);
    expect(window.location.hash).toBe("");
  });

  it("renders the error card when neither error nor auth is returned", () => {
    window.history.replaceState(null, "", "/exchange/callback");
    renderCallback("/exchange/callback");
    expect(screen.getByRole("alert")).toHaveTextContent("GitHub sign-in didn't complete");
    expect(screen.getByRole("alert")).toHaveTextContent(/did not return an API key/i);
    expect(screen.getByRole("button", { name: "Try signing in again" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Network" })).toHaveAttribute("href", "/");
  });
});
