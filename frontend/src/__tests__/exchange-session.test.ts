import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { EXCHANGE_API, getMe } from "@/lib/exchange/client";
import {
  EXCHANGE_RETURN_TO_STORAGE_KEY,
  EXCHANGE_SELECT_ACCOUNT_STORAGE_KEY,
  EXCHANGE_SESSION_STORAGE_KEY,
  SESSION_EXPIRED_NOTICE,
  ExchangeSessionProvider,
  GithubSignInLink,
  consumeReturnTo,
  getGithubLoginUrl,
  isSafeReturnTo,
  parseExchangeCallbackError,
  parseExchangeFragment,
  useExchangeSession,
} from "@/lib/exchange/session";
import { routerFuture } from "@/app/routerFuture";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

describe("parseExchangeFragment & parseExchangeCallbackError", () => {
  it("reads the OAuth API key and decoded GitHub login", () => {
    expect(parseExchangeFragment("#auth=key%2Fwith%2Bsymbols&account_id=42&login=octo+cat")).toEqual({
      apiKey: "key/with+symbols",
      githubLogin: "octo cat",
    });
  });

  it("rejects a fragment without auth", () => {
    expect(parseExchangeFragment("#login=octocat")).toBeNull();
  });

  it("extracts #error= before ?error=", () => {
    expect(parseExchangeCallbackError("#error=access_denied", "?error=invalid_state")).toBe("access_denied");
    expect(parseExchangeCallbackError("", "?error=invalid_state")).toBe("invalid_state");
    expect(parseExchangeCallbackError("#auth=abc", "")).toBeNull();
  });
});

describe("return_to validation and GitHub login URL helper", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  it("accepts safe relative paths and rejects unsafe or callback-loop paths", () => {
    expect(isSafeReturnTo("/markets/m1?sort=volume")).toBe(true);
    expect(isSafeReturnTo("/portfolio")).toBe(true);
    expect(isSafeReturnTo("//evil.com/phish")).toBe(false);
    expect(isSafeReturnTo("https://evil.com")).toBe(false);
    expect(isSafeReturnTo("/\\evil.com")).toBe(false);
    expect(isSafeReturnTo("/exchange/callback")).toBe(false);
    expect(isSafeReturnTo("/exchange/callback#auth=abc")).toBe(false);
    expect(isSafeReturnTo("")).toBe(false);
  });

  it("stores safe returnTo and appends ?prompt=select_account when select-account flag is set", () => {
    expect(getGithubLoginUrl("/markets/m1")).toBe(`${EXCHANGE_API}/v1/auth/github/login`);
    expect(sessionStorage.getItem(EXCHANGE_RETURN_TO_STORAGE_KEY)).toBe("/markets/m1");
    expect(consumeReturnTo()).toBe("/markets/m1");
    expect(sessionStorage.getItem(EXCHANGE_RETURN_TO_STORAGE_KEY)).toBeNull();

    // Unsafe returnTo is never stored
    getGithubLoginUrl("//evil.com");
    expect(sessionStorage.getItem(EXCHANGE_RETURN_TO_STORAGE_KEY)).toBeNull();

    // select_account flag appends query param
    sessionStorage.setItem(EXCHANGE_SELECT_ACCOUNT_STORAGE_KEY, "1");
    expect(getGithubLoginUrl()).toBe(`${EXCHANGE_API}/v1/auth/github/login?prompt=select_account`);
  });
});

