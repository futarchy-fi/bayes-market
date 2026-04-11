import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { AssumptionProvider, useAssumptions } from "@/features/assumptions/AssumptionContext";
import type { ReactNode } from "react";

function wrapper({ children }: { children: ReactNode }) {
  return <AssumptionProvider>{children}</AssumptionProvider>;
}

describe("AssumptionContext", () => {
  describe("initial state", () => {
    it("starts with empty assumptions array", () => {
      const { result } = renderHook(() => useAssumptions(), { wrapper });
      expect(result.current.assumptions).toEqual([]);
    });

    it("hasAssumption returns false for any variableId", () => {
      const { result } = renderHook(() => useAssumptions(), { wrapper });
      expect(result.current.hasAssumption("v1")).toBe(false);
    });

    it("getAssumption returns undefined for any variableId", () => {
      const { result } = renderHook(() => useAssumptions(), { wrapper });
      expect(result.current.getAssumption("v1")).toBeUndefined();
    });

    it("contextPayload is empty array", () => {
      const { result } = renderHook(() => useAssumptions(), { wrapper });
      expect(result.current.contextPayload).toEqual([]);
    });
  });

  describe("addAssumption", () => {
    it("adds a single assumption", () => {
      const { result } = renderHook(() => useAssumptions(), { wrapper });
      act(() => result.current.addAssumption({ variableId: "v1", outcomeId: "o1", label: "Label 1" }));
      expect(result.current.assumptions).toEqual([
        { variableId: "v1", outcomeId: "o1", label: "Label 1" },
      ]);
    });

    it("adds multiple assumptions with different variableIds", () => {
      const { result } = renderHook(() => useAssumptions(), { wrapper });
      act(() => result.current.addAssumption({ variableId: "v1", outcomeId: "o1", label: "L1" }));
      act(() => result.current.addAssumption({ variableId: "v2", outcomeId: "o2", label: "L2" }));
      expect(result.current.assumptions).toHaveLength(2);
      expect(result.current.assumptions[0]!.variableId).toBe("v1");
      expect(result.current.assumptions[1]!.variableId).toBe("v2");
    });

    it("replaces assumption with same variableId", () => {
      const { result } = renderHook(() => useAssumptions(), { wrapper });
      act(() => result.current.addAssumption({ variableId: "v1", outcomeId: "o1", label: "Old" }));
      act(() => result.current.addAssumption({ variableId: "v1", outcomeId: "o2", label: "New" }));
      expect(result.current.assumptions).toHaveLength(1);
      expect(result.current.assumptions[0]).toEqual({ variableId: "v1", outcomeId: "o2", label: "New" });
    });
  });

  describe("removeAssumption", () => {
    it("removes an existing assumption by variableId", () => {
      const { result } = renderHook(() => useAssumptions(), { wrapper });
      act(() => result.current.addAssumption({ variableId: "v1", outcomeId: "o1", label: "L1" }));
      act(() => result.current.removeAssumption("v1"));
      expect(result.current.assumptions).toEqual([]);
    });

    it("is a no-op when removing non-existent variableId", () => {
      const { result } = renderHook(() => useAssumptions(), { wrapper });
      act(() => result.current.addAssumption({ variableId: "v1", outcomeId: "o1", label: "L1" }));
      act(() => result.current.removeAssumption("v-nonexistent"));
      expect(result.current.assumptions).toHaveLength(1);
    });
  });

  describe("clearAll", () => {
    it("removes all assumptions", () => {
      const { result } = renderHook(() => useAssumptions(), { wrapper });
      act(() => result.current.addAssumption({ variableId: "v1", outcomeId: "o1", label: "L1" }));
      act(() => result.current.addAssumption({ variableId: "v2", outcomeId: "o2", label: "L2" }));
      act(() => result.current.clearAll());
      expect(result.current.assumptions).toEqual([]);
    });
  });

  describe("hasAssumption and getAssumption", () => {
    it("hasAssumption returns true for existing variableId", () => {
      const { result } = renderHook(() => useAssumptions(), { wrapper });
      act(() => result.current.addAssumption({ variableId: "v1", outcomeId: "o1", label: "L1" }));
      expect(result.current.hasAssumption("v1")).toBe(true);
    });

    it("hasAssumption returns false for missing variableId", () => {
      const { result } = renderHook(() => useAssumptions(), { wrapper });
      act(() => result.current.addAssumption({ variableId: "v1", outcomeId: "o1", label: "L1" }));
      expect(result.current.hasAssumption("v2")).toBe(false);
    });

    it("getAssumption returns the matching Assumption", () => {
      const { result } = renderHook(() => useAssumptions(), { wrapper });
      act(() => result.current.addAssumption({ variableId: "v1", outcomeId: "o1", label: "L1" }));
      expect(result.current.getAssumption("v1")).toEqual({ variableId: "v1", outcomeId: "o1", label: "L1" });
    });

    it("getAssumption returns undefined for missing variableId", () => {
      const { result } = renderHook(() => useAssumptions(), { wrapper });
      act(() => result.current.addAssumption({ variableId: "v1", outcomeId: "o1", label: "L1" }));
      expect(result.current.getAssumption("v2")).toBeUndefined();
    });
  });

  describe("contextPayload", () => {
    it("contains only variableId and outcomeId (no label)", () => {
      const { result } = renderHook(() => useAssumptions(), { wrapper });
      act(() => result.current.addAssumption({ variableId: "v1", outcomeId: "o1", label: "L1" }));
      act(() => result.current.addAssumption({ variableId: "v2", outcomeId: "o2", label: "L2" }));
      expect(result.current.contextPayload).toEqual([
        { variableId: "v1", outcomeId: "o1" },
        { variableId: "v2", outcomeId: "o2" },
      ]);
    });
  });

  describe("useAssumptions outside provider", () => {
    const originalError = console.error;
    beforeEach(() => { console.error = vi.fn(); });
    afterEach(() => { console.error = originalError; });

    it("throws when used outside AssumptionProvider", () => {
      expect(() => renderHook(() => useAssumptions())).toThrow(
        "useAssumptions must be used within AssumptionProvider",
      );
    });
  });
});
