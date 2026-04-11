import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { SessionProvider, useSession } from "@/features/session/context";
import type { ReactNode } from "react";

const STORAGE_KEY = "bayes-session";

function wrapper({ children }: { children: ReactNode }) {
  return <SessionProvider>{children}</SessionProvider>;
}

describe("Session context", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  describe("loadSession", () => {
    it("returns defaults when localStorage is empty", () => {
      const { result } = renderHook(() => useSession(), { wrapper });
      expect(result.current.session).toEqual({ accountId: "", agentId: "" });
    });

    it("loads valid stored session", () => {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ accountId: "acc-1", agentId: "agent-1" }),
      );
      const { result } = renderHook(() => useSession(), { wrapper });
      expect(result.current.session).toEqual({ accountId: "acc-1", agentId: "agent-1" });
    });

    it("returns defaults for invalid JSON (corrupt storage)", () => {
      localStorage.setItem(STORAGE_KEY, "not-json{{{");
      const { result } = renderHook(() => useSession(), { wrapper });
      expect(result.current.session).toEqual({ accountId: "", agentId: "" });
    });

    it("returns defaults for valid JSON with missing fields", () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({}));
      const { result } = renderHook(() => useSession(), { wrapper });
      expect(result.current.session).toEqual({ accountId: "", agentId: "" });
    });

    it("returns partial data for valid JSON with only some fields", () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ accountId: "acc-2" }));
      const { result } = renderHook(() => useSession(), { wrapper });
      expect(result.current.session).toEqual({ accountId: "acc-2", agentId: "" });
    });
  });

  describe("saveSession via SessionProvider", () => {
    it("setAccountId persists to localStorage", () => {
      const { result } = renderHook(() => useSession(), { wrapper });
      act(() => result.current.setAccountId("acc-new"));
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY)!);
      expect(stored.accountId).toBe("acc-new");
    });

    it("setAgentId persists to localStorage", () => {
      const { result } = renderHook(() => useSession(), { wrapper });
      act(() => result.current.setAgentId("agent-new"));
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY)!);
      expect(stored.agentId).toBe("agent-new");
    });

    it("writes correct JSON structure to storage", () => {
      const { result } = renderHook(() => useSession(), { wrapper });
      act(() => result.current.setAccountId("acc-x"));
      act(() => result.current.setAgentId("agent-y"));
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY)!);
      expect(stored).toEqual({ accountId: "acc-x", agentId: "agent-y" });
    });
  });

  describe("isConfigured", () => {
    it("is false when both accountId and agentId are empty", () => {
      const { result } = renderHook(() => useSession(), { wrapper });
      expect(result.current.isConfigured).toBe(false);
    });

    it("is true when accountId is set and agentId is empty", () => {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ accountId: "acc-1", agentId: "" }),
      );
      const { result } = renderHook(() => useSession(), { wrapper });
      expect(result.current.isConfigured).toBe(true);
    });

    it("is false when accountId is empty and agentId is set", () => {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ accountId: "", agentId: "agent-1" }),
      );
      const { result } = renderHook(() => useSession(), { wrapper });
      expect(result.current.isConfigured).toBe(false);
    });

    it("is true when both accountId and agentId are set", () => {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ accountId: "acc-1", agentId: "agent-1" }),
      );
      const { result } = renderHook(() => useSession(), { wrapper });
      expect(result.current.isConfigured).toBe(true);
    });
  });

  describe("useSession outside provider", () => {
    const originalError = console.error;
    beforeEach(() => { console.error = vi.fn(); });
    afterEach(() => { console.error = originalError; });

    it("throws when used outside SessionProvider", () => {
      expect(() => renderHook(() => useSession())).toThrow(
        "useSession must be used within SessionProvider",
      );
    });
  });
});