describe("ExchangeSessionProvider lifecycle, 401 recovery, and cross-tab sync", () => {
  let queryClient: QueryClient;

  function SessionProbe() {
    const ctx = useExchangeSession();
    return React.createElement(
      "div",
      null,
      React.createElement("span", { "data-testid": "signed-in" }, ctx.isSignedIn ? "yes" : "no"),
      React.createElement("span", { "data-testid": "login" }, ctx.session.githubLogin),
      React.createElement("span", { "data-testid": "notice" }, ctx.sessionNotice ?? ""),
      React.createElement("button", { type: "button", onClick: ctx.signOut }, "Sign out"),
      React.createElement(GithubSignInLink, { children: "Sign in" }),
    );
  }

  function renderProbe(initialRoute = "/markets/m1") {
    return render(
      React.createElement(
        QueryClientProvider,
        { client: queryClient },
        React.createElement(
          ExchangeSessionProvider,
          null,
          React.createElement(
            MemoryRouter,
            { future: routerFuture, initialEntries: [initialRoute] },
            React.createElement(SessionProbe),
          ),
        ),
      ),
    );
  }

  beforeEach(() => {
    mockFetch.mockReset();
    localStorage.clear();
    sessionStorage.clear();
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  });

  afterEach(() => {
    queryClient.clear();
  });

  it("persists session across reloads from localStorage", () => {
    localStorage.setItem(
      EXCHANGE_SESSION_STORAGE_KEY,
      JSON.stringify({ apiKey: "live-key", githubLogin: "octocat" }),
    );
    renderProbe();
    expect(screen.getByTestId("signed-in")).toHaveTextContent("yes");
    expect(screen.getByTestId("login")).toHaveTextContent("octocat");
  });

  it("signOut calls /v1/auth/logout, clears storage & user caches, and sets select_account", async () => {
    localStorage.setItem(
      EXCHANGE_SESSION_STORAGE_KEY,
      JSON.stringify({ apiKey: "key-123", githubLogin: "alice" }),
    );
    queryClient.setQueryData(["exchange", "me", "alice"], { account_id: 1, available: "100" });
    queryClient.setQueryData(["exchange", "portfolio", "alice"], { orders: [] });
    queryClient.setQueryData(["exchange", "me-net"], { orders: [] });
    queryClient.setQueryData(["exchange", "book", "orders", "alice"], { orders: [] });
    queryClient.setQueryData(["exchange", "book-orders-mine"], { orders: [] });
    queryClient.setQueryData(["exchange", "book-positions-mine"], { positions: [] });
    queryClient.setQueryData(["exchange", "leaderboard"], { entries: [] });

    mockFetch.mockResolvedValue({ ok: true, status: 204, text: async () => "" });

    renderProbe();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    expect(screen.getByTestId("signed-in")).toHaveTextContent("no");
    expect(localStorage.getItem(EXCHANGE_SESSION_STORAGE_KEY)).toBeNull();
    expect(sessionStorage.getItem(EXCHANGE_SELECT_ACCOUNT_STORAGE_KEY)).toBe("1");
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      `${EXCHANGE_API}/v1/auth/github/login?prompt=select_account`,
    );

    // User caches cleared, public leaderboard preserved
    expect(queryClient.getQueryData(["exchange", "me", "alice"])).toBeUndefined();
    expect(queryClient.getQueryData(["exchange", "portfolio", "alice"])).toBeUndefined();
    expect(queryClient.getQueryData(["exchange", "me-net"])).toBeUndefined();
    expect(queryClient.getQueryData(["exchange", "book", "orders", "alice"])).toBeUndefined();
    expect(queryClient.getQueryData(["exchange", "book-orders-mine"])).toBeUndefined();
    expect(queryClient.getQueryData(["exchange", "book-positions-mine"])).toBeUndefined();
    expect(queryClient.getQueryData(["exchange", "leaderboard"])).toEqual({ entries: [] });

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(`${EXCHANGE_API}/v1/auth/logout`, {
        method: "POST",
        headers: { Authorization: "Bearer key-123" },
      });
    });
  });

  it("auto-recovers on authenticated HTTP 401 by clearing session, caches, and showing notice", async () => {
    localStorage.setItem(
      EXCHANGE_SESSION_STORAGE_KEY,
      JSON.stringify({ apiKey: "active-key", githubLogin: "alice" }),
    );
    queryClient.setQueryData(["exchange", "me", "alice"], { account_id: 1, available: "100" });
    queryClient.setQueryData(["exchange", "me-net"], { orders: [] });
    queryClient.setQueryData(["exchange", "book-orders-mine"], { orders: [] });
    queryClient.setQueryData(["exchange", "book-positions-mine"], { positions: [] });

    renderProbe();
    expect(screen.getByTestId("signed-in")).toHaveTextContent("yes");

    // Stale 401 from an unrelated old key must NOT sign out the current key
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ error: { code: "invalid_api_key", message: "stale" } }),
    });
    await act(async () => {
      await getMe("old-stale-key").catch(() => undefined);
    });
    expect(screen.getByTestId("signed-in")).toHaveTextContent("yes");

    // Real 401 for the active key clears session, caches, and displays expiry notice
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ error: { code: "invalid_api_key", message: "expired" } }),
    });
    await act(async () => {
      await getMe("active-key").catch(() => undefined);
    });

    expect(screen.getByTestId("signed-in")).toHaveTextContent("no");
    expect(localStorage.getItem(EXCHANGE_SESSION_STORAGE_KEY)).toBeNull();
    expect(screen.getByTestId("notice")).toHaveTextContent(SESSION_EXPIRED_NOTICE);
    expect(queryClient.getQueryData(["exchange", "me", "alice"])).toBeUndefined();
    expect(queryClient.getQueryData(["exchange", "me-net"])).toBeUndefined();
    expect(queryClient.getQueryData(["exchange", "book-orders-mine"])).toBeUndefined();
    expect(queryClient.getQueryData(["exchange", "book-positions-mine"])).toBeUndefined();
  });

  it("syncs sign-in and sign-out across browser tabs via the storage event", () => {
    renderProbe();
    expect(screen.getByTestId("signed-in")).toHaveTextContent("no");

    // Another tab signs in
    act(() => {
      localStorage.setItem(
        EXCHANGE_SESSION_STORAGE_KEY,
        JSON.stringify({ apiKey: "tab2-key", githubLogin: "bob" }),
      );
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: EXCHANGE_SESSION_STORAGE_KEY,
          newValue: localStorage.getItem(EXCHANGE_SESSION_STORAGE_KEY),
          storageArea: localStorage,
        }),
      );
    });
    expect(screen.getByTestId("signed-in")).toHaveTextContent("yes");
    expect(screen.getByTestId("login")).toHaveTextContent("bob");

    queryClient.setQueryData(["exchange", "me", "bob"], { account_id: 2 });

    // Another tab signs out
    act(() => {
      localStorage.removeItem(EXCHANGE_SESSION_STORAGE_KEY);
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: EXCHANGE_SESSION_STORAGE_KEY,
          newValue: null,
          storageArea: localStorage,
        }),
      );
    });
    expect(screen.getByTestId("signed-in")).toHaveTextContent("no");
    expect(queryClient.getQueryData(["exchange", "me", "bob"])).toBeUndefined();
  });
});
