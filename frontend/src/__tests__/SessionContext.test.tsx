import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import type { ReactNode } from "react";
import { SessionProvider, useSession } from "@/features/session/context";

const STORAGE_KEY = "bayes-session";

const wrapper = ({ children }: { children: ReactNode }) => (
  <SessionProvider>{children}</SessionProvider>
);

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("useSession", () => {
  it("returns default session values", () => {
    const { result } = renderHook(() => useSession(), { wrapper });
    expect(result.current.session).toEqual({ accountId: "", agentId: "" });
  });

  it("loads session from localStorage on mount", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ accountId: "acc1", agentId: "ag1" }));
    const { result } = renderHook(() => useSession(), { wrapper });
    expect(result.current.session).toEqual({ accountId: "acc1", agentId: "ag1" });
  });

  it("setAccountId updates state and persists to localStorage", () => {
    const { result } = renderHook(() => useSession(), { wrapper });
    act(() => result.current.setAccountId("acc2"));
    expect(result.current.session.accountId).toBe("acc2");
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!).accountId).toBe("acc2");
  });

  it("setAgentId updates state and persists to localStorage", () => {
    const { result } = renderHook(() => useSession(), { wrapper });
    act(() => result.current.setAgentId("ag2"));
    expect(result.current.session.agentId).toBe("ag2");
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!).agentId).toBe("ag2");
  });

  it("handles corrupt localStorage gracefully", () => {
    localStorage.setItem(STORAGE_KEY, "not-json!!{");
    const { result } = renderHook(() => useSession(), { wrapper });
    expect(result.current.session).toEqual({ accountId: "", agentId: "" });
  });

  it("fills missing fields with empty string for partial data", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ accountId: "acc3" }));
    const { result } = renderHook(() => useSession(), { wrapper });
    expect(result.current.session).toEqual({ accountId: "acc3", agentId: "" });
  });

  it("isConfigured is true when accountId is non-empty", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ accountId: "acc4", agentId: "" }));
    const { result } = renderHook(() => useSession(), { wrapper });
    expect(result.current.isConfigured).toBe(true);
  });

  it("isConfigured is false when accountId is empty", () => {
    const { result } = renderHook(() => useSession(), { wrapper });
    expect(result.current.isConfigured).toBe(false);
  });

  it("throws when used outside SessionProvider", () => {
    expect(() => renderHook(() => useSession())).toThrow(
      "useSession must be used within SessionProvider",
    );
  });
});
